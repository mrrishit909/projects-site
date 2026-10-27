import { expect, test } from "@playwright/test";
import { readData, expectNoOverflow, ready, watch } from "./support";

const manifest = readData<{ dataset_version: string; dataset_hash: string; generated_at: string }>("manifest.json");
const ROUTES = ["catalog", "glossary", "scorecard", "rules", "issues", "lineage", "duplicates", "merges", "impact", "evidence", "case-study"];
const cell = (page: import("@playwright/test").Page, scope: string, row: string, k: string) => page.locator(`${scope} tr${row} [data-k=${k}]`);

test("landing: honesty labels, manifest strip, back-link, the decision and the snapshot note", async ({ page, request }) => {
  const errors = watch(page);
  await page.goto("./");
  await ready(page);
  await expect(page).toHaveTitle(/TrustLedger/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("TrustLedger");
  await expect(page.getByTestId("synthetic-badge")).toHaveText("Synthetic data, demo mode");
  await expect(page.getByTestId("honesty")).toContainText("Nothing is merged, closed or disabled from this site");
  await expect(page.getByTestId("honesty")).toContainText("no live activity");
  const strip = page.getByTestId("manifest-strip");
  await expect(strip.locator("[data-k=dataset_version]")).toHaveText(manifest.dataset_version);
  await expect(strip.locator("[data-k=dataset_hash]")).toHaveAttribute("title", manifest.dataset_hash);
  await expect(strip.locator("[data-k=generated_at]")).toHaveText(manifest.generated_at);
  await expect(strip.locator("[data-k=code_sha]")).toBeVisible();
  await expect(page.getByTestId("footer-honesty")).toContainText("simulation in browser memory");
  await expect(page.getByTestId("decision")).toContainText("Which data issues should be fixed first, and who is accountable?");
  await expect(page.getByTestId("snapshot-note")).toContainText("40 datasets");
  await expect(page.getByTestId("snapshot-note")).toContainText("2026-10-05T00:00:00Z");
  await expect(page.getByTestId("card-scorecard")).toContainText("0.990175");
  await expect(page.getByTestId("card-scorecard")).toContainText("critical override");
  await expect(page.getByTestId("card-ownership")).toContainText("0.875000");
  await expect(page.getByTestId("card-lineage")).toContainText("0.725000");
  await expect(page.getByTestId("card-issues")).toContainText("315 / 99 / 160");
  await expect(page.getByTestId("backlink").locator("a")).toHaveAttribute("href", "https://mrrishit909.github.io/projects-site/");
  expect(await page.locator('link[rel="author"]').getAttribute("href")).toBe("https://mrrishit909.github.io/projects-site/");
  const html = await (await request.get("./")).text();
  expect(html).toMatch(/<noscript[^>]*>[\s\S]*https:\/\/mrrishit909\.github\.io\/projects-site\/[\s\S]*<\/noscript>/);
  expect(html).toContain('<link rel="author" href="https://mrrishit909.github.io/projects-site/"');
  expect(html).toContain("/projects-site/labs/trustledger/assets/");
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
    expect(new URL(page.url()).pathname).toBe(`/projects-site/labs/trustledger/${path}/`);
    await expect(page.getByTestId("synthetic-badge")).toBeVisible();
    await expect(page.getByTestId("honesty")).toContainText("Synthetic data, demo mode");
    await expect(page.getByTestId("footer-honesty")).toContainText("simulation in browser memory");
  }
  await page.goto("no-such-route/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Not found");
  expect(errors.filter((e) => !e.includes("no-such-route"))).toEqual([]);
});

test("scorecard, golden: each dimension apart, both validity figures labelled, the weighted score with the override in vermilion", async ({ page }) => {
  const errors = watch(page);
  await page.goto("scorecard/?dataset=golden");
  await ready(page);
  await expect(page.getByTestId("golden-flag")).toBeVisible();
  await page.getByTestId("dim-timeliness").waitFor();
  await expect(cell(page, "[data-testid=dim-completeness]", "[data-rule=r-cust-complete-email]", "value")).toHaveText("0.950000");
  const v = "[data-testid=dim-validity] tr[data-rule=r-cust-valid-email]";
  await expect(page.locator(`${v} [data-k=populated_only]`)).toHaveText("0.947368");
  await expect(page.locator(`${v} [data-k=populated_only]`)).toHaveAttribute("data-label", "validity_populated_only");
  await expect(page.locator(`${v} [data-k=all_eligible]`)).toHaveText("0.900000");
  await expect(page.locator(`${v} [data-k=all_eligible]`)).toHaveAttribute("data-label", "validity_all_eligible");
  const u = "[data-testid=dim-uniqueness] tr[data-rule=r-cust-key-unique]";
  await expect(page.locator(`${u} [data-k=group_share]`)).toHaveText("0.010204");
  await expect(page.locator(`${u} [data-k=row_share]`)).toHaveText("0.020000");
  const r = "[data-testid=dim-relationship] tr[data-rule=r-ord-cust-fk]";
  await expect(page.locator(`${r} [data-k=value]`)).toHaveText("0.947368");
  await expect(page.locator(`${r} [data-k=null_fk]`)).toHaveText("2");
  await expect(page.locator("[data-testid=dim-timeliness] [data-figure=timeliness]")).toHaveText("0.750000");
  await expect(page.locator("[data-testid=dim-timeliness] tr[data-dataset=ds-shipments] [data-k=on_time]")).toContainText("late");
  const row = "[data-testid=score-table] tr[data-dataset=ds-customers]";
  await expect(page.locator(`${row} [data-k=score]`)).toContainText("0.963932");
  await expect(page.locator(`${row} [data-k=w2]`)).toHaveText("0.963932");
  await expect(page.locator(`${row} [data-k=w1]`)).toHaveText("0.958116");
  const chip = page.locator(`${row} [data-k=score] [data-chip=override]`);
  await expect(chip).toBeVisible();
  expect(await chip.evaluate((e) => getComputedStyle(e).backgroundColor)).toBe("rgb(184, 67, 42)"); // vermilion #b8432a
  await expect(page.locator(`${row} [data-k=critical]`)).toHaveText("2");
  await expect(page.locator(`${row} [data-k=critical-issues]`)).toHaveText("1");
  await expect(page.locator("[data-testid=score-table] tr[data-dataset=ds-products] [data-k=score]")).toHaveText("n/a");
  // the version switch changes the selected score and not the dimension figures
  await page.getByTestId("wv-switch").getByText("w1", { exact: true }).click();
  await expect(page.locator(`${row} [data-k=score]`)).toContainText("0.958116");
  await expect(page.locator(`${v} [data-k=populated_only]`)).toHaveText("0.947368");
  expect(new URL(page.url()).searchParams.get("wv")).toBe("w1");
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("scorecard, snapshot: ds-customers keeps its override beside a high score; the version shift; five uncovered datasets", async ({ page }) => {
  const errors = watch(page);
  await page.goto("scorecard/");
  await ready(page);
  await page.getByTestId("score-table").waitFor();
  const row = "[data-testid=score-table] tr[data-dataset=ds-customers]";
  await expect(page.locator(`${row} [data-k=score]`)).toContainText("0.990175");
  await expect(page.locator(`${row} [data-k=w1]`)).toHaveText("0.990329");
  await expect(page.locator(`${row} [data-k=override]`)).toContainText("override: true");
  await expect(page.locator(`${row} [data-chip=override]`)).toBeVisible();
  await expect(page.locator("[data-testid=score-table] tbody tr").first()).toHaveAttribute("data-dataset", "ds-customers"); // overrides sort first
  await expect(page.getByTestId("critical-summary").locator("[data-figure=overridden]")).toHaveText("1");
  await expect(page.locator("[data-testid=portfolio] [data-figure=scored]")).toHaveText("29");
  await expect(page.locator("[data-testid=portfolio] [data-figure=moved]")).toHaveText("13");
  await expect(page.locator("[data-testid=portfolio] [data-figure=moved-big]")).toHaveText("7");
  await expect(page.locator("[data-testid=portfolio] [data-figure=largest]")).toHaveText("−0.167477");
  await expect(page.getByTestId("ownership-strip").locator("[data-figure=ownership]")).toHaveText("0.875000");
  await expect(page.getByTestId("ownership-strip")).toContainText("ds-contacts, ds-invoices, ds-ledger-entries, ds-returns, ds-suppliers");
  await page.getByTestId("wv-switch").getByText("w1", { exact: true }).click();
  await expect(page.locator(`${row} [data-k=score]`)).toContainText("0.990329");
  await page.getByTestId("dataset-filter").selectOption("ds-orders");
  await expect(page.locator("[data-testid=dim-relationship] tr[data-rule=r-orders-fk-customer_key] [data-k=null_fk]")).toHaveText("5");
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("catalog: search across datasets, fields and owners; ownership coverage with the inactive owners", async ({ page }) => {
  const errors = watch(page);
  await page.goto("catalog/");
  await ready(page);
  await expect(page.getByTestId("ownership").locator("[data-figure=ownership-value]")).toHaveText("0.875000");
  await expect(page.getByTestId("uncovered").locator("tbody tr")).toHaveCount(5);
  await expect(page.getByTestId("uncovered")).toContainText("ds-ledger-entries");
  await page.getByTestId("search").fill("inactive");
  await expect(page.getByTestId("owners").locator("tbody tr")).toHaveCount(3);
  await page.getByTestId("search").fill("ds-customers");
  await expect(page.getByTestId("datasets").locator("tbody tr")).toHaveCount(1);
  await page.getByTestId("search").fill("customer_key");
  await expect(page.getByTestId("fields").locator("tbody tr").first()).toContainText("customer_key");
  await page.getByTestId("scope").getByText("Owners", { exact: true }).click();
  await expect(page.getByTestId("datasets")).toHaveCount(0);
  expect(new URL(page.url()).searchParams.get("q")).toBe("customer_key");
  await page.getByTestId("search").fill("zzzz-nothing");
  await expect(page.getByTestId("result-counts")).toContainText("0 datasets, 0 fields and 0 owners");
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("glossary: versions side by side, what changed, the checklist gaps", async ({ page }) => {
  const errors = watch(page);
  await page.goto("glossary/?dataset=golden");
  await ready(page);
  await expect(page.getByTestId("versions").locator("[data-version]")).toHaveCount(2);
  await expect(page.locator("[data-version=mv-rev-2] dd[data-item=definition]")).toHaveAttribute("data-state", "changed");
  await expect(page.locator("[data-version=mv-rev-2] dd[data-item=grain]")).toHaveAttribute("data-state", "same");
  await expect(page.getByTestId("effective")).toContainText("mv-rev-2");
  await expect(page.getByTestId("effective")).toContainText("mv-rev-1");
  await expect(page.getByTestId("coverage")).toContainText("0.750000");
  await page.getByTestId("show").getByText(/^All/).click();
  await page.getByTestId("metric-list").getByText("Customer lifetime value").click();
  await expect(page.getByTestId("checklist-gaps")).toContainText("Grain, Refresh");
  await page.goto("glossary/");
  await ready(page);
  await expect(page.getByTestId("coverage").locator("[data-figure=definition-coverage]")).toHaveText("0.766667");
  await expect(page.getByTestId("coverage").locator("[data-figure=redefined]")).toHaveText("15");
  expect(await page.locator("[data-testid=versions] dd[data-state=changed]").count()).toBeGreaterThan(0);
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("rules: eligible population, failing examples, and RULE_VERSION_DIFFERS refuses the comparison", async ({ page }) => {
  const errors = watch(page);
  await page.goto("rules/?dataset=golden");
  await ready(page);
  const d = page.getByTestId("rule-detail");
  await expect(d).toHaveAttribute("data-rule", "r-cust-valid-email");
  await expect(page.getByTestId("eligible")).toContainText("100 rows in ds-customers; eligible: all rows");
  await expect(d.locator("[data-figure=eligible]")).toHaveText("100");
  await expect(d.locator("[data-figure=failures]")).toHaveText("10");
  await expect(page.getByTestId("failing").locator("tbody tr")).toHaveCount(10);
  await expect(page.getByTestId("failing")).toContainText('"   "'); // whitespace is visible
  await expect(page.getByTestId("not-comparable")).toContainText("RULE_VERSION_DIFFERS");
  await expect(page.getByTestId("not-comparable")).toContainText("no rates are compared");
  await page.goto("rules/?dataset=golden&rule=r-cust-complete-email");
  await expect(page.getByTestId("comparison")).toContainText("comparable");
  await expect(page.getByTestId("comparison")).not.toContainText("RULE_VERSION_DIFFERS");
  await page.goto("rules/");
  await ready(page);
  await expect(page.getByTestId("rule-detail")).toHaveAttribute("data-rule", "r-contacts-fk-customer_key");
  await expect(page.getByTestId("not-comparable")).toContainText("eligible 65");
  await expect(page.getByTestId("rule-detail").locator("[data-figure=null-fk]")).toBeVisible();
  await page.getByTestId("rule-filter").getByText(/^Disabled/).click();
  await expect(page.getByTestId("rule-index").locator("tbody tr")).toHaveCount(5);
  await page.getByTestId("rule-index").getByRole("link", { name: "r-leads-valid-email" }).click();
  await expect(page.getByTestId("disabled-info")).toContainText("77 runs and 17 issues are retained");
  await expect(page.getByTestId("no-measure")).toBeVisible();
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("issues: claimed against resolved, aging, ownership; simulated actions change nothing published", async ({ page }) => {
  const errors = watch(page);
  await page.goto("issues/");
  await ready(page);
  const s = page.getByTestId("claimed-vs-resolved");
  await expect(s.locator("[data-figure=resolved]")).toHaveText("315");
  await expect(s.locator("[data-figure=claimed]")).toHaveText("99");
  await expect(s.locator("[data-figure=open]")).toHaveText("160");
  await expect(s.locator("[data-figure=mean-hours]")).toHaveText("68.2716");
  await expect(page.getByTestId("aging").locator("tbody tr")).toHaveCount(4);
  await expect(page.locator("[data-testid=issue-ownership] tr[data-team='Data Platform'] [data-k=mean]")).toHaveText("34.4202");
  await expect(page.getByTestId("team-contrast")).toContainText("86.1833");
  const detail = page.getByTestId("issue-detail");
  await expect(detail).toHaveAttribute("data-issue", "iss-0461"); // the open critical issue is selected first
  await expect(page.getByTestId("sim-note").first()).toContainText("Simulation, browser memory only");
  await detail.getByRole("button", { name: /close without a rerun/ }).click();
  await expect(page.getByTestId("sim-log")).toContainText("claimed");
  await expect(page.getByTestId("sim-counts")).toContainText("claimed 100");
  await expect(s.locator("[data-figure=claimed]")).toHaveText("99"); // the published count is unchanged
  await detail.getByRole("button", { name: /rerun the same rule version/ }).click();
  await expect(page.getByTestId("sim-log").locator("li").last()).toContainText("RERUN_STILL_FAILING");
  await page.getByTestId("class-filter").getByText("Claimed", { exact: true }).click();
  await expect(page.getByTestId("issue-table").locator("tbody tr").first()).toBeVisible();
  await page.reload();
  await ready(page);
  await expect(page.getByTestId("sim-log")).toHaveCount(0); // gone on reload
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("lineage: three edge styles, coverage 0.725000, inferred edges labelled and never observed", async ({ page }) => {
  const errors = watch(page);
  await page.goto("lineage/");
  await ready(page);
  await page.getByTestId("graph").waitFor();
  await expect(page.getByTestId("coverage").locator("[data-figure=lineage-coverage]")).toHaveText("0.725000");
  await expect(page.getByTestId("legend").locator("li")).toHaveCount(3);
  const g = page.getByTestId("graph");
  await expect(g.locator("path[data-edge=declared]")).toHaveCount(80);
  await expect(g.locator("path[data-edge=observed]")).toHaveCount(70);
  await expect(g.locator("g[data-edge=inferred]")).toHaveCount(10);
  await expect(g.locator("g[data-edge=inferred] text")).toHaveCount(10);
  await expect(g.locator("rect[data-marker=undeclared]")).toHaveCount(12);
  const style = async (sel: string) => g.locator(sel).first().evaluate((e) => { const c = getComputedStyle(e); return { w: Number.parseFloat(c.strokeWidth), dash: c.strokeDasharray }; });
  const dec = await style("path.e-declared"), obs = await style("path.e-observed"), inf = await style("path.e-inferred");
  expect(obs.w).toBeGreaterThan(dec.w * 2);
  expect(dec.dash).toBe("none");
  expect(obs.dash).toBe("none");
  expect(inf.dash).not.toBe("none");
  await expect(page.getByTestId("undeclared").locator("tbody tr")).toHaveCount(12);
  await expect(page.getByTestId("inferred-list").locator("tbody tr")).toHaveCount(10);
  await page.getByTestId("kind-toggles").getByText("inferred", { exact: true }).click();
  await expect(g.locator("g[data-edge=inferred]")).toHaveCount(0);
  await g.locator("g[data-node=ds-orders]").click();
  await expect(page.getByTestId("focus-panel")).toContainText("ds-orders");
  await expectNoOverflow(page);
  await page.goto("lineage/?dataset=golden");
  await ready(page);
  await expect(page.getByTestId("coverage").locator("[data-figure=lineage-coverage]")).toHaveText("0.833333");
  expect(errors).toEqual([]);
});

test("duplicates: side by side, the uncertainty note, and no control that merges", async ({ page }) => {
  const errors = watch(page);
  await page.goto("duplicates/");
  await ready(page);
  await expect(page.getByTestId("no-auto-merge")).toContainText("Nothing is merged automatically");
  await expect(page.getByTestId("candidate-detail")).toHaveAttribute("data-candidate", "cand-0001");
  await expect(page.getByTestId("uncertainty")).toContainText("Shared name and address");
  await expect(page.getByTestId("uncertainty")).toContainText("never merged automatically");
  await expect(page.getByTestId("side-by-side").locator("tr[data-field=normalized_name] [data-k=compare]")).toHaveText("same");
  await expect(page.getByTestId("side-by-side").locator("tr[data-field=record_id] [data-k=compare]")).toHaveText("differs");
  await expect(page.getByRole("button", { name: /merge/i })).toHaveCount(0);
  await expect(page.getByTestId("sim-note").first()).toContainText("no button on this site that merges anything");
  const proposer = await page.getByTestId("reviewer").locator("option", { hasText: "proposer" }).getAttribute("value");
  await page.getByTestId("reviewer").selectOption(proposer!);
  await page.getByTestId("record-review").click();
  await expect(page.getByTestId("review-log")).toContainText("REVIEWER_IS_PROPOSER");
  await page.getByTestId("reviewer").selectOption({ index: 0 });
  await page.getByTestId("record-review").click();
  await expect(page.getByTestId("review-log").locator("li").last()).toContainText(/recorded|ALREADY_REVIEWED/);
  await page.goto("duplicates/?dataset=golden");
  await ready(page);
  await expect(page.getByTestId("uncertainty")).toContainText("possible household");
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("merges: reversible mappings, precision from the verification layer, a simulated reversal", async ({ page }) => {
  const errors = watch(page);
  await page.goto("merges/");
  await ready(page);
  await expect(page.getByTestId("verification").locator("[data-figure=precision]")).toHaveText("0.988506");
  await expect(page.getByTestId("verification").locator("[data-figure=reviewed-share]")).toHaveText("0.840909");
  await expect(page.getByTestId("verification")).toContainText("synthetic truth");
  await expect(page.getByTestId("merge-summary").locator("[data-figure=reversed]")).toHaveText("15");
  await expect(page.getByTestId("merge-detail")).toContainText("Reversal restores both source identities and keeps the mapping history");
  await expect(page.getByTestId("mapping").locator("[data-k=from-now]")).toContainText("(restored)");
  await page.getByTestId("merge-state").getByText(/^Active/).click();
  await page.getByTestId("merge-list").locator("tbody a").first().click();
  await expect(page.getByTestId("mapping").locator("[data-k=from-now]")).not.toContainText("(restored)");
  await page.getByTestId("simulate-reversal").click();
  await expect(page.getByTestId("reversal-log")).toContainText("INVALID_REVERSAL");
  await page.getByTestId("reversal-reason").fill("wrong person");
  await page.getByTestId("simulate-reversal").click();
  await expect(page.getByTestId("reversal-log")).toContainText("Simulated reversal");
  await expect(page.getByTestId("mapping").locator("[data-k=from-now]")).toContainText("(restored)");
  await page.goto("merges/?dataset=golden");
  await ready(page);
  await expect(page.getByTestId("verification").locator("[data-figure=precision]")).toHaveText("0.666667");
  await expect(page.getByTestId("verification").locator("[data-figure=reviewed-share]")).toHaveText("0.500000");
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("impact: a definition change, what it reaches, and the honest limit", async ({ page }) => {
  const errors = watch(page);
  await page.goto("impact/?dataset=golden");
  await ready(page);
  await expect(page.getByTestId("change-summary")).toContainText("Net revenue changed from v1 to v2");
  await expect(page.getByTestId("diff").locator("tr[data-item=definition] [data-k=changed]")).toContainText("changed");
  await expect(page.getByTestId("diff").locator("tr[data-item=grain] [data-k=changed]")).toContainText("same");
  await expect(page.getByTestId("reach")).toContainText("ds-orders");
  await expect(page.getByTestId("downstream")).toContainText("ds-shipments");
  await expect(page.getByTestId("downstream-metrics").locator("tr[data-metric=m-aov]")).toContainText("same data");
  await expect(page.getByTestId("downstream-metrics").locator("tr[data-metric=m-nps]")).toHaveCount(0); // a draft is not published
  await expect(page.getByTestId("not-built")).toContainText("does not predict");
  await page.goto("impact/");
  await ready(page);
  await expect(page.getByTestId("change-picker").locator("option")).toHaveCount(15);
  await expect(page.getByTestId("weight-change").locator("tbody tr").first()).toContainText("ds-tickets");
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("evidence: the golden case equals expected.json live; the generator's checks hold; disclosures are shown", async ({ page }) => {
  const errors = watch(page);
  await page.goto("evidence/");
  await ready(page);
  const g = page.getByTestId("evidence-golden");
  await expect(g.locator(".callout")).toHaveAttribute("data-ok", "true");
  await expect(g.locator("[data-k=leaves]")).toHaveText("391 of 391");
  await page.getByTestId("injections").waitFor();
  await expect(page.getByTestId("injections").locator("tbody tr")).toHaveCount(12);
  await expect(page.getByTestId("injections").locator("[data-k=holds]")).toHaveText(Array(12).fill(/ hold$/));
  await expect(page.getByTestId("designed").locator("tbody tr").filter({ hasText: "differs" })).toHaveCount(0);
  await expect(page.getByTestId("disclosures")).toContainText("No realised outcome was re-drawn");
  await expect(page.getByTestId("row-counts").locator("tr[data-entity=rule_runs] td").nth(1)).toHaveText("4,609");
  await expect(page.getByTestId("limits")).toContainText("Nothing here is live");
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("case study: findings are computed from the data", async ({ page }) => {
  const errors = watch(page);
  await page.goto("case-study/");
  await ready(page);
  await expect(page.getByTestId("cs-problem")).toContainText("Which data issues should be fixed first");
  await expect(page.locator("[data-finding=override]")).toContainText("ds-customers scores 0.990175 under w2 and 0.990329 under w1, above 0.95 under both versions");
  await expect(page.locator("[data-finding=ownership]")).toContainText("0.875000");
  await expect(page.locator("[data-finding=lineage]")).toContainText("0.725000");
  await expect(page.locator("[data-finding=matching]")).toContainText("0.988506");
  await expect(page.getByTestId("cs-honesty")).toContainText("simulate in browser memory");
  await expect(page.getByTestId("not-built")).toBeVisible();
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});
