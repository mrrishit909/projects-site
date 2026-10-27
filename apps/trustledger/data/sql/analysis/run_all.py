"""Run every analysis investigation and reconcile it with the independent sources (P07-ART-04).

Usage (from apps/trustledger):
  ../../.venv/bin/python data/sql/analysis/run_all.py [--json artifacts/analysis-results.json] [--bi-out artifacts/bi] [--keep]

With no environment variables it creates two scratch databases (artifacts07_run_snapshot, artifacts07_run_golden) on the local PostgreSQL named by ARTIFACTS_ADMIN_URL
(default: the repository's local development login, 127.0.0.1:5432), loads the published snapshot ``web/public/data`` and the golden fixture through ``data/migrate.py`` and
``data/seed.py`` (prepare_snapshot.py), runs everything and drops them again (``--keep`` leaves them). To use databases you prepared yourself, set ARTIFACTS_DATABASE_URL and
ARTIFACTS_GOLDEN_DATABASE_URL (names must start with artifacts07_; the shared trustledger database is never touched).

What runs, in order (exit code 0 only if every query ran and every reconciliation row is equal):
  00_measure_rules.sql (the as-of, the active rules, their row-level measurement, the timeliness states and the issue classes, into temporary tables), 01..08 and 10 on the snapshot
  (files hold several blocks marked ``-- @@ name``), 09 on the golden database, bi_dimensions.sql and bi_fact_*.sql on the snapshot (written as CSV with --bi-out).
Reconciliation (the rows printed at the end, ``reconciliation`` in the JSON):
  A  golden fixture: data/sql/reference_metrics.sql, the Python domain and tests/fixtures/golden/expected.json agree on every metric key and the whole expected shape; the SQL of
     investigation 09 equals the hand answer of expected.json and CALCULATION.md (95/100, 90/95, 90/100, 0.963932 and 0.958116 with the override, 35/37, 3/4, 4/5, 3/4, 5/6, 2/3);
  B  snapshot headline figures: the domain, the reference SQL and the analysis temporary tables at the as-of and at two earlier instants and at the timeliness probes, rule by rule;
  C  every result set cell by cell against python_side.py (plain Python from the raw JSON rows, no SQL and no domain code);
  D  the designed relationships (DR-01..DR-06), the injection manifest and the manifest statistics against what the SQL finds;
  E  the BI measures recomputed from the CSV facts against the reference, the domain and the analysis.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sys
from datetime import timedelta
from decimal import Decimal
from fractions import Fraction as F
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / "domain"), str(ROOT), str(HERE)]

import python_side as ps  # noqa: E402
from prepare_snapshot import DEFAULT_ADMIN_URL, create_database, drop_database, prepare, snapshot_inputs, with_db  # noqa: E402
from trustledger import run_pipeline  # noqa: E402
from trustledger.contract import METRIC_KEYS  # noqa: E402
from trustledger.timeutil import parse_ts  # noqa: E402

REFERENCE = ROOT / "data" / "sql" / "reference_metrics.sql"
GOLDEN_DIR = ROOT / "tests" / "fixtures" / "golden"
SNAP_DIR = ROOT / "web" / "public" / "data"
CODE_REVISION = "0b5d686"
DATASET_HASH = "a9f7a3321b102752dd7aa95b76df14c1d9372103e685e10222959fd6438f27ff"
RUN_SNAPSHOT_DB, RUN_GOLDEN_DB = "artifacts07_run_snapshot", "artifacts07_run_golden"
AS_OF = "2026-10-05T00:00:00Z"
EARLIER = ("2026-09-14T00:00:00Z", "2026-08-17T00:00:00Z")           # the two earlier instants tests/test_generator.py also reads
SNAPSHOT_FILES = ["01", "02", "03", "04", "05", "06", "07", "08", "10"]
BI_FILES = ["bi_dimensions", "bi_fact_rule_measure", "bi_fact_dataset_score", "bi_fact_issue", "bi_fact_lineage_edge", "bi_fact_candidate", "bi_fact_timeliness"]


def fmt(v) -> str:
    return ps.norm(v)


def canon(v) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), default=str)


def digest(v) -> str:
    return hashlib.sha256(canon(v).encode()).hexdigest()[:16]


def blocks(path: Path) -> list[tuple[str | None, str]]:
    text = path.read_text()
    parts = re.split(r"(?m)^-- @@ (\w+)\n", text)
    return [(None, text)] if len(parts) == 1 else [(parts[i], parts[i + 1]) for i in range(1, len(parts), 2)]


def run_file(conn, path: Path) -> dict[str, list[dict]]:
    out = {}
    for name, sql in blocks(path):
        out[path.stem if name is None else f"{path.stem}__{name}"] = [dict(r) for r in conn.execute(sql).fetchall()]
    return out


def run_script(conn, path: Path) -> None:
    """Execute every block of a file that creates temporary tables (00_measure_rules.sql); nothing is fetched."""
    for _, sql in blocks(path):
        conn.execute(sql)


class Recon:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.ok = True

    def add(self, check: str, a, b, c=None, d=None) -> None:
        vals = [a, b] + [v for v in (c, d) if v is not None]
        eq = all(fmt(v) == fmt(a) for v in vals)
        self.ok &= eq
        self.rows.append({"check": check, "analysis_sql": fmt(a), "second_source": fmt(b), "third_source": "" if c is None else fmt(c),
                          "fourth_source": "" if d is None else fmt(d), "equal": eq})


def reference(conn, as_of: str, wv: str | None = None) -> dict:
    return dict(conn.execute(REFERENCE.read_text(), {"as_of": parse_ts(as_of), "wv": wv}).fetchone())


def export_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        cols = list(rows[0])
        w.writerow(cols)
        for r in rows:
            w.writerow([fmt(r[c]) for c in cols])


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


# ---- BI measures from the exported facts (no database, no domain): exact arithmetic over the CSV strings ----------------------------------------------------------
def bi_measures(csvs: dict[str, list[dict]]) -> list[dict]:
    """The measures of docs/bi-package.md evaluated over the CSV facts. Every row has a status; nothing is dropped: a zero denominator or an unmeasured dataset is stated."""
    rows: list[dict] = []

    def add(measure: str, slice_: str, num, den=None, places: int | None = 6, value=None, status: str = "value", note: str = "") -> None:
        if value is None and den is not None:
            if den == 0:
                status, v = "null: zero denominator", ""
            else:
                v = fmt(ps.rnd(F(num) / F(den), places))
        elif value is not None:
            v = fmt(value)
        else:
            v = fmt(num)
        rows.append({"measure": measure, "slice": slice_, "value": v, "numerator": "" if num is None else fmt(num), "denominator": "" if den is None else fmt(den), "status": status, "note": note})

    ds, owners, rules = csvs["dim_dataset"], {o["owner_id"]: o for o in csvs["dim_owner"]}, csvs["fact_rule_measure"]
    cov = sum(int(d["owner_covered"]) for d in ds)
    add("ownership_coverage", "portfolio", cov, len(ds), note="datasets whose accountable owner is active / datasets")
    add("datasets_without_an_accountable_owner", "portfolio", len(ds) - cov)
    mets = csvs["dim_metric"]
    add("definition_coverage", "portfolio", sum(int(m["checklist_complete"]) for m in mets), len(mets), note="published metrics with a complete checklist cl-1 / published metrics")
    edges = csvs["fact_lineage_edge"]
    dec = {(e["source_dataset_id"], e["target_dataset_id"]) for e in edges if e["evidence_type"] == "declared"}
    obs = {(e["source_dataset_id"], e["target_dataset_id"]) for e in edges if e["evidence_type"] == "observed"}
    inf = {(e["source_dataset_id"], e["target_dataset_id"]) for e in edges if e["evidence_type"] == "inferred"}
    add("lineage_coverage", "portfolio", len(dec & obs), len(dec), note="distinct observed pairs that match a declared pair / declared pairs; inferred pairs never count")
    add("undeclared_observed_pairs", "portfolio", len(obs - dec))
    add("declared_not_observed_pairs", "portfolio", len(dec - obs))
    add("inferred_pairs", "portfolio", len(inf), note="never counted as observed")
    iss = csvs["fact_issue"]
    for k in ("resolved", "claimed", "open"):
        add("issues", k, sum(1 for i in iss if i["class"] == k), len(iss), note="share of all issues")
    add("issues", "all", len(iss))
    res = [i for i in iss if i["class"] == "resolved"]

    def mean(xs: list[dict]):
        return (sum((F(x["hours"]) for x in xs), F(0)) / len(xs)) if xs else None
    own_team = {o: v["team"] for o, v in owners.items()}
    for label, sub in (("all resolved", res), ("Data Platform", [i for i in res if own_team[i["owner_id"]] == "Data Platform"]),
                       ("all other teams", [i for i in res if own_team[i["owner_id"]] != "Data Platform"])):
        add("mean_resolution_hours", label, len(sub), None, value=ps.rnd(mean(sub), 4) if sub else None, status="value" if sub else "null: no resolved issue",
            note="mean of (verifying rerun - first detected_at), 4 places, resolved issues only; claimed and open issues are not in it")
    for team in sorted({own_team[i["owner_id"]] for i in res}):
        sub = [i for i in res if own_team[i["owner_id"]] == team]
        add("mean_resolution_hours", f"team: {team}", len(sub), None, value=ps.rnd(mean(sub), 4))
    unres = [i for i in iss if i["class"] != "resolved"]
    for s in ("critical", "high", "medium", "low"):
        add("unresolved_issues", f"severity: {s}", sum(1 for i in unres if i["severity"] == s))
    add("unresolved_issues", "all", len(unres), note="open + claimed")
    add("unresolved_issues_with_an_inactive_owner", "all", sum(1 for i in unres if i["owner_accountable"] == "0"))
    tl = csvs["fact_timeliness"]
    pend, on = sum(1 for t in tl if t["state"] == "pending"), sum(1 for t in tl if t["state"] == "on_time")
    add("timeliness", "portfolio", on, len(tl) - pend, note="on time / (monitored - pending); pending is outside the denominator")
    add("timeliness_pending", "portfolio", pend)
    add("timeliness_late", "portfolio", sum(1 for t in tl if t["state"] == "late"))
    cands = csvs["fact_candidate"]
    ap = [c for c in cands if c["decision"] == "approve"]
    rv = [c for c in cands if c["decision"] in ("approve", "reject")]
    add("match_precision", "portfolio", sum(1 for c in ap if c["truth_same_entity"] == "1"), len(ap), note="approved decisions the truth confirms / approved decisions")
    add("reviewed_correct_share", "portfolio", sum(1 for c in rv if c["truth_same_entity"] == "1"), len(rv), note="reviewed candidates that are the same entity / reviewed candidates (the contract's share)")
    add("decision_agreement_share", "portfolio", sum(1 for c in rv if (c["decision"] == "approve") == (c["truth_same_entity"] == "1")), len(rv), note="reviews that agree with the truth / reviews")
    add("approvals_reversed", "portfolio", sum(1 for c in ap if c["reversed"] == "1"))
    # weighted score of every dataset under every weight version, recomputed from the exact rule fractions and the weights; never 0 for a dataset that measures nothing
    wts = {w["weight_version"]: {k[2:]: F(v) for k, v in w.items() if k.startswith("w_")} for w in csvs["dim_weight_version"]}
    by: dict[tuple[str, str], list[F]] = {}
    for r in rules:
        if r["score_status"] == "measured":
            by.setdefault((r["dataset_id"], r["dimension"]), []).append(F(int(r["score_numerator"]), int(r["score_denominator"])))
    scores: dict[tuple[str, str], F | None] = {}
    for d in ds:
        for wv, w in wts.items():
            dims = {dim: sum(x, F(0)) / len(x) for (dd, dim), x in by.items() if dd == d["dataset_id"]}
            if dims:
                scores[(d["dataset_id"], wv)] = sum((w[k] * v for k, v in dims.items()), F(0)) / sum((w[k] for k in dims), F(0))
                add("weighted_score", f"{d['dataset_id']}|{wv}", None, None, value=ps.rnd(scores[(d["dataset_id"], wv)], 6))
            else:
                scores[(d["dataset_id"], wv)] = None
                add("weighted_score", f"{d['dataset_id']}|{wv}", None, None, value="", status="not_measured: no rule measures a value", note="withheld, never 0")
    for wv in wts:
        got = [v for (d, w), v in scores.items() if w == wv and v is not None]
        add("mean_weighted_score", wv, len(got), None, value=ps.rnd(sum(got, F(0)) / len(got), 6), note=f"mean over the {len(got)} datasets that measure something")
    both = [(scores[(d["dataset_id"], "w1")], scores[(d["dataset_id"], "w2")]) for d in ds if scores[(d["dataset_id"], "w1")] is not None]
    add("datasets_with_a_different_score", "w1 vs w2", sum(1 for a, b in both if a != b), len(both), places=6)
    add("datasets_moved_at_least_0_005", "w1 vs w2", sum(1 for a, b in both if abs(b - a) >= F(5, 1000)), len(both), places=6)
    add("largest_move", "w1 vs w2", None, None, value=ps.rnd(max((b - a for a, b in both), key=lambda x: abs(x)), 6))
    crit = {}
    for r in rules:
        if r["severity"] == "critical":
            crit[r["dataset_id"]] = crit.get(r["dataset_id"], 0) + int(r["failing"])
    add("critical_failures", "portfolio", sum(crit.values()), note="failing rows of active critical rules, counted apart from any score")
    ov = {s["dataset_id"] for s in csvs["fact_dataset_score"] if s["critical_override"] == "1"}
    add("datasets_with_the_critical_override", "portfolio", len(ov))
    add("open_critical_issues", "portfolio", sum(1 for i in unres if i["severity"] == "critical"))
    return rows


def main(argv: list[str]) -> int:
    json_out = Path(argv[argv.index("--json") + 1]) if "--json" in argv else None
    bi_out = Path(argv[argv.index("--bi-out") + 1]) if "--bi-out" in argv else None
    keep = "--keep" in argv
    admin = os.environ.get("ARTIFACTS_ADMIN_URL", DEFAULT_ADMIN_URL)
    snap_url, gold_url = os.environ.get("ARTIFACTS_DATABASE_URL"), os.environ.get("ARTIFACTS_GOLDEN_DATABASE_URL")
    created: list[str] = []
    try:
        if not snap_url:
            create_database(admin, RUN_SNAPSHOT_DB)
            created.append(RUN_SNAPSHOT_DB)
            snap_url = with_db(admin, RUN_SNAPSHOT_DB)
        if not gold_url:
            create_database(admin, RUN_GOLDEN_DB)
            created.append(RUN_GOLDEN_DB)
            gold_url = with_db(admin, RUN_GOLDEN_DB)
        return _run(snap_url, gold_url, json_out, bi_out)
    finally:
        if not keep:
            for name in created:
                drop_database(admin, name)


def _run(snap_url: str, gold_url: str, json_out: Path | None, bi_out: Path | None) -> int:
    rec = Recon()
    R: dict[str, list[dict]] = {}
    prep_s, prep_g = prepare(snap_url, False), prepare(gold_url, True)
    print(f"snapshot prepared: {prep_s['inserted']} (dataset {prep_s['dataset_version']}, hash {prep_s['dataset_hash'][:12]}...)")
    print(f"golden prepared:   {prep_g['inserted']} (hash {prep_g['dataset_hash'][:12]}...)")
    inputs, manifest = snapshot_inputs()
    truth = manifest["synthetic_truth"]["true_entity"]
    bi: dict[str, list[dict]] = {}
    ref: dict[tuple[str, str | None], dict] = {}
    scalar: dict[str, object] = {}
    with psycopg.connect(snap_url, row_factory=dict_row, autocommit=True, options="-c timezone=UTC") as c:
        run_script(c, HERE / "00_measure_rules.sql")
        print("the as-of, the rule measurement, the timeliness states and the issue classes built (tl_p, tl_rule_measure, tl_tstate, tl_issue)")
        for prefix in SNAPSHOT_FILES:
            f = next(HERE.glob(f"{prefix}_*.sql"))
            R.update(run_file(c, f))
            print(f"ran {f.name}")
        for name in BI_FILES:
            for k, rows in run_file(c, HERE / f"{name}.sql").items():
                bi[k.split("__")[-1] if "__" in k else k.removeprefix("bi_")] = rows
        print("ran the BI dimension and fact queries")
        for as_of in (AS_OF, *EARLIER):
            ref[(as_of, None)] = reference(c, as_of)
        for wv in ("w1", "w2"):
            ref[(AS_OF, wv)] = reference(c, AS_OF, wv)
        for seq, at in enumerate(("2026-10-05T10:30:00Z", "2026-10-05T13:00:00Z", "2026-10-06T01:00:00Z"), start=1):
            ref[(at, None)] = reference(c, at)
        print("reference_metrics.sql at the as-of, two earlier instants, both weight versions and the timeliness probes")
        scalar["max_row_version"] = c.execute("SELECT max(row_version) AS n FROM dataset_rows").fetchone()["n"]
        scalar["refreshes"] = c.execute("SELECT count(*) AS n FROM dataset_refreshes").fetchone()["n"]
        scalar["counts"] = {t: c.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"] for t in
                            ("owners", "datasets", "fields", "quality_rules", "rule_runs", "issues", "lineage_edges", "metric_versions", "definition_changes", "customer_records", "match_candidates",
                             "merge_decisions", "dataset_rows", "quality_rule_versions", "verification_truth")}
        scalar["counts"]["weight_versions"] = c.execute("SELECT count(*) AS n FROM rule_weight_versions").fetchone()["n"]
        scalar["tl_rule_measure"] = [dict(r) for r in c.execute("SELECT rule_id, dimension, eligible, populated, failing, score FROM tl_rule_measure ORDER BY rule_id COLLATE \"C\"").fetchall()]
        scalar["tl_issue"] = [dict(r) for r in c.execute("SELECT issue_id, class, hours, cycles FROM tl_issue ORDER BY issue_id COLLATE \"C\"").fetchall()]
        scalar["tstate"] = [dict(r) for r in c.execute("SELECT seq, dataset_id, state FROM tl_tstate ORDER BY seq, dataset_id COLLATE \"C\"").fetchall()]
    with psycopg.connect(gold_url, row_factory=dict_row, autocommit=True, options="-c timezone=UTC") as c:
        run_script(c, HERE / "00_measure_rules.sql")
        G = run_file(c, HERE / "09_golden_known_answer.sql")
        g_inputs = json.loads((GOLDEN_DIR / "inputs.json").read_text())
        ref_g = {wv: reference(c, g_inputs["as_of"], wv) for wv in (None, "w1", "w2")}
    R.update(G)

    # ---- A: golden fixture ---------------------------------------------------------------------------------------------------------
    exp = json.loads((GOLDEN_DIR / "expected.json").read_text())
    dom_g = run_pipeline(g_inputs)
    for k in METRIC_KEYS:
        rec.add(f"A golden metric {k}: reference SQL = Python domain = expected.json (digest)", digest(ref_g[None][k]), digest(exp["metrics"][k]), digest(dom_g.metrics[k]))
    rec.add("A golden empty_population (reference SQL vs expected.json vs domain)", ref_g[None]["empty_population"], exp["empty_population"], dom_g.empty_population)
    rec.add("A golden whole shape of expected.json (domain result.golden() vs the file, digest)", digest(dom_g.golden()), digest(exp))
    rec.add("A golden timeliness probes (domain vs expected.json, digest)", digest(dom_g.golden()["timeliness_probes"]), digest(exp["timeliness_probes"]))
    for wv in ("w1", "w2"):
        dw = run_pipeline(g_inputs, weight_version=wv)
        rec.add(f"A golden weighted_score under {wv} (reference SQL vs domain, digest)", digest(ref_g[wv]["weighted_score"]), digest(dw.metrics["weighted_score"]))
    cv = G["09_golden_known_answer__completeness_validity"][0]
    ec, ev = exp["metrics"]["completeness"]["r-cust-complete-email"], exp["metrics"]["validity"]["r-cust-valid-email"]
    rec.add("A golden completeness: eligible | missing | populated | value (09 vs expected.json vs the spec's hand answer 100 | 5 | 95 | 0.950000)",
            f"{cv['eligible']}|{cv['missing']}|{cv['populated']}|{fmt(cv['completeness'])}", f"{ec['eligible_count']}|{ec['missing_count']}|{ec['populated_count']}|{ec['value']}", "100|5|95|0.950000")
    rec.add("A golden validity: populated | passing | populated-only | all-eligible (09 vs expected.json vs the hand answer 95 | 90 | 0.947368 | 0.900000)",
            f"{cv['validity_populated']}|{cv['passing']}|{fmt(cv['validity_populated_only'])}|{fmt(cv['validity_all_eligible'])}",
            f"{ev['populated_count']}|{ev['passing_count']}|{ev['populated_only']['value']}|{ev['all_eligible']['value']}", "95|90|0.947368|0.900000")
    ur = G["09_golden_known_answer__uniqueness_relationship"][0]
    eu, er = exp["metrics"]["uniqueness"]["r-cust-key-unique"], exp["metrics"]["relationship_integrity"]["r-ord-cust-fk"]
    rec.add("A golden uniqueness: eligible | distinct keys | groups | duplicate rows | group share | row share (09 vs expected.json)",
            f"{ur['uniqueness_eligible']}|{ur['distinct_keys']}|{ur['duplicate_groups']}|{ur['duplicate_rows']}|{fmt(ur['group_share'])}|{fmt(ur['row_share'])}",
            f"{eu['eligible_count']}|{eu['distinct_keys']}|{eu['duplicate_groups']}|{eu['duplicate_rows']}|{eu['group_share']['value']}|{eu['row_share']['value']}")
    rec.add("A golden relationship: total | null or empty | eligible | matched | value (09 vs expected.json; ds-orders 35 of 37, D-10 R7-11)",
            f"{ur['fk_total']}|{ur['fk_null_or_empty']}|{ur['fk_eligible']}|{ur['fk_matched']}|{fmt(ur['relationship'])}",
            f"{er['total_fk_count']}|{er['null_fk_count']}|{er['eligible_count']}|{er['matched_count']}|{er['value']}")
    for r in G["09_golden_known_answer__weighted_scores"]:
        wv = r["weight_version"]
        dsc = run_pipeline(g_inputs, weight_version=wv).metrics["weighted_score"]["datasets"]["ds-customers"]
        hand = {"w1": "0.958116", "w2": "0.963932"}[wv]
        rec.add(f"A golden ds-customers under {wv}: score | weight sum | critical failures | open critical | override (09 vs domain vs hand answer {hand})",
                f"{fmt(r['weighted_score'])}|{fmt(r['weight_sum'])}|{r['critical_failures']}|{r['critical_open_issues']}|{fmt(r['critical_override'])}",
                f"{dsc['value']}|{dsc['weight_sum']}|{dsc['critical_failures']}|{dsc['critical_open_issues']}|{fmt(dsc['critical_override'])}", f"{hand}|0.850000|2|1|true" if wv == "w2" else f"{hand}|0.950000|2|1|true")
    pf = G["09_golden_known_answer__portfolio"][0]
    rec.add("A golden timeliness: monitored | on time (09 vs expected.json)", f"{pf['timeliness_monitored']}|{pf['timeliness_on_time']}",
            f"{exp['metrics']['timeliness']['monitored_datasets']}|{exp['metrics']['timeliness']['on_time_count']}")
    rec.add("A golden ownership: datasets | covered (09 vs expected.json)", f"{pf['datasets']}|{pf['ownership_covered']}", f"{exp['metrics']['ownership_coverage']['datasets']}|{exp['metrics']['ownership_coverage']['covered']}")
    rec.add("A golden definitions: published | complete (09 vs expected.json)", f"{pf['published_metrics']}|{pf['definitions_complete']}",
            f"{exp['metrics']['definition_coverage']['published_metrics']}|{exp['metrics']['definition_coverage']['complete_metrics']}")
    rec.add("A golden lineage: declared | observed matching declared (09 vs expected.json)", f"{pf['lineage_declared']}|{pf['lineage_observed_matching']}",
            f"{exp['metrics']['lineage_coverage']['declared_edges']}|{exp['metrics']['lineage_coverage']['observed_matching_declared']}")
    rr = exp["metrics"]["resolution_time"]
    rec.add("A golden issues: resolved | claimed | open | mean hours (09 vs expected.json)", f"{pf['issues_resolved']}|{pf['issues_claimed']}|{pf['issues_open']}|{fmt(pf['resolution_mean_hours'])}",
            f"{rr['resolved_count']}|{rr['claimed_count']}|{rr['open_count']}|{rr['mean_hours']}")
    mp = exp["metrics"]["match_precision"]
    rec.add("A golden match precision: approved | approved correct (09 vs expected.json)", f"{pf['approved']}|{pf['approved_correct']}", f"{mp['approved_decisions']}|{mp['approved_correct']}")

    # ---- B: snapshot headline figures ------------------------------------------------------------------------------------------------
    assert scalar["max_row_version"] == 1 and scalar["refreshes"] == 0, "the loaded snapshot must carry no row corrections or recorded refreshes (00_measure_rules.sql reads the rows as loaded)"
    rec.add("B loaded row counts equal the manifest row_counts (every entity)", digest(sorted((k, v) for k, v in scalar["counts"].items() if k in manifest["row_counts"])),
            digest(sorted((k, v) for k, v in manifest["row_counts"].items())))
    rec.add("B verification_truth rows equal the manifest's synthetic truth entries (records)", scalar["counts"]["verification_truth"], len(truth))
    dom = {}
    for as_of in (AS_OF, *EARLIER):
        dom[as_of] = run_pipeline(inputs, as_of=as_of, truth=truth)
        for k in METRIC_KEYS:
            rec.add(f"B reference SQL equals the Python domain on {k} at {as_of} (digest)", digest(ref[(as_of, None)][k]), digest(dom[as_of].metrics[k]))
    for wv in ("w1", "w2"):
        dw = run_pipeline(inputs, as_of=AS_OF, weight_version=wv, truth=truth)
        rec.add(f"B reference SQL equals the Python domain on weighted_score and critical_failures under {wv} at the as-of (digest)",
                digest([ref[(AS_OF, wv)]["weighted_score"], ref[(AS_OF, wv)]["critical_failures"]]), digest([dw.metrics["weighted_score"], dw.metrics["critical_failures"]]))
    for at in ("2026-10-05T10:30:00Z", "2026-10-05T13:00:00Z", "2026-10-06T01:00:00Z"):
        dp = run_pipeline(inputs, as_of=at, truth=truth)
        rec.add(f"B timeliness at the probe {at}: reference SQL = Python domain (digest)", digest(ref[(at, None)]["timeliness"]), digest(dp.metrics["timeliness"]))
        seq = {"2026-10-05T10:30:00Z": 1, "2026-10-05T13:00:00Z": 2, "2026-10-06T01:00:00Z": 3}[at]
        row = R["08_timeliness_states__by_read_instant"][seq]
        t = ref[(at, None)]["timeliness"]
        rec.add(f"B timeliness at the probe {at}: on time | pending | late | evaluated | value (08 vs reference SQL vs domain)",
                f"{row['on_time']}|{row['pending']}|{row['late']}|{row['evaluated']}|{fmt(row['timeliness'])}",
                f"{t['on_time_count']}|{t['pending_count']}|{t['evaluated_datasets'] - t['on_time_count']}|{t['evaluated_datasets']}|{t['value']}",
                f"{dp.metrics['timeliness']['on_time_count']}|{dp.metrics['timeliness']['pending_count']}|{dp.metrics['timeliness']['evaluated_datasets'] - dp.metrics['timeliness']['on_time_count']}|"
                f"{dp.metrics['timeliness']['evaluated_datasets']}|{dp.metrics['timeliness']['value']}")
    r0, d0 = ref[(AS_OF, None)], dom[AS_OF]
    # per-rule measurement: the analysis temporary table against the reference's per-rule figures and the domain's
    meas = {m["rule_id"]: m for m in scalar["tl_rule_measure"]}
    for label, source in (("reference SQL", r0), ("Python domain", d0.metrics)):
        got = {}
        for rid, x in source["completeness"].items():
            got[rid] = (x["eligible_count"], x["missing_count"], x["value"])
        for rid, x in source["validity"].items():
            got[rid] = (x["eligible_count"], x["eligible_count"] - x["passing_count"], x["populated_only"]["value"])
        for rid, x in source["uniqueness"].items():
            got[rid] = (x["eligible_count"], x["null_key_count"] + x["duplicate_rows"], fmt(ps.rnd(F(x["eligible_count"] - x["null_key_count"] - x["duplicate_rows"], x["eligible_count"]), 6)))
        for rid, x in source["relationship_integrity"].items():
            got[rid] = (x["eligible_count"], x["unmatched_count"], x["value"])
        mine = {rid: (m["eligible"], int(m["failing"]), fmt(ps.rnd(F(m["score"]), 6)) if m["score"] is not None else "") for rid, m in meas.items() if m["dimension"] != "timeliness"}
        rec.add(f"B per-rule measurement of the {len(mine)} row-based rules: eligible | failing | score (analysis temp table vs {label}, digest)",
                digest(sorted((k, [x for x in v]) for k, v in mine.items())), digest(sorted((k, [x for x in (v[0], v[1], v[2] or "")]) for k, v in got.items() if k in mine)))
    tdoms = d0.metrics["timeliness"]["datasets"]
    rec.add("B timeliness state of each of the 15 monitored datasets at the as-of (analysis tl_tstate vs reference SQL vs domain, digest)",
            digest([(r["dataset_id"], r["state"]) for r in scalar["tstate"] if r["seq"] == 0]), digest(sorted((k, v["state"]) for k, v in r0["timeliness"]["datasets"].items())),
            digest(sorted((k, v["state"]) for k, v in tdoms.items())))
    mi = {r["issue_id"]: r for r in scalar["tl_issue"]}
    rec.add("B class and hours of every one of the 574 issues (analysis tl_issue vs reference SQL, digest)", digest(sorted((k, v["class"], str(round(v["hours"], 4))) for k, v in mi.items())),
            digest(sorted((k, v["class"], str(Decimal(v["resolution_hours"] or v["claimed_hours"] or v["age_hours"]))) for k, v in r0["resolution_time"]["issues"].items())))
    rec.add("B class of every issue (analysis vs Python domain, digest)", digest(sorted((k, v["class"]) for k, v in mi.items())), digest(sorted((k, v["class"]) for k, v in d0.metrics["resolution_time"]["issues"].items())))
    rec.add("B ds-customers weighted score under the version in force (w2): the analysis vs reference SQL vs domain", fmt(R["01_ds_customers_override_both_weights__weighted"][1]["weighted_score"]),
            r0["weighted_score"]["datasets"]["ds-customers"]["value"], d0.metrics["weighted_score"]["datasets"]["ds-customers"]["value"])
    rec.add("B ds-customers weighted score under w1: the analysis vs reference SQL (by_weight_version) vs domain under w1", fmt(R["01_ds_customers_override_both_weights__weighted"][0]["weighted_score"]),
            r0["weighted_score"]["by_weight_version"]["w1"]["ds-customers"], run_pipeline(inputs, weight_version="w1", truth=truth).metrics["weighted_score"]["datasets"]["ds-customers"]["value"])
    cr = R["01_ds_customers_override_both_weights__critical"][0]
    wsd = r0["weighted_score"]["datasets"]["ds-customers"]
    rec.add("B ds-customers critical failures | open critical issues | override (01 vs reference SQL vs domain)", f"{cr['critical_failures']}|{cr['critical_open_issues']}|{fmt(cr['critical_override'])}",
            f"{wsd['critical_failures']}|{wsd['critical_open_issues']}|{fmt(wsd['critical_override'])}", "|".join(fmt(d0.metrics["weighted_score"]["datasets"]["ds-customers"][k]) for k in ("critical_failures", "critical_open_issues", "critical_override")))
    dims = {r["dimension"]: fmt(r["score"]) for r in R["01_ds_customers_override_both_weights__dimensions"]}
    rec.add("B ds-customers dimension scores (01 vs reference SQL vs domain)", digest(dims), digest(wsd["dimension_scores"]), digest(d0.metrics["weighted_score"]["datasets"]["ds-customers"]["dimension_scores"]))
    shift = {r["dataset_id"]: (fmt(r["score_w1"]), fmt(r["score_w2"])) for r in R["03_weight_shift_dr03__shift_by_dataset"]}
    bw = r0["weighted_score"]["by_weight_version"]
    rec.add("B all 29 scored datasets under w1 and w2 (03 vs reference SQL by_weight_version, digest)", digest(sorted(shift.items())),
            digest(sorted((d, (bw["w1"][d], bw["w2"][d])) for d in bw["w1"] if bw["w1"][d] is not None)))
    o = R["02_ownership_coverage__summary"][0]
    oc = r0["ownership_coverage"]
    rec.add("B ownership coverage: datasets | covered | value | uncovered list (02 vs reference SQL vs domain)", f"{o['datasets']}|{o['covered']}|{fmt(o['coverage'])}|{','.join(r['dataset_id'] for r in R['02_ownership_coverage__uncovered'])}",
            f"{oc['datasets']}|{oc['covered']}|{oc['value']}|{','.join(oc['uncovered'])}", f"{d0.metrics['ownership_coverage']['datasets']}|{d0.metrics['ownership_coverage']['covered']}|{d0.metrics['ownership_coverage']['value']}|"
            f"{','.join(d0.metrics['ownership_coverage']['uncovered'])}")
    cl = {r["class"]: r["issues"] for r in R["04_issue_classes_and_resolution__classes"]}
    ro = R["04_issue_classes_and_resolution__resolution_overall"][0]
    rt = r0["resolution_time"]
    rec.add("B issues: resolved | claimed | open | reopened | cycles | mean hours (04 vs reference SQL vs domain)", f"{cl['resolved']}|{cl['claimed']}|{cl['open']}|{ro['reopened_issues']}|{ro['reopen_cycles']}|{fmt(ro['mean_hours'])}",
            f"{rt['resolved_count']}|{rt['claimed_count']}|{rt['open_count']}|{rt['reopened_count']}|{rt['reopen_cycles_total']}|{rt['mean_hours']}",
            "|".join(fmt(d0.metrics["resolution_time"][k]) for k in ("resolved_count", "claimed_count", "open_count", "reopened_count", "reopen_cycles_total", "mean_hours")))
    ln = R["05_lineage_coverage_evidence__coverage"][0]
    lc = r0["lineage_coverage"]
    rec.add("B lineage: declared | observed | matching | coverage | undeclared | inferred (05 vs reference SQL vs domain)",
            f"{ln['declared_pairs']}|{ln['observed_pairs']}|{ln['observed_matching_declared']}|{fmt(ln['coverage'])}|{ln['undeclared_observed']}|{ln['inferred_pairs']}",
            f"{lc['declared_edges']}|{lc['observed_distinct']}|{lc['observed_matching_declared']}|{lc['value']}|{len(lc['undeclared_observed'])}|{len(lc['inferred_edges'])}",
            f"{d0.metrics['lineage_coverage']['declared_edges']}|{d0.metrics['lineage_coverage']['observed_distinct']}|{d0.metrics['lineage_coverage']['observed_matching_declared']}|{d0.metrics['lineage_coverage']['value']}|"
            f"{len(d0.metrics['lineage_coverage']['undeclared_observed'])}|{len(d0.metrics['lineage_coverage']['inferred_edges'])}")
    rec.add("B lineage undeclared and declared-not-observed pair lists (05 vs reference SQL, digest)",
            digest([[(r["source_dataset_id"], r["target_dataset_id"]) for r in R["05_lineage_coverage_evidence__undeclared_observed"]], [(r["source_dataset_id"], r["target_dataset_id"]) for r in R["05_lineage_coverage_evidence__declared_not_observed"]]]),
            digest([[(x["source_dataset_id"], x["target_dataset_id"]) for x in lc["undeclared_observed"]], [(x["source_dataset_id"], x["target_dataset_id"]) for x in lc["declared_not_observed"]]]))
    dsum = R["06_definition_coverage__summary"][0]
    dcv = r0["definition_coverage"]
    rec.add("B definitions: published | complete | value | incomplete metrics and their missing items (06 vs reference SQL vs domain)",
            f"{dsum['published_metrics']}|{dsum['complete_metrics']}|{fmt(dsum['coverage'])}|{digest({r['metric_id']: r['missing_items'].split(',') for r in R['06_definition_coverage__incomplete']})}",
            f"{dcv['published_metrics']}|{dcv['complete_metrics']}|{dcv['value']}|{digest(dcv['incomplete'])}",
            f"{d0.metrics['definition_coverage']['published_metrics']}|{d0.metrics['definition_coverage']['complete_metrics']}|{d0.metrics['definition_coverage']['value']}|{digest(d0.metrics['definition_coverage']['incomplete'])}")
    mp = R["07_match_precision__precision"][0]
    rm = r0["match_precision"]
    rec.add("B match precision: approved | correct | precision | reviewed | reviewed correct | share (07 vs reference SQL vs domain)",
            f"{mp['approved']}|{mp['approved_correct']}|{fmt(mp['precision'])}|{mp['reviewed']}|{mp['reviewed_correct']}|{fmt(mp['reviewed_correct_share'])}",
            f"{rm['approved_decisions']}|{rm['approved_correct']}|{rm['precision']}|{rm['reviewed']}|{rm['reviewed_correct']}|{rm['reviewed_correct_share']}",
            "|".join(fmt(d0.metrics["match_precision"][k]) for k in ("approved_decisions", "approved_correct", "precision", "reviewed", "reviewed_correct", "reviewed_correct_share")))
    ts_ = R["08_timeliness_states__summary"][0]
    rtm = r0["timeliness"]
    rec.add("B timeliness at the as-of: monitored | evaluated | on time | pending | value (08 vs reference SQL vs domain)",
            f"{ts_['monitored_datasets']}|{ts_['evaluated']}|{ts_['on_time']}|{ts_['pending']}|{fmt(ts_['timeliness'])}", f"{rtm['monitored_datasets']}|{rtm['evaluated_datasets']}|{rtm['on_time_count']}|{rtm['pending_count']}|{rtm['value']}",
            "|".join(fmt(d0.metrics["timeliness"][k]) for k in ("monitored_datasets", "evaluated_datasets", "on_time_count", "pending_count", "value")))
    cf = r0["critical_failures"]
    rec.add("B critical failures: failures | open critical issues | datasets overridden | carried (analysis 01 and portfolio vs reference SQL vs domain)",
            f"{cr['critical_failures']}|{cr['critical_open_issues']}|{R['01_ds_customers_override_both_weights__portfolio_override'][0]['datasets_overridden']}|0",
            f"{cf['failures']}|{cf['open_issues']}|{cf['datasets_overridden']}|{len(cf['carried'])}",
            f"{d0.metrics['critical_failures']['failures']}|{d0.metrics['critical_failures']['open_issues']}|{d0.metrics['critical_failures']['datasets_overridden']}|{len(d0.metrics['critical_failures']['carried'])}")
    qr = R["10_fix_first_queue__accountability"][0]
    rec.add("B unresolved issues (10 vs reference SQL vs domain): open + claimed", qr["unresolved"], rt["claimed_count"] + rt["open_count"], d0.metrics["resolution_time"]["claimed_count"] + d0.metrics["resolution_time"]["open_count"])

    # ---- C: every result set cell by cell against python_side.py -------------------------------------------------------------------
    P = ps.results()
    for key, prows in P.items():
        srows = R[key]
        a, b = ps.normalised(srows), ps.normalised(prows)
        eq = a == b
        if not eq:
            for i, (x, y) in enumerate(zip(a, b)):
                if x != y:
                    print(f"DIFF {key} row {i}: SQL {x} / python {y}")
                    break
            else:
                print(f"DIFF {key}: {len(a)} SQL rows / {len(b)} python rows")
        rec.add(f"C {key}: {len(a)} row(s), every cell (SQL result set vs plain Python from the raw JSON)", digest(a), digest(b))
    missing = sorted(k for k in R if k not in P and not k.startswith("09_"))
    assert not missing, f"result sets with no python-side counterpart: {missing}"

    # ---- D: designed relationships, the injection manifest and the manifest statistics ----------------------------------------------------
    inj_doc = json.loads((SNAP_DIR / "injection-manifest.json").read_text())
    dr = {d["id"]: d["realised"] for d in inj_doc["designed_relationships"]}
    inj = {i["id"]: i for i in inj_doc["injections"]}
    rec.add("D injection manifest and manifest carry the dataset hash and version of this package", f"{inj_doc['dataset_hash']}|{inj_doc['dataset_version']}", f"{manifest['dataset_hash']}|{manifest['dataset_version']}", f"{DATASET_HASH}|tl-20261026-20261026")
    w = {r["weight_version"]: r for r in R["01_ds_customers_override_both_weights__weighted"]}
    rec.add("D DR-01 near-perfect score with an open critical key failure: w1 | w2 | critical failures | open critical issues | override | datasets overridden | issue | rule (01 vs the manifest)",
            f"{fmt(w['w1']['weighted_score'])}|{fmt(w['w2']['weighted_score'])}|{cr['critical_failures']}|{cr['critical_open_issues']}|{fmt(cr['critical_override'])}|{R['01_ds_customers_override_both_weights__portfolio_override'][0]['datasets_overridden']}|"
            f"{[r for r in R['01_ds_customers_override_both_weights__critical_issue'] if r['class'] != 'resolved'][0]['issue_id']}|{[r for r in R['01_ds_customers_override_both_weights__rules'] if r['severity'] == 'critical'][0]['rule_id']}",
            f"{dr['DR-01']['weighted_score_w1']}|{dr['DR-01']['weighted_score_w2']}|{dr['DR-01']['critical_failures']}|{dr['DR-01']['critical_open_issues']}|{fmt(dr['DR-01']['critical_override'])}|{dr['DR-01']['datasets_overridden']}|{dr['DR-01']['issue_id']}|{dr['DR-01']['rule_id']}")
    rec.add("D DR-02 inactive owners leave five datasets uncovered: covered | value | uncovered list | inactive owners (02 vs the manifest)",
            f"{o['covered']}|{fmt(o['coverage'])}|{','.join(r['dataset_id'] for r in R['02_ownership_coverage__uncovered'])}|{','.join(r['owner_id'] for r in R['02_ownership_coverage__inactive_owners'])}",
            f"{dr['DR-02']['covered']}|{dr['DR-02']['value']}|{','.join(dr['DR-02']['uncovered'])}|{','.join(dr['DR-02']['inactive_owners'])}")
    sm, rw, rc = R["03_weight_shift_dr03__summary"][0], R["03_weight_shift_dr03__runs_by_weight_version"], R["03_weight_shift_dr03__rule_changes_near_the_weight_change"][0]
    d3 = dr["DR-03"]
    rec.add("D DR-03 the weight change moves scores: scored | different | moved >= 0.005 | mean w1 | mean w2 | largest move | runs w1 | runs w2 | rule changes within 14 days (03 vs the manifest)",
            f"{sm['datasets_scored']}|{sm['datasets_with_different_score']}|{sm['datasets_moved_at_least_0_005']}|{fmt(sm['mean_score_w1'])}|{fmt(sm['mean_score_w2'])}|{fmt(sm['largest_move'])}|{rw[0]['runs']}|{rw[1]['runs']}|{rc['within_14_days_of_the_weight_change']}",
            f"{d3['datasets_scored']}|{d3['datasets_with_different_score']}|{d3['datasets_moved_at_least_0.005']}|{d3['mean_score_w1']}|{d3['mean_score_w2']}|{d3['largest_move']}|{d3['runs_under_w1']}|{d3['runs_under_w2']}|{d3['rule_version_changes_within_14_days_of_the_weight_change']}")
    fv = {r["group_name"]: r for r in R["04_issue_classes_and_resolution__fast_team_vs_others"]}
    d4 = dr["DR-04"]
    rec.add("D DR-04 one team resolves twice as fast: fast resolved | fast mean | other resolved | other mean | ratio (04 vs the manifest)",
            f"{fv['Data Platform']['resolved']}|{fmt(fv['Data Platform']['mean_hours'])}|{fv['all other teams']['resolved']}|{fmt(fv['all other teams']['mean_hours'])}|{fmt(ro['fast_team_ratio'])}",
            f"{d4['fast_resolved']}|{d4['fast_mean_hours']}|{d4['other_resolved']}|{d4['other_mean_hours']}|{d4['ratio']}")
    cs = R["04_issue_classes_and_resolution__claimed_split"][0]
    d5 = dr["DR-05"]
    rec.add("D DR-05 the oldest unresolved issues are all claimed: unresolved | oldest issue | oldest detected | claimed among the oldest 25 of 25 (04 vs the manifest)",
            f"{cs['unresolved']}|{cs['oldest_unresolved_issue']}|{cs['oldest_unresolved_detected_at']}|{cs['claimed_among_the_oldest_25_unresolved']}",
            f"{d5['unresolved']}|{d5['oldest_issue']}|{d5['oldest_detected_at']}|{25 if d5['all_of_the_oldest_25_claimed'] else 0}")
    rec.add("D DR-05 the leading run of claimed issues among the unresolved, oldest first: length | first issue that is not claimed (04 vs the manifest)", f"{cs['leading_claimed_run']}|{cs['first_not_claimed']}",
            f"{d5['leading_claimed_run']}|{d5['first_not_claimed']}")
    mp6, d6 = R["07_match_precision__precision"][0], dr["DR-06"]
    cd, rv_ = R["07_match_precision__candidates"][0], R["07_match_precision__reversals"][0]
    wa = R["07_match_precision__wrong_approvals"]
    rec.add("D DR-06 precision: candidates | reviewed | approved | rejected | correct | precision | reviewed share | reversals | reversed wrong approvals (07 vs the manifest)",
            f"{cd['candidates']}|{mp6['reviewed']}|{mp6['approved']}|{mp6['rejected']}|{mp6['approved_correct']}|{fmt(mp6['precision'])}|{fmt(mp6['reviewed_correct_share'])}|{rv_['reversals']}|{rv_['reversals_of_wrong_approvals']}",
            f"{d6['candidates']}|{d6['reviewed']}|{d6['approved']}|{d6['rejected']}|{d6['approved_correct']}|{d6['precision']}|{d6['reviewed_correct_share']}|{d6['reversals']}|{d6['reversed_wrong_approvals']}")
    rec.add("D DR-06 households: candidates flagged as a possible household | wrongly approved households (07 vs the manifest)",
            f"{cd['candidates_flagged_shared_name_and_address']}|{sum(1 for r in wa if r['flagged_possible_household'])}", f"{d6['shared_name_address_candidates']}|{d6['households_wrongly_approved']}")
    rec.add("D synthetic_truth precision block in the manifest (07 vs the manifest)", f"{mp6['approved']}|{mp6['approved_correct']}|{fmt(mp6['precision'])}|{mp6['reviewed']}|{fmt(mp6['reviewed_correct_share'])}",
            f"{manifest['synthetic_truth']['precision']['approved']}|{manifest['synthetic_truth']['precision']['approved_correct']}|{manifest['synthetic_truth']['precision']['precision']}|{manifest['synthetic_truth']['precision']['reviewed']}|"
            f"{manifest['synthetic_truth']['precision']['reviewed_correct_share']}")
    st = manifest["stats"]
    rec.add("D manifest stats.issues: resolved | claimed | open | claimed with a failed rerun | reopened issues (04 vs the manifest)",
            f"{cl['resolved']}|{cl['claimed']}|{cl['open']}|{cs['claimed_with_a_failed_rerun']}|{ro['reopened_issues']}",
            f"{st['issues']['by_class']['resolved']}|{st['issues']['by_class']['claimed']}|{st['issues']['by_class']['open']}|{st['issues']['claimed_with_failed_rerun']}|{st['issues']['reopened']}")
    rec.add("D manifest stats.lineage: declared | observed | undeclared observed | inferred | inferred on declared unobserved (05 vs the manifest)",
            f"{ln['declared_pairs']}|{ln['observed_pairs']}|{ln['undeclared_observed']}|{ln['inferred_pairs']}|{ln['inferred_on_declared_unobserved']}",
            f"{st['lineage']['declared']}|{st['lineage']['observed']}|{st['lineage']['undeclared_observed']}|{st['lineage']['inferred']}|{st['lineage']['inferred_on_declared_unobserved']}")
    rec.add("D manifest stats.datasets and timeliness: monitored | on time (08 vs the manifest)", f"{ts_['monitored_datasets']}|{ts_['on_time']}", f"{st['datasets']['monitored']}|{st['timeliness_on_time']}")
    rec.add("D manifest stats.definitions_incomplete: the seven incomplete metrics and the item missing from each (06 vs the manifest)",
            digest({r["metric_id"]: r["missing_items"].replace("owner", "owner_id") for r in R["06_definition_coverage__incomplete"]}), digest(st["definitions_incomplete"]))
    vs = R["06_definition_coverage__versions"][0]
    rec.add("D INJ-11 definitions: change records | versions without a change record | metrics with a second version (06 vs the injection manifest)",
            f"{vs['change_records']}|{vs['versions_without_change_record']}|{vs['metrics_with_more_than_one_version']}", f"{[c for c in inj['INJ-11']['checks'] if c['path'] == 'definitions.change_records'][0]['equals']}|"
            f"{[c for c in inj['INJ-11']['checks'] if c['path'] == 'definitions.versions_without_change_record'][0]['length']}|{st['rules']['version_2_or_more'] + 1}")
    rec.add("D INJ-07 ownership and INJ-08 lineage checks (02 and 05 vs the injection manifest): uncovered list | value | lineage value | observed | matching | undeclared | inferred",
            f"{','.join(r['dataset_id'] for r in R['02_ownership_coverage__uncovered'])}|{fmt(o['coverage'])}|{fmt(ln['coverage'])}|{ln['observed_pairs']}|{ln['observed_matching_declared']}|{ln['undeclared_observed']}|{ln['inferred_pairs']}",
            f"{','.join([c for c in inj['INJ-07']['checks'] if c['path'].endswith('uncovered')][0]['equals'])}|{[c for c in inj['INJ-07']['checks'] if c['path'].endswith('value')][0]['equals']}|"
            f"{[c for c in inj['INJ-08']['checks'] if c['path'].endswith('lineage_coverage.value')][0]['equals']}|{[c for c in inj['INJ-08']['checks'] if c['path'].endswith('observed_distinct')][0]['equals']}|"
            f"{[c for c in inj['INJ-08']['checks'] if c['path'].endswith('observed_matching_declared')][0]['equals']}|{[c for c in inj['INJ-08']['checks'] if c['path'].endswith('undeclared_observed')][0]['length']}|"
            f"{[c for c in inj['INJ-08']['checks'] if c['path'].endswith('inferred_edges')][0]['length']}")
    rec.add("D INJ-09 issues closed without a verifying rerun: claimed | iss-0004 is claimed (04 and 01 vs the injection manifest)", f"{cl['claimed']}|{cs['oldest_unresolved_issue']}", f"{[c for c in inj['INJ-09']['checks'] if c['path'].endswith('claimed_count')][0]['equals']}|iss-0004")
    for inj_id, rid, path in (("INJ-04", "r-orders-fk-customer_key", "relationship_integrity"),):
        want = {c["path"].rsplit(".", 1)[1]: c["equals"] for c in inj[inj_id]["checks"]}
        x = r0[path][rid]
        rec.add(f"D {inj_id} null foreign keys counted apart on {rid}: null | eligible | unmatched (reference SQL vs the injection manifest)", f"{x['null_fk_count']}|{x['eligible_count']}|{x['unmatched_count']}",
                f"{want['null_fk_count']}|{want['eligible_count']}|{want['unmatched_count']}")
    dr_rows = {r["rule_id"]: r for r in R["04_issue_classes_and_resolution__disabled_rules"]}
    want2 = {c["path"].split(".")[2] + "." + c["path"].split(".")[3]: c["equals"] for c in inj["INJ-02"]["checks"]}
    rec.add("D INJ-02 the five disabled rules keep their runs and issues: runs retained | issues retained for each rule (04 vs the injection manifest)",
            "|".join(f"{rid}:{dr_rows[rid]['runs_retained']}:{dr_rows[rid]['issues_retained']}" for rid in sorted(dr_rows)),
            "|".join(f"{rid}:{want2[rid + '.runs_retained']}:{want2[rid + '.issues_retained']}" for rid in sorted(dr_rows)))
    sh = {r["dataset_id"]: r for r in R["03_weight_shift_dr03__shift_by_dataset"]}
    w5 = {c["path"].split(".")[3]: c["equals"] for c in inj["INJ-05"]["checks"]}
    rec.add("D INJ-05 identical rows score differently under w1 and w2: ds-orders (03 vs the injection manifest)", f"{fmt(sh['ds-orders']['score_w1'])}|{fmt(sh['ds-orders']['score_w2'])}", f"{w5['w1']}|{w5['w2']}")
    mm = dom[AS_OF].golden()["matching"]
    w6 = {c["path"].split(".", 1)[1]: c["equals"] for c in inj["INJ-06"]["checks"]}
    rec.add("D INJ-06 15 approved merges are reversed and both identities restored: reversals | identity map of rec-1275 and rec-0102 (07 and the domain vs the injection manifest)",
            f"{rv_['reversals']}|{mm['identity_map']['rec-1275']}|{mm['identity_map']['rec-0102']}", f"{w6['merges_reversed']}|{w6['identity_map.rec-1275']}|{w6['identity_map.rec-0102']}")
    rec.add("D INJ-03 and INJ-10 400 distinct canonical candidates, none merged automatically: candidates | distinct canonical pairs | reviews by the proposer (07 vs the injection manifest)",
            f"{cd['candidates']}|{cd['canonical_distinct_pairs']}|{cd['reviews_by_the_proposer']}", f"{[c for c in inj['INJ-10']['checks']][0]['equals']}|{[c for c in inj['INJ-03']['checks']][0]['equals']}|0")
    cmp_ = dom[AS_OF].golden()["rules"]["comparisons"]["r-contacts-fk-customer_key"]
    want = {c["path"].rsplit(".", 1)[1]: c["equals"] for c in inj["INJ-12"]["checks"]}
    rec.add("D INJ-12 a changed denominator is not comparable: comparable | reason | previous eligible | current eligible (domain vs the injection manifest)",
            f"{fmt(cmp_['comparable'])}|{cmp_['reason']}|{cmp_['previous_eligible_count']}|{cmp_['current_eligible_count']}", f"{fmt(want['comparable'])}|{want['reason']}|{want['previous_eligible_count']}|{want['current_eligible_count']}")
    n_cmp, differ = _stored_vs_measured(snap_url)
    rec.add("D the stored last scheduled run of each active row-based rule equals the row-level measurement except the INJ-12 rule (rules compared | rules that differ: analysis tl_rule_measure vs the stored runs)",
            f"{n_cmp}|{','.join(differ)}", f"{n_cmp}|r-contacts-fk-customer_key")

    # ---- E: the BI package ----------------------------------------------------------------------------------------------------------
    csvs = {k: [{c: fmt(v) for c, v in r.items()} for r in rows] for k, rows in bi.items()}
    meas_rows = bi_measures(csvs)
    mv = {(m["measure"], m["slice"]): m for m in meas_rows}
    rec.add("E BI row counts: dim_owner | dim_dataset | dim_rule | dim_metric | fact_rule_measure | fact_dataset_score | fact_issue | fact_lineage_edge | fact_candidate | fact_timeliness",
            "|".join(str(len(csvs[k])) for k in ("dim_owner", "dim_dataset", "dim_rule", "dim_metric", "fact_rule_measure", "fact_dataset_score", "fact_issue", "fact_lineage_edge", "fact_candidate", "fact_timeliness")),
            f"{manifest['row_counts']['owners']}|{manifest['row_counts']['datasets']}|{manifest['row_counts']['quality_rules']}|30|55|80|{manifest['row_counts']['issues']}|{manifest['row_counts']['lineage_edges']}|"
            f"{manifest['row_counts']['match_candidates']}|15")
    rec.add("E BI ownership coverage | definition coverage | lineage coverage (CSV facts vs reference SQL vs domain)", f"{mv[('ownership_coverage', 'portfolio')]['value']}|{mv[('definition_coverage', 'portfolio')]['value']}|{mv[('lineage_coverage', 'portfolio')]['value']}",
            f"{oc['value']}|{dcv['value']}|{lc['value']}", f"{d0.metrics['ownership_coverage']['value']}|{d0.metrics['definition_coverage']['value']}|{d0.metrics['lineage_coverage']['value']}")
    rec.add("E BI issue classes | mean resolution hours | Data Platform mean (CSV facts vs reference SQL vs domain)",
            f"{mv[('issues', 'resolved')]['numerator']}|{mv[('issues', 'claimed')]['numerator']}|{mv[('issues', 'open')]['numerator']}|{mv[('mean_resolution_hours', 'all resolved')]['value']}|{mv[('mean_resolution_hours', 'Data Platform')]['value']}",
            f"{rt['resolved_count']}|{rt['claimed_count']}|{rt['open_count']}|{rt['mean_hours']}|{fmt(fv['Data Platform']['mean_hours'])}",
            f"{d0.metrics['resolution_time']['resolved_count']}|{d0.metrics['resolution_time']['claimed_count']}|{d0.metrics['resolution_time']['open_count']}|{d0.metrics['resolution_time']['mean_hours']}|{fmt(fv['Data Platform']['mean_hours'])}")
    rec.add("E BI timeliness | pending | late (CSV facts vs reference SQL vs domain)", f"{mv[('timeliness', 'portfolio')]['value']}|{mv[('timeliness_pending', 'portfolio')]['value']}|{mv[('timeliness_late', 'portfolio')]['value']}",
            f"{rtm['value']}|{rtm['pending_count']}|{rtm['evaluated_datasets'] - rtm['on_time_count']}", f"{d0.metrics['timeliness']['value']}|{d0.metrics['timeliness']['pending_count']}|{d0.metrics['timeliness']['evaluated_datasets'] - d0.metrics['timeliness']['on_time_count']}")
    rec.add("E BI match precision | reviewed correct share (CSV facts vs reference SQL vs domain)", f"{mv[('match_precision', 'portfolio')]['value']}|{mv[('reviewed_correct_share', 'portfolio')]['value']}",
            f"{rm['precision']}|{rm['reviewed_correct_share']}", f"{d0.metrics['match_precision']['precision']}|{d0.metrics['match_precision']['reviewed_correct_share']}")
    rec.add("E BI weighted score of every dataset under w1 and w2: the 80 rows recomputed from the exact rule fractions vs the SQL fact vs reference SQL (digest; unmeasured datasets stay empty)",
            digest(sorted((m["slice"], m["value"]) for m in meas_rows if m["measure"] == "weighted_score")),
            digest(sorted((f"{r['dataset_id']}|{r['weight_version']}", r["weighted_score"]) for r in csvs["fact_dataset_score"])),
            digest(sorted((f"{d}|{wv}", v or "") for wv in ("w1", "w2") for d, v in r0["weighted_score"]["by_weight_version"][wv].items())))
    rec.add("E BI weighted score mean under w1 | w2 | datasets that differ | moved | largest move (CSV facts vs 03 vs the manifest DR-03)",
            f"{mv[('mean_weighted_score', 'w1')]['value']}|{mv[('mean_weighted_score', 'w2')]['value']}|{mv[('datasets_with_a_different_score', 'w1 vs w2')]['numerator']}|{mv[('datasets_moved_at_least_0_005', 'w1 vs w2')]['numerator']}|{mv[('largest_move', 'w1 vs w2')]['value']}",
            f"{fmt(sm['mean_score_w1'])}|{fmt(sm['mean_score_w2'])}|{sm['datasets_with_different_score']}|{sm['datasets_moved_at_least_0_005']}|{fmt(sm['largest_move'])}",
            f"{d3['mean_score_w1']}|{d3['mean_score_w2']}|{d3['datasets_with_different_score']}|{d3['datasets_moved_at_least_0.005']}|{d3['largest_move']}")
    rec.add("E BI critical failures | datasets with the override | open critical issues (CSV facts vs reference SQL vs domain)", f"{mv[('critical_failures', 'portfolio')]['value']}|{mv[('datasets_with_the_critical_override', 'portfolio')]['value']}|{mv[('open_critical_issues', 'portfolio')]['value']}",
            f"{cf['failures']}|{cf['datasets_overridden']}|{cf['open_issues']}", f"{d0.metrics['critical_failures']['failures']}|{d0.metrics['critical_failures']['datasets_overridden']}|{d0.metrics['critical_failures']['open_issues']}")
    rec.add("E BI unresolved issues | with an inactive owner (CSV facts vs 10)", f"{mv[('unresolved_issues', 'all')]['value']}|{mv[('unresolved_issues_with_an_inactive_owner', 'all')]['value']}", f"{qr['unresolved']}|{qr['either_owner_inactive']}")
    rec.add("E BI nothing withheld silently: every dataset x weight version has a measure row and each empty value carries a status (rows | empty values | empty values with a non-value status)",
            f"{sum(1 for m in meas_rows if m['measure'] == 'weighted_score')}|{sum(1 for m in meas_rows if m['value'] == '')}|{sum(1 for m in meas_rows if m['value'] == '' and m['status'] != 'value')}",
            f"{2 * manifest['row_counts']['datasets']}|{sum(1 for m in meas_rows if m['value'] == '')}|{sum(1 for m in meas_rows if m['value'] == '')}")

    # ---- results -----------------------------------------------------------------------------------------------------------------------------------------
    equal = sum(1 for r in rec.rows if r["equal"])
    meta = {"dataset_hash": DATASET_HASH, "dataset_version": manifest["dataset_version"], "code_revision": CODE_REVISION, "contract_version": 1, "seed": manifest["generator"]["seed"], "as_of": AS_OF,
            "golden_dataset_hash": prep_g["dataset_hash"], "datasets": manifest["row_counts"]["datasets"], "issues": manifest["row_counts"]["issues"], "rule_runs": manifest["row_counts"]["rule_runs"],
            "reconciliation_rows": len(rec.rows), "reconciliation_equal": equal, "result_sets": len(R), "result_rows": sum(len(R[k]) for k in R)}
    for r in rec.rows:
        print(("OK   " if r["equal"] else "DIFF ") + r["check"] + (" | " + " | ".join(str(r[k]) for k in ("analysis_sql", "second_source", "third_source", "fourth_source") if r[k] != "") if not r["equal"] else ""))
    print(f"RESULT: {'OK' if rec.ok else 'FAILED'} ({len(rec.rows)} reconciliation rows, {equal} equal; {meta['result_sets']} result sets, {meta['result_rows']} rows)")
    if bi_out:
        for k, rows in csvs.items():
            export_csv(bi_out / f"{k}.csv", rows)
        export_csv(bi_out / "measures_recomputed.csv", meas_rows)
        print(f"wrote {len(csvs) + 1} CSV files to {bi_out}")
    if json_out:
        out = {"meta": [meta], **{k: ps.normalised(v) for k, v in R.items()}, "bi_measures": meas_rows,
               "bi_measures_portfolio": [m for m in meas_rows if m["measure"] != "weighted_score"], "bi_measures_dataset_scores": [m for m in meas_rows if m["measure"] == "weighted_score"], "reconciliation": rec.rows}
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(out, indent=1, sort_keys=False) + "\n")
        print(f"wrote {json_out}")
    return 0 if rec.ok else 1


def _stored_vs_measured(snap_url: str) -> tuple[int, list[str]]:
    """Compare each active rule's last scheduled run at the as-of (the counts the stored runs carry) with the row-level measurement: (rules compared, rules that differ)."""
    with psycopg.connect(snap_url, row_factory=dict_row, autocommit=True, options="-c timezone=UTC") as c:
        run_script(c, HERE / "00_measure_rules.sql")
        rows = c.execute("""SELECT m.rule_id, m.eligible, m.failing, lr.eligible_count, lr.failure_count
                            FROM tl_rule_measure m JOIN LATERAL (SELECT r.eligible_count, r.failure_count FROM rule_runs r, tl_p WHERE r.rule_id = m.rule_id AND r.kind = 'scheduled' AND r.run_at <= tl_p.as_of
                                                                 ORDER BY r.run_at DESC LIMIT 1) lr ON true
                            WHERE m.dimension <> 'timeliness'""").fetchall()
    differ = [r["rule_id"] for r in rows if (r["eligible"], int(r["failing"])) != (r["eligible_count"], r["failure_count"])]
    print(f"stored last scheduled runs vs row-level measurement: {len(rows)} row-based rules compared, differing: {differ}")
    return len(rows), differ


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
