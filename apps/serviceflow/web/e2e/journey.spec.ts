import { expect, test, type Page } from "@playwright/test";
import { expectNoOverflow, readData, ready, watch } from "./support";

interface Rows<T> { rows: T[] }
const manifest = readData<{ dataset_version: string; dataset_hash: string; generated_at: string }>("manifest.json");
const tickets = readData<Rows<{ ticket_id: string; created_at: string; queue_id: string }>>("tickets.json").rows;
const shifts = readData<Rows<{ shift_id: string; starts_at: string; ends_at: string }>>("shifts.json").rows;
const figure = (page: Page, name: string) => page.locator(`[data-figure="${name}"] dd`).first();
const minutes = (s: { starts_at: string; ends_at: string }): number => (Date.parse(s.ends_at) - Date.parse(s.starts_at)) / 60000;

test("landing: honesty labels, the manifest strip, the back-link and the entry journey", async ({ page, request }) => {
  const errors = watch(page);
  await page.goto("./");
  await ready(page);
  await expect(page).toHaveTitle(/ServiceFlow/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("ServiceFlow");
  await expect(page.getByTestId("synthetic-badge")).toHaveText("Synthetic data, demo mode");
  const strip = page.getByTestId("manifest-strip");
  await expect(strip.locator("[data-k=dataset_version]")).toHaveText(manifest.dataset_version);
  await expect(strip.locator("[data-k=dataset_hash]")).toHaveAttribute("title", manifest.dataset_hash);
  await expect(strip.locator("[data-k=generated_at]")).toHaveText(manifest.generated_at);
  await expect(strip.locator("[data-k=code_sha]")).toBeVisible();
  await expect(page.locator("footer")).toContainText("Nothing here is live");
  await expect(page.getByTestId("decision")).toContainText("Which staffing or routing change meets support targets");
  await expect(page.getByTestId("backlink")).toHaveAttribute("href", "https://mrrishit909.github.io/projects-site/");
  expect(await page.locator('link[rel="author"]').getAttribute("href")).toBe("https://mrrishit909.github.io/projects-site/");
  await expect(page.getByTestId("journey").locator("li")).toHaveCount(6);
  await expect(page.getByTestId("glance")).toContainText("Open overdue, shown separately");
  // the static HTML carries the back-link inside <noscript>, like the other apps
  const html = await (await request.get("./")).text();
  expect(html).toMatch(/<noscript[^>]*>[\s\S]*https:\/\/mrrishit909\.github\.io\/projects-site\/[\s\S]*<\/noscript>/);
  expect(html).toContain('<link rel="author" href="https://mrrishit909.github.io/projects-site/"');
  expect(html).toContain('/projects-site/labs/serviceflow/assets/');
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("every route is reachable by direct entry and reload on the nested base path", async ({ page }) => {
  const errors = watch(page);
  for (const path of ["overview", "queues", "tickets", "staffing", "sla", "simulation", "compare", "surveys", "evidence", "case-study"]) {
    await page.goto(`${path}/`);
    await ready(page);
    await page.reload();
    await ready(page);
    expect(new URL(page.url()).pathname).toBe(`/projects-site/labs/serviceflow/${path}/`);
    await expect(page.getByTestId("synthetic-badge")).toBeVisible();
  }
  await page.goto("no-such-route/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Not found");
  expect(errors.filter((e) => !e.includes("no-such-route"))).toEqual([]);
});

test("the golden dataset: overview figures, switch persists across routes, golden flag", async ({ page }) => {
  const errors = watch(page);
  await page.goto("overview/?dataset=golden");
  await ready(page);
  await expect(page.getByTestId("golden-flag")).toContainText("golden fixture");
  await expect(page.getByTestId("manifest-strip").locator("[data-k=dataset_version]")).toHaveText("golden-v1");
  await expect(figure(page, "first_response_mean")).toHaveText("10.0000 min");
  await expect(figure(page, "first_response_p90")).toHaveText("20.0000 min");
  await expect(figure(page, "wait_mean")).toHaveText("10.0000 min");
  await expect(figure(page, "resolution_mean")).toHaveText("20.0000 min");
  await expect(page.locator('[data-metric="sla_first_response_compliance"] td')).toHaveText("0.666667");
  await expect(page.locator('[data-metric="sla_resolution_compliance"] td')).toHaveText("1.000000");
  await expect(page.locator('[data-metric="agent_occupancy"] td')).toHaveText("0.500000");
  await expect(page.locator('[data-metric="staffed_available_minutes"] td')).toHaveText("60.0000");
  await expect(page.locator('[data-metric="handling_minutes_total"] td')).toHaveText("30.0000");
  await expect(page.locator('[data-metric="abandonment_rate"] td')).toContainText("no value");
  await expect(page.locator('[data-metric="csat"] td')).toHaveText("1.000000");
  await expect(figure(page, "backlog_end")).toHaveText("0");
  await expect(figure(page, "overdue_end")).toHaveText("0");
  await page.getByRole("link", { name: "Ticket timeline" }).first().click();
  expect(new URL(page.url()).searchParams.get("dataset")).toBe("golden");
  await expect(page.getByTestId("timeline-table").locator("tbody tr")).toHaveCount(3);
  await expect(page.getByTestId("timeline-summary")).toContainText("3 tickets arrived on 2026-07-06");
  expect(errors).toEqual([]);
});

test("overview: 28 metric keys, window toggle, group_by and the tail beside the mean", async ({ page }) => {
  const errors = watch(page);
  await page.goto("overview/");
  await ready(page);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Service overview");
  await expect(page.getByTestId("metric-sheet").locator("tbody tr")).toHaveCount(28);
  await expect(page.getByTestId("rejected")).toContainText("rejected");
  for (const id of ["first_response_mean", "first_response_p90", "wait_mean", "wait_p90", "resolution_mean", "resolution_p90"]) await expect(figure(page, id)).toBeVisible();
  await expect(page.getByTestId("open-work")).toContainText("Open overdue");
  await expect(page.getByTestId("open-work")).toContainText("Abandoned arrivals");
  const full = await page.locator('[data-metric="arrival_count"] td').innerText();
  await page.getByLabel("Training, weeks 1-8").check({ force: true });
  expect(new URL(page.url()).searchParams.get("window")).toBe("training");
  await expect(page.getByTestId("window-line")).toContainText("2026-08-31T00:00:00Z");
  const train = await page.locator('[data-metric="arrival_count"] td').innerText();
  await page.getByLabel("Holdout, weeks 9-12").check({ force: true });
  const hold = await page.locator('[data-metric="arrival_count"] td').innerText();
  expect(Number(train) + Number(hold)).toBe(Number(full));
  expect(Number(hold)).toBeGreaterThan(0);
  await page.getByLabel("Full window").check({ force: true });
  await page.locator("#group-by").selectOption("queue");
  await expect(page.getByTestId("metric-sheet").locator("thead th")).toHaveText(["Metric key", "q-001", "q-002", "q-003"]);
  await expect(page.locator('[data-metric="staffed_available_minutes"] td').first()).toContainText("no value");
  await page.locator("#group-by").selectOption("agent");
  await expect(page.getByTestId("metric-sheet").locator("thead th")).toHaveCount(19);
  expect(await page.locator('[data-metric="agent_occupancy"] td').first().innerText()).not.toContain("no value");
  await page.locator("#group-by").selectOption("priority");
  await expect(page.getByTestId("metric-sheet").locator("thead th")).toHaveText(["Metric key", "P1", "P2", "P3"]);
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("tickets: the queue timeline, keyboard navigation, queue filter and the matching table", async ({ page }) => {
  const errors = watch(page);
  const day = "2026-09-07";
  await page.goto(`tickets/?day=${day}`);
  await ready(page);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Queue timeline");
  const raw = tickets.filter((t) => t.created_at.startsWith(day)).length;
  const rows = page.locator("[data-testid=timeline] g.tl-row");
  const n = await rows.count();
  expect(n).toBeGreaterThan(raw - 9);
  expect(n).toBeLessThanOrEqual(raw);
  await expect(page.getByTestId("timeline-table").locator("tbody tr")).toHaveCount(n);
  await expect(page.getByTestId("timeline-summary")).toContainText(`${n} tickets arrived on ${day}`);
  await expect(page.getByTestId("timeline").locator("svg")).toBeVisible();
  for (const cls of [".tl-wait", ".tl-service", ".tl-done"]) expect(await page.locator(`[data-testid=timeline] ${cls}`).count(), cls).toBeGreaterThan(0);
  // keyboard: arrows move between rows, Enter selects and opens the event log
  await rows.first().focus();
  await page.keyboard.press("ArrowDown");
  expect(await page.evaluate(() => document.activeElement?.getAttribute("data-ticket"))).toBe(await rows.nth(1).getAttribute("data-ticket"));
  await page.keyboard.press("Enter");
  const picked = await rows.nth(1).getAttribute("data-ticket");
  await expect(page.getByTestId("ticket-detail")).toContainText(`${picked}: event log`);
  await expect(page.getByTestId("ticket-detail")).toContainText("created");
  expect(new URL(page.url()).searchParams.get("ticket")).toBe(picked);
  // queue filter
  await page.locator("#queue").selectOption("q-002");
  const nq = await rows.count();
  expect(nq).toBeGreaterThan(0);
  expect(nq).toBeLessThan(n);
  await expect(page.getByTestId("timeline-table").locator("tbody tr")).toHaveCount(nq);
  await expect(page.getByTestId("timeline-table").locator("tbody tr td:nth-child(2)")).toHaveText(Array(nq).fill("Technical"));
  await page.locator("#priority").selectOption("P1");
  const np = await rows.count();
  expect(np).toBeLessThanOrEqual(nq);
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("staffing: the shift grid on the daylight-saving weekend, 420 against 480 minutes", async ({ page }) => {
  const errors = watch(page);
  await page.goto("staffing/");
  await ready(page);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Shift grid");
  await expect(page.locator("#sday")).toHaveValue("2026-09-05");
  await expect(page.getByTestId("shift-grid").locator("g[data-agent]")).toHaveCount(18);
  await expect(page.getByTestId("grid-summary")).toContainText("of 18 agents");
  await page.goto("staffing/?day=2026-09-06");
  await ready(page);
  await expect(page.getByTestId("dst-marker")).toContainText("America/Santiago clocks UTC-04:00 to UTC-03:00 at 04:00Z");
  const sh761 = shifts.find((s) => s.shift_id === "sh-0761")!, sh762 = shifts.find((s) => s.shift_id === "sh-0762")!;
  expect(minutes(sh761)).toBe(420);
  expect(minutes(sh762)).toBe(480);
  const r761 = page.locator('[data-shift="sh-0761"]'), r762 = page.locator('[data-shift="sh-0762"]');
  await expect(r761.locator("td.num").first()).toHaveText("420");
  await expect(r761).toContainText("crosses the clock change");
  await expect(r762.locator("td.num").first()).toHaveText("480");
  await expect(r762).toContainText("INJ-08");
  await expect(page.getByTestId("shift-table")).toContainText("Europe/Berlin");
  expect(await page.locator("[data-testid=shift-grid] .sg-brk").count()).toBeGreaterThan(0);
  expect(await page.locator("[data-testid=shift-grid] .sg-shift").count()).toBeGreaterThan(0);
  await page.getByTestId("day-presets").getByRole("link", { name: "2026-09-05" }).click();
  await expect(page.locator("#sday")).toHaveValue("2026-09-05");
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("sla: compliance per priority, open overdue separately, P90 beside the mean", async ({ page }) => {
  const errors = watch(page);
  await page.goto("sla/");
  await ready(page);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("SLA review");
  const table = page.getByTestId("sla-table");
  await expect(table.locator("tbody tr")).toHaveCount(4);
  await expect(table).toContainText("Open overdue");
  await expect(table).toContainText("P90 (min)");
  await expect(table).toContainText("Mean (min)");
  const cells = async (p: string): Promise<number[]> => (await page.locator(`[data-priority="${p}"] td.num`).allInnerTexts()).filter((t) => /^\d+ \/ \d+$/.test(t)).flatMap((t) => t.split(" / ").map(Number));
  const sum = [0, 0, 0, 0];
  for (const p of ["P1", "P2", "P3"]) (await cells(p)).forEach((v, i) => { sum[i]! += v; });
  expect(await cells("all")).toEqual(sum);
  const over = await Promise.all(["P1", "P2", "P3"].map(async (p) => Number(await page.locator(`[data-priority="${p}"] [data-cell=overdue]`).innerText())));
  expect(Number(await page.locator('[data-priority="all"] [data-cell=overdue]').innerText())).toBe(over.reduce((a, b) => a + b, 0));
  await expect(page.getByTestId("sla-headline")).toContainText("not in the ratio above");
  await expect(page.getByTestId("sla-compare-table").locator("tbody tr")).toHaveCount(2);
  await page.goto("sla/?dataset=golden");
  await ready(page);
  await expect(page.locator('[data-priority="P2"]')).toContainText("2 / 3");
  await expect(page.locator('[data-priority="P2"]')).toContainText("66.67 %");
  await expect(page.locator('[data-priority="P2"]')).toContainText("20.0000");
  await expect(page.locator('[data-priority="P2"] [data-cell=overdue]')).toHaveText("0");
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("simulation: the golden case in the browser, the published runs against the Python reference, seeded runs", async ({ page }) => {
  const errors = watch(page);
  await page.goto("simulation/");
  await ready(page);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Simulation studio");
  const golden = page.getByTestId("golden-figures");
  await expect(golden.locator('[data-figure="golden_waits"] dd').first()).toHaveText("0.0000 / 10.0000 / 20.0000");
  await expect(golden.locator('[data-figure="golden_mean"] dd').first()).toHaveText("10.0000");
  await expect(golden.locator('[data-figure="golden_completion"] dd').first()).toHaveText("30.0000");
  await expect(page.getByTestId("golden-event-ids")).toHaveText("se-001 se-002 se-003 se-004 se-005 se-006");
  await expect(page.getByTestId("golden-checks").locator("li.ok")).toHaveCount(4);
  await expect(page.getByTestId("golden-checks").locator("li.bad")).toHaveCount(0);
  await expect(page.getByTestId("golden-events").locator("tbody tr")).toHaveCount(6);
  await expect(page.getByTestId("golden-events")).toContainText("service_started");
  await expect(page.getByTestId("golden-case")).toContainText("P04-GOLD-01");
  // the three published runs, re-simulated with their seed
  for (const id of ["sim-001", "sim-002", "sim-003"]) {
    await expect(page.getByTestId(`match-${id}`)).toContainText("equal the stored Python reference");
    await expect(page.getByTestId(`run-${id}`)).toContainText("seed 20261026");
  }
  await expect(page.getByTestId("run-sim-001")).toContainText("14.6140");
  await expect(page.getByTestId("run-sim-002")).toContainText("3.8776");
  await expect(page.getByTestId("run-sim-003")).toContainText("33.6237");
  await expect(page.getByTestId("published-runs")).toContainText("Estimate from a seeded model");
  await expect(page.getByTestId("runs-table").locator("tbody tr")).toHaveCount(3);
  await expect(page.getByTestId("holdout-facts")).toContainText("Relative change");
  // seeded studio: deterministic, and a different seed gives a different estimate
  const mean = (): Promise<string> => page.locator('[data-fact="studio-mean"]').innerText();
  const first = await mean();
  await expect(page.locator('[data-fact="reps"]')).toHaveText("10");
  await page.getByTestId("run-sim").click();
  expect(await mean()).toBe(first);
  await page.locator("#sim-seed").fill("7");
  await page.getByTestId("run-sim").click();
  expect(await mean()).not.toBe(first);
  await page.locator("#sim-seed").fill("7");
  await page.getByTestId("run-sim").click();
  const seven = await mean();
  await page.getByTestId("run-sim").click();
  expect(await mean()).toBe(seven);
  await page.locator("#sim-reps").fill("1");
  await page.getByTestId("run-sim").click();
  await expect(page.locator('[data-fact="studio-ci"]')).toContainText("no value");
  await expect(page.getByTestId("studio-result")).toContainText("Estimate from a seeded model");
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("evidence: live golden checks equal their expected values and the CI and source links are present", async ({ page }) => {
  const errors = watch(page);
  await page.goto("evidence/");
  await ready(page);
  const summary = page.getByTestId("live-summary");
  await expect(summary).toContainText("checks equal their expected value");
  await expect(summary).toHaveClass(/ok/);
  const m = /(\d+) of (\d+) checks/.exec(await summary.innerText())!;
  expect(m[1]).toBe(m[2]);
  expect(Number(m[2])).toBeGreaterThanOrEqual(28);
  await expect(page.getByTestId("live-table").locator("tbody tr").filter({ hasText: "DIFFERS" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Open the CI workflow" })).toHaveAttribute("href", "https://github.com/mrrishit909/projects-site/actions/workflows/serviceflow-ci.yml");
  await expect(page.getByRole("link", { name: "Source on GitHub" }).first()).toHaveAttribute("href", "https://github.com/mrrishit909/projects-site/tree/business-data-lab/apps/serviceflow");
  await expect(page.getByTestId("evidence-manifest")).toContainText(manifest.dataset_hash);
  expect(errors).toEqual([]);
});

test("case study: what is built and not built, the 501 commands, the recomputed tail and the injected defects", async ({ page }) => {
  const errors = watch(page);
  await page.goto("case-study/");
  await ready(page);
  await expect(page.getByTestId("not-built-list")).toContainText("C07 build-shift-scenario");
  await expect(page.getByTestId("not-built-list")).toContainText("C10 export-recommendation");
  await expect(page.getByTestId("not-built-list")).toContainText("501 NOT_IMPLEMENTED");
  await expect(page.getByTestId("built-list").locator("li")).toHaveCount(6);
  await expect(page.getByTestId("data-line")).toContainText("3826 tickets");
  await expect(page.getByTestId("tech-p1")).toContainText("technical queue, P1");
  await expect(page.getByTestId("injection-table").locator("tbody tr")).toHaveCount(9);
  await expect(page.getByTestId("known-staffed")).toContainText("add up to more than");
  for (const r of ["queues", "compare", "surveys"]) {
    await page.goto(`${r}/`);
    await ready(page);
    await expect(page.getByTestId("stub")).toContainText("Not built yet");
    await expect(page.getByTestId("stub").locator("table")).toHaveCount(0);
  }
  expect(errors).toEqual([]);
});
