// Screenshots of every entry route at four widths (and a 200% zoom run), with overflow and console checks.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";

const OUT = new URL("../evidence/", import.meta.url);
const WIDTHS = [360, 768, 1280, 1920];
const ROUTES = ["", "overview/", "bridge/", "evidence/", "case-study/"];
const name = (route: string): string => (route === "" ? "landing" : route.replace(/\/$/, ""));
const shots: { file: string; route: string; width: number; scrollWidth: number; innerWidth: number; note?: string }[] = [];

async function ready(page: Page, route: string): Promise<void> {
  if (route === "overview/") await expect(page.getByTestId("trend-svg")).toBeVisible();
  if (route === "bridge/") await expect(page.getByTestId("step-contribution")).toBeVisible();
  if (route === "evidence/") await expect(page.getByTestId("ledger-totals")).toBeVisible();
  if (route === "case-study/") await expect(page.getByRole("heading", { name: "Limits" })).toBeVisible();
  if (route === "") await expect(page.getByRole("heading", { name: "Revenue Atlas" }).first()).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
}

test.beforeAll(() => mkdirSync(OUT, { recursive: true }));
test.afterAll(() => {
  mkdirSync(OUT, { recursive: true });
  writeFileSync(new URL("index.json", OUT), JSON.stringify({ generated_at: new Date().toISOString(), count: shots.length, screenshots: shots }, null, 2) + "\n");
});

for (const width of WIDTHS) {
  for (const route of ROUTES) {
    test(`screen ${name(route)} at ${width}px`, async ({ browser }) => {
      const ctx = await browser.newContext({ viewport: { width, height: 900 }, baseURL: test.info().project.use.baseURL! });
      const page = await ctx.newPage();
      const problems: string[] = [];
      page.on("console", (m) => { if (m.type() === "error") problems.push(m.text()); });
      page.on("pageerror", (e) => problems.push(e.message));
      await page.goto(route);
      await ready(page, route);
      const m = await page.evaluate(() => ({ sw: document.scrollingElement!.scrollWidth, iw: window.innerWidth }));
      expect(m.sw, `${route} at ${width}: scrollWidth ${m.sw} > innerWidth ${m.iw}`).toBeLessThanOrEqual(m.iw);
      const file = `${name(route)}-${width}.png`;
      await page.screenshot({ path: new URL(file, OUT).pathname, fullPage: true });
      shots.push({ file, route: `/${route}`, width, scrollWidth: m.sw, innerWidth: m.iw });
      expect(problems).toEqual([]);
      await ctx.close();
    });
  }
}

test("bridge at 200% zoom (640 CSS px wide viewport, deviceScaleFactor 2)", async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 640, height: 450 }, deviceScaleFactor: 2, baseURL: test.info().project.use.baseURL! });
  const page = await ctx.newPage();
  const problems: string[] = [];
  page.on("console", (m) => { if (m.type() === "error") problems.push(m.text()); });
  page.on("pageerror", (e) => problems.push(e.message));
  await page.goto("bridge/");
  await ready(page, "bridge/");
  const m = await page.evaluate(() => ({ sw: document.scrollingElement!.scrollWidth, iw: window.innerWidth }));
  expect(m.sw).toBeLessThanOrEqual(m.iw);
  await page.screenshot({ path: new URL("bridge-zoom200.png", OUT).pathname, fullPage: true });
  shots.push({ file: "bridge-zoom200.png", route: "/bridge/", width: 640, scrollWidth: m.sw, innerWidth: m.iw, note: "1280 CSS px at 200% zoom = 640 CSS px viewport, deviceScaleFactor 2" });
  expect(problems).toEqual([]);
  await ctx.close();
});
