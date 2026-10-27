// Fixes adopted from review R10 (docs/contracts.md D-09): the contrast of every text node, the model card at 360 px, and the statements the pages now make
// about their populations, their baselines and the choices made after looking at outcomes.
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { TEST_COUNTS } from "../src/lib/counts";
import { ready, watch } from "./support";

const ROUTES = ["./", "overview/", "cohorts/", "features/", "models/", "calibration/", "capacity/", "account/", "queue/", "monitoring/", "evidence/", "case-study/"];
const fig = (page: Page, k: string) => page.locator(`[data-figure="${k}"]`).first();
const manifest = JSON.parse(readFileSync("public/data/manifest.json", "utf8")) as { disclosures: { id: string; items?: string[] }[] };

/** Every visible text node under 18 px (24 px or 18.66 px bold are "large" and need 3:1) against its composited background, measured in the page. */
async function lowContrast(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const parse = (s: string): { c: number[]; a: number } | null => { const m = s.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1]!.split(/[ ,/]+/).filter(Boolean).map(Number); return { c: p.slice(0, 3), a: p.length > 3 ? p[3]! : 1 }; };
    const bgOf = (el: Element): { c: number[] } | null => {
      const layers: { c: number[]; a: number }[] = [];
      for (let e: Element | null = el; e; e = e.parentElement) {
        const s = getComputedStyle(e);
        if (s.backgroundImage && s.backgroundImage !== "none") return null;                 // a gradient or image: not measurable here
        const b = parse(s.backgroundColor);
        if (b && b.a > 0) { layers.push(b); if (b.a >= 1) break; }
      }
      let c = [255, 255, 255];
      for (let i = layers.length - 1; i >= 0; i--) { const l = layers[i]!; c = c.map((v, k) => l.c[k]! * l.a + v * (1 - l.a)); }
      return { c };
    };
    const lum = (c: number[]): number => { const a = c.map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }); return 0.2126 * a[0]! + 0.7152 * a[1]! + 0.0722 * a[2]!; };
    const bad: string[] = [];
    const seen = new Set<Element>();
    const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (tw.nextNode()) {
      const t = tw.currentNode as Text;
      if (!t.textContent || !t.textContent.trim()) continue;
      const el = t.parentElement;
      if (!el || seen.has(el)) continue;
      seen.add(el);
      const s = getComputedStyle(el);
      if (s.visibility === "hidden" || s.display === "none" || el.getClientRects().length === 0 || el.closest("svg")) continue;
      if (el.closest(":disabled, [aria-disabled=true], [disabled]")) continue;                // disabled controls are exempt
      const size = parseFloat(s.fontSize), bold = parseInt(s.fontWeight) >= 700;
      const fg = parse(s.color), bg = bgOf(el);
      if (!fg || !bg) continue;
      const fgc = fg.c.map((v, k) => v * fg.a + bg.c[k]! * (1 - fg.a));
      const l1 = lum(fgc), l2 = lum(bg.c);
      const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
      const large = size >= 24 || (bold && size >= 18.66);
      const need = size < 18 ? 4.5 : large ? 3 : 4.5;
      if (ratio < need) bad.push(`${ratio.toFixed(2)} < ${need} (${size}px ${s.color} on rgb(${bg.c.map(Math.round)})) "${t.textContent.trim().slice(0, 50)}" <${el.tagName.toLowerCase()} class="${String((el as HTMLElement).className)}">`);
    }
    return bad;
  });
}

test.describe("R10-02: every text node reads at 4.5:1 or better at 1280 px", () => {
  test.use({ viewport: { width: 1280, height: 900 } });
  for (const r of ROUTES) {
    test(`contrast on ${r === "./" ? "home" : r}`, async ({ page }) => {
      await page.goto(r);
      await ready(page);
      await page.waitForTimeout(300);
      // open every definition popover and fold so that the text inside them is measured too
      await page.evaluate(() => document.querySelectorAll("details").forEach((d) => d.setAttribute("open", "")));
      await page.waitForTimeout(100);
      expect(await lowContrast(page)).toEqual([]);
    });
  }
});

test("R10-03: the model card stacks its pairs at 360 px and no word is broken inside itself", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 900 });
  await page.goto("case-study/");
  await ready(page);
  const card = page.getByTestId("model-card");
  await card.waitFor();
  const r = await card.evaluate((root) => {
    const dts = Array.from(root.querySelectorAll("dt")), dds = Array.from(root.querySelectorAll("dd"));
    const stacked = dts.every((dt, i) => { const a = dt.getBoundingClientRect(), b = dds[i]!.getBoundingClientRect(); return b.top >= a.bottom - 1 && Math.abs(b.left - a.left) < 2; });
    const broken: string[] = [];
    for (const dd of dds) {
      if (getComputedStyle(dd).wordBreak === "break-all") broken.push("word-break: break-all");
      const tw = document.createTreeWalker(dd, NodeFilter.SHOW_TEXT);
      while (tw.nextNode()) {
        const t = tw.currentNode as Text, s = t.data;
        const range = document.createRange();
        const tops: number[] = [];
        for (let i = 0; i < s.length; i++) { range.setStart(t, i); range.setEnd(t, i + 1); const rc = range.getClientRects(); tops.push(rc.length ? rc[0]!.top : NaN); }
        for (let i = 0; i + 1 < s.length; i++) {
          if (/\s/.test(s[i]!) || /\s/.test(s[i + 1]!) || Number.isNaN(tops[i]) || Number.isNaN(tops[i + 1])) continue;
          if (tops[i + 1]! > tops[i]! + 2 && !/[-_]/.test(s[i]!)) broken.push(`${s.slice(Math.max(0, i - 12), i + 1)}|${s.slice(i + 1, i + 8)}`);     // a line break between two letters of one word
        }
      }
    }
    const widest = Math.max(...dds.map((d) => d.scrollWidth - d.clientWidth));
    return { stacked, broken, widest, pairs: dts.length };
  });
  expect(r.pairs).toBeGreaterThanOrEqual(8);
  expect(r.stacked, "dt/dd pairs are stacked below 480 px").toBe(true);
  expect(r.broken, "words broken mid-word on the model card").toEqual([]);
  expect(r.widest).toBeLessThanOrEqual(0);
  await page.setViewportSize({ width: 900, height: 900 });                                     // and side by side when there is room
  const wide = await card.evaluate((root) => { const dt = root.querySelector("dt")!.getBoundingClientRect(), dd = root.querySelector("dd")!.getBoundingClientRect(); return dd.left > dt.right - 1; });
  expect(wide).toBe(true);
});

test("R10-04, R10-06, R10-14: populations are stated beside the economics, rows are not accounts, the prevalence constant is the Brier reference", async ({ page }) => {
  const errors = watch(page);
  await page.goto("capacity/");
  await ready(page);
  await page.getByTestId("published-table").waitFor();
  const text = (await page.getByTestId("published-economics").innerText()).replace(/\s+/g, " ");
  expect(text).toContain("scored accounts of the published cohort");
  await expect(fig(page, "cohort-scored")).toHaveText("97");
  expect(text).toContain("1,241 scored accounts");
  for (const [sid, cohort, full] of [["sc-001", "21.38", "81.13"], ["sc-002", "-6.87", "71.04"], ["sc-003", "-95.46", "-29.12"]] as const) {
    await expect(page.locator(`[data-testid=published-table] tr[data-scenario=${sid}] [data-k=ev]`)).toHaveText(cohort);
    await expect(page.locator(`[data-testid=published-table] tr[data-scenario=${sid}] [data-k=ev-full]`)).toHaveText(full);
  }
  await page.goto("models/");
  await ready(page);
  await page.getByTestId("model-table").waitFor();
  await expect(fig(page, "rows-n")).toHaveText("1,513");
  await expect(fig(page, "rows-accounts")).toHaveText("442");
  await expect(fig(page, "churn-rows-n")).toHaveText("189");
  await expect(fig(page, "churn-accounts")).toHaveText("95");
  await expect(page.getByTestId("rows-accounts")).toContainText("no confidence interval is given");
  await expect(page.locator("[data-testid=model-table] tr[data-model=prevalence_baseline] [data-k=brier]")).toHaveText("0.109664");
  await expect(page.locator("[data-testid=model-table] tr[data-model=prevalence_baseline] [data-k=ap]")).toHaveText("0.124917");
  await expect(page.locator("[data-margin=brier_under_prevalence_constant] [data-k=margin]")).toHaveText("0.004645");
  await expect(page.locator("[data-margin=brier_under_random]")).toContainText("uninformative");
  await expect(page.locator("[data-margin=brier_under_rule] [data-k=margin]")).toHaveText("0.004236");              // the declared margins stay as declared
  await expect(page.getByTestId("uninformative")).toContainText("uninformative");
  await page.getByTestId("pop-select").selectOption("test-3");                                                          // a single cutoff: fewer rows, still stated
  await expect(page.getByTestId("rows-accounts")).toContainText("distinct accounts");
  expect(errors).toEqual([]);
});

test("R10-07, R10-08, R10-09: the apac series and its false positives, Platt made the model worse, the largest regional gap was not designed", async ({ page }) => {
  const errors = watch(page);
  await page.goto("monitoring/");
  await ready(page);
  await page.getByTestId("apac-series").waitFor();
  await expect(fig(page, "apac-exceed")).toHaveText("10");
  await expect(fig(page, "apac-false")).toHaveText("5");
  await expect(fig(page, "apac-real")).toHaveText("5");
  await expect(fig(page, "apac-false-floored")).toHaveText("4");
  const series = (await page.locator("[data-k=apac-series]").innerText()).split(", ");
  expect(series).toHaveLength(21);
  expect(series.slice(0, 3)).toEqual(["0.108350", "0.638981", "0.051031"]);
  const note = (await page.getByTestId("apac-series").innerText()).replace(/\s+/g, " ");
  expect(note).toContain("false positives");
  expect(note).toContain("0.0001 floor");
  await page.goto("calibration/");
  await ready(page);
  await page.getByTestId("platt-worse").waitFor();
  await expect(fig(page, "platt-brier-before")).toHaveText("0.104515");
  await expect(fig(page, "platt-brier-after")).toHaveText("0.105019");
  await expect(fig(page, "platt-gap-before")).toHaveText("−2.26 pp");
  await expect(fig(page, "platt-gap-after")).toHaveText("−2.86 pp");
  await expect(fig(page, "platt-fit-n")).toHaveText("289");
  const platt = (await page.getByTestId("platt-worse").innerText()).replace(/\s+/g, " ");
  expect(platt).toContain("made the model worse");
  expect(platt).toContain("one cutoff");
  await expect(fig(page, "worst-region-gap")).toHaveText("−10.68 pp");
  const gap = (await page.getByTestId("apac-gap").innerText()).replace(/\s+/g, " ");
  expect(gap).toContain("apac");
  expect(gap).toContain("not designed");
  expect(gap).toContain("one-draw realisation");
  expect(errors).toEqual([]);
});

test("R10-05, R10-11, R10-13: the case study lists every outcome-informed choice, states the retained and fitted rows, and quotes the same counts as the evidence page", async ({ page }) => {
  const errors = watch(page);
  await page.goto("case-study/");
  await ready(page);
  await page.getByTestId("model-card").waitFor();
  await expect(page.locator("[data-k=train-rows]")).toHaveText("1,088 retained rows, 744 eligible and mature for fitting (79 churners)");
  await expect(page.locator("[data-k=validation-rows]")).toHaveText("384 retained rows, 289 eligible and mature for calibration (27 churners)");
  await expect(page.locator("[data-k=test-rows]")).toContainText("1,513 rows from 442 accounts");
  const items = manifest.disclosures.filter((d) => d.id === "D-G02" || d.id === "D-G03").flatMap((d) => d.items ?? []);
  expect(items.length).toBe(11);
  const listed = await page.locator("[data-testid=choices-list] li").allInnerTexts();
  expect(listed.map((t) => t.replace(/\s+/g, " ").trim())).toEqual(items.map((t) => t.replace(/\s+/g, " ").trim()));
  const choices = listed.join(" ");
  expect(choices).toContain("from 700 to 600");
  expect(choices).toContain("INJ-02 examples");
  expect(choices).toContain("hash of its id");
  const econ = (await page.locator("section[aria-labelledby=int-h]").innerText()).replace(/\s+/g, " ");
  expect(econ).toContain("97");
  expect(econ).toContain("scored accounts of the published cohort");
  expect(econ).toContain("1,241 scored accounts");
  expect(econ).toContain("81.13 at K 5");
  const counts = (await page.getByTestId("test-counts").innerText()).replace(/\s+/g, " ");
  const caseCounts = [TEST_COUNTS.pytest, TEST_COUNTS.reference, TEST_COUNTS.golden, TEST_COUNTS.review, TEST_COUNTS.e2e].map((n) => n.toLocaleString("en-US"));
  for (const n of caseCounts) expect(counts).toContain(n);
  await page.goto("evidence/");
  await ready(page);
  const evidenceCounts = (await page.getByTestId("test-counts").innerText()).replace(/\s+/g, " ");
  for (const n of caseCounts) expect(evidenceCounts).toContain(n);
  expect(errors).toEqual([]);
});
