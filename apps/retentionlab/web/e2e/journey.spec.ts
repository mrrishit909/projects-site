import { expect, test, type Page } from "@playwright/test";
import { expectNoOverflow, readData, ready, watch } from "./support";
import { readFileSync } from "node:fs";

const manifest = readData<{ dataset_version: string; dataset_hash: string; generated_at: string }>("manifest.json");
const ref = JSON.parse(readFileSync("scripts/snapshot-reference.json", "utf8")) as { test_table: Record<string, Record<string, { average_precision: string; brier_score: string; n: number; positives: number }>>; cohort: { scenarios: Record<string, { expected_value: string; contact_budget: string }> } };
const ROUTES = ["overview", "cohorts", "features", "models", "calibration", "capacity", "account", "queue", "monitoring", "evidence", "case-study"];
const fig = (page: Page, k: string) => page.locator(`[data-figure="${k}"]`).first();

test("landing: honesty labels, manifest strip, back-link, the decision and the verified figures", async ({ page, request }) => {
  const errors = watch(page);
  await page.goto("./");
  await ready(page);
  await expect(page).toHaveTitle(/RetentionLab/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("RetentionLab");
  await expect(page.getByTestId("synthetic-badge")).toHaveText("Synthetic data, demo mode");
  await expect(page.getByTestId("honesty")).toContainText("simulations in browser memory that reset on reload");
  await expect(page.getByTestId("honesty")).toContainText("not treatment responsiveness");
  await expect(page.getByTestId("honesty")).toContainText("reached by construction");
  const strip = page.getByTestId("manifest-strip");
  await expect(strip.locator("[data-k=dataset_version]")).toHaveText(manifest.dataset_version);
  await expect(strip.locator("[data-k=dataset_hash]")).toHaveAttribute("title", manifest.dataset_hash);
  await expect(strip.locator("[data-k=generated_at]")).toHaveText(manifest.generated_at);
  await expect(page.getByTestId("decision")).toContainText("Which accounts deserve limited retention attention");
  await expect(fig(page, "ap-logistic")).toHaveText("0.238552");
  await expect(fig(page, "ap-rule")).toHaveText("0.136653");
  await expect(fig(page, "ap-random")).toHaveText("0.126793");
  await expect(fig(page, "brier")).toHaveText("0.105019");
  await expect(page.getByTestId("by-construction")).toContainText("Reached by construction");
  await expect(page.getByTestId("route-cards").locator("a")).toHaveCount(11);
  await expect(page.getByTestId("footer-honesty")).toContainText("simulations in browser memory");
  expect(await page.locator('link[rel="author"]').getAttribute("href")).toBe("https://mrrishit909.github.io/projects-site/");
  const html = await (await request.get("./")).text();
  expect(html).toMatch(/<noscript[^>]*>[\s\S]*https:\/\/mrrishit909\.github\.io\/projects-site\/[\s\S]*<\/noscript>/);
  expect(html).toContain("/projects-site/labs/retentionlab/assets/");
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
    expect(new URL(page.url()).pathname).toBe(`/projects-site/labs/retentionlab/${path}/`);
    await expect(page.getByTestId("synthetic-badge")).toBeVisible();
    await expect(page.getByTestId("honesty")).toContainText("Synthetic data, demo mode");
    await expect(page.getByTestId("honesty")).toContainText("not treatment responsiveness");
    await expect(page.getByTestId("honesty")).toContainText("reached by construction");
    await expect(page.getByTestId("footer-honesty")).toContainText("browser memory");
    await expect(page.getByTestId("contracts")).toContainText("Contracts:");
    await expect(page.getByTestId("related")).toBeVisible();
  }
  await page.goto("no-such-route/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Not found");
  expect(errors.filter((e) => !e.includes("no-such-route"))).toEqual([]);
});

test("overview: mature churn, the censored tail hatched and never zero, filters with a way out", async ({ page }) => {
  const errors = watch(page);
  await page.goto("overview/");
  await ready(page);
  await expect(fig(page, "mature-churn")).toHaveText("0.104500");
  await expect(fig(page, "censored-share")).toHaveText("0.397610");
  await expect(page.getByTestId("churn-definition")).toContainText("label_end ≤ as_of");
  const feb = page.locator("[data-testid=cutoff-table] tr[data-cutoff=\"2026-09-01\"]");
  await expect(feb.locator("[data-k=rate]")).toContainText("censored");
  await expect(feb.locator("[data-k=censored]")).toContainText("1,241 censored");
  await expect(page.locator("[data-testid=cutoff-table] tr[data-cutoff=\"2026-03-01\"] [data-k=rate]")).not.toHaveText("0.000000");
  await page.getByTestId("range-filter").selectOption("test");
  await expect(page.getByTestId("cutoff-table").locator("tbody tr")).toHaveCount(4);
  await expect(fig(page, "mature-churn")).toHaveText("0.124917");
  const dl = page.waitForEvent("download");
  await page.getByTestId("export-overview-cutoffs").click();
  const d = await dl;
  expect(d.suggestedFilename()).toBe("retentionlab-overview-cutoffs.csv");
  await page.getByRole("button", { name: "Clear the filter" }).click();
  await expect(fig(page, "mature-churn")).toHaveText("0.104500");
  expect(errors).toEqual([]);
});

test("models: the figures equal the Python digests; the margin is labelled as reached by construction; the golden case is recomputed", async ({ page }) => {
  const errors = watch(page);
  await page.goto("models/");
  await ready(page);
  await page.getByTestId("model-table").waitFor();
  const t = ref.test_table["test"]!;
  for (const [row, key] of [["random_baseline", "random_baseline"], ["business_rule", "business_rule"], ["logistic_uncalibrated", "logistic_uncalibrated"], ["logistic_calibrated", "logistic_calibrated"], ["prevalence_baseline", "prevalence_baseline"]] as const) {
    const r = page.locator(`[data-testid=model-table] tr[data-model=${row}]`);
    await expect(r.locator("[data-k=ap]")).toHaveText(t[key]!.average_precision);
    await expect(r.locator("[data-k=brier]")).toHaveText(t[key]!.brier_score);
  }
  await expect(page.getByTestId("by-construction")).toContainText("strengthened");
  await expect(page.locator("[data-margin=ap_over_rule] [data-k=margin]")).toHaveText("0.101899");
  await expect(page.locator("[data-margin=ap_over_rule]")).toContainText("met, by construction");
  await expect(fig(page, "golden-bad")).toHaveText("0");
  await expect(fig(page, "golden-leaves")).toHaveText("912");
  await expect(page.locator("[data-k=golden-precision]")).toHaveText("0.500000");
  await expect(page.locator("[data-k=golden-ap]")).toHaveText("0.833333");
  await expect(page.locator("[data-k=golden-brier]")).toHaveText("0.192500");
  await expect(page.locator("[data-k=golden-ev]")).toHaveText("8.45");
  await page.getByTestId("pop-select").selectOption("test-3");
  const t3 = ref.test_table["test-3"]!;
  await expect(page.locator("[data-testid=model-table] tr[data-model=logistic_calibrated] [data-k=ap]")).toHaveText(t3["logistic_calibrated"]!.average_precision);
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("golden case (?dataset=golden): precision and recall 0.500000 at K = 2, AP 0.833333, Brier 0.192500, lift 1.000000, budget 10.00, value 8.45, the late event, the censored February cohort", async ({ page }) => {
  const errors = watch(page);
  await page.goto("capacity/?dataset=golden");
  await ready(page);
  await expect(page.getByTestId("golden-flag")).toBeVisible();
  await expect(page.getByTestId("manifest-strip").locator("[data-k=dataset_version]")).toHaveText("golden-fixture-v1");
  await expect(fig(page, "k")).toHaveText("2");
  await expect(fig(page, "precision")).toHaveText("0.500000");
  await expect(fig(page, "recall")).toHaveText("0.500000");
  await expect(fig(page, "lift")).toHaveText("1.000000");
  await expect(fig(page, "budget")).toHaveText("$10.00");
  await expect(fig(page, "ev")).toHaveText("$8.45");
  await expect(page.getByTestId("budget")).toContainText("hypothetical");
  await page.goto("models/?dataset=golden");
  await ready(page);
  await expect(page.locator("[data-testid=model-table] [data-k=ap]").first()).toHaveText("0.833333");
  await expect(page.locator("[data-testid=model-table] [data-k=brier]").first()).toHaveText("0.192500");
  await page.goto("overview/?dataset=golden");
  await ready(page);
  const feb = page.locator("[data-testid=cutoff-table] tr[data-cutoff=\"2026-02-01\"]");
  await expect(feb.locator("[data-k=censored]")).toContainText("4 censored");
  await expect(feb.locator("[data-k=rate]")).toContainText("censored");
  await page.goto("features/?dataset=golden");
  await ready(page);
  await expect(page.getByTestId("lineage-facts")).toContainText("arrived late");
  await expect(page.locator("[data-testid=lineage-events] tr[data-status=late]").first()).toBeVisible();
  await page.goto("monitoring/?dataset=golden");
  await ready(page);
  await expect(fig(page, "scoring-hours")).toHaveText("2,878");
  await expect(fig(page, "data-hours")).toHaveText("264");
  await expect(page.locator("[data-testid=drift-table] [data-k=psi]").first()).toHaveText("0.074266");
  await page.goto("evidence/?dataset=golden");
  await ready(page);
  await expect(fig(page, "leaves-bad")).toHaveText("0");
  await expect(fig(page, "leaves")).toHaveText("912");
  expect(errors).toEqual([]);
});

test("capacity planner: the published scenario, a simulated change, a refusal above the population, and the reset", async ({ page }) => {
  const errors = watch(page);
  await page.goto("capacity/");
  await ready(page);
  await expect(page.getByTestId("sim-note")).toContainText("Nothing is sent");
  await expect(page.getByTestId("sim-state")).toContainText("published scenario");
  await expect(fig(page, "k")).toHaveText("5");
  const before = await fig(page, "precision").innerText();
  const evBefore = await fig(page, "ev").innerText();
  await page.getByTestId("preset-sc-003").click();
  await expect(fig(page, "k")).toHaveText("20");
  await expect(fig(page, "precision")).toHaveText("0.250000");
  await expect(fig(page, "recall")).toHaveText("0.026455");
  await expect(page.getByTestId("sim-state")).toContainText("simulated");
  await page.getByTestId("k-input").fill("100");
  await expect(fig(page, "precision")).toHaveText("0.320000");
  await page.getByTestId("effect-input").fill("0.5");
  await expect(fig(page, "budget")).toHaveText("$800.00");
  await page.getByTestId("k-input").fill("5000");
  await expect(page.getByTestId("k-message")).toContainText("CAPACITY_EXCEEDS_POPULATION");
  await expect(page.getByTestId("no-k-result")).toBeVisible();
  await page.getByTestId("effect-input").fill("2");
  await expect(page.getByTestId("k-message")).toContainText("ASSUMED_EFFECT_OUT_OF_RANGE");
  // the published scenarios on the draft queue equal the manifest
  for (const [sid, w] of Object.entries(ref.cohort.scenarios)) {
    await expect(page.locator(`[data-testid=published-table] tr[data-scenario=${sid}] [data-k=ev]`)).toHaveText(w.expected_value);
    await expect(page.locator(`[data-testid=published-table] tr[data-scenario=${sid}] [data-k=budget]`)).toHaveText(w.contact_budget);
  }
  await page.getByTestId("reset-sim").click();
  await expect(page.getByTestId("sim-state")).toContainText("published scenario");
  await expect(fig(page, "k")).toHaveText("5");
  await expect(fig(page, "precision")).toHaveText(before);
  await expect(fig(page, "ev")).toHaveText(evBefore);
  // a reload also restores the published state
  await page.getByTestId("preset-sc-002").click();
  await page.reload();
  await ready(page);
  await expect(page.getByTestId("sim-state")).toContainText("published scenario");
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("calibration: the reliability table is reachable and operable by keyboard, bins without rows are not zero", async ({ page }) => {
  const errors = watch(page);
  await page.goto("calibration/");
  await ready(page);
  const table = page.getByTestId("reliability-table");
  await expect(table.locator("tbody tr")).toHaveCount(10);
  await expect(page.locator("[data-testid=reliability-table] tr[data-bin=\"0\"] [data-k=count]")).toHaveText("815");
  await expect(page.locator("[data-testid=reliability-table] tr[data-bin=\"4\"] [data-k=observed]")).toContainText("no rows");
  await expect(page.locator("[data-testid=reliability-table] tr[data-bin=\"4\"] [data-k=gap]")).not.toHaveText("0.00 pp");
  await expect(fig(page, "brier")).toHaveText("0.105019");
  await expect(fig(page, "empty-bins")).toHaveText("6");
  // Tab into the table: the selected row is the one tab stop
  await page.locator("[data-testid=reliability-table] tr[data-bin=\"0\"]").focus();
  await expect(page.getByTestId("bin-readout")).toContainText("815 rows");
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("bin-readout")).toHaveAttribute("data-bin", "1");
  await expect(page.getByTestId("bin-readout")).toContainText("640 rows");
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("bin-readout")).toContainText("50 rows");
  await page.keyboard.press("End");
  await expect(page.getByTestId("bin-readout")).toContainText("no rows");
  await expect(page.locator("[data-testid=reliability-table] tr[aria-selected=true]")).toHaveAttribute("data-bin", "9");
  await page.keyboard.press("Home");
  await expect(page.getByTestId("bin-readout")).toContainText("815 rows");
  // the published curve: the table equals calibration.json bin for bin
  const cal = readData<{ reliability_calibrated: { count: number; mean_predicted: string | null; observed_rate: string | null }[] }>("calibration.json");
  for (const [i, b] of cal.reliability_calibrated.entries()) {
    const row = page.locator(`[data-testid=reliability-table] tr[data-bin="${i}"]`);
    await expect(row.locator("[data-k=count]")).toHaveText(b.count.toLocaleString("en-US"));
    if (b.mean_predicted !== null) await expect(row.locator("[data-k=mean]")).toHaveText(b.mean_predicted);
  }
  await page.getByTestId("series-choice").getByLabel("Before Platt scaling").check();
  await expect(page.locator("[data-testid=reliability-table] tr[data-bin=\"0\"] [data-k=count]")).toHaveText("778");
  await expect(fig(page, "overall-gap")).toHaveText("−2.26 pp");
  await expect(page.locator("[data-testid=gap-segment] tr[data-group=starter] [data-k=gap]")).toContainText("7.06");
  await page.getByTestId("series-choice").getByLabel("After Platt scaling").check();
  await expect(page.locator("[data-testid=gap-segment] tr[data-group=starter] [data-k=gap]")).toContainText("8.07");
  expect(errors).toEqual([]);
});

test("monitoring: the whole population hides the apac cohort; recomputed PSI equals the published series; two freshness clocks", async ({ page }) => {
  const errors = watch(page);
  await page.goto("monitoring/");
  await ready(page);
  await expect(fig(page, "psi-all-last")).toHaveText("0.002069");
  await expect(fig(page, "psi-apac-last")).toHaveText("0.491035");
  await expect(fig(page, "psi-apac-max")).toHaveText("0.765053");
  const r = page.locator("[data-testid=drift-table] tr[data-cutoff=\"2026-05-01\"]");
  await expect(r.locator("[data-k=apac]")).toContainText("0.513545");
  await expect(r.locator("[data-k=all]")).toHaveText("0.017043");
  await expect(r).toContainText("equal");
  await expect(page.locator("[data-testid=drift-table] tr[data-cutoff=\"2026-03-01\"]")).toContainText("equal");
  await expect(fig(page, "scoring-hours")).toHaveText("812");
  await expect(fig(page, "data-hours")).toHaveText("1");
  await expect(fig(page, "immature-rows")).toHaveText("3,594");
  await expect(page.getByTestId("publications").locator("tbody tr")).toHaveCount(12);
  expect(errors).toEqual([]);
});

test("features: refusals by reason, a late event excluded, availability proof", async ({ page }) => {
  const errors = watch(page);
  await page.goto("features/");
  await ready(page);
  await expect(page.locator("[data-testid=registry] tr[data-feature=cancellation_reason]")).toContainText("POST_OUTCOME_FIELD");
  await expect(page.locator("[data-testid=registry] tr[data-feature=latent_churn_propensity]")).toContainText("LATENT_TRUTH");
  await expect(page.locator("[data-testid=registry] tr[data-feature=creation_sequence]")).toContainText("ID_FEATURE");
  await expect(page.locator("[data-testid=registry] tr[data-feature=usage_events_30d]")).toContainText("built");
  await expect(fig(page, "proof-bad")).toHaveText("0");
  await page.getByTestId("request-input").fill("usage_events_30d, latent_made_up, creation_sequence");
  await expect(page.getByTestId("request-result")).toContainText("refused LATENT_TRUTH");
  await page.getByTestId("request-input").fill("usage_events_30d, billing_total_90d");
  await expect(page.getByTestId("request-result")).toContainText("accepted");
  await expect(page.getByTestId("lineage-select")).toHaveValue("co-0043-20260601");
  await expect(page.locator("[data-testid=lineage-events] tr[data-status=late]").first()).toContainText("arrived late, excluded");
  await expect(page.locator("[data-testid=lineage-features] tr[data-feature=usage_events_30d] [data-k=stored]")).toContainText("same");
  await expect(page.locator("[data-testid=lineage-features] [data-k=ignoring]").filter({ hasText: "would change" }).first()).toBeVisible();
  expect(errors).toEqual([]);
});

test("account and queue: risk factors without causal claims; draft actions, simulated marks, the responsiveness refusal", async ({ page }) => {
  const errors = watch(page);
  await page.goto("account/");
  await ready(page);
  await expect(page.getByTestId("account-select")).toHaveValue("1928");
  await expect(fig(page, "rank")).toHaveText("1");
  await expect(fig(page, "outcome")).toHaveText("unknown");
  await expect(page.getByTestId("no-causal")).toContainText("not treatment responsiveness");
  await expect(page.locator("[data-testid=contributions] tr[data-term=intercept]")).toBeVisible();
  await expect(fig(page, "logit")).toBeVisible();
  await page.goto("queue/");
  await ready(page);
  await expect(page.getByTestId("queue-table").locator("tbody tr")).toHaveCount(5);
  await expect(page.getByTestId("queue-table")).toContainText("equals the 5 published draft rows");
  await expect(fig(page, "queue-sent")).toHaveText("0");
  await page.getByRole("button", { name: "Mark account 1928 reviewed (simulated)" }).click();
  await expect(page.locator("[data-testid=queue-table] tr[data-account=\"1928\"]")).toHaveAttribute("data-mark", "reviewed");
  await expect(page.getByTestId("marks-summary")).toContainText("1 reviewed");
  await page.getByTestId("basis-select").selectOption("responsiveness");
  await page.getByTestId("basis-check").click();
  await expect(page.getByTestId("basis-log")).toContainText("refused RISK_NOT_RESPONSIVENESS");
  await page.getByTestId("reset-marks").click();
  await expect(page.getByTestId("marks-summary")).toContainText("none");
  await page.getByTestId("scenario-select").selectOption("sc-003");
  await expect(page.getByTestId("queue-table").locator("tbody tr")).toHaveCount(20);
  expect(errors).toEqual([]);
});

test("cohorts and evidence: filters with a no-data way out; designed relationships and injected defects equal the manifest", async ({ page }) => {
  const errors = watch(page);
  await page.goto("cohorts/?segment=enterprise&region=apac&cutoff=2026-02-01");
  await ready(page);
  await page.getByTestId("cohort-segment").or(page.getByTestId("no-data")).first().waitFor();
  await page.goto("cohorts/?segment=starter");
  await ready(page);
  await expect(page.locator("[data-testid=cohort-segment] tr[data-group=starter] [data-k=gap]")).toContainText("8.07");
  await page.getByRole("button", { name: "Clear the filters" }).click();
  await expect(page.locator("[data-testid=cohort-segment] tr")).toHaveCount(5);
  await page.goto("evidence/");
  await ready(page);
  await expect(fig(page, "dr-ok")).toHaveText("116");
  await expect(fig(page, "dr-total")).toHaveText("116");
  await expect(fig(page, "inj-ok")).toHaveText("32");
  await expect(fig(page, "replay-ok")).toHaveText("19");
  await expect(page.getByTestId("disclosures").locator("li")).toHaveCount(9);
  await expect(page.getByTestId("disclosures")).toContainText("strengthen");
  await expect(page.getByTestId("latent-ceiling")).toContainText("0.310365");
  await expect(page.getByTestId("injections").locator("details")).toHaveCount(12);
  expect(errors).toEqual([]);
});

test("a failed load shows an honest error and no figure; retry recovers", async ({ page }) => {
  let fail = true;
  await page.route("**/data/manifest.json", (route) => (fail ? route.fulfill({ status: 500, body: "nope" }) : route.continue()));
  await page.goto("models/");
  await expect(page.getByTestId("load-error")).toContainText("manifest.json: HTTP 500");
  await expect(page.getByTestId("model-table")).toHaveCount(0);
  await expect(page.getByTestId("manifest-strip")).toContainText("unavailable");
  fail = false;
  await page.getByRole("button", { name: "Try again" }).click();
  await ready(page);
  await expect(page.getByTestId("model-table")).toBeVisible();
});

test("keyboard: skip link, visible focus on the first controls, the menu toggle at a narrow width", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto("capacity/");
  await ready(page);
  await page.keyboard.press("Tab");
  await expect(page.locator(".skip")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main")).toBeFocused();
  await page.getByTestId("menu-toggle").click();
  await expect(page.locator("#primary-nav")).toBeVisible();
  await page.getByRole("link", { name: "Queue", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Outreach queue");
  await expectNoOverflow(page);
});
