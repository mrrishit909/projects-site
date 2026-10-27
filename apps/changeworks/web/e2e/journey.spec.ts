import { expect, test, type Page } from "@playwright/test";
import { expectNoOverflow, plain, readData, ready, reference, watch } from "./support";

const manifest = readData<{ dataset_version: string; dataset_hash: string; generated_at: string; as_of: string }>("manifest.json");
const ref = reference();
const ROUTES = ["portfolio", "baseline", "business-case", "sensitivity", "roadmap", "impact", "readiness", "benefits", "forecast", "evidence", "case-study"];
const BASE = "/projects-site/labs/changeworks/";
const txt = async (page: Page, sel: string): Promise<string> => plain(await page.locator(sel).first().innerText());

test("landing: honesty labels, manifest strip, back-link, the decision and the snapshot note", async ({ page, request }) => {
  const errors = watch(page);
  await page.goto("./");
  await ready(page);
  await expect(page).toHaveTitle(/ChangeWorks/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("ChangeWorks");
  await expect(page.getByTestId("synthetic-badge")).toHaveText("Synthetic data, demo mode");
  const honesty = page.getByTestId("honesty");
  await expect(honesty).toContainText("Synthetic data, demo mode");
  await expect(honesty).toContainText("simulations in browser memory");
  await expect(honesty).toContainText("reset on reload");
  await expect(honesty).toContainText("first-year case");
  await expect(honesty).toContainText("Nothing here is funded");
  await expect(honesty).toContainText("proposal");
  const strip = page.getByTestId("manifest-strip");
  await expect(strip.locator("[data-k=dataset_version]")).toHaveText(manifest.dataset_version);
  await expect(strip.locator("[data-k=dataset_hash]")).toHaveAttribute("title", manifest.dataset_hash);
  await expect(strip.locator("[data-k=generated_at]")).toHaveText(manifest.generated_at);
  await expect(strip.locator("[data-k=as_of]")).toHaveText(manifest.as_of);
  await expect(page.getByTestId("footer-honesty")).toContainText("simulations in browser memory");
  await expect(page.getByTestId("decision")).toContainText("which transformation initiative should be funded, and how will success be established?");
  await expect(page.getByTestId("snapshot-note")).toContainText("24 initiatives in 4 programmes, 30 draft scenarios, 36 monthly periods");
  await expect(page.getByTestId("snapshot-note")).toContainText("9 matured periods");
  const p25 = ref.portfolio["scn-025"];
  expect(await txt(page, "[data-figure=npv-total]")).toBe(p25.npv_total);
  expect(await txt(page, "[data-figure=residual]")).toBe(p25.residual);
  expect(await txt(page, "[data-figure=never-simple]")).toBe(`${p25.never_simple} of ${p25.initiatives}`);
  expect(await txt(page, "[data-figure=adoption-summary]")).toBe(ref.designed["DR-07"].adoption);
  expect(await txt(page, "[data-figure=training-summary]")).toBe(ref.designed["DR-07"].training);
  await expect(page.getByTestId("backlink").locator("a")).toHaveAttribute("href", "https://mrrishit909.github.io/projects-site/");
  expect(await page.locator('link[rel="author"]').getAttribute("href")).toBe("https://mrrishit909.github.io/projects-site/");
  const html = await (await request.get("./")).text();
  expect(html).toMatch(/<noscript[^>]*>[\s\S]*https:\/\/mrrishit909\.github\.io\/projects-site\/[\s\S]*<\/noscript>/);
  expect(html).toContain(`${BASE}assets/`);
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("every route is reachable by direct entry and reload on the nested base path, with the honesty labels", async ({ page }) => {
  const errors = watch(page);
  for (const path of ROUTES) {
    await page.goto(`${path}/`);
    await ready(page);
    await page.reload();
    await ready(page);
    expect(new URL(page.url()).pathname).toBe(`${BASE}${path}/`);
    await expect(page.getByTestId("synthetic-badge")).toBeVisible();
    await expect(page.getByTestId("honesty")).toContainText("Synthetic data, demo mode");
    await expect(page.getByTestId("honesty")).toContainText("simulations in browser memory");
    await expect(page.getByTestId("honesty")).toContainText("first-year case");
    await expect(page.getByTestId("footer-honesty")).toContainText("Nothing here is live and nothing is funded");
    await expect(page.locator("nav[aria-label=Primary] a[aria-current=page]")).toHaveAttribute("href", `${BASE}${path}/`);
  }
  await expect(page.locator("nav[aria-label=Primary] a")).toHaveCount(11);
  await page.goto("no-such-route/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Not found");
  expect(errors.filter((e) => !e.includes("no-such-route"))).toEqual([]);
});

test("portfolio: every figure equals the Python domain's, class columns apart, nothing summed across classes", async ({ page }) => {
  const errors = watch(page);
  await page.goto("portfolio/");
  await ready(page);
  await page.getByTestId("initiatives-table").waitFor();
  expect(new URL(page.url()).searchParams.get("scenario")).toBeNull();
  await expect(page.getByTestId("scenario-picker")).toHaveValue("scn-025");
  const p = ref.portfolio["scn-025"];
  const t = "[data-testid=initiatives-table] tfoot tr[data-total=all]";
  for (const [k, f] of [["costs", "costs"], ["cash", "cash"], ["revenue", "revenue"], ["avoided", "avoided"], ["capacity-usd", "capacity_usd"], ["avoided-beside", "avoided_beside"], ["capacity-hours", "capacity_hours"], ["npv", "npv_total"]] as const) {
    expect(await txt(page, `${t} [data-k=${k}]`), `scn-025 ${k}`).toBe(p[f]);
  }
  await expect(page.locator("[data-testid=initiatives-table] tbody tr")).toHaveCount(p.initiatives);
  await expect(page.locator("[data-testid=initiatives-table] thead")).not.toContainText("Total benefits");
  await expect(page.getByTestId("units")).toContainText("Totals add only within a column");
  expect(await txt(page, "[data-testid=double-count] [data-figure=planned]")).toBe(p.planned);
  expect(await txt(page, "[data-testid=double-count] [data-figure=attributable]")).toBe(p.attributable);
  expect(await txt(page, "[data-testid=double-count] [data-figure=residual]")).toBe("207146.32");
  await expect(page.locator("[data-testid=double-count] [data-figure=explanation]")).toHaveText("yes");
  await expect(page.locator("[data-testid=overlaps] tbody tr")).toHaveCount(10);
  await expect(page.locator("[data-testid=overlaps] tbody tr").first()).toContainText("src-fin-ap-shared-team");
  await expect(page.locator("[data-testid=overlaps] tbody tr").first()).toContainText("init-001");
  await expect(page.locator("[data-testid=overlaps] tbody tr").first()).toContainText("init-002");
  // all 30 scenarios against Python
  const rows = page.locator("[data-testid=scenario-compare] tbody tr");
  await expect(rows).toHaveCount(30);
  for (const [sid, v] of Object.entries<any>(ref.portfolio)) { // eslint-disable-line @typescript-eslint/no-explicit-any
    const r = page.locator(`[data-testid=scenario-compare] tr[data-scenario=${sid}]`);
    expect([plain(await r.locator("[data-k=costs]").innerText()), plain(await r.locator("[data-k=npv]").innerText()), plain(await r.locator("[data-k=residual]").innerText()), plain(await r.locator("[data-k=never]").innerText())], sid).toEqual([v.costs, v.npv_total, v.residual, String(v.never_simple)]);
  }
  // an initiative row: init-009 is capacity only
  const r9 = page.locator("[data-testid=initiatives-table] tr[data-initiative=init-009]");
  expect(await txt(page, "[data-testid=initiatives-table] tr[data-initiative=init-009] [data-k=npv]")).toBe(ref.designed["DR-01"]["init-009"].npv);
  await expect(r9.locator("[data-k=capacity-hours]")).toContainText("2,920.49");
  await expect(r9.locator("[data-k=simple]")).toHaveText("never");
  // a scenario without a residual
  await page.getByTestId("scenario-picker").selectOption("scn-001");
  await expect(page.getByTestId("no-overlap")).toBeVisible();
  expect(await txt(page, "[data-testid=double-count] [data-figure=residual]")).toBe("0.00");
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("portfolio: filters have a no-data state with a way out; the table is exportable; proposing is a simulation that resets on reload", async ({ page }) => {
  const errors = watch(page);
  await page.goto("portfolio/");
  await ready(page);
  await page.getByTestId("initiatives-table").waitFor();
  await page.getByTestId("programme-filter").selectOption("prog-work");
  await page.getByTestId("evidence-filter").selectOption("strong");
  await expect(page.getByTestId("no-data")).toBeVisible();
  await page.getByTestId("no-data").getByRole("button", { name: "Clear the filters" }).click();
  await expect(page.locator("[data-testid=initiatives-table] tbody tr")).toHaveCount(24);
  await page.getByTestId("programme-filter").selectOption("prog-fin");
  await expect(page.locator("[data-testid=initiatives-table] tbody tr")).toHaveCount(6);
  expect(decodeURIComponent((await page.getByTestId("export-csv").getAttribute("href"))!)).toContain("init-001");
  await expect(page.getByTestId("export-csv")).toHaveAttribute("download", "portfolio-scn-025.csv");
  // propose: refused without an explanation, accepted with one, final afterwards
  await page.getByTestId("propose-button").click();
  await expect(page.getByTestId("proposal-log")).toContainText("DOUBLE_COUNT_UNEXPLAINED");
  await expect(page.getByTestId("proposal-log")).toContainText("src-fin-ap-shared-team");
  await page.getByTestId("explanation").fill("init-002 shares the accounts-payable team; counted once at the larger claim");
  await page.getByTestId("propose-button").click();
  await expect(page.getByTestId("proposal-log")).toContainText("proposed (simulated)");
  await page.getByTestId("propose-button").click();
  await expect(page.getByTestId("proposal-log")).toContainText("ALREADY_PROPOSED");
  await expect(page.getByTestId("propose")).not.toContainText("funded (");
  await expect(page.getByTestId("propose").getByTestId("sim-note")).toContainText("no funded status");
  await page.reload();
  await ready(page);
  await expect(page.getByTestId("proposal-log")).toContainText("No proposals in this session");
  expect(errors).toEqual([]);
});

test("business case: the cash-flow table beside its assumption versions, NPV and both paybacks, the golden case recomputed", async ({ page }) => {
  const errors = watch(page);
  await page.goto("business-case/?scenario=scn-025&initiative=init-009");
  await ready(page);
  await page.getByTestId("cashflow-table").waitFor();
  const d1 = ref.designed["DR-01"]["init-009"];
  expect(await txt(page, "[data-figure=npv]")).toBe(d1.npv);
  await expect(page.locator("[data-figure=simple-payback]")).toContainText("never within the horizon (null)");
  await expect(page.locator("[data-figure=discounted-payback]")).toContainText("never within the horizon (null)");
  expect(await txt(page, "[data-k=capacity-excluded]")).toContain(d1.capacity_hours_not_converted);
  await expect(page.locator("[data-figure=capacity-released]")).toHaveText(d1.released);
  await expect(page.getByTestId("measures")).toContainText("first-year case");
  await expect(page.getByTestId("measures")).toContainText("estimate");
  await expect(page.locator("[data-testid=cashflow-table] tbody tr")).toHaveCount(36);
  await expect(page.locator("[data-testid=cashflow-table] tbody tr").first().locator("[data-k=assumptions]")).toContainText("rate:");
  // a ramped initiative: the assumption versions sit beside the rows
  await page.goto("business-case/?scenario=scn-025&initiative=init-003");
  await ready(page);
  await page.getByTestId("cashflow-table").waitFor();
  await expect(page.getByTestId("cashflow-table").locator("[data-k=assumptions]").filter({ hasText: /ramp a-003-adopti-\d v\d/ }).first()).toBeVisible();
  await expect(page.getByTestId("cashflow-table")).toContainText("converted by");
  await expect(page.locator("[data-testid=assumptions] tbody tr").first()).toBeVisible();
  await expect(page.locator("[data-testid=assumptions] .chip").first()).toBeVisible();
  await expect(page.getByTestId("beside")).toContainText("Adoption ramp");
  // the golden case, recomputed whatever the dataset
  const g = page.getByTestId("golden-case");
  await g.waitFor();
  await expect(g.locator("[data-g=npv]")).toHaveText("41.32 = 5000/121");
  await expect(g.locator("[data-g=simple]")).toHaveText("period 2, interpolated 1.6667");
  await expect(g.locator("[data-g=discounted]")).toHaveText("period 2, interpolated 1.9167");
  await expect(g.locator("[data-g=excluded]")).toHaveText("800.00 h");
  await expect(g.locator("[data-g=released]")).toHaveText("400.0000 h");
  await expect(g.locator("[data-g=residual]")).toContainText("75.00");
  await expect(g.locator("[data-g=delays]")).toHaveText("init-002: 2 periods; init-003: 3 periods");
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("?dataset=golden: the whole site on the hand-derived case", async ({ page }) => {
  const errors = watch(page);
  await page.goto("business-case/?dataset=golden");
  await ready(page);
  await expect(page.getByTestId("golden-flag")).toBeVisible();
  await expect(page.locator("[data-testid=manifest-strip] [data-k=dataset_version]")).toHaveText("golden-fixture-v1");
  await page.getByTestId("cashflow-table").waitFor();
  expect(await txt(page, "[data-figure=npv]")).toBe("41.32");
  await expect(page.locator("[data-figure=npv-exact]")).toHaveText("5000/121");
  await expect(page.locator("[data-figure=simple-payback]")).toHaveText("period 2, interpolated 1.6667");
  await expect(page.locator("[data-figure=discounted-payback]")).toHaveText("period 2, interpolated 1.9167");
  const rows = page.locator("[data-testid=cashflow-table] tbody tr");
  await expect(rows).toHaveCount(3);
  expect([await txt(page, "[data-testid=cashflow-table] tr[data-period='0'] [data-k=costs]"), await txt(page, "[data-testid=cashflow-table] tr[data-period='0'] [data-k=net]"), await txt(page, "[data-testid=cashflow-table] tr[data-period='1'] [data-k=cash]"), await txt(page, "[data-testid=cashflow-table] tr[data-period='2'] [data-k=cumulative]")]).toEqual(["1000.00", "-1000.00", "600.00", "200.00"]);
  await expect(page.locator("[data-testid=cashflow-table] tr[data-period='1'] [data-k=df]")).toHaveText("0.909091");
  await expect(page.locator("[data-testid=cashflow-table] tr[data-period='2'] [data-k=df]")).toHaveAttribute("title", "exact 100/121");
  expect(await txt(page, "[data-k=capacity-excluded]")).toContain("800.00 h over 2 rows");
  await expect(page.locator("[data-figure=capacity-released]")).toHaveText("400.0000");
  // links keep the dataset
  await page.getByRole("link", { name: "Portfolio" }).first().click();
  await expect(page).toHaveURL(/dataset=golden/);
  await page.getByTestId("initiatives-table").waitFor();
  expect(await txt(page, "[data-testid=double-count] [data-figure=residual]")).toBe("75.00");
  await expect(page.locator("[data-testid=overlaps] tbody tr")).toHaveCount(1);
  await expect(page.getByTestId("overlaps")).toContainText("cost-line:CC-4410");
  await page.goto("roadmap/?dataset=golden");
  await ready(page);
  await page.getByTestId("roadmap-table").waitFor();
  expect([await txt(page, "[data-testid=roadmap-table] tr[data-initiative=init-002] [data-k=delay]"), await txt(page, "[data-testid=roadmap-table] tr[data-initiative=init-003] [data-k=delay]")]).toEqual(["2", "3"]);
  await page.goto("evidence/?dataset=golden");
  await ready(page);
  await expect(page.locator("[data-testid=evidence-golden] [data-k=leaves]")).toHaveText("572 of 572");
  await page.goto("./?dataset=golden");
  await ready(page);
  await expect(page.getByTestId("snapshot-note")).toContainText("The golden fixture");
  await page.getByTestId("golden-exit").click();
  await expect(page.locator("[data-testid=manifest-strip] [data-k=dataset_version]")).toHaveText(manifest.dataset_version);
  expect(errors).toEqual([]);
});

test("roadmap: bars with dependency arrows and resource lanes; keyboard navigation; simulated edits refused with their reasons; reset on reload", async ({ page }) => {
  const errors = watch(page);
  await page.goto("roadmap/");
  await ready(page);
  const chart = page.getByTestId("roadmap-chart");
  await chart.waitFor();
  await expect(chart.locator("g[role=button]")).toHaveCount(24);
  await expect(chart.locator("path[data-dep]")).toHaveCount(40);
  await expect(page.getByTestId("lanes-chart").locator("g[data-lane]")).toHaveCount(8);
  await expect(page.locator("[data-testid=roadmap-table] tbody tr")).toHaveCount(24);
  await expect(page.locator("[data-testid=resource-table] tr[data-resource=res-03] [data-k=full]")).toContainText("14, 15, 16");
  await expect(page.locator("[data-testid=resource-table] tr[data-resource=res-03] [data-k=refused]")).toContainText("period 14 (0.50 requested");
  await expect(page.locator("[data-testid=resource-table] tr[data-resource=res-03] [data-k=over]")).toHaveText("none");
  // keyboard: the first bar is the roving stop, arrows move, Enter selects
  const bars = chart.locator("g[role=button]");
  await expect(bars.first()).toHaveAttribute("tabindex", "0");
  await bars.first().focus();
  await expect(bars.first()).toBeFocused();
  const first = await bars.first().getAttribute("data-initiative");
  await page.keyboard.press("ArrowDown");
  await expect(bars.nth(1)).toBeFocused();
  await expect(bars.nth(1)).toHaveAttribute("data-active", "true");
  await expect(bars.first()).toHaveAttribute("tabindex", "-1");
  await page.keyboard.press("End");
  await expect(bars.nth(23)).toBeFocused();
  const last = await bars.nth(23).getAttribute("data-initiative");
  await page.keyboard.press("ArrowLeft"); // to the prerequisite that binds
  const prereq = await page.locator("[data-active=true]").getAttribute("data-initiative");
  expect(prereq).not.toBe(last);
  await page.keyboard.press("Home");
  await expect(bars.first()).toBeFocused();
  await page.keyboard.press("Enter");
  const det = page.getByTestId("roadmap-detail");
  await expect(det).toContainText(first!);
  expect(new URL(page.url()).searchParams.get("initiative")).toBe(first);
  await expect(chart.locator(`g[data-initiative=${first}]`)).toHaveAttribute("aria-pressed", "true");
  // the delayed initiatives carry their dependency delay
  const delayed = page.locator("[data-testid=roadmap-table] tbody tr").filter({ has: page.locator("[data-k=delay]", { hasText: /^[1-9]/ }) });
  await expect(delayed).toHaveCount(4);
  // simulated edits
  await page.getByTestId("dep-initiative").selectOption("init-001");
  await page.getByTestId("dep-prereq").selectOption("init-002");
  await page.getByTestId("dep-add").click();
  await expect(page.getByTestId("edit-log")).toContainText("DEPENDENCY_CYCLE");
  await expect(page.getByTestId("edit-log")).toContainText("init-001 → init-002 → init-001");
  await page.getByTestId("alloc-resource").selectOption("res-03");
  await page.getByTestId("alloc-period").fill("14");
  await page.getByTestId("alloc-amount").fill("0.50");
  await page.getByTestId("alloc-add").click();
  await expect(page.getByTestId("edit-log")).toContainText("RESOURCE_OVERALLOCATED");
  await expect(page.getByTestId("edit-log")).toContainText("2.00 of 2.00");
  await page.getByTestId("alloc-period").fill("30");
  await page.getByTestId("alloc-add").click();
  await expect(page.getByTestId("edit-log")).toContainText("allocation of 0.50 res-03 to");
  await expect(page.getByTestId("edit-log").locator("li").last()).toContainText("accepted");
  const before = await txt(page, `[data-testid=roadmap-table] tr[data-initiative=${first}] [data-k=feasible]`);
  await page.getByTestId("shift-later").click();
  const after = await txt(page, `[data-testid=roadmap-table] tr[data-initiative=${first}] [data-k=feasible]`);
  expect(Number(after)).toBe(Number(before) + 1);
  await expect(page.getByTestId("roadmap-edits").getByTestId("sim-note")).toContainText("Reload to return to the published roadmap");
  await page.reload();
  await ready(page);
  await page.getByTestId("roadmap-table").waitFor();
  await expect(page.getByTestId("edit-log")).toContainText("No edits in this session");
  expect(await txt(page, `[data-testid=roadmap-table] tr[data-initiative=${first}] [data-k=feasible]`)).toBe(before);
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("sensitivity lab: a simulation that moves the exact NPV, refuses an unconverted rate, and resets", async ({ page }) => {
  const errors = watch(page);
  await page.goto("sensitivity/");
  await ready(page);
  await page.getByTestId("lab-result").locator("[data-figure=lab-npv]").waitFor();
  await expect(page.getByTestId("sim-note").first()).toContainText("simulation in browser memory");
  const base = await txt(page, "[data-figure=lab-npv]");
  expect(await txt(page, "[data-figure=lab-published]")).toBe(base);
  expect(await txt(page, "[data-figure=lab-delta]")).toBe("0.00");
  await expect(page.getByTestId("lab-result")).toContainText("as published");
  const baseExact = await txt(page, "[data-figure=lab-npv-exact]");
  // cross-check with the business case for the same initiative and scenario
  const init = await page.getByTestId("lab-initiative").inputValue();
  const scn = await page.getByTestId("lab-scenario").inputValue();
  await page.getByTestId("lab-rate").fill("12");
  await expect(page.getByTestId("lab-result")).toContainText("simulated");
  expect(await txt(page, "[data-figure=lab-npv]")).not.toBe(base);
  await expect(page.getByTestId("lab-ratenote")).toContainText("annual converted to");
  await page.getByTestId("lab-rate").fill("8");
  expect(await txt(page, "[data-figure=lab-npv-exact]")).toBe(baseExact); // the published rate again: the exact rational is back
  await page.getByTestId("lab-cost").getByText("+20 %").click();
  const dearer = await txt(page, "[data-figure=lab-npv]");
  expect(Number.parseFloat(dearer)).toBeLessThan(Number.parseFloat(base));
  await page.getByTestId("lab-ramp").getByText("Two periods late").click();
  expect(await txt(page, "[data-figure=lab-npv]")).not.toBe(dearer);
  await expect(page.locator("[data-testid=lab-grid] td[aria-current=true]")).toHaveCount(1); // the grid marks the cell of the current rate and cost
  // the unconverted annual rate on monthly periods is refused, not applied
  await page.getByTestId("lab-reset").click();
  expect(await txt(page, "[data-figure=lab-npv]")).toBe(base);
  await page.getByTestId("lab-raw").check();
  await expect(page.getByTestId("lab-refusal")).toContainText("RATE_PERIOD_MISMATCH");
  await expect(page.getByTestId("lab-refusal")).toContainText("explicit conversion");
  await page.getByTestId("lab-raw").uncheck();
  await page.getByTestId("lab-rate").fill("abc");
  await expect(page.getByTestId("lab-refusal")).toContainText("INVALID_RATE");
  await page.getByTestId("lab-reset").click();
  expect(await txt(page, "[data-figure=lab-npv]")).toBe(base);
  // the same initiative on the business case shows the published figure
  await page.getByTestId("lab-cost").getByText("-10 %").click();
  await page.reload();
  await ready(page);
  await page.getByTestId("lab-result").locator("[data-figure=lab-npv]").waitFor();
  expect(await txt(page, "[data-figure=lab-npv]")).toBe(base);
  await page.goto(`business-case/?scenario=${scn}&initiative=${init}`);
  await ready(page);
  await page.getByTestId("cashflow-table").waitFor();
  expect(await txt(page, "[data-figure=npv]")).toBe(base);
  expect(errors).toEqual([]);
});

test("baseline, impact and readiness: counts, filters, null for unassessed", async ({ page }) => {
  const errors = watch(page);
  await page.goto("baseline/");
  await ready(page);
  await page.getByTestId("baselines").waitFor();
  await expect(page.locator("[data-testid=baselines] tbody tr")).toHaveCount(30);
  await expect(page.locator("[data-testid=baseline-facts] [data-figure=unapproved]")).toHaveText("6");
  await page.getByTestId("version-filter").selectOption("approved");
  const approved = await page.locator("[data-testid=baselines] tbody tr").count();
  expect(approved).toBe(Number(await txt(page, "[data-figure=approved]")));
  await expect(page.getByTestId("baselines")).toContainText("approved");
  await page.goto("impact/");
  await ready(page);
  await page.getByTestId("mappings").waitFor();
  await expect(page.locator("[data-testid=mappings] tbody tr")).toHaveCount(106);
  await expect(page.locator("[data-testid=impact-facts] [data-figure=groups]")).toHaveText("60");
  await page.getByTestId("level-filter").selectOption("high");
  const high = await page.locator("[data-testid=mappings] tbody tr").count();
  expect(high).toBeGreaterThan(0);
  expect(high).toBeLessThan(106);
  await page.getByTestId("impact-search").fill("zzzz-nothing");
  await expect(page.getByTestId("no-data")).toBeVisible();
  await page.getByTestId("no-data").getByRole("button").click();
  await expect(page.locator("[data-testid=mappings] tbody tr")).toHaveCount(106);
  await page.goto("readiness/");
  await ready(page);
  await page.getByTestId("readiness-table").waitFor();
  await expect(page.locator("[data-testid=readiness-table] tbody tr")).toHaveCount(60);
  await expect(page.locator("[data-testid=readiness-table] tbody tr").first()).toContainText("assessment, not a probability");
  await expect(page.locator("[data-testid=readiness-facts] [data-figure=groups]")).toHaveText("60");
  await page.getByTestId("assessed-filter").selectOption("assessed");
  expect(await page.locator("[data-testid=readiness-table] tbody tr").count()).toBe(Number(await txt(page, "[data-figure=assessed]")));
  await expect(page.getByTestId("pooled")).toContainText(ref.designed["DR-07"].training);
  await expect(page.getByTestId("pooled")).toContainText(ref.designed["DR-07"].adoption);
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("benefits: realisation within a type, the trend beside the raw change, observed not attributed, the disclosure", async ({ page }) => {
  const errors = watch(page);
  await page.goto("benefits/?scenario=scn-025&type=cash&initiative=init-008");
  await ready(page);
  await page.getByTestId("realization-table").waitFor();
  const r = ref.designed["DR-06"];
  const row = "[data-testid=realization-table] tr[data-initiative=init-008]";
  expect([await txt(page, `${row} [data-k=planned]`), await txt(page, `${row} [data-k=observed]`), await txt(page, `${row} [data-k=realization]`), await txt(page, `${row} [data-k=trend]`), await txt(page, `${row} [data-k=above]`)])
    .toEqual([r.planned_comparable, r.observed_comparable, r.realization, r.baseline_trend, r.observed_above_trend]);
  await expect(page.locator(row)).toContainText("observed, not attributed");
  await expect(page.getByTestId("attribution-caveat")).toContainText("beside the baseline trend");
  await expect(page.getByTestId("class-overview").locator("tbody tr")).toHaveCount(4);
  await expect(page.getByTestId("class-overview")).toContainText("hours");
  await expect(page.getByTestId("class-overview")).not.toContainText("Total");
  await expect(page.locator("[data-testid=observations] tbody tr").first()).toBeVisible();
  const disc = page.getByTestId("disclosure");
  await expect(disc).toContainText("never uses it");
  await disc.locator("summary").click();
  await expect(disc.locator("tr[data-initiative=init-008] [data-k=true-share]")).toHaveText("0.150000");
  await page.getByTestId("type-picker").selectOption("capacity");
  await page.getByTestId("realization-table").waitFor();
  await expect(page.getByTestId("realization-table")).toContainText("hours");
  await expect(page.getByTestId("realization-table").locator("caption")).toContainText("hours");
  expect(errors).toEqual([]);
});

test("forecast: original, revisions and observed, with the original kept", async ({ page }) => {
  const errors = watch(page);
  await page.goto("forecast/");
  await ready(page);
  await page.getByTestId("forecast-table").waitFor();
  const versions = ref.designed["DR-04"].versions as [number, string, string][];
  for (const [n, total] of versions) expect(await txt(page, `[data-figure=total-${n}]`)).toBe(total);
  expect(await txt(page, "[data-figure=latest-minus-original]")).toBe(ref.designed["DR-04"].latest_minus_original);
  await expect(page.locator("[data-figure=preserved]")).toHaveText("yes, version 1");
  await expect(page.getByTestId("forecast-chart")).toHaveAttribute("role", "img");
  await expect(page.getByTestId("forecast-chart").locator("polyline")).toHaveCount(3);
  await expect(page.getByTestId("revisions").locator("li")).toHaveCount(3);
  await expect(page.getByTestId("revisions")).toContainText("revision, original kept");
  await expect(page.locator("[data-testid=forecast-table] tbody tr").first().locator("[data-k=v1]")).not.toHaveText("");
  await page.getByTestId("forecast-picker").selectOption({ index: 1 });
  await expect(page.getByTestId("forecast-table")).toBeVisible();
  expect(errors).toEqual([]);
});

test("evidence: the golden case equals expected.json live; the designed relationships and injected defects hold; disclosures", async ({ page }) => {
  const errors = watch(page);
  await page.goto("evidence/");
  await ready(page);
  const g = page.getByTestId("evidence-golden");
  await expect(g.locator(".callout")).toHaveAttribute("data-ok", "true");
  await expect(g.locator("[data-k=leaves]")).toHaveText("572 of 572");
  await page.getByTestId("designed").waitFor();
  await expect(page.locator("[data-testid=designed-table] tbody tr")).toHaveCount(7);
  await expect(page.locator("[data-testid=designed-table] [data-k=holds]").filter({ hasText: "differs" })).toHaveCount(0);
  await expect(page.locator("[data-testid=injections-table] tbody tr")).toHaveCount(12);
  await expect(page.locator("[data-testid=injections-table] [data-k=holds]").filter({ hasText: "hold" })).toHaveCount(12);
  await expect(page.locator("[data-testid=replay-table] tbody tr")).toHaveCount(19);
  await expect(page.locator("[data-testid=replay-table] tbody tr").filter({ hasText: "differs" })).toHaveCount(0);
  await expect(page.getByTestId("disclosures")).toContainText("first-year-after-go-live case");
  await expect(page.getByTestId("truth-disclosure")).toContainText("never an input");
  await expect(page.getByTestId("truth-disclosure")).toContainText("0.150000");
  await expect(page.locator("[data-testid=row-counts] tr[data-entity=benefit_items] td").nth(1)).toHaveText("700");
  await expect(page.getByTestId("limits")).toContainText("browser-memory simulations");
  await expect(page.getByTestId("limits")).toContainText(/first-year case/i);
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("case study: findings are computed from the data", async ({ page }) => {
  const errors = watch(page);
  await page.goto("case-study/");
  await ready(page);
  await page.getByTestId("cs-findings").waitFor();
  await expect(page.getByTestId("cs-problem")).toContainText("Which transformation initiative should be funded");
  await expect(page.locator("[data-finding=capacity]")).toContainText(`${ref.designed["DR-01"]["init-009"].npv.replace("-", "−").replace(/\B(?=(\d{3})+(?!\d))/g, ",")}`);
  await expect(page.locator("[data-finding=double-count]")).toContainText("207,146.32");
  await expect(page.locator("[data-finding=double-count]")).toContainText("src-fin-ap-shared-team");
  await expect(page.locator("[data-finding=never-pays-back]")).toContainText("8 of its 8 scenarios");
  await expect(page.locator("[data-finding=forecast]")).toContainText("v1 745,800.06 → v2 598,900.05 → v3 534,207.54");
  await expect(page.locator("[data-finding=resource]")).toContainText("14, 15, 16");
  await expect(page.locator("[data-finding=resource]")).toContainText("3 further requests are refused");
  await expect(page.locator("[data-finding=attribution]")).toContainText("0.975795");
  await expect(page.locator("[data-finding=people]")).toContainText(ref.designed["DR-07"].training);
  await expect(page.getByTestId("not-built")).toBeVisible();
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("a failed data load shows an honest error and no figures; retry recovers", async ({ page }) => {
  await page.route("**/data/manifest.json", (r) => r.abort());
  await page.goto("portfolio/");
  await expect(page.getByTestId("load-error")).toBeVisible();
  await expect(page.getByTestId("load-error")).toContainText("No figure is shown");
  await expect(page.getByTestId("initiatives-table")).toHaveCount(0);
  await expect(page.getByTestId("manifest-strip")).toContainText("provenance unavailable");
  await page.unroute("**/data/manifest.json");
  await page.getByTestId("load-error").getByRole("button", { name: "Try again" }).click();
  await ready(page);
  await page.getByTestId("initiatives-table").waitFor();
  await page.route("**/data/benefit_items.json", (r) => r.fulfill({ status: 500, body: "boom" }));
  await page.goto("business-case/");
  await expect(page.getByTestId("load-error")).toContainText("HTTP 500");
});
