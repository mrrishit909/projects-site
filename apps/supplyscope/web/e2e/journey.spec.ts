import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { expectNoOverflow, readData, ready, watch } from "./support";

interface Manifest { contract_version: string; dataset_version: string; dataset_hash: string }
interface Rows<T> { rows: T[] }
const manifest = readData<Manifest>("manifest.json");
const injections = readData<{ injections: { id: string; record_ids: string[] }[] }>("injection-manifest.json").injections;
const intermittent = injections.find((i) => i.id === "INJ-05")!.record_ids[0]!; // a designed intermittent SKU

const figure = (page: Page, name: string) => page.locator(`[data-figure="${name}"] dd`).first();

test("direct entry to /reorder/ and reload keep the route", async ({ page }) => {
  const errors = watch(page);
  await page.goto("reorder/");
  await ready(page);
  await expect(page).toHaveTitle(/SupplyScope/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Reorder workbench");
  await expect(page.getByTestId("draft-banner")).toContainText("Draft, never a purchase order");
  await expect(page.getByTestId("reorder-table")).toBeVisible();
  await page.reload();
  await ready(page);
  expect(new URL(page.url()).pathname).toMatch(/\/reorder\/$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Reorder workbench");
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("the golden SKU shows on hand 40, on order 30, backorders 10, position 60, ROP 70, target 120, raw 60, after MOQ 60, draft 72 and the arithmetic", async ({ page }) => {
  const errors = watch(page);
  await page.goto("skus/?dataset=golden&sku=prod-001&loc=loc-001");
  await ready(page);
  await expect(page.locator("footer")).toContainText("golden fixture");
  const want: [string, string][] = [["on_hand", "40"], ["on_order", "30"], ["backorders", "10"], ["position", "60"], ["rop", "70"], ["target", "120"], ["raw", "60"], ["after_moq", "60"], ["draft", "72"], ["reserved", "0"], ["available", "40"]];
  for (const [k, v] of want) await expect(figure(page, k), k).toHaveText(v);
  await expect(page.getByTestId("arithmetic")).toContainText("raw 60 → MOQ 50: 60 → pack 24: 72");
  await expect(page.getByTestId("arithmetic")).toContainText("Draft order, never a purchase order");
  // the trajectory is drawn and its table lists the marks (one receipt-free window: the 03-12 stockout and three receipts)
  await expect(page.getByTestId("trajectory")).toBeVisible();
  await expect(page.getByTestId("events-table")).toContainText("Stockout day");
  await expect(page.getByTestId("events-table")).toContainText("2026-03-12");
  await expect(page.getByTestId("censor-sentence")).toContainText("observed sales only");

  await page.goto("skus/?dataset=golden&sku=prod-001&loc=loc-001&state=position_80");
  await ready(page);
  await expect(figure(page, "position")).toHaveText("80");
  await expect(figure(page, "on_order")).toHaveText("50");
  await expect(figure(page, "draft")).toHaveText("0");
  await expect(figure(page, "raw")).toHaveText("0");
  await expect(page.getByTestId("arithmetic")).toContainText("position 80 ≥ reorder point 70: not triggered");
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("the SKU picker and the location are URL view settings", async ({ page }) => {
  const errors = watch(page);
  await page.goto("skus/");
  await ready(page);
  const second = readData<Rows<{ product_id: string }>>("products.json").rows[1]!.product_id;
  await page.locator("#sku-picker").selectOption(second);
  expect(new URL(page.url()).searchParams.get("sku")).toBe(second);
  await expect(page.getByTestId("sku-figures")).toBeVisible();
  await expect(page.getByRole("heading", { name: new RegExp(`SKU-0\\d\\d at loc-0\\d at`) })).toBeVisible();
  await page.locator("#loc-picker").selectOption("loc-03");
  expect(new URL(page.url()).searchParams.get("loc")).toBe("loc-03");
  expect(errors).toEqual([]);
});

test("forecast shows the baselines and model, and a null WAPE for an intermittent SKU's zero-demand folds", async ({ page }) => {
  const errors = watch(page);
  await page.goto("forecast/");
  await ready(page);
  const models = page.getByTestId("models-table");
  await expect(models).toContainText("Naive");
  await expect(models).toContainText("Seasonal naive");
  await expect(models).toContainText("Model (EWMA");
  await expect(page.getByTestId("beats-ewma")).toContainText(/(yes|no|not judged) \(vs seasonal naive\)/);
  await expect(page.getByTestId("forecast-table").locator("tbody tr")).toHaveCount(readData<Manifest & { row_counts: Record<string, number> }>("manifest.json").row_counts["replenishment_params"]!);

  await page.goto(`forecast/?sku=${intermittent}`);
  await ready(page);
  await expect(page.getByTestId("forecast-detail")).toContainText(intermittent.replace("prod", "SKU"));
  const folds = page.getByTestId("folds-table");
  await expect(folds).toBeVisible();
  expect(await folds.locator("code.null").count(), "null WAPE cells of zero-demand folds").toBeGreaterThan(0);
  await expect(page.getByTestId("forecast-detail")).toContainText(/[1-9]\d* of them with zero actual demand/);
  // a fold with actual demand has a numeric WAPE; a null is never rendered as 0
  const nullRows = await folds.locator("tbody tr").evaluateAll((trs) => trs.filter((tr) => tr.querySelector("code.null")).map((tr) => tr.children[2]!.textContent));
  expect(nullRows.every((a) => a === "0")).toBe(true);
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("reorder: location filter in the URL changes the row count, Clear filters restores, CSV matches the visible rows", async ({ page }) => {
  const errors = watch(page);
  await page.goto("reorder/");
  await ready(page);
  const shown = async (): Promise<number> => Number(await page.getByTestId("population-shown").innerText());
  const bodyRows = (): Promise<number> => page.getByTestId("reorder-table").locator("tbody tr").count();
  const total = await shown();
  expect(total).toBe(readData<Manifest & { row_counts: Record<string, number> }>("manifest.json").row_counts["replenishment_params"]);
  expect(await bodyRows()).toBe(total);

  await page.locator("#f-loc").selectOption("loc-02");
  expect(new URL(page.url()).searchParams.get("loc")).toBe("loc-02");
  await expect.poll(shown).toBeLessThan(total);
  const n = await shown();
  expect(n).toBeGreaterThan(0);
  expect(await bodyRows()).toBe(n);

  await page.reload(); // the filter lives in the address
  await ready(page);
  expect(await shown()).toBe(n);

  const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("export-csv").click()]);
  const text = readFileSync(await download.path(), "utf8");
  const lines = text.split("\r\n").filter((l) => l.length > 0);
  const header = lines.filter((l) => l.startsWith("#"));
  const body = lines.filter((l) => !l.startsWith("#"));
  expect(header).toContain(`# contract_version: ${manifest.contract_version}`);
  expect(header).toContain(`# dataset_version: ${manifest.dataset_version}`);
  expect(header).toContain(`# dataset_hash: ${manifest.dataset_hash}`);
  expect(header.some((l) => l.startsWith("# as_of: 2026-09-30T23:59:59Z"))).toBe(true);
  expect(header.some((l) => l.includes("location = loc-02"))).toBe(true);
  expect(header).toContain(`# row_count: ${n}`);
  expect(header[0]).toContain("never a purchase order");
  expect(body.length - 1).toBe(n); // minus the column header
  expect(body[0]).toMatch(/^status,sku,product_id,location_id,/);
  expect(body.slice(1).every((l) => l.startsWith("draft,") && l.split(",")[3] === "loc-02")).toBe(true);
  expect(download.suggestedFilename()).toContain(manifest.dataset_version);

  await page.getByTestId("clear-filters").click();
  expect(new URL(page.url()).searchParams.get("loc")).toBeNull();
  await expect.poll(shown).toBe(total);
  expect(await bodyRows()).toBe(total);
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("reorder table sorts with the keyboard and shows the arithmetic", async ({ page }) => {
  const errors = watch(page);
  await page.goto("reorder/?dataset=golden");
  await ready(page);
  await expect(page.getByTestId("reorder-table").locator("tbody tr")).toHaveCount(1);
  await expect(page.getByTestId("reorder-table")).toContainText("120 − 60 = 60 → MOQ 50: 60 → pack 24: 72");
  await page.goto("reorder/");
  await ready(page);
  const header = page.getByRole("columnheader", { name: /^Position/ });
  await header.getByRole("button").focus();
  await page.keyboard.press("Enter");
  await expect(header).toHaveAttribute("aria-sort", "ascending");
  await page.keyboard.press("Enter");
  await expect(header).toHaveAttribute("aria-sort", "descending");
  expect(errors).toEqual([]);
});

test("overview: the as-of picker is a URL setting; quarantine lists the injected rejections", async ({ page }) => {
  const errors = watch(page);
  await page.goto("overview/");
  await ready(page);
  await expect(page.getByTestId("by-location")).toContainText("loc-01");
  await expect(page.getByTestId("by-supplier")).toContainText("sup-03");
  const wc = async (): Promise<string> => (await figure(page, "working_capital").innerText());
  const wc0 = await wc();
  const rejected = page.getByTestId("rejected-table").locator("tbody tr");
  await expect(rejected).toHaveCount(4);
  for (const id of ["mv-002230", "mv-006574", "mv-005418", "rcpt-01309"]) await expect(page.getByTestId("rejected-table")).toContainText(id);
  await page.locator("#as-of").fill("2025-12-31");
  expect(new URL(page.url()).searchParams.get("as_of")).toBe("2025-12-31");
  await expect(page.getByTestId("as-of-line")).toContainText("2025-12-31");
  await expect.poll(wc).not.toBe(wc0);
  await page.goto("overview/?as_of=2031-01-01");
  await ready(page);
  await expect(page.getByRole("alert")).toContainText("outside the data");
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("case study carries the evidence links, the decision records and the designed relationships", async ({ page }) => {
  const errors = watch(page);
  await page.goto("case-study/");
  await ready(page);
  await expect(page.getByRole("link", { name: /CI workflow/ })).toHaveAttribute("href", "https://github.com/mrrishit909/projects-site/actions/workflows/supplyscope-ci.yml");
  await expect(page.getByRole("link", { name: "Back to the portfolio" })).toHaveAttribute("href", "https://mrrishit909.github.io/projects-site/");
  await expect(page.getByTestId("designed-relationships").locator("li")).toHaveCount(readData<{ designed_relationships: string[] }>("injection-manifest.json").designed_relationships.length);
  for (const d of ["D-01", "D-02", "D-03", "D-04", "D-05", "D-06"]) await expect(page.getByRole("main")).toContainText(d);
  expect(errors).toEqual([]);
});

test("landing: decision, start link, mode disclosure and links", async ({ page }) => {
  const errors = watch(page);
  await page.goto("./");
  await ready(page);
  await expect(page.getByTestId("decision")).toContainText("What should be ordered, when");
  await expect(page.getByRole("heading", { name: "Mode disclosure" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Portfolio entry" })).toHaveAttribute("href", "https://mrrishit909.github.io/projects-site/supplyscope/");
  await expect(page.getByRole("link", { name: /Source on GitHub/ })).toHaveAttribute("href", "https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/supplyscope");
  await expect(page.getByRole("link", { name: /Evidence: CI workflow/ })).toHaveAttribute("href", "https://github.com/mrrishit909/projects-site/actions/workflows/supplyscope-ci.yml");
  await page.getByRole("link", { name: "Start the demo" }).click();
  await ready(page);
  expect(new URL(page.url()).pathname).toMatch(/\/reorder\/$/);
  expect(errors).toEqual([]);
});

test("in-progress routes are marked in the nav and an unknown route is not-found", async ({ page }) => {
  const errors = watch(page);
  await page.goto("./");
  await ready(page);
  for (const name of ["Locations", "Suppliers", "Simulator", "Capital", "Draft"]) {
    await expect(page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: new RegExp(`^${name} in progress`) })).toBeVisible();
  }
  await page.goto("locations/");
  await ready(page);
  await expect(page.getByRole("main")).toContainText("In progress");
  await page.goto("no-such-route/");
  await ready(page);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("This page is not part of SupplyScope");
  // not-found may be served with a 404 status by some servers; only page-level errors count here
  expect(errors.filter((e) => e.startsWith("pageerror"))).toEqual([]);
});

test("the footer prints the provenance, and every route renders without console errors or horizontal overflow", async ({ page }) => {
  const errors = watch(page);
  for (const r of ["./", "overview/", "skus/", "locations/", "suppliers/", "forecast/", "reorder/", "simulator/", "capital/", "draft/", "case-study/"]) {
    await page.goto(r);
    await ready(page);
    await expectNoOverflow(page);
  }
  const footer = page.locator("footer .provenance");
  await expect(footer).toContainText(manifest.dataset_version);
  await expect(footer).toContainText("contract_version");
  await expect(footer).toContainText("not recorded");
  await expect(page.locator("footer")).toContainText("Synthetic data");
  expect(errors).toEqual([]);
});
