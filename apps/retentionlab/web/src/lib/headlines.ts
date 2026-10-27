// The one verified figure each route leads with on the start page. Every value is computed from the loaded dataset by the domain mirror.
import type { Dataset } from "../data/dataset";
import { p6, ratio } from "../domain/num";
import { minus, n0 } from "./format";
import type { Row } from "../domain/models";
import { cohortRows, groupStats } from "./cohort";
import { blockOf, driftByRegion, seriesOf } from "./derive";
import { designedClaims, injectionChecks } from "./claims";

export interface Headline { value: string; label: string; note?: string }
export function headlines(ds: Dataset): Record<string, Headline> {
  const out: Record<string, Headline> = {};
  const rows = ds.cutoffRows();
  const sum = (k: "eligible" | "mature" | "censored" | "churned"): number => rows.reduce((s, r) => s + r[k], 0);
  const pop = ds.populations[0]!;
  const primary = blockOf(seriesOf(pop, ds.primarySeries));
  if (ds.id === "snapshot") {
    out["overview"] = { value: p6(ratio(sum("churned"), sum("mature")))!, label: "mature churn rate", note: `${p6(ratio(sum("censored"), sum("eligible")))} of eligible rows are censored` };
    const gaps = groupStats(cohortRows(ds), "segment").find((g) => g.group === "starter");
    out["cohorts"] = { value: `${minus(gaps?.gap ?? "n/a")} pp`, label: "starter segment: mean predicted minus observed churn", note: "an unobserved repricing no feature sees" };
    out["features"] = { value: String(rows.reduce((s, r) => s + r.late_total, 0)), label: "events that occurred before a cutoff and arrived after it", note: "excluded and counted, 21 cutoffs" };
    const rule = blockOf(seriesOf(pop, "business_rule"));
    out["models"] = { value: primary.average_precision!, label: "average precision, logistic (test)", note: `rule ${rule.average_precision}; margin reached by construction` };
    out["calibration"] = { value: primary.brier_score!, label: "Brier score, test", note: `${primary.bins.filter((b) => b.count === 0).length} of 10 bins have no rows` };
    const sc = ds.setAt("2026-09-01T00:00:00Z", "logistic_regression", "sc-001")["economics"];
    const fwSc = (ds.aggregates?.["economics_full_world"] as Row | undefined)?.["scenarios"]?.["sc-001"] as Row | undefined;
    out["capacity"] = { value: sc ? sc.expected_value : "n/a", label: "expected value at K = 5, hypothetical (USD), on the scored accounts of the published cohort",
      note: `contact budget ${sc?.contact_budget}; the whole world (${fwSc ? n0(fwSc["scored_accounts"]) : "?"} scored accounts): ${fwSc?.["expected_value"] ?? "n/a"}` };
    const drift = driftByRegion(ds.testRows!, 4)[3]!;
    out["monitoring"] = { value: drift.apac.psi ?? "n/a", label: "apac usage drift (PSI, 2026-05-01)", note: `the whole population: ${drift.all_accounts.psi}` };
    const q = ds.setAt("2026-09-01T00:00:00Z", "logistic_regression", "sc-001")["outreach_queue"];
    out["queue"] = { value: String(q?.account_ids.length ?? 0), label: "draft actions at K = 5", note: "none sent" };
    out["account"] = { value: String(q?.account_ids[0] ?? "n/a"), label: "highest-risk account at the latest cutoff", note: "risk factors, not causes" };
    const dr = designedClaims(ds);
    out["evidence"] = { value: `${dr.filter((c) => c.ok).length} of ${dr.length}`, label: "designed-relationship figures equal the manifest", note: `${injectionChecks(ds).length} injected-defect checks` };
  } else {
    const jan = ds.setAt("2026-01-01T00:00:00Z", undefined, "sc-001");
    out["overview"] = { value: jan["churn_rate"].value, label: "churn rate, mature set 2026-01-01", note: `February: ${ds.setAt("2026-02-01T00:00:00Z")["population"].censored} rows censored` };
    out["cohorts"] = { value: String(cohortRows(ds).length), label: "mature scored rows grouped by plan and region", note: "the golden set" };
    out["features"] = { value: String(jan["late_events"].total), label: "events that arrived after the cutoff", note: "counted, not used" };
    out["models"] = { value: jan["average_precision"].value, label: "average precision", note: `Brier ${jan["brier_score"].value}` };
    out["calibration"] = { value: jan["brier_score"].value, label: "Brier score", note: "the golden set, empty bins stay empty" };
    out["capacity"] = { value: jan["economics"].expected_value, label: "expected value at K = 2, hypothetical (USD)", note: `contact budget ${jan["economics"].contact_budget}` };
    out["monitoring"] = { value: jan["population_drift"]?.psi ?? "n/a", label: "usage drift PSI against 2025-03-01", note: "a diagnostic" };
    out["queue"] = { value: String(jan["outreach_queue"].account_ids.length), label: "draft actions", note: "none sent" };
    out["account"] = { value: String(jan["outreach_queue"].account_ids[0]), label: "highest-risk account", note: "" };
    out["evidence"] = { value: "expected.json", label: "the fixture's oracle, compared leaf by leaf in this browser", note: "see the evidence page" };
  }
  out["case-study"] = { value: "model card", label: "evaluation, limits and what was not shown", note: "" };
  return out;
}
