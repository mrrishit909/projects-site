// Part 2 journey: overview -> bridge -> ledger -> filters -> export, on the production build under the nested base.
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";

const watch = (page: Page): string[] => {
  const problems: string[] = [];
  page.on("console", (m) => { if (m.type() === "error") problems.push(`console: ${m.text()}`); });
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  // A request aborted by our own navigation or reload (net::ERR_ABORTED) is not a failure of the page.
  page.on("requestfailed", (r) => { if (r.failure()?.errorText !== "net::ERR_ABORTED") problems.push(`requestfailed: ${r.url()}`); });
  return problems;
};
const noOverflow = async (page: Page): Promise<void> => {
  const m = await page.evaluate(() => ({ sw: document.scrollingElement!.scrollWidth, iw: window.innerWidth }));
  expect(m.sw, `scrollWidth ${m.sw} vs innerWidth ${m.iw}`).toBeLessThanOrEqual(m.iw);
};
const text = async (page: Page, id: string): Promise<string> => ((await page.getByTestId(id).textContent()) ?? "").trim();

test("journey: overview, bridge, ledger, filters, export, not-found", async ({ page, request }) => {
  const problems = watch(page);
  const manifest = await (await request.get("data/manifest.json")).json();

  // Direct entry and reload keep the route.
  const res = await page.goto("overview/");
  expect(res?.status()).toBe(200);
  await expect(page).toHaveTitle(/Revenue Atlas/);
  await expect(page.getByTestId("trend-svg")).toBeVisible();
  await expect(page.getByTestId("population-summary")).toContainText("Shipment date, UTC");
  await expect(page.getByTestId("rate-comparison")).toContainText("%");
  await expect(page.getByTestId("trend-table").locator("tbody tr")).toHaveCount(24);
  await noOverflow(page);
  await page.reload();
  expect(new URL(page.url()).pathname).toMatch(/\/overview\/$/);
  await expect(page.getByTestId("trend-svg")).toBeVisible();

  // Overview -> bridge via the primary action.
  await page.getByTestId("open-bridge").click();
  await expect(page).toHaveURL(/\/bridge\/$/);
  await expect(page.getByTestId("step-contribution")).toBeVisible();
  await expect(page.getByTestId("reconcile")).toContainText("Steps reconcile: allocation residual 0.00");
  await expect(page.getByTestId("region-table")).toContainText("UNASSIGNED");
  await noOverflow(page);
  const bridgeCm = await text(page, "step-contribution");
  expect(bridgeCm).toMatch(/^-?[\d,]+\.\d{2}$/);

  // Click a step -> evidence with highlight; totals equal the bridge (default filters).
  await page.getByTestId("drill-contribution").click();
  await expect(page).toHaveURL(/\/evidence\/\?hl=contribution$/);
  await expect(page.getByTestId("highlight-note")).toContainText("Contribution margin");
  await expect(page.locator('th[data-col="freight"][data-highlight="true"]')).toBeVisible();
  await expect(page.locator('th[data-col="region"][data-highlight="true"]')).toHaveCount(0);
  expect(await text(page, "totals-contribution")).toBe(bridgeCm);
  await expect(page.getByTestId("ledger-totals-row")).toBeVisible();
  const allCount = Number((await text(page, "population-count")).replace(/,/g, ""));
  expect(allCount).toBeGreaterThan(6000);
  await expect(page.getByTestId("quarantine-note")).toContainText("COST_VERSION_AMBIGUOUS");
  await noOverflow(page);

  // Ledger sorts (keyboard-operable header buttons), ties by line id.
  const firstCell = () => page.getByTestId("ledger").locator("tbody tr").first().locator('td[data-col="line"]').textContent();
  await page.getByRole("button", { name: /^Line/ }).focus();
  await page.keyboard.press("Enter");
  const asc = await firstCell();
  await page.keyboard.press("Enter");
  const desc = await firstCell();
  expect(asc).not.toBe(desc);
  await expect(page.getByTestId("ledger").locator("tbody tr")).toHaveCount(50);
  await page.getByRole("button", { name: "Next page" }).click();
  await expect(page.getByTestId("page-status")).toContainText("Rows 51–100");

  // Region filter via the UI: URL updates, totals change; Clear filters restores.
  await page.getByLabel("Region").selectOption("reg-west");
  await expect(page).toHaveURL(/region=reg-west/);
  await expect(page.getByTestId("active-filters")).toContainText("region reg-west");
  const westCm = await text(page, "totals-contribution");
  expect(westCm).not.toBe(bridgeCm);
  const westCount = Number((await text(page, "population-count")).replace(/,/g, ""));
  expect(westCount).toBeLessThan(allCount);

  // Same filters on the bridge give the same contribution as the ledger.
  await page.getByRole("link", { name: "Compare with the margin bridge" }).click();
  await expect(page).toHaveURL(/\/bridge\/\?region=reg-west$/);
  expect(await text(page, "step-contribution")).toBe(westCm);
  await page.goBack();
  await expect(page).toHaveURL(/\/evidence\//);

  // Export the current filtered population.
  const [dl] = await Promise.all([page.waitForEvent("download"), page.getByTestId("export-filtered").click()]);
  const csv = readFileSync(await dl.path(), "utf8");
  const head = csv.split(/\r?\n/).filter((l) => l.startsWith("#"));
  const joined = head.join("\n");
  expect(joined).toContain(`contract_version: ${manifest.contract_version}`);
  expect(joined).toContain(`dataset_version: ${manifest.dataset_version}`);
  expect(joined).toContain(`dataset_hash: ${manifest.dataset_hash}`);
  expect(joined).toContain("region reg-west");
  const body = csv.split(/\r?\n/).filter((l) => l !== "" && !l.startsWith("#"));
  expect(body.length - 1).toBe(westCount); // minus the column-header row
  expect(joined).toContain(`row_count: ${westCount}`);

  // Full population export is labelled and bigger.
  const [dl2] = await Promise.all([page.waitForEvent("download"), page.getByTestId("export-full").click()]);
  const csv2 = readFileSync(await dl2.path(), "utf8");
  expect(csv2.split(/\r?\n/).filter((l) => l !== "" && !l.startsWith("#")).length - 1).toBe(allCount);
  expect(csv2).toContain("scope: full population");

  // Clear filters restores.
  await page.getByRole("button", { name: "Clear filters" }).click();
  await expect(page).not.toHaveURL(/region=/);
  expect(await text(page, "totals-contribution")).toBe(bridgeCm);
  expect(Number((await text(page, "population-count")).replace(/,/g, ""))).toBe(allCount);

  // A deep link applies filters and an empty window gives an explicit empty state, not totals.
  await page.goto("evidence/?from=2030-01-01&to=2030-02-01");
  await expect(page.getByTestId("empty-state")).toContainText("No shipment lines match");
  await expect(page.getByTestId("ledger-totals")).toHaveCount(0);
  await page.getByRole("button", { name: "Clear filters" }).first().click();
  await expect(page.getByTestId("ledger-totals")).toBeVisible();

  // Case study and unknown route.
  await page.goto("case-study/");
  await expect(page.getByRole("heading", { name: "Analytical choices" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Continuous-integration runs/ })).toHaveAttribute("href", "https://github.com/mrrishit909/projects-site/actions/workflows/revenue-atlas-ci.yml");
  await noOverflow(page);
  await page.goto("no-such-screen/");
  await expect(page.getByRole("heading", { name: /not in the atlas/ })).toBeVisible();
  await noOverflow(page);

  expect(problems).toEqual([]);
});

test("golden dataset: bridge and ledger show the hand-derived after-return answers (P01-GOLD-06)", async ({ page }) => {
  const problems = watch(page);
  await page.goto("bridge/?dataset=golden");
  await expect(page.getByTestId("golden-banner")).toBeVisible();
  const expected: Record<string, string> = {
    gross: "250.00", discounts: "-25.00", credits: "-90.00", net: "135.00", cogs: "-80.00",
    gross_profit: "55.00", shipping_revenue: "0.00", shipping_cost: "-15.00", contribution: "40.00",
  };
  for (const [id, v] of Object.entries(expected)) await expect(page.getByTestId(`step-${id}`)).toHaveText(v);
  await expect(page.getByTestId("reconcile")).toContainText("Steps reconcile: allocation residual 0.00");
  await expect(page.getByTestId("population-count")).toHaveText("2");
  // Ledger for the same dataset: totals equal the bridge.
  await page.goto("evidence/?dataset=golden");
  const want: Record<string, string> = { gross: "250.00", discounts: "25.00", credits: "90.00", net: "135.00", cogs: "80.00", gross_profit: "55.00", shipping_cost: "15.00", contribution: "40.00" };
  for (const [id, v] of Object.entries(want)) await expect(page.getByTestId(`totals-${id}`)).toHaveText(v);
  await expect(page.getByTestId("ledger").locator("tbody tr")).toHaveCount(2);
  await expect(page.getByTestId("quarantine-note")).toContainText("No records were quarantined");
  expect(problems).toEqual([]);
});

test("clicking a waterfall bar drills into the ledger with that step highlighted", async ({ page }) => {
  const problems = watch(page);
  await page.goto("bridge/?region=reg-north");
  await page.getByTestId("bar-discounts").click();
  await expect(page).toHaveURL(/\/evidence\/\?region=reg-north&hl=discounts$/);
  await expect(page.locator('th[data-col="discount"][data-highlight="true"]')).toBeVisible();
  await expect(page.getByTestId("highlight-note")).toContainText("Allocated discounts");
  expect(problems).toEqual([]);
});

test("R-04 / D-09: a window holding credits for earlier shipments shows credit rows and the ledger equals the bridge", async ({ page }) => {
  const problems = watch(page);
  await page.goto("bridge/?from=2024-11-01&to=2024-12-01");
  await expect(page.getByTestId("credit-basis-note")).toContainText("credits dated inside it for lines shipped earlier");
  const want: Record<string, string> = {};
  for (const id of ["gross", "discounts", "credits", "net", "contribution"]) want[id] = (await text(page, `step-${id}`)).replace(/^-/, "");
  expect(want.credits).toBe("6,096.40"); // the SQL month table (credit month 2024-11), not the shipment-month 15,266.75
  await page.goto("evidence/?from=2024-11-01&to=2024-12-01");
  await expect(page.getByTestId("outside-credits")).toBeVisible();
  await expect(page.getByTestId("outside-credits-table").locator("tbody tr").first()).toBeVisible();
  for (const [step, id] of [["gross", "gross"], ["discounts", "discounts"], ["credits", "credits"], ["net", "net"], ["contribution", "contribution"]] as const) {
    expect((await text(page, `totals-${id}`)).replace(/^-/, "")).toBe(want[step]);
  }
  // The overview month for 2024-11 carries the same credits.
  await page.goto("overview/");
  const row = page.getByTestId("trend-table").locator("tbody tr").filter({ hasText: "2024-11" });
  await expect(row).toHaveCount(1);
  expect(problems).toEqual([]);
});
