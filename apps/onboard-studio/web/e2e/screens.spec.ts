import { expect, test } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { overflow, readData, ready, watch } from "./support";

const EVIDENCE = "evidence";
const resolve = (d: string, f: string): string => `${d}/${f}`;
const WIDTHS = [360, 768, 1280, 1920];
const firstCase = readData<{ rows: { case_id: string }[] }>("cases.json").rows[0]!.case_id;
const ROUTES: { name: string; url: string; wait: string }[] = [
  { name: "home", url: "./", wait: ".landing" },
  { name: "cases", url: `cases/?case=${firstCase}`, wait: ".tl__svg" },
  { name: "workflow", url: "workflow/", wait: ".dag__svg" },
  { name: "sla", url: "sla/", wait: ".hists" },
  { name: "queue", url: "queue/", wait: "[data-testid=queue-table]" },
  { name: "case-study", url: "case-study/", wait: "[data-testid=designed-relationships]" },
];
const index: { file: string; route: string; width: number; scrollWidth: number; innerWidth: number; deviceScaleFactor: number }[] = [];

test.beforeAll(() => mkdirSync(EVIDENCE, { recursive: true }));
test.afterAll(() => writeFileSync(resolve(EVIDENCE, "index.json"), JSON.stringify({ generated_by: "e2e/screens.spec.ts", shots: index }, null, 2)));

for (const width of WIDTHS) {
  test.describe(`width ${width}`, () => {
    test.use({ viewport: { width, height: 900 } });
    for (const r of ROUTES) {
      test(`${r.name} at ${width}px`, async ({ page }) => {
        const errors = watch(page);
        await page.goto(r.url);
        await ready(page);
        await page.locator(r.wait).first().waitFor();
        if (r.name === "cases") await expect(page.getByRole("list", { name: "Case facts" })).toContainText(firstCase);
        const o = await overflow(page);
        expect(o.scrollWidth, `${r.name} overflows at ${width}`).toBeLessThanOrEqual(o.innerWidth);
        const file = `${r.name}-${width}.png`;
        await page.screenshot({ path: resolve(EVIDENCE, file), fullPage: true });
        index.push({ file, route: r.url, width, ...o, deviceScaleFactor: 1 });
        expect(errors).toEqual([]);
      });
    }
  });
}

test.describe("200% zoom", () => {
  test.use({ viewport: { width: 640, height: 450 }, deviceScaleFactor: 2 });
  test("cases at 200% zoom (640 css px viewport, device scale 2)", async ({ page }) => {
    const errors = watch(page);
    await page.goto(`cases/?case=${firstCase}`);
    await ready(page);
    await page.locator(".tl__svg").waitFor();
    const o = await overflow(page);
    expect(o.scrollWidth).toBeLessThanOrEqual(o.innerWidth);
    await page.screenshot({ path: resolve(EVIDENCE, "cases-zoom200.png"), fullPage: true });
    index.push({ file: "cases-zoom200.png", route: `cases/?case=${firstCase}`, width: 640, ...o, deviceScaleFactor: 2 });
    expect(errors).toEqual([]);
  });
});
