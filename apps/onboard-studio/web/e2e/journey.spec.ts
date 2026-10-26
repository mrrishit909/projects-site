import { expect, test } from "@playwright/test";
import { expectNoOverflow, readData, ready, watch } from "./support";

interface Manifest { contract_version: string; dataset_version: string; dataset_hash: string }
interface Rows<T> { rows: T[] }
const manifest = readData<Manifest>("manifest.json");

const figure = (page: import("@playwright/test").Page, name: string) => page.locator(`[data-figure="${name}"] dd`);

test("direct entry to /cases/ and reload keep the route", async ({ page }) => {
  const errors = watch(page);
  await page.goto("cases/");
  await ready(page);
  await expect(page).toHaveTitle(/Onboard Studio/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/One case, one business-hours axis/);
  await expect(page.locator(".tl__svg")).toBeVisible();
  await page.reload();
  await ready(page);
  expect(new URL(page.url()).pathname).toMatch(/\/cases\/$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/One case/);
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("the golden case shows calendar 66, business 2, paused 65, active 1 and SLA met; the pause toggle recomputes", async ({ page }) => {
  const errors = watch(page);
  await page.goto("cases/?dataset=golden&case=case-001");
  await ready(page);
  await expect(page.locator("footer")).toContainText("golden fixture");
  await expect(figure(page, "calendar")).toContainText("66.0000");
  await expect(figure(page, "business")).toContainText("2.0000");
  await expect(figure(page, "paused")).toContainText("65.0000");
  await expect(figure(page, "overlap")).toContainText("1.0000");
  await expect(figure(page, "active")).toContainText("1.0000");
  await expect(figure(page, "sla")).toContainText("SLA met");
  await expect(page.getByTestId("sla-rule")).toContainText("480 business minutes");
  await expect(page.getByTestId("sla-rule")).toContainText("customer_info_requested");
  // the weekend gap is compressed and marked; every drawn element is also in the table
  expect(await page.locator(".tl__gap").count()).toBeGreaterThanOrEqual(1);
  await expect(page.getByTestId("timeline-table")).toContainText("Non-working gap (compressed)");
  await expect(page.getByTestId("timeline-table")).toContainText("Waiting interval");
  await expect(page.getByTestId("timeline-table")).toContainText("pause-eligible: deducted from active time");

  await page.getByRole("radio", { name: "None" }).check();
  expect(new URL(page.url()).searchParams.get("pause")).toBe("none");
  await expect(figure(page, "active")).toContainText("2.0000");
  await expect(figure(page, "paused")).toContainText("0.0000");
  await expect(figure(page, "sla")).toContainText("SLA met");
  await expect(page.getByTestId("timeline-table")).toContainText("not pause-eligible: counted as active time");
  await page.getByRole("radio", { name: "Configured" }).check();
  await expect(figure(page, "active")).toContainText("1.0000");
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("the case picker is a URL view setting", async ({ page }) => {
  const errors = watch(page);
  await page.goto("cases/");
  await ready(page);
  const second = readData<Rows<{ case_id: string }>>("cases.json").rows[1]!.case_id;
  await page.locator("#case-picker").selectOption(second);
  expect(new URL(page.url()).searchParams.get("case")).toBe(second);
  await expect(page.getByRole("list", { name: "Case facts" })).toContainText(second);
  expect(errors).toEqual([]);
});

test("workflow shows both versions and the steps in topological order", async ({ page }) => {
  const errors = watch(page);
  await page.goto("workflow/");
  await ready(page);
  const versions = readData<Rows<{ version_number: number; definition_hash: string }>>("workflow_versions.json").rows;
  await expect(page.getByRole("radio", { name: "v1" })).toBeChecked();
  await expect(page.getByRole("radio", { name: "v2" })).toBeVisible();
  for (const v of versions) await expect(page.getByTestId("versions-table")).toContainText(v.definition_hash);
  await expect(page.getByTestId("definition-hash")).toContainText(versions[0]!.definition_hash);
  await expect(page.locator(".dag__svg")).toBeVisible();
  const order = async (): Promise<(string | null)[]> => page.locator('[data-testid="steps-order"] > li').evaluateAll((els) => els.map((e) => e.getAttribute("data-step")));
  expect(await order()).toEqual(["collect_documents", "verify_identity", "compliance_review", "approve_account", "activate_account"]);
  await page.getByRole("radio", { name: "v2" }).check();
  await expect(page.getByTestId("definition-hash")).toContainText(versions[1]!.definition_hash);
  expect(await order()).toEqual(["collect_documents", "collect_address_proof", "compliance_review", "approve_account", "activate_account"]);
  await expect(page.getByTestId("steps-order").locator("li").nth(2)).toContainText("After collect documents (mandatory) and collect address proof (mandatory)");
  expect(new URL(page.url()).searchParams.get("v")).toBe("2");
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("SLA explorer: region filter in the URL changes the denominator, Clear filters restores, CSV matches the visible population", async ({ page }) => {
  const errors = watch(page);
  await page.goto("sla/");
  await ready(page);
  const den = async (): Promise<number> => Number(await page.getByTestId("sla-denominator").innerText());
  const shown = async (): Promise<number> => Number(await page.getByTestId("population-shown").innerText());
  const den0 = await den(), shown0 = await shown();
  expect(den0).toBeGreaterThan(0);
  await expect(page.getByTestId("open-cases")).toContainText(/\d+/);

  await page.locator("#f-region").selectOption("reg-north");
  expect(new URL(page.url()).searchParams.get("region")).toBe("reg-north");
  await expect.poll(den).toBeLessThan(den0);
  const den1 = await den(), shown1 = await shown();
  expect(shown1).toBeLessThan(shown0);
  expect(den1).toBeGreaterThan(0);

  // a reload keeps the filter because it lives in the address
  await page.reload();
  await ready(page);
  expect(await den()).toBe(den1);

  const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("export-csv").click()]);
  const path = await download.path();
  const { readFileSync } = await import("node:fs");
  const text = readFileSync(path, "utf8");
  const lines = text.split("\r\n").filter((l) => l.length > 0);
  const header = lines.filter((l) => l.startsWith("#"));
  const body = lines.filter((l) => !l.startsWith("#"));
  expect(header).toContain(`# contract_version: ${manifest.contract_version}`);
  expect(header).toContain(`# dataset_version: ${manifest.dataset_version}`);
  expect(header).toContain(`# dataset_hash: ${manifest.dataset_hash}`);
  expect(header.some((l) => l.startsWith("# calendar_id: cal-001"))).toBe(true);
  expect(header.some((l) => l.startsWith("# pause_policy: configured"))).toBe(true);
  expect(header.some((l) => l.includes("region = reg-north"))).toBe(true);
  expect(header).toContain(`# row_count: ${shown1}`);
  expect(body.length - 1).toBe(shown1); // minus the column header
  expect(body[0]).toMatch(/^case_id,organization_id,/);
  expect(download.suggestedFilename()).toContain(manifest.dataset_version);

  await page.getByTestId("clear-filters").click();
  expect(new URL(page.url()).searchParams.get("region")).toBeNull();
  await expect.poll(den).toBe(den0);
  expect(await shown()).toBe(shown0);
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("an empty filtered population is explicit and recoverable", async ({ page }) => {
  const errors = watch(page);
  await page.goto("sla/?from=2035-01-01");
  await ready(page);
  await expect(page.getByText("No cases match these filters")).toBeVisible();
  await expect(page.getByTestId("population-shown")).toHaveText("0");
  await page.getByRole("main").getByRole("button", { name: "Clear filters" }).last().click();
  await expect(page.getByTestId("sla-denominator")).toBeVisible();
  expect(new URL(page.url()).searchParams.get("from")).toBeNull();
  await page.goto("sla/?from=2025-06-01&to=2025-05-01");
  await ready(page);
  await expect(page.getByRole("alert")).toContainText("window start must be before");
  expect(errors).toEqual([]);
});

test("the queue is sortable with the keyboard", async ({ page }) => {
  const errors = watch(page);
  await page.goto("queue/");
  await ready(page);
  await expect(page.getByTestId("queue-count")).toContainText("open step instances");
  const header = page.getByRole("columnheader", { name: /^Case/ });
  await header.getByRole("button").focus();
  await page.keyboard.press("Enter");
  await expect(header).toHaveAttribute("aria-sort", "ascending");
  await page.keyboard.press("Enter");
  await expect(header).toHaveAttribute("aria-sort", "descending");
  expect(errors).toEqual([]);
});

test("case study carries the evidence links and the designed relationships", async ({ page }) => {
  const errors = watch(page);
  await page.goto("case-study/");
  await ready(page);
  await expect(page.getByRole("link", { name: /CI workflow/ })).toHaveAttribute("href", "https://github.com/mrrishit909/projects-site/actions/workflows/onboard-studio-ci.yml");
  await expect(page.getByRole("link", { name: "Back to the portfolio" })).toHaveAttribute("href", "https://mrrishit909.github.io/projects-site/");
  await expect(page.getByTestId("designed-relationships").locator("li")).toHaveCount(4);
  for (const d of ["D-01", "D-02", "D-03", "D-04", "D-05", "D-06"]) await expect(page.getByRole("main")).toContainText(d);
  expect(errors).toEqual([]);
});

test("in-progress routes are marked in the nav and an unknown route is not-found", async ({ page }) => {
  const errors = watch(page);
  await page.goto("./");
  await ready(page);
  for (const name of ["Intake", "Documents", "Bottlenecks", "Versions", "Simulation"]) {
    await expect(page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: new RegExp(`^${name} in progress`) })).toBeVisible();
  }
  await page.goto("intake/");
  await ready(page);
  await expect(page.getByRole("main")).toContainText("In progress");
  await page.goto("no-such-route/");
  await ready(page);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("This page is not part of Onboard Studio");
  // not-found may be served with a 404 status by some servers; only page-level errors count here
  expect(errors.filter((e) => e.startsWith("pageerror"))).toEqual([]);
});

test("every route renders without console errors or horizontal overflow", async ({ page }) => {
  const errors = watch(page);
  for (const r of ["./", "intake/", "queue/", "cases/", "workflow/", "documents/", "sla/", "bottlenecks/", "versions/", "simulation/", "case-study/"]) {
    await page.goto(r);
    await ready(page);
    await expectNoOverflow(page);
  }
  expect(errors).toEqual([]);
});
