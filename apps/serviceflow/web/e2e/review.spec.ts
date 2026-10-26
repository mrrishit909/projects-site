// Site corrections from the independent review A-031 (docs/contracts.md D-09): wording, the chosen-realisation label and the
// replication means with the paired difference.
import { expect, test } from "@playwright/test";
import { expectNoOverflow, ready, watch } from "./support";

test("overview: wait to first service, the original-arrival basis, the final-queue note and the chosen realisation", async ({ page }) => {
  const errors = watch(page);
  await page.goto("overview/");
  await ready(page);
  await expect(page.locator('[data-figure="wait_mean"]')).toContainText("Wait to first service, mean");
  await expect(page.locator('[data-figure="wait_p90"]')).toContainText("Wait to first service, P90");
  await expect(page.locator('[data-metric="mean_wait_minutes"]')).toContainText("Mean wait to first service (min)");
  await expect(page.getByTestId("resolution-basis")).toContainText("original arrival");
  await expect(page.getByTestId("resolution-basis")).toContainText("dormant gap");
  await expect(page.getByTestId("queue-basis")).toHaveCount(0);
  await expect(page.locator('[data-fact="reopened"]')).toContainText("completed in the window");
  await expect(page.getByTestId("realisation-note")).toContainText("Chosen realisation; noise sd ≈ 4 pts");
  await expect(page.getByTestId("realisation-note")).toContainText("attempt 7");
  await expect(page.getByTestId("realisation-note")).toContainText("+12.9 %");
  await page.goto("overview/?group=queue");
  await ready(page);
  await expect(page.getByTestId("queue-basis")).toContainText("final queue");
  await page.goto("overview/?dataset=golden");
  await ready(page);
  await expect(page.getByTestId("realisation-note")).toHaveText("");          // the golden fixture has no realisation record
  expect(errors).toEqual([]);
});

test("sla: resolution compliance says it is measured from the original arrival; the realisation is labelled", async ({ page }) => {
  const errors = watch(page);
  await page.goto("sla/");
  await ready(page);
  await expect(page.locator('[data-figure="sla_rs"]')).toContainText("measured from the original arrival");
  await expect(page.getByTestId("realisation-note")).toContainText("Chosen realisation; noise sd ≈ 4 pts");
  await expect(page.getByTestId("domain-warnings")).toHaveCount(0);           // the snapshot's calendar is cal-001 (24x7)
  expect(errors).toEqual([]);
});

test("case study: the chosen realisation and the review corrections are stated", async ({ page }) => {
  const errors = watch(page);
  await page.goto("case-study/");
  await ready(page);
  await expect(page.getByTestId("realisation")).toContainText("Chosen realisation; noise sd ≈ 4 pts");
  await expect(page.getByTestId("realisation")).toContainText("attempts 0 to 6 gave +12.9 %, +14.6 %, +22.8 %, +16.9 %, +12.7 %, +22.0 %, +30.5 %");
  await expect(page.locator("main")).toContainText("SERVICE_OUTSIDE_SHIFT");
  expect(errors).toEqual([]);
});

test("tickets: the wait column is wait to first service", async ({ page }) => {
  await page.goto("tickets/");
  await ready(page);
  await expect(page.locator("main")).toContainText("Wait to first service (min)");
});

test("simulation: 50 replications with 95 % intervals, the paired difference and the caveats", async ({ page }) => {
  const errors = watch(page);
  await page.goto("simulation/");
  await ready(page);
  const table = page.getByTestId("replications-table");
  await expect(table.locator("tbody tr")).toHaveCount(3, { timeout: 60_000 });
  await expect(page.locator('[data-run="sim-001"]')).toContainText("18.8435");
  await expect(page.locator('[data-run="sim-001"]')).toContainText("8.2004");
  await expect(page.locator('[data-run="sim-002"]')).toContainText("7.9502");
  await expect(page.locator('[data-run="sim-003"]')).toContainText("30.6253");
  for (const id of ["sim-001", "sim-002", "sim-003"]) await expect(page.getByTestId(`rep-match-${id}`)).toHaveText("equal");
  const paired = page.getByTestId("paired-facts");
  await expect(paired.locator('[data-fact="paired-diff"]')).toContainText("-10.8932");
  await expect(paired.locator('[data-fact="paired-diff"]')).toContainText("3.4329");
  await expect(paired.locator('[data-fact="paired-diff"]')).toContainText("50 paired replications");
  await expect(paired.locator('[data-fact="paired-same"]')).toContainText("yes");
  await expect(paired.locator('[data-fact="paired-match"]')).toHaveText("equal");
  const caveats = page.getByTestId("replication-caveats");
  await expect(caveats).toContainText("sim-003 does not share the demand path, by design");
  await expect(caveats).toContainText("Dedicated servers are a simplification");
  await expect(page.getByTestId("published-runs")).toContainText("excluded from the wait statistics and counted separately");
  await expect(page.getByTestId("published-runs")).not.toContainText("reported as censored, not dropped");
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});
