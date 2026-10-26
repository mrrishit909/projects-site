import { expect, test } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { overflow, readData, ready, watch } from "./support";

const EVIDENCE = "evidence";
const WIDTHS = [360, 768, 1280, 1920];
const firstA = readData<{ rows: { product_id: string; abc_class: string }[] }>("products.json").rows.find((p) => p.abc_class === "A")!.product_id;
const ROUTES: { name: string; url: string; wait: string }[] = [
  { name: "home", url: "./", wait: ".landing" },
  { name: "overview", url: "overview/", wait: "[data-testid=by-location]" },
  { name: "skus", url: `skus/?sku=${firstA}`, wait: "[data-testid=trajectory]" },
  { name: "forecast", url: "forecast/", wait: "[data-testid=forecast-table]" },
  { name: "reorder", url: "reorder/", wait: "[data-testid=reorder-table]" },
  { name: "case-study", url: "case-study/", wait: "[data-testid=designed-relationships]" },
];
const index: { file: string; route: string; width: number; scrollWidth: number; innerWidth: number; deviceScaleFactor: number }[] = [];

test.beforeAll(() => mkdirSync(EVIDENCE, { recursive: true }));
test.afterAll(() => writeFileSync(`${EVIDENCE}/index.json`, JSON.stringify({ generated_by: "e2e/screens.spec.ts", count: index.length, shots: index }, null, 2)));

for (const width of WIDTHS) {
  test.describe(`width ${width}`, () => {
    test.use({ viewport: { width, height: 900 } });
    for (const r of ROUTES) {
      test(`${r.name} at ${width}px`, async ({ page }) => {
        const errors = watch(page);
        await page.goto(r.url);
        await ready(page);
        await page.locator(r.wait).first().waitFor();
        const o = await overflow(page);
        expect(o.scrollWidth, `${r.name} overflows at ${width}`).toBeLessThanOrEqual(o.innerWidth);
        const file = `${r.name}-${width}.png`;
        await page.screenshot({ path: `${EVIDENCE}/${file}`, fullPage: true });
        index.push({ file, route: r.url, width, ...o, deviceScaleFactor: 1 });
        expect(errors).toEqual([]);
      });
    }
  });
}

test.describe("200% zoom", () => {
  test.use({ viewport: { width: 640, height: 450 }, deviceScaleFactor: 2 });
  test("skus at 200% zoom (640 css px viewport, device scale 2)", async ({ page }) => {
    const errors = watch(page);
    await page.goto(`skus/?sku=${firstA}`);
    await ready(page);
    await page.locator("[data-testid=trajectory]").waitFor();
    const o = await overflow(page);
    expect(o.scrollWidth).toBeLessThanOrEqual(o.innerWidth);
    await page.screenshot({ path: `${EVIDENCE}/skus-zoom200.png`, fullPage: true });
    index.push({ file: "skus-zoom200.png", route: `skus/?sku=${firstA}`, width: 640, ...o, deviceScaleFactor: 2 });
    expect(errors).toEqual([]);
  });
});
