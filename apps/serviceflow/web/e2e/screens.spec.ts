import { expect, test } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { overflow, ready, watch } from "./support";

const EVIDENCE = "evidence";
const WIDTHS = [360, 768, 1280, 1920];
const ROUTES: { name: string; url: string; wait: string }[] = [
  { name: "home", url: "./", wait: "[data-testid=glance]" },
  { name: "overview", url: "overview/", wait: "[data-testid=metric-sheet]" },
  { name: "queues", url: "queues/", wait: "[data-testid=stub]" },
  { name: "tickets", url: "tickets/", wait: "[data-testid=timeline]" },
  { name: "staffing", url: "staffing/", wait: "[data-testid=shift-grid]" },
  { name: "sla", url: "sla/", wait: "[data-testid=sla-table]" },
  { name: "simulation", url: "simulation/", wait: "[data-testid=studio-result]" },
  { name: "compare", url: "compare/", wait: "[data-testid=stub]" },
  { name: "surveys", url: "surveys/", wait: "[data-testid=stub]" },
  { name: "evidence", url: "evidence/", wait: "[data-testid=live-summary]" },
  { name: "case-study", url: "case-study/", wait: "[data-testid=tech-p1]" },
];
const index: { file: string; route: string; width: number; scrollWidth: number; innerWidth: number; deviceScaleFactor: number; zoom: string }[] = [];

test.beforeAll(() => mkdirSync(EVIDENCE, { recursive: true }));
test.afterAll(() => writeFileSync(`${EVIDENCE}/index.json`, JSON.stringify({ generated_by: "e2e/screens.spec.ts", count: index.length, shots: index }, null, 2)));

async function shoot(page: import("@playwright/test").Page, r: (typeof ROUTES)[number], width: number, dsf: number, zoom: string): Promise<void> {
  const errors = watch(page);
  await page.goto(r.url);
  await ready(page);
  await page.locator(r.wait).first().waitFor({ timeout: 30_000 });
  const o = await overflow(page);
  if (o.scrollWidth > o.innerWidth) {
    const wide = await page.evaluate((iw) => Array.from(document.querySelectorAll("body *")).map((el) => { const b = el.getBoundingClientRect(); return [Math.round(b.right), el.tagName, String(el.className).slice(0, 40), (el.textContent || "").trim().slice(0, 30)]; }).filter((x) => (x[0] as number) > iw).slice(0, 20), o.innerWidth);
    writeFileSync(`${EVIDENCE}/overflow-${r.name}-${width}-${zoom}.json`, JSON.stringify(wide, null, 1));
  }
  expect(o.scrollWidth, `${r.name} overflows at ${width} (${zoom})`).toBeLessThanOrEqual(o.innerWidth);
  const file = zoom === "100%" ? `${r.name}-${width}.png` : `${r.name}-zoom200.png`;
  await page.screenshot({ path: `${EVIDENCE}/${file}`, fullPage: true });
  index.push({ file, route: r.url, width, ...o, deviceScaleFactor: dsf, zoom });
  expect(errors).toEqual([]);
}

for (const width of WIDTHS) {
  test.describe(`width ${width}`, () => {
    test.use({ viewport: { width, height: 900 } });
    for (const r of ROUTES) test(`${r.name} at ${width}px`, async ({ page }) => { await shoot(page, r, width, 1, "100%"); });
  });
}

test.describe("200% zoom (640 css px viewport, device scale 2)", () => {
  test.use({ viewport: { width: 640, height: 450 }, deviceScaleFactor: 2 });
  for (const r of ROUTES) test(`${r.name} at 200% zoom`, async ({ page }) => { await shoot(page, r, 640, 2, "200%"); });
});
