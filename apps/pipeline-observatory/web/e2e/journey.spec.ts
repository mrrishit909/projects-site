import { expect, test } from "@playwright/test";
import { expectNoOverflow, fig, readData, ready, reference, watch } from "./support";

const manifest = readData<{ dataset_version: string; dataset_hash: string; generated_at: string }>("manifest.json");
const ROUTES = ["overview", "dag", "runs", "sources", "quarantine", "gate", "backfill", "incidents", "benchmark", "evidence", "case-study"];
const ref = reference();
const n0 = (n: number): string => n.toLocaleString("en-US");

test("landing: honesty labels, manifest strip, back-link, the decision and the verdict", async ({ page, request }) => {
  const errors = watch(page);
  await page.goto("./");
  await ready(page);
  await expect(page).toHaveTitle(/Pipeline Observatory/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Pipeline Observatory");
  await expect(page.getByTestId("decision")).toHaveText("Is this dataset safe, complete, and fresh enough to publish?");
  await expect(page.getByTestId("synthetic-badge")).toHaveText("Synthetic data, demo mode");
  await expect(page.getByTestId("honesty")).toContainText("browser memory that reset on reload");
  await expect(page.getByTestId("honesty")).toContainText("2,000-row sample of 40,191");
  const strip = page.getByTestId("manifest-strip");
  await expect(strip.locator("[data-k=dataset_version]")).toHaveText(manifest.dataset_version);
  await expect(strip.locator("[data-k=dataset_hash]")).toHaveAttribute("title", manifest.dataset_hash);
  await expect(strip.locator("[data-k=generated_at]")).toHaveText(manifest.generated_at);
  await expect(strip.locator("[data-k=code_sha]")).toHaveText("not recorded");
  await expect(page.getByTestId("footer-honesty")).toContainText("simulations in browser memory");
  await expect(page.getByTestId("verdict")).toContainText("src-refunds");
  await expect(fig(page, "current-publication")).toHaveText(ref.complete_world.pointer.current);
  await expect(fig(page, "gate-allowed")).toHaveText(n0(ref.sample_world.headline.gate.allowed));
  await expect(fig(page, "incidents")).toHaveText(String(ref.complete_world.incidents.total));
  await expect(page.getByTestId("snapshot-note")).toContainText("2,000 rows in 62 whole batches, 50 of which carry rows, are published");
  // D-09 (R8-07): the funnel, not "25 blocked": 1,343 runs, 1,328 reached the gate (1,318 allowed, 10 blocked), 15 failed before it
  await expect(page.locator("[data-readout=gate-allowed] [data-testid=run-funnel]")).toHaveText("1,343 runs: 1,328 reached the gate (1,318 allowed, 10 blocked); 15 failed before it. A run blocked at the gate or failed before it publishes nothing and opens an incident.");
  const html = await (await request.get("./")).text();
  expect(html).toMatch(/<noscript[^>]*>[\s\S]*https:\/\/mrrishit909\.github\.io\/projects-site\/[\s\S]*<\/noscript>/);
  expect(html).toContain("/projects-site/labs/pipeline-observatory/assets/");
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
    expect(new URL(page.url()).pathname).toBe(`/projects-site/labs/pipeline-observatory/${path}/`);
    await expect(page.getByTestId("synthetic-badge")).toBeVisible();
    await expect(page.getByTestId("honesty")).toContainText("Synthetic data, demo mode");
    await expect(page.getByTestId("honesty")).toContainText("simulations in browser memory");
    await expect(page.getByTestId("footer-honesty")).toContainText("simulations in browser memory");
    await expect(page.locator("[data-testid=manifest-strip] [data-k=code_sha]")).toHaveText("not recorded");
  }
  await page.goto("no-such-route/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Not found");
  expect(errors.filter((e) => !e.includes("no-such-route"))).toEqual([]);
});

test("overview: freshness beside ingestion age equals the Python reference; the silent source is hatched while its jobs are green", async ({ page }) => {
  const errors = watch(page);
  await page.goto("overview/");
  await ready(page);
  await page.getByTestId("fresh-table").waitFor();
  for (const f of ref.complete_world.freshness) {
    const row = page.locator(`[data-testid=fresh-table] tr[data-source=${f.source_id}]`);
    await expect(row.locator("[data-k=freshness]")).toHaveAttribute("data-seconds", String(f.freshness_seconds));
    await expect(row.locator("[data-k=ingestion-age]")).toHaveAttribute("data-seconds", String(f.ingestion_age_seconds));
    await expect(row.locator("[data-k=gap]")).toContainText(String(f.gap_seconds));
    await expect(row.locator("[data-k=cadences]")).toHaveText(f.cadences);
    await expect(row.locator("[data-k=jobs]")).toContainText(`last batch ${f.last_batch[1]}`);
    await expect(row.locator("[data-k=state] [data-status]")).toHaveAttribute("data-status", f.silent ? "silent" : "fresh");
  }
  const refunds = page.locator("[data-testid=fresh-table] tr[data-source=src-refunds]");
  await expect(refunds.locator("[data-k=jobs]")).toContainText("12 committed in the last 72 h");
  await expect(page.locator("[data-testid=freshness-chart] [data-source=src-refunds] [data-bar=freshness]")).toBeVisible();
  // complete-world ingestion, runs and gate equal Python's
  const O = ref.complete_world.ingestion.overall;
  await expect(fig(page, "received")).toHaveText(n0(O.received));
  await expect(fig(page, "accepted")).toHaveText(n0(O.accepted_unique));
  await expect(fig(page, "duplicate")).toHaveText(n0(O.duplicate));
  await expect(fig(page, "quarantined")).toHaveText(n0(O.quarantined));
  await expect(fig(page, "rejection-rate")).toHaveText(O.rejection_rate);
  await expect(fig(page, "duplicate-rate")).toHaveText(O.duplicate_rate);
  const R = ref.complete_world.runs;
  await expect(fig(page, "runs-total")).toHaveText(n0(R.durations.successful.count + R.durations.failed.count));
  await expect(fig(page, "task-success-rate")).toHaveText(R.overall.task_success_rate);
  await expect(fig(page, "attempt-success-rate")).toHaveText(R.overall.attempt_success_rate);
  await expect(fig(page, "duration-success")).toHaveText(R.durations.successful.mean_minutes);
  await expect(fig(page, "duration-failed")).toHaveText(R.durations.failed.mean_minutes);
  await expect(fig(page, "pointer")).toHaveText(ref.complete_world.pointer.current);
  // the sample is shown beside, labelled
  const S = ref.sample_world.headline.ingestion_overall;
  await expect(page.getByTestId("sample-note")).toContainText(`${n0(S.received)} received, ${n0(S.accepted_unique)} accepted`);
  await expect(page.getByTestId("window")).toContainText(manifest.generated_at.slice(0, 4));
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("overview: the CSV export holds every row of the table", async ({ page }) => {
  await page.goto("overview/");
  await ready(page);
  const [dl] = await Promise.all([page.waitForEvent("download"), page.getByTestId("export-fresh").click()]);
  const path = await dl.path();
  const { readFileSync } = await import("node:fs");
  const lines = readFileSync(path!, "utf8").trim().split("\n");
  expect(lines.length).toBe(7);
  expect(lines[0]).toContain("source_id,cadence,ingestion_age_seconds,freshness_seconds");
});

test("golden case, recomputed in the browser: 10 / 8 / 1 / 1, replay leaves 8, crash never a ninth, freshness vs ingestion age, completeness 8/9", async ({ page }) => {
  const errors = watch(page);
  await page.goto("runs/?dataset=golden");
  await ready(page);
  await expect(page.getByTestId("golden-flag")).toBeVisible();
  await expect(page.locator("[data-testid=manifest-strip] [data-k=dataset_version]")).toHaveText("golden-fixture-1");
  await page.getByTestId("golden-batches").waitFor();
  const b1 = page.locator("[data-testid=golden-batches] tr[data-batch=b-001]");
  await expect(b1.locator("[data-k=received]")).toHaveText("10");
  await expect(b1.locator("[data-k=accepted]")).toHaveText("8");
  await expect(b1.locator("[data-k=duplicate]")).toHaveText("1");
  await expect(b1.locator("[data-k=quarantined]")).toHaveText("1");
  const b2 = page.locator("[data-testid=golden-batches] tr[data-batch=b-002]");
  await expect(b2.locator("[data-k=accepted]")).toHaveText("0");
  await expect(b2.locator("[data-k=duplicate]")).toHaveText("9");
  await expect(page.locator("[data-testid=golden-batches] tr[data-batch=b-003]")).toContainText("aborted");
  await expect(page.getByTestId("golden-rows").locator("tr[data-class=accepted]")).toHaveCount(8);
  await expect(page.getByTestId("golden-rows").locator("tr[data-class=duplicate]")).toHaveCount(1);
  await expect(page.getByTestId("golden-rows").locator("tr[data-class=quarantined]")).toContainText("NEGATIVE_QUANTITY");
  await expect(page.getByTestId("golden-totals").locator("[data-figure=golden-accepted]")).toHaveText("8");
  const total = (id: string) => page.locator(`[data-experiment=${id}] [data-k=total]`);
  await expect(page.locator("[data-experiment=replay]")).toHaveAttribute("data-holds", "true");
  await expect(total("replay")).toHaveText(["8", "8"]);
  await expect(total("storm")).toHaveText(["8", "8", "8", "8", "8", "8"]);
  await expect(total("crash")).toHaveText(["8", "8", "8"]);
  await expect(total("crash-new-key")).toHaveText(["8", "8", "9"]);
  // the default run of the golden dataset is its blocked run
  await expect(page.getByTestId("run-detail")).toHaveAttribute("data-run", "run-002");
  // overview
  await page.goto("overview/?dataset=golden");
  await ready(page);
  const o = page.locator("[data-testid=fresh-table] tr[data-source=src-orders]");
  await expect(o.locator("[data-k=freshness]")).toHaveAttribute("data-seconds", "52200");
  await expect(o.locator("[data-k=ingestion-age]")).toHaveAttribute("data-seconds", "42900");
  await expect(page.locator("[data-testid=completeness-table] tr[data-source=src-orders] [data-k=value]")).toHaveText("0.888889");
  // the gate and the pointer
  await page.goto("gate/?dataset=golden");
  await ready(page);
  await expect(page.getByTestId("gate-decision")).toHaveAttribute("data-decision", "blocked");
  await expect(page.locator("[data-testid=gate-checks] tr[data-rule=keys_unique]")).toHaveAttribute("data-passed", "false");
  await expect(page.locator("[data-testid=gate-outcome] [data-k=pointer-before]")).toHaveText("pub-001");
  await expect(page.locator("[data-testid=gate-outcome] [data-k=pointer-after]")).toHaveText("pub-001");
  // incidents, backfill
  await page.goto("incidents/?dataset=golden");
  await ready(page);
  await expect(fig(page, "mean-recovery")).toHaveText("475.0000");
  await expect(page.locator("[data-testid=incident-detail] [data-figure=recovery-minutes]")).toHaveText("475.0000");
  await page.goto("backfill/?dataset=golden");
  await ready(page);
  await expect(fig(page, "coverage")).toHaveText("0.666667");
  await expect(page.getByTestId("backfill-totals")).toContainText("2/3");
  // evidence: fixture hashes, golden reconciliation shows through the digest table; late event through the case study experiment
  await page.goto("evidence/?dataset=golden");
  await ready(page);
  await expect(page.locator("[data-testid=hash-table] tr[data-check=fixture]")).toHaveAttribute("data-ok", "true");
  await expect(page.locator("[data-testid=hash-table] tr[data-check=payload]")).toHaveAttribute("data-ok", "true");
  await expect(page.locator("[data-testid=hash-table] tr[data-check=content]")).toHaveAttribute("data-ok", "true");
  await page.goto("case-study/?dataset=golden");
  await ready(page);
  await expect(page.getByTestId("run-INJ-09")).toBeEnabled();
  await page.getByTestId("run-INJ-09").click();
  await expect(page.locator("tr[data-inj=INJ-09] [data-k=result]")).toContainText("REF-2001");
  await expect(page.locator("tr[data-inj=INJ-09] [data-k=result]")).toContainText("pub-003");
  expect(errors).toEqual([]);
});

test("dag: freshness on the nodes, and keyboard isolation of a node", async ({ page }) => {
  const errors = watch(page);
  await page.goto("dag/");
  await ready(page);
  await page.getByTestId("dag").waitFor();
  const nodes = page.locator("[data-testid=dag-node]");
  await expect(nodes).toHaveCount(ref.complete_world.graph.nodes);
  // freshness is drawn independently of the job mark: refunds is amber while its job mark is the green check
  const refunds = page.locator("[data-node=src-refunds]");
  await expect(refunds).toHaveAttribute("data-stale", "true");
  await expect(refunds.locator(".dag__job")).toHaveText("✓");
  await expect(page.locator("[data-node=src-orders]")).toHaveAttribute("data-stale", "false");
  await expect(page.locator("[data-node=pub\\:sales_daily]")).toHaveAttribute("data-stale", "true");   // inherited from the stalest upstream source
  // keyboard: focus the refunds node, isolate it with Enter
  await refunds.focus();
  await expect(refunds).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(refunds).toHaveAttribute("data-state", "selected");
  await expect(page.locator("[data-node=src-orders]")).toHaveAttribute("data-state", "dimmed");
  await expect(page.locator("[data-node=m-stg-refunds]")).toHaveAttribute("data-state", "related");
  await expect(page.locator("[data-node=pub\\:sales_daily]")).toHaveAttribute("data-state", "related");
  await expect(page.locator("[data-testid=dag-detail] [data-k=downstream]")).toContainText("m-stg-refunds");
  expect(new URL(page.url()).searchParams.get("node")).toBe("src-refunds");
  // arrow keys move between nodes; Escape clears
  await page.keyboard.press("ArrowRight");
  await expect(page.locator("[data-node=m-stg-refunds]")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.locator("[data-testid=dag-node][data-state=dimmed]")).toHaveCount(0);
  await refunds.focus();
  await page.keyboard.press("Space");
  await expect(page.getByTestId("dag-clear")).toBeVisible();
  await page.getByTestId("dag-clear").click();
  await expect(page.locator("[data-testid=dag-node][data-state=selected]")).toHaveCount(0);
  await expect(page.getByTestId("dag-table").locator("tbody tr")).toHaveCount(ref.complete_world.graph.nodes);
  expect(errors).toEqual([]);
});

test("runs: the blocked run keeps the pointer; steps, attempts, quality results, the log and the redaction check", async ({ page }) => {
  const errors = watch(page);
  await page.goto("runs/?run=run-1187");
  await ready(page);
  await page.getByTestId("run-detail").waitFor();
  await expect(page.getByTestId("run-detail")).toHaveAttribute("data-run", "run-1187");
  await expect(page.getByTestId("run-outcome")).toContainText("No publication row exists");
  await expect(page.getByTestId("run-outcome")).toContainText("pub-1186");
  await expect(page.getByTestId("run-outcome")).toContainText("inc-022");
  await expect(page.getByTestId("run-outcome")).toContainText("67.8833");
  await expect(page.locator("[data-testid=run-quality] tr[data-rule=relationships_intact]")).toContainText("failed");
  await expect(page.locator("[data-testid=run-steps] tr[data-task=publish]")).toContainText("not run");
  await expect(page.getByTestId("run-timeline")).toBeVisible();
  await expect(page.getByTestId("run-log").locator("tbody tr").first()).toContainText("run run-1187 started");
  await expect(page.getByTestId("run-log")).not.toContainText("LOG LINE WITHHELD");
  // controls
  await page.getByTestId("run-prev").click();
  await expect(page.getByTestId("run-detail")).toHaveAttribute("data-run", "run-1186");
  await page.getByTestId("run-latest").click();
  await expect(page.getByTestId("run-detail")).toHaveAttribute("data-run", "run-1343");
  await page.getByTestId("run-select").selectOption("run-0731");
  await expect(page.getByTestId("run-detail")).toHaveAttribute("data-run", "run-0731");
  await expect(page.getByTestId("run-outcome")).toContainText("inc-015");
  await page.goto("runs/?run=run-9999");
  await expect(page.getByTestId("run-missing")).toBeVisible();
  expect(errors).toEqual([]);
});

test("gate: critical checks, the decision, the pointer; fault injection re-decides in memory and resets on reload", async ({ page }) => {
  const errors = watch(page);
  await page.goto("gate/");
  await ready(page);
  await page.getByTestId("gate-decision").waitFor();
  await expect(page.getByTestId("gate-run")).toHaveValue("run-1187");
  await expect(page.getByTestId("gate-decision")).toHaveAttribute("data-decision", "blocked");
  await expect(page.locator("[data-testid=gate-checks] tr[data-rule=relationships_intact] [data-k=result]")).toContainText("failed");
  await expect(page.locator("[data-testid=gate-checks] tr[data-rule=keys_unique] [data-k=result]")).toContainText("passed");
  await expect(page.locator("[data-testid=gate-outcome] [data-k=pointer-before]")).toHaveText("pub-1186");
  await expect(page.locator("[data-testid=gate-outcome] [data-k=pointer-after]")).toHaveText("pub-1186");
  await expect(page.getByTestId("gate-totals")).toContainText("1,343 runs: 1,328 reached the gate (1,318 allowed, 10 blocked); 15 failed before it");
  await expect(page.getByRole("heading", { name: "Every failed run" })).toBeVisible();
  await expect(page.locator("[data-testid=blocked-table] tr[data-kind=blocked]")).toHaveCount(10);
  await expect(page.locator("[data-testid=blocked-table] tr[data-kind=before-gate]")).toHaveCount(15);
  await expect(page.locator("[data-testid=blocked-table] tr[data-run=run-1187] [data-k=kind]")).toHaveText("blocked at the gate");
  await expect(page.getByRole("button", { name: "Show the gate of run-1187" })).toBeVisible();      // the "Show" buttons have accessible names
  await expect(page.getByTestId("completeness-signal")).toContainText("fails in");
  await expect(page.getByTestId("blocked-table").locator("tbody tr")).toHaveCount(ref.sample_world.headline.gate.blocked);
  // what-if: force the failing check to pass -> allowed, would move to a candidate; force a warning to fail -> still allowed
  await expect(page.getByTestId("whatif-decision")).toContainText("blocked");
  await page.getByTestId("fault-relationships_intact").selectOption("pass");
  await expect(page.getByTestId("whatif-decision")).toContainText("allowed");
  await expect(page.getByTestId("whatif-run")).toHaveText("success");
  await expect(page.getByTestId("whatif-pointer")).toContainText("candidate of run-1187");
  await page.getByTestId("fault-completeness_vs_expectation").selectOption("fail");
  await expect(page.getByTestId("whatif-decision")).toContainText("allowed");
  await page.getByTestId("fault-keys_unique").selectOption("fail");
  await expect(page.getByTestId("whatif-decision")).toContainText("blocked");
  await expect(page.getByTestId("whatif-pointer")).toHaveText("pub-1186");
  await page.getByTestId("fault-record").click();
  await expect(page.getByTestId("fault-log").locator("tbody tr")).toHaveCount(1);
  // the published decision above did not change
  await expect(page.getByTestId("gate-decision")).toHaveAttribute("data-decision", "blocked");
  await expect(page.getByTestId("sim-note")).toBeVisible();
  // pick an allowed run
  await page.getByTestId("gate-run").selectOption("run-1343");
  await expect(page.getByTestId("gate-decision")).toHaveAttribute("data-decision", "allowed");
  await page.reload();
  await ready(page);
  await expect(page.getByTestId("fault-log")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("quarantine desk: filters, no-data state, replay of a corrected row in memory, discard needs a reason, reset", async ({ page }) => {
  const errors = watch(page);
  await page.goto("quarantine/");
  await ready(page);
  await page.getByTestId("q-table").waitFor();
  const total = ref.dataset.row_counts.quarantine_records;
  await expect(page.getByTestId("q-count")).toContainText(`${n0(total)} of ${n0(total)} rows match`);
  await page.getByTestId("f-reason").selectOption("NEGATIVE_QUANTITY");
  await expect(page.getByTestId("q-count")).toContainText("220 of");
  await page.getByTestId("f-payload").selectOption("yes");
  const rows = page.getByTestId("q-table").locator("tbody tr");
  await expect(rows.first()).toBeVisible();
  // no data, then clear
  await page.getByTestId("f-q").fill("zzz-no-such-key");
  await expect(page.getByTestId("empty")).toBeVisible();
  await page.getByTestId("empty").getByRole("button", { name: "Clear filters" }).click();
  await expect(page.getByTestId("q-count")).toContainText(`${n0(total)} of`);
  // open a row whose payload is published, correct it, replay
  await page.getByTestId("f-reason").selectOption("NEGATIVE_QUANTITY");
  await page.getByTestId("f-payload").selectOption("yes");
  await rows.first().getByRole("button", { name: /Open/ }).click();
  await expect(page.getByTestId("q-detail")).toContainText("NEGATIVE_QUANTITY");
  await page.getByTestId("q-retry").click();
  await expect(page.getByTestId("q-result")).toContainText("still quarantined (NEGATIVE_QUANTITY)");
  const ta = page.getByTestId("q-payload");
  const payload = JSON.parse(await ta.inputValue());
  payload.quantity = Math.abs(payload.quantity);
  await ta.fill(JSON.stringify(payload));
  await page.getByTestId("q-retry").click();
  await expect(page.getByTestId("q-result")).toContainText(/accepted|duplicate/);
  await expect(page.getByTestId("sim-note").first()).toBeVisible();
  await expect(page.locator("[data-figure=sim-touched]")).toHaveText("1");
  // discard needs a reason
  await expect(page.getByTestId("q-discard")).toBeDisabled();
  await page.getByTestId("q-why").fill("source confirmed the row was a test");
  await page.getByTestId("q-discard").click();
  await expect(page.locator("[data-figure=sim-discarded]")).toHaveText("1");
  await expect(page.getByTestId("sim-log").locator("tbody tr")).toHaveCount(3);
  // the published figures did not move
  await expect(page.locator("[data-testid=reason-table] tr[data-reason=NEGATIVE_QUANTITY] [data-k=rows]")).toHaveText("220");
  // a row with no published payload cannot be replayed
  await page.getByTestId("f-payload").selectOption("no");
  await page.getByTestId("q-table").locator("tbody tr").first().getByRole("button", { name: /Open/ }).click();
  await expect(page.getByTestId("q-nopayload")).toBeVisible();
  // reset
  await page.getByTestId("sim-reset").click();
  await expect(page.locator("[data-figure=sim-touched]")).toHaveText("0");
  // reload also resets
  await page.getByTestId("f-payload").selectOption("yes");
  await page.getByTestId("q-table").locator("tbody tr").first().getByRole("button", { name: /Open/ }).click();
  await page.getByTestId("q-retry").click();
  await expect(page.locator("[data-figure=sim-touched]")).toHaveText("1");
  await page.reload();
  await ready(page);
  await expect(page.locator("[data-figure=sim-touched]")).toHaveText("0");
  expect(errors).toEqual([]);
});

test("backfill: totals equal Python's; the refused requests; the console accepts the range a settled request left unverified, refuses an overlap with a request still requested, then resets", async ({ page }) => {
  const errors = watch(page);
  await page.goto("backfill/");
  await ready(page);
  const B = ref.complete_world.backfills;
  await expect(fig(page, "requested")).toHaveText(String(B.overall.requested_partitions));
  await expect(fig(page, "verified")).toHaveText(String(B.overall.verified_partitions));
  await expect(fig(page, "coverage")).toHaveText(B.overall.coverage);
  await expect(page.locator("[data-testid=backfill-table] tr[data-req=bf-006]")).toContainText("refused BACKFILL_OVERLAP: overlaps bf-004");
  await expect(page.locator("[data-testid=backfill-table] tr[data-req=bf-012]")).toContainText("overlaps bf-010");
  await expect(page.locator("[data-testid=backfill-table] tr[data-refused=true]")).toHaveCount(B.refused.length);
  await page.getByTestId("bf-source").selectOption("src-inventory");
  await page.getByTestId("bf-start").fill("2026-08-22");
  await page.getByTestId("bf-end").fill("2026-08-24");
  await page.getByTestId("bf-submit").click();
  // D-09 (R8-12): bf-004 settled partial, so it no longer blocks: the range over its unverified partition is accepted and says what it backfills again
  await expect(page.getByTestId("bf-result")).toContainText("accepted: 2 daily partitions");
  await expect(page.getByTestId("bf-result")).toContainText("2026-08-22 (left unverified by bf-004, which has settled)");
  await page.getByTestId("bf-start").fill("2026-09-20");
  await page.getByTestId("bf-end").fill("2026-09-22");
  await page.getByTestId("bf-submit").click();
  await expect(page.getByTestId("bf-result")).toContainText("accepted: 2 daily partitions");
  await page.getByRole("button", { name: /Mark the next partition of request 2 verified/ }).click();
  await expect(page.locator("tr[data-sim='2'] [data-k=progress]")).toContainText("1/2 = 0.500000");
  await page.getByTestId("bf-start").fill("2026-09-20");
  await page.getByTestId("bf-end").fill("2026-09-21");
  await page.getByTestId("bf-submit").click();
  await expect(page.getByTestId("bf-result")).toContainText("refused BACKFILL_OVERLAP");
  await page.getByTestId("bf-start").fill("2026-08-22");                          // the range accepted first is still requested: a second request over it is refused
  await page.getByTestId("bf-end").fill("2026-08-24");
  await page.getByTestId("bf-submit").click();
  await expect(page.getByTestId("bf-result")).toContainText("refused BACKFILL_OVERLAP");
  await page.getByTestId("bf-reset").click();
  await expect(page.getByTestId("sim-backfills")).toHaveCount(0);
  await expect(fig(page, "coverage")).toHaveText(B.overall.coverage);
  expect(errors).toEqual([]);
});

test("incidents, sources, benchmark, evidence and case study: figures equal Python's", async ({ page }) => {
  const errors = watch(page);
  const I = ref.complete_world.incidents;
  await page.goto("incidents/");
  await ready(page);
  await expect(fig(page, "incidents-total")).toHaveText(String(I.total));
  await expect(fig(page, "mean-recovery")).toHaveText(I.mean_recovery_minutes);
  await expect(page.getByTestId("incident-detail")).toHaveAttribute("data-incident", "inc-022");
  await expect(page.locator("[data-testid=incident-detail] [data-figure=recovery-minutes]")).toHaveText("67.8833");
  await expect(page.getByTestId("residual-note")).toContainText("every publication reconciles to 0.00");
  for (const [c, n] of Object.entries(I.by_class)) await expect(page.locator(`[data-testid=class-table] tr[data-class=${c}] [data-k=count]`)).toHaveText(String(n));
  await page.locator("[data-testid=incident-mark][data-incident=inc-015]").focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("incident-detail")).toHaveAttribute("data-incident", "inc-015");
  await expect(page.locator("[data-testid=incident-detail] [data-figure=recovery-minutes]")).toHaveText("63.1000");
  await expect(page.getByTestId("incident-table").locator("tbody tr")).toHaveCount(I.total);
  await page.goto("sources/");
  await ready(page);
  const r = ref.complete_world.retry;
  await expect(fig(page, "rate-limited")).toHaveText(String(r.rate_limited_responses));
  await expect(fig(page, "honoured")).toHaveText(String(r.retries_honouring_retry_after));
  await expect(page.getByTestId("sources-table").locator("tbody tr")).toHaveCount(6);
  await expect(page.getByTestId("version-compare")).toContainText("channel");
  await page.getByTestId("tester-version").fill("2");
  await expect(page.getByTestId("tester-result")).toContainText("SCHEMA_CHANGED");
  await page.getByTestId("tester-version").fill("");
  await page.getByTestId("tester-payload").fill('{"record_id":"X","quantity":-1,"unit_price":"1.00","amount":"1.00","event_ts":"2026-10-04T00:00:00Z"}');
  await expect(page.getByTestId("tester-result")).toContainText("NEGATIVE_QUANTITY");
  await page.goto("benchmark/");
  await ready(page);
  const P = ref.sample_world.headline.processing_rate;
  await expect(page.locator("[data-testid=bench-recorded] [data-k=rate]")).toHaveText(P.records_per_second);
  await expect(page.locator("[data-testid=bench-recorded] [data-k=rec-rate]")).toHaveText("39.253789");
  await page.getByTestId("bench-run").click();
  await expect(page.getByTestId("bench-result")).toContainText("Pipeline, 3 runs");
  await expect(page.getByTestId("bench-size").locator("tbody tr")).toHaveCount(17);
  await page.goto("evidence/");
  await ready(page);
  await expect(page.locator("[data-testid=hash-table] tr[data-check=dataset]")).toHaveAttribute("data-ok", "true");
  await expect(page.locator("[data-testid=hash-table] tr[data-check=payload]")).toHaveAttribute("data-ok", "true");
  await expect(page.locator("[data-testid=hash-table] tr[data-check=definition]")).toHaveAttribute("data-ok", "true");
  await expect(page.locator("[data-testid=hash-table] tr[data-check=content]")).toContainText("not verifiable here");
  for (const k of Object.keys(ref.sample_world.digests)) await expect(page.locator(`[data-testid=digest-table] tr[data-block=${k}] td code`)).toHaveText(ref.sample_world.digests[k]);
  await expect(page.getByTestId("inj-total")).toContainText(`${ref.claims.injection_holding} of ${ref.claims.injection.length}`);
  await expect(page.locator("[data-dr=DR-02] tr[data-claim='DR-02:recovery_minutes']")).toHaveAttribute("data-ok", "true");
  await expect(page.locator("[data-dr=DR-01] tr[data-claim='DR-01:freshness_seconds']")).toHaveAttribute("data-ok", "null");
  await page.goto("case-study/");
  await ready(page);
  await expect(page.getByTestId("guarantees")).toContainText("never exactly-once");
  for (const id of ["INJ-01", "INJ-02", "INJ-03", "INJ-04", "INJ-05", "INJ-06", "INJ-07", "INJ-08", "INJ-09", "INJ-10", "INJ-11"]) {
    await page.getByTestId(`run-${id}`).click();
    await expect(page.locator(`tr[data-inj=${id}] [data-k=result]`)).toContainText("as expected");
  }
  await expect(page.locator("tr[data-inj=INJ-12]")).toContainText("backend CI only");
  expect(errors).toEqual([]);
});

test("failed data: a server error shows a failed-data state and invents nothing", async ({ page }) => {
  await page.route("**/data/pipeline_runs.json", (route) => route.fulfill({ status: 500, body: "boom" }));
  await page.goto("overview/");
  await expect(page.getByTestId("load-error")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("load-error")).toContainText("HTTP 500");
  await expect(page.getByTestId("fresh-table")).toHaveCount(0);
  await expect(page.locator("[data-testid=manifest-strip]")).toContainText("unavailable");
  await expect(page.getByTestId("honesty")).toBeVisible();
});

test("keyboard: every control on the gate page is reachable and shows a visible focus ring", async ({ page }) => {
  await page.goto("gate/");
  await ready(page);
  await page.getByTestId("gate-decision").waitFor();
  const seen = new Set<string>();
  for (let i = 0; i < 40; i++) {
    await page.keyboard.press("Tab");
    const info = await page.evaluate(() => { const e = document.activeElement as HTMLElement; const cs = getComputedStyle(e); return { tag: e.tagName, test: e.getAttribute("data-testid") ?? "", outline: cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) >= 2 }; });
    if (info.test) seen.add(info.test);
    if (["SELECT", "BUTTON", "A", "INPUT"].includes(info.tag)) expect(info.outline, `${info.tag} ${info.test} has no focus outline`).toBe(true);
  }
  expect(seen.has("gate-run")).toBe(true);
  expect(seen.has("fault-keys_unique")).toBe(true);
});

test("D-09 wording: quarantine scope, minutes beside seconds, header-asserted identity, the staged crash, the vacuous golden crash", async ({ page }) => {
  const errors = watch(page);
  await page.goto("overview/");
  await ready(page);
  await expect(page.locator("main")).toContainText("in committed batches; the 17 rows of the schema-quarantined batch are listed separately");
  await expect(page.locator("main")).toContainText(/\d+\.\d{4} min/);
  await page.goto("evidence/");
  await ready(page);
  await expect(page.getByTestId("identity-note")).toContainText("header");
  await expect(page.locator("main")).toContainText("schema-quarantined batch");
  await page.goto("case-study/");
  await ready(page);
  await expect(page.getByTestId("identity-note")).toContainText("no authentication");
  await expect(page.locator("main")).toContainText("staged");
  await page.goto("runs/?dataset=golden");
  await ready(page);
  await expect(page.getByTestId("golden-vacuous")).toContainText("vacuous");
  expect(errors, "console errors").toEqual([]);
});
