import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { expectNoOverflow, readData, ready, watch } from "./support";

const manifest = readData<{ dataset_version: string; dataset_hash: string; generated_at: string }>("manifest.json");
const ref = JSON.parse(readFileSync("scripts/snapshot-reference.json", "utf8")); // the Python domain's results over the snapshot
const asOf = ref.as_of_metrics["xv-001"];
const ROUTES = ["overview", "funnel", "cohorts", "tracking", "experiments", "result", "population", "segments", "decision", "evidence", "case-study"];
const row = (page: Page, id: string) => page.locator(`[data-testid=metrics-table] tr[data-metric="${id}"] [data-k=value]`);

test("landing: honesty labels, manifest strip, back-link, the decision and the snapshot note", async ({ page, request }) => {
  const errors = watch(page);
  await page.goto("./");
  await ready(page);
  await expect(page).toHaveTitle(/ProductSignal/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("ProductSignal");
  await expect(page.getByTestId("synthetic-badge")).toHaveText("Synthetic data, demo mode");
  await expect(page.getByTestId("honesty")).toContainText("Nothing ships from this site");
  await expect(page.getByTestId("honesty")).toContainText("no live activity");
  const strip = page.getByTestId("manifest-strip");
  await expect(strip.locator("[data-k=dataset_version]")).toHaveText(manifest.dataset_version);
  await expect(strip.locator("[data-k=dataset_hash]")).toHaveAttribute("title", manifest.dataset_hash);
  await expect(strip.locator("[data-k=generated_at]")).toHaveText(manifest.generated_at);
  await expect(strip.locator("[data-k=code_sha]")).toBeVisible();
  await expect(page.getByTestId("footer-honesty")).toContainText("Nothing here is live");
  await expect(page.getByTestId("decision")).toContainText("Should an onboarding change ship, stop, or receive more investigation?");
  await expect(page.getByTestId("snapshot-note")).toContainText("600 accounts");
  await expect(page.getByTestId("snapshot-note")).toContainText("2026-10-05T00:00:00Z");
  await expect(page.getByTestId("card-v1")).toContainText("+9.50 pp");
  await expect(page.getByTestId("card-v1")).toContainText("conclusive");
  await expect(page.getByTestId("card-v2")).toContainText("Sample ratio mismatch");
  await expect(page.getByTestId("backlink").locator("a")).toHaveAttribute("href", "https://mrrishit909.github.io/projects-site/");
  expect(await page.locator('link[rel="author"]').getAttribute("href")).toBe("https://mrrishit909.github.io/projects-site/");
  const html = await (await request.get("./")).text();
  expect(html).toMatch(/<noscript[^>]*>[\s\S]*https:\/\/mrrishit909\.github\.io\/projects-site\/[\s\S]*<\/noscript>/);
  expect(html).toContain('<link rel="author" href="https://mrrishit909.github.io/projects-site/"');
  expect(html).toContain("/projects-site/labs/productsignal/assets/");
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
    expect(new URL(page.url()).pathname).toBe(`/projects-site/labs/productsignal/${path}/`);
    await expect(page.getByTestId("synthetic-badge")).toBeVisible();
    await expect(page.getByTestId("honesty")).toContainText("Synthetic data, demo mode");
    await expect(page.getByTestId("footer-honesty")).toContainText("simulation in browser memory");
  }
  await page.goto("no-such-route/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Not found");
  expect(errors.filter((e) => !e.includes("no-such-route"))).toEqual([]);
});

test("overview: the twelve metrics equal the Python domain's figures; the cutoff picker shows the D-08 rule", async ({ page }) => {
  const errors = watch(page);
  await page.goto("overview/");
  await ready(page);
  const t = page.getByTestId("metrics-table");
  await expect(t.locator("tbody tr")).toHaveCount(12);
  expect(await t.locator("tbody tr").evaluateAll((els) => els.map((e) => e.getAttribute("data-metric")))).toEqual(Array.from({ length: 12 }, (_, i) => `MET-${String(i + 1).padStart(2, "0")}`));
  const ex = asOf.experiment;
  await expect(row(page, "MET-01")).toHaveText(asOf.signup_conversion.rate);
  await expect(row(page, "MET-02")).toHaveText(asOf.activation.rate);
  await expect(row(page, "MET-03")).toHaveText(asOf.funnel.overall_conversion);
  await expect(row(page, "MET-04")).toHaveText(asOf.retention.day7.rate);
  await expect(row(page, "MET-05")).toHaveText(asOf.retention.week4.rate);
  await expect(row(page, "MET-06")).toHaveText(asOf.feature_adoption.rate);
  await expect(row(page, "MET-07")).toHaveText("+9.50 pp");
  await expect(row(page, "MET-08")).toHaveText(ex.primary.relative_lift);
  await expect(row(page, "MET-09")).toHaveText(ex.exposure.overall.rate);
  await expect(row(page, "MET-10")).toHaveText("OK");
  await expect(row(page, "MET-11")).toHaveText(`${ex.guardrail.by_variant.control.error_rate} / ${ex.guardrail.by_variant.treatment.error_rate}`);
  await expect(row(page, "MET-12")).toHaveText(`${ex.revenue_per_assigned_account.by_variant.control.mean} / ${ex.revenue_per_assigned_account.by_variant.treatment.mean}`);
  // the cutoff picker: as-of and the three interim cutoffs of the analysis runs
  const picker = page.getByTestId("cutoff-picker");
  for (const c of ["2026-05-18", "2026-06-15", "2026-07-13", "2026-10-05"]) await expect(picker).toContainText(c);
  await picker.getByText("2026-05-18").click();
  await expect(page).toHaveURL(/cutoff=2026-05-18/);
  const d = page.getByTestId("d08");
  await expect(d.locator("[data-figure='d08.assigned']")).toHaveText("155");
  await expect(d.locator("[data-figure='d08.assigned_all']")).toHaveText("400");
  await expect(d).toContainText("control 77, treatment 78");
  await expect(d).toContainText("245 assignments");
  await expect(row(page, "MET-10")).toHaveText("OK");
  await expect(page.locator("[data-testid=metrics-table] tr[data-metric=MET-12] .basis")).toContainText("control total 5322.00");
  await expect(page.locator("[data-testid=metrics-table] tr[data-metric=MET-12] .basis")).toContainText("treatment total 5481.00");
  // version 2 at its final cutoff: the lift is withheld in place
  await page.goto("overview/?cutoff=2026-10-04T00%3A00%3A00Z&xv=xv-002");
  await ready(page);
  await expect(row(page, "MET-10")).toHaveText("MISMATCH");
  await expect(row(page, "MET-07")).toContainText("withheld");
  await expect(page.getByTestId("arm-funnel-withheld")).toBeVisible();
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("funnel: ordered events, the funnel equals Python, exclusions are listed", async ({ page }) => {
  const errors = watch(page);
  await page.goto("funnel/");
  await ready(page);
  const steps = page.locator("[data-testid=visitor-funnel] li");
  await expect(steps).toHaveCount(4);
  for (const [i, s] of asOf.funnel.steps.entries()) {
    await expect(steps.nth(i)).toHaveAttribute("data-step", s.step);
    await expect(steps.nth(i).locator("[data-k=units]")).toHaveText(String(s.units));
  }
  await expect(page.getByTestId("definition")).toContainText("visit → signup → onboarding_step_1 → activated");
  await expect(page.getByTestId("definition")).toContainText("48 hours");
  const tq = ref.as_of_tracking_quality;
  for (const k of ["bot_events_excluded", "internal_events_excluded", "unknown_identity", "duplicates_dropped", "received_after_cutoff"]) {
    await expect(page.locator(`[data-exclusion=${k}] [data-k=n]`)).toHaveText(Number(tq[k]).toLocaleString("en-US"));
  }
  await expect(page.getByTestId("identity")).toContainText(Number(ref.as_of_identity.attributed_by_link).toLocaleString("en-US"));
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("cohorts: the maturity-aware grid has blank immature cells, in the account timezone", async ({ page }) => {
  const errors = watch(page);
  await page.goto("cohorts/?cutoff=2026-06-15T00%3A00%3A00Z");
  await ready(page);
  const grid = page.getByTestId("cohort-grid");
  await expect(grid.locator("tbody tr").first()).toBeVisible();
  await expect(grid.locator("td[data-state=blank]").first()).toBeVisible(); // recent weeks cannot have week-4 yet
  await expect(grid.locator("td[data-state=full]").first()).toBeVisible();
  const lastRow = grid.locator("tbody tr").last();
  await expect(lastRow.locator("td[data-col=week4]")).toHaveAttribute("data-state", "blank");
  await expect(lastRow.locator("td[data-col=day28]")).toHaveAttribute("data-state", "blank");
  await expect(page.getByTestId("legend")).toContainText("blank");
  // a blank cell is never printed as a zero
  expect(await grid.locator("td[data-state=blank]").first().innerText()).toBe(" ");
  // the as-of grid equals Python's weekly grid, cell by cell
  await page.goto("cohorts/");
  await ready(page);
  await expect(grid.locator("tbody tr")).toHaveCount(ref.weekly_grid[ref.as_of].rows.length);
  for (const r of ref.weekly_grid[ref.as_of].rows.slice(0, 6)) {
    for (const c of ["day7", "week4"]) {
      const cell = grid.locator(`tr[data-week="${r.week}"] td[data-col=${c}]`);
      const want = r.cells[c];
      if (want.mature_accounts === 0) await expect(cell).toHaveAttribute("data-state", "blank");
      else await expect(cell).toContainText(`${want.retained}/${want.mature_accounts}`);
    }
  }
  const w = asOf.retention;
  await expect(page.locator("[data-figure='retention.day7']")).toHaveText(w.day7.rate);
  await expect(page.locator("[data-figure='retention.on_or_after']")).toHaveText(w.on_or_after_day7.rate);
  await expect(page.locator("[data-figure='retention.week4']")).toHaveText(w.week4.rate);
  await page.getByTestId("tz-picker").getByText("Europe/London").click();
  await expect(page).toHaveURL(/tz=Europe%2FLondon/);
  await expect(grid.locator("tbody tr").first()).toBeVisible();
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("tracking: the counts equal Python and the injected problems are listed", async ({ page }) => {
  const errors = watch(page);
  await page.goto("tracking/");
  await ready(page);
  const tq = ref.as_of_tracking_quality;
  for (const k of Object.keys(tq)) await expect(page.locator(`[data-tq=${k}] [data-k=n]`)).toHaveText(Number(tq[k]).toLocaleString("en-US"));
  await expect(page.locator("[data-testid=injections] tbody tr")).toHaveCount(12);
  await expect(page.getByTestId("injection-summary")).toContainText("not replayed here");
  await expect(page.getByTestId("linked-share")).toContainText("Real users (not bots) with a link");    // R6-10
  expect(errors).toEqual([]);
});

test("result under ?dataset=golden: the golden case, sample ratio before the lift", async ({ page }) => {
  const errors = watch(page);
  await page.goto("result/?dataset=golden");
  await ready(page);
  await expect(page.getByTestId("golden-flag")).toContainText("golden fixture");
  await expect(page.getByTestId("manifest-strip").locator("[data-k=dataset_version]")).toHaveText("golden-v1");
  const g = page.getByTestId("golden-case");
  await expect(g.locator("[data-figure='control.conversion']")).toHaveText("0.200000");
  await expect(g.locator("[data-figure='treatment.conversion']")).toHaveText("0.300000");
  await expect(g.locator("[data-figure=absolute_lift_pp]")).toHaveText("+10.00 pp");
  await expect(g.locator("[data-figure=relative_lift]")).toHaveText("0.500000");
  await expect(g.locator("[data-figure=interval]")).toHaveText("[−0.020249, 0.216734]");
  await expect(g.getByTestId("srm")).toHaveAttribute("data-verdict", "OK");
  await expect(g.getByTestId("srm")).toContainText("SRM OK");
  await expect(g.getByTestId("verdict")).toContainText("not conclusive");
  await expect(g.getByTestId("prior-runs")).toHaveText("1 prior run of this version");
  await expect(g.getByTestId("golden-check")).toHaveAttribute("data-ok", "true");
  await expect(g.getByTestId("golden-check").locator("[data-k=leaves]")).toHaveText("205 of 205");
  const a = await g.getByTestId("srm").boundingBox(), b = await g.getByTestId("primary").boundingBox();
  expect(a!.y, "the sample ratio is above the lift").toBeLessThan(b!.y);
  // the snapshot experiment is still on the page, from the snapshot
  await expect(page.getByTestId("snapshot-case").getByTestId("run-head")).toHaveAttribute("data-run", "an-004");
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("result on the snapshot: v1 final conclusive by a hair with the disclosure; v2 SRM MISMATCH in place of a lift; interim runs", async ({ page }) => {
  const errors = watch(page);
  await page.goto("result/");
  await ready(page);
  const s = page.getByTestId("snapshot-case");
  await expect(s.getByTestId("run-head")).toContainText("final run");
  await expect(s.getByTestId("prior-runs")).toHaveText("3 prior runs of this version");
  await expect(s.locator("[data-figure='control.activated']")).toHaveText("63");
  await expect(s.locator("[data-figure='treatment.activated']")).toHaveText("82");
  await expect(s.locator("[data-figure='control.mature']")).toHaveText("200");
  await expect(s.locator("[data-figure=absolute_lift_pp]")).toHaveText("+9.50 pp");
  await expect(s.locator("[data-figure=interval]")).toHaveText("[0.000812, 0.186863]");
  await expect(s.getByTestId("verdict")).toContainText("conclusive");
  await expect(s.getByTestId("by-a-hair")).toBeVisible();
  // R6-08: the instrumentation gap is disclosed beside "conclusive by a hair": 11 v1 accounts, drawn +11.50 pp, published +9.50, +9.96 without them
  await expect(s.getByTestId("gap-note")).toContainText("INJ-10");
  await expect(s.getByTestId("gap-note")).toContainText("11 ");
  await expect(s.getByTestId("gap-note")).toContainText("11.50");
  await expect(s.getByTestId("gap-note")).toContainText("9.96");
  await expect(s.getByTestId("srm")).toHaveAttribute("data-verdict", "OK");
  await expect(s.getByTestId("guardrail")).toHaveAttribute("data-verdict", "OK");
  const rv = ref.runs["an-004"].experiment.revenue_per_assigned_account.by_variant;
  await expect(s.getByTestId("revenue")).toContainText(rv.control.mean);
  await expect(s.getByTestId("revenue")).toContainText(rv.treatment.mean);
  const dis = s.getByTestId("disclosure");
  await expect(dis).toBeVisible();
  await expect(dis).toContainText("permuted blocks of four");
  await expect(dis).toContainText("223 control / 177 treatment");
  expect(await dis.locator("[data-k=disclosure]").count()).toBeGreaterThanOrEqual(4);
  // v2: the sample ratio mismatch replaces the lift
  await s.getByTestId("run-picker").getByText("an-005").click();
  await expect(s.getByTestId("run-head")).toHaveAttribute("data-run", "an-005");
  await expect(s.getByTestId("srm")).toHaveAttribute("data-verdict", "MISMATCH");
  await expect(s.getByTestId("srm")).toContainText("SRM MISMATCH");
  await expect(s.locator("[data-figure='srm.statistic']")).toHaveText("25.004329");
  await expect(s.locator("[data-figure='srm.p_value']")).toHaveText("0.000001");
  await expect(s.getByTestId("lift-withheld")).toBeVisible();
  await expect(s.getByTestId("primary")).toHaveCount(0);
  await expect(s.locator("[data-figure=absolute_lift_pp]")).toHaveCount(0);
  await expect(s.getByTestId("prior-runs")).toHaveText("0 prior runs of this version");
  // an interim run is labelled as such, with its prior-run count
  await s.getByTestId("run-picker").getByText("an-002").click();
  await expect(s.getByTestId("run-head")).toContainText("interim run");
  await expect(s.getByTestId("prior-runs")).toHaveText("1 prior run of this version");
  await expect(s.getByTestId("verdict")).toContainText("not conclusive");
  await expect(s.getByTestId("verdict")).toContainText("interim");
  expect(errors).toEqual([]);
});

test("population, segments: denominators, exploratory label, Bonferroni threshold", async ({ page }) => {
  const errors = watch(page);
  await page.goto("population/");
  await ready(page);
  const ex = ref.runs["an-004"].experiment;
  await expect(page.locator("[data-testid=denominators] tr[data-arm=control] [data-k=assigned]")).toHaveText("200");
  await expect(page.locator("[data-testid=denominators] tr[data-arm=control] [data-k=exposed]")).toHaveText(String(ex.exposure.by_variant.control.exposed));
  await expect(page.locator("[data-testid=denominators] [data-k=overall-rate]")).toHaveText(ex.exposure.overall.rate);
  await expect(page.getByTestId("itt-vs-exposed")).toContainText("exploratory");
  await page.goto("segments/?by=segment");
  await ready(page);
  await expect(page.getByTestId("exploratory-label")).toContainText("exploratory");
  await expect(page.getByTestId("exploratory-label")).toContainText("3 segments tested");
  // D-10 (R6-13): k counts every segment tested in every split the page offers (plan, segment, timezone), so the threshold is alpha / 9
  await expect(page.getByTestId("exploratory-label").locator("[data-k=threshold]")).toHaveText(ref.segments_family["an-004/segment"].bonferroni_threshold);
  await expect(page.getByTestId("exploratory-label")).toContainText(`${ref.segments_family["an-004/segment"].family_size} comparisons`);
  await expect(page.locator("[data-testid=segment-table] tbody tr")).toHaveCount(3);
  expect(await page.locator("[data-testid=segment-table] [data-chip=exploratory]").count()).toBe(3);
  await page.goto("segments/?run=an-005");
  await ready(page);
  await expect(page.getByTestId("segments-withheld")).toBeVisible();
  expect(errors).toEqual([]);
});

test("experiments: plans verified in the browser, every run with its label and prior-run count; the draft is a simulation", async ({ page }) => {
  const errors = watch(page);
  await page.goto("experiments/");
  await ready(page);
  await expect(page.locator("[data-testid=versions] tbody tr")).toHaveCount(2);
  await expect(page.locator("[data-testid=versions] tbody [data-chip=OK]")).toHaveCount(2);
  const runs = page.locator("[data-testid=runs] tbody tr");
  await expect(runs).toHaveCount(5);
  await expect(runs.nth(3).locator("[data-k=prior]")).toHaveText("3");
  await expect(runs.nth(0).locator("[data-chip]").first()).toHaveAttribute("data-chip", "interim");
  await page.getByRole("button", { name: /Freeze this plan/ }).click();
  await expect(page.getByTestId("drafts")).toContainText("xv-003");
  const h = await page.locator("[data-testid=drafts] tbody td").nth(3).innerText();
  expect(h).toMatch(/^[0-9a-f]{24}/);
  await expect(page.getByTestId("draft")).toContainText("Nothing is stored or registered");
  expect(errors).toEqual([]);
});

test("decision: evidence, the inconclusive option, blocked options, the simulation is labelled and in memory", async ({ page }) => {
  const errors = watch(page);
  await page.goto("decision/");
  await ready(page);
  await expect(page.getByTestId("sim-label")).toContainText("Nothing is shipped, stopped or changed");
  await expect(page.getByTestId("evidence")).toContainText("Sample ratio");
  await expect(page.locator("[data-option=inconclusive]")).toHaveAttribute("data-allowed", "true");
  await expect(page.locator("[data-option=ship]")).toHaveAttribute("data-allowed", "true");
  // an interim run blocks ship
  await page.getByTestId("run-picker").getByText("an-002").click();
  await expect(page.locator("[data-option=ship]")).toHaveAttribute("data-allowed", "false");
  await expect(page.locator("[data-option=ship] [data-reason=INTERIM_RUN]")).toBeVisible();
  // a sample ratio mismatch blocks ship and stop; only inconclusive remains
  await page.getByTestId("run-picker").getByText("an-005").click();
  await expect(page.locator("[data-option=ship] [data-reason=SRM_MISMATCH]")).toBeVisible();
  await expect(page.locator("[data-option=stop] [data-reason=SRM_MISMATCH]")).toBeVisible();
  await expect(page.locator("[data-option=inconclusive]")).toHaveAttribute("data-allowed", "true");
  await page.getByTestId("record-ship").click();
  await expect(page.locator("[data-testid=sim-log] tr[data-status=refused]")).toHaveCount(1);
  await page.getByTestId("record-inconclusive").click();
  await expect(page.locator("[data-testid=sim-log] tr[data-status=recorded]")).toHaveCount(1);
  await page.reload();
  await ready(page);
  await expect(page.getByTestId("sim-empty")).toBeVisible(); // memory only
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("evidence and case study: live golden check, provenance, the disclosures and the modes", async ({ page }) => {
  const errors = watch(page);
  await page.goto("evidence/");
  await ready(page);
  await expect(page.getByTestId("evidence-golden").locator("[data-k=leaves]")).toHaveText("205 of 205");
  await expect(page.locator("[data-testid=row-counts] tbody tr")).toHaveCount(12);
  await expect(page.locator("[data-testid=row-counts] tr[data-entity=events] td").nth(0)).toHaveText("12,552");
  await expect(page.getByTestId("routes")).toContainText("/case-study/");
  await page.goto("case-study/");
  await ready(page);
  await expect(page.getByTestId("cs-v1")).toContainText("63/200");
  await expect(page.getByTestId("cs-v1")).toContainText("[0.000812, 0.186863]");
  await expect(page.getByTestId("cs-v2")).toContainText("MISMATCH");
  await expect(page.getByTestId("cs-p")).toHaveText("p < 0.000001");                                  // R6-12: never "p 0.000001"
  await expect(page.getByTestId("gap-note")).toContainText("INJ-10");                                 // R6-08
  const sec = page.getByTestId("secondary-figures");                                                  // R6-10: intervals computed on the site
  await expect(sec.locator("[data-k='week4.interval']")).toContainText("includes 0");
  await expect(sec.locator("[data-k='guardrail.interval']")).toContainText("includes 0");
  await expect(sec.locator("[data-k='revenue.interval']")).toContainText("Welch");
  await expect(sec.locator("[data-k='week4.difference']")).toContainText("4.50");
  await expect(page.getByTestId("disclosure")).toContainText("223 control / 177 treatment");
  await expect(page.getByTestId("cs-modes")).toContainText("Mode B");
  await expect(page.getByTestId("cs-notbuilt")).toBeVisible();
  expect(errors).toEqual([]);
});
