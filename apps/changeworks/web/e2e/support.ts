import { expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";

const dataDir = "public/data/"; // Playwright runs from the web/ directory
export const readData = <T>(file: string): T => JSON.parse(readFileSync(`${dataDir}${file}`, "utf8")) as T;

/** Collects console errors, page errors and failed requests of one page. */
export function watch(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(`console: ${m.text()}`); });
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  // A request aborted by our own navigation or reload (net::ERR_ABORTED) is not a failure of the page.
  page.on("requestfailed", (r) => { if (r.failure()?.errorText !== "net::ERR_ABORTED") errors.push(`requestfailed: ${r.url()}`); });
  page.on("response", (r) => { if (r.status() >= 400) errors.push(`http ${r.status()}: ${r.url()}`); });
  return errors;
}

/** The dataset is loaded (the manifest strip shows it) and the view has its heading. */
export async function ready(page: Page): Promise<void> {
  await page.locator("[data-testid=manifest-strip] [data-k=dataset_version]").waitFor({ state: "visible", timeout: 30_000 });
  await page.locator("main h1").first().waitFor();
}

export const overflow = (page: Page): Promise<{ scrollWidth: number; innerWidth: number }> =>
  page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth }));

export async function expectNoOverflow(page: Page): Promise<void> {
  const o = await overflow(page);
  expect(o.scrollWidth, `horizontal overflow ${o.scrollWidth} > ${o.innerWidth} on ${page.url()}`).toBeLessThanOrEqual(o.innerWidth);
}

/** A figure as the page prints it (thousands separators and the typographic minus), back to the plain decimal string of the data. */
export const plain = (s: string | null): string => (s ?? "").replace(/,/g, "").replace(/−/g, "-").replace(/\s*h$/, "").trim();
export const reference = (): Record<string, any> => JSON.parse(readFileSync("scripts/snapshot-reference.json", "utf8")); // eslint-disable-line @typescript-eslint/no-explicit-any

/** R9-21: every text node under 18 px (24 px bold counts as large, so is not exempt here) measured against its opaque background, or against every colour stop of a gradient
 * behind it, whichever is worst. Disabled controls are excepted. Returns the failures as "ratio colour on background size: text". */
export function lowContrast(page: Page, min = 4.5): Promise<string[]> {
  return page.evaluate((limit) => {
    type C = { r: number; g: number; b: number; a: number };
    const parse = (c: string): C | null => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null; const v = m[1]!.split(/[ ,/]+/).filter(Boolean).map(Number); return { r: v[0]!, g: v[1]!, b: v[2]!, a: v.length > 3 ? v[3]! : 1 }; };
    const lum = (c: C): number => { const f = (x: number): number => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
    const ratio = (a: C, b: C): number => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
    const backgrounds = (el: Element): C[] => {
      for (let e: Element | null = el; e; e = e.parentElement) {
        const cs = getComputedStyle(e);
        const stops = [...cs.backgroundImage.matchAll(/rgba?\([^)]+\)/g)].map((m) => parse(m[0])).filter((c): c is C => !!c && c.a > 0.5);
        if (stops.length) return stops;
        const c = parse(cs.backgroundColor);
        if (c && c.a > 0.5) return [c];
      }
      return [{ r: 255, g: 255, b: 255, a: 1 }];
    };
    const out: string[] = [];
    for (const el of document.querySelectorAll("body *")) {
      const own = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent!.trim()).join(" ").trim();
      if (!own) continue;
      const cs = getComputedStyle(el);
      if (cs.visibility === "hidden" || cs.display === "none" || +cs.opacity === 0) continue;
      const rc = el.getBoundingClientRect();
      if (!rc.width || !rc.height) continue;
      if (el.closest("[disabled], [aria-disabled=true], script, style, noscript")) continue;
      const size = parseFloat(cs.fontSize);
      if (size >= 18) continue;
      const fg = parse(cs.color);
      if (!fg) continue;
      for (const bg of backgrounds(el)) {
        const r = ratio(fg, bg);
        if (r < limit) out.push(`${r.toFixed(2)} ${cs.color} on rgb(${bg.r}, ${bg.g}, ${bg.b}) ${size}px: ${own.slice(0, 40)}`);
      }
    }
    return out;
  }, min);
}
