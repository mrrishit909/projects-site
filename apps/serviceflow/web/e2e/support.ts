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

/** The snapshot is loaded (the manifest strip shows the dataset) and the view has its heading. */
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
