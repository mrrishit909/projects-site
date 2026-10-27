"""Run every analysis investigation and reconcile it with the independent sources (P08-ART-04).

Usage (from apps/pipeline-observatory):
  ../../.venv/bin/python data/sql/analysis/run_all.py [--json artifacts/analysis-results.json] [--bi-out artifacts/bi] [--keep]

With no environment variables it creates two scratch databases (artifacts08_run_snapshot, artifacts08_run_golden) on the local PostgreSQL named by ARTIFACTS_ADMIN_URL
(default: the repository's local development login, 127.0.0.1:5432), loads the published snapshot ``web/public/data`` and the golden fixture through ``data/migrate.py`` and
``data/seed.py`` (prepare_snapshot.py), runs everything and drops them again (``--keep`` leaves them). To use databases you prepared yourself, set ARTIFACTS_DATABASE_URL and
ARTIFACTS_GOLDEN_DATABASE_URL (names must start with artifacts08_; the shared pipeline_observatory database is never touched).

What runs, in order (exit code 0 only if every query ran and every reconciliation row is equal):
  00_definitions.sql (the as-of, the gate result and the stage and failure kind of every run, the verified recovery of every incident, into temporary tables), 01..08 and 10 on the
  snapshot (files hold several blocks marked ``-- @@ name``), 09 on the golden database, bi_dimensions.sql and bi_fact_*.sql on the snapshot (written as CSV with --bi-out).
Reconciliation (the rows printed at the end, ``reconciliation`` in the JSON). Every figure carries its SCOPE: complete world, 2,000-row sample, or recorded (D-08, D-09 R8-09):
  A  golden fixture: data/sql/reference_metrics.sql, the Python domain and tests/fixtures/golden/expected.json agree on every metric key and the whole expected shape; the SQL of
     investigation 09 equals the hand answer of expected.json and CALCULATION.md (10 / 8 / 1 / 1, 52,200 s against 42,900 s, 8 of 9, 1.000000 against 0.800000, pub-001 / pub-001 / pub-003,
     289.94 / 289.97 / -0.03 / 0.00, 475.0000 minutes, 2 of 3, 0.666667);
  B  the loaded snapshot: row counts and the dataset hash against the manifest; the reference SQL against the Python domain over the sample, at the as-of and an earlier instant; the
     complete-world investigations against the manifest's recorded statistics and the domain; the sample figures against the domain over the sample;
  C  every result set cell by cell against python_side.py (plain Python from the raw JSON rows, no SQL and no domain code);
  D  the designed relationships (DR-01..DR-05), the injected defects (INJ-01..INJ-10) and the manifest statistics against what the SQL finds;
  E  the BI package: row counts, the measures recomputed from the CSV facts against the SQL, the domain and the manifest, and nothing withheld without a status.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sys
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
from pipeline_observatory import run_pipeline  # noqa: E402
from pipeline_observatory.contract import METRIC_KEYS  # noqa: E402

REFERENCE = ROOT / "data" / "sql" / "reference_metrics.sql"
GOLDEN_DIR = ROOT / "tests" / "fixtures" / "golden"
SNAP_DIR = ROOT / "web" / "public" / "data"
CODE_REVISION = "ed7eb5a"
DATASET_HASH = "0a90687778634365c402c5431661b56625de20785e28d9b2388d36c0cad19aab"
RUN_SNAPSHOT_DB, RUN_GOLDEN_DB = "artifacts08_run_snapshot", "artifacts08_run_golden"
AS_OF = "2026-10-05T00:00:00Z"
EARLIER = "2026-09-14T00:00:00Z"
SNAPSHOT_FILES = ["01", "02", "03", "04", "05", "06", "07", "08", "10"]
BI_FILES = ["bi_dimensions", "bi_fact_batch", "bi_fact_run", "bi_fact_gate_check", "bi_fact_incident", "bi_fact_backfill_partition", "bi_fact_fetch", "bi_fact_freshness"]


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
    """Execute every block of a file that creates temporary tables (00_definitions.sql); nothing is fetched."""
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


def reference(conn, cutoff: str) -> dict:
    return dict(conn.execute(REFERENCE.read_text(), {"cutoff": cutoff}).fetchone())


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


# ---- BI measures from the exported facts (no database, no domain): exact arithmetic over the CSV strings --------------------------------------------------------
def bi_measures(csvs: dict[str, list[dict]], facts: dict) -> list[dict]:
    """The measures of docs/bi-package.md evaluated over the CSV facts. Every row has a scope and a status; nothing is dropped: a zero denominator, a figure only the generator records
    and a figure the sample cannot show are stated with the reason, never left out and never 0."""
    rows: list[dict] = []

    def add(measure: str, slice_: str, scope: str, num=None, den=None, places: int | None = 6, value=None, status: str = "value", note: str = "") -> None:
        if value is None and den is not None:
            if den == 0:
                status, v = "null: zero denominator", ""
            else:
                v = fmt(ps.rnd(F(num) / F(den), places))
        elif value is not None:
            v = fmt(value)
        else:
            v = fmt(num)
        rows.append({"measure": measure, "slice": slice_, "scope": scope, "value": v, "numerator": "" if num is None else fmt(num), "denominator": "" if den is None else fmt(den),
                     "status": status, "note": note})

    t = lambda s: s == "true"
    batches, runs, fresh = csvs["fact_batch"], csvs["fact_run"], csvs["fact_freshness"]
    sources = [s["source_id"] for s in csvs["dim_source"]]
    counted = [b for b in batches if t(b["counted"])]
    for slice_ in ["all"] + sources:
        sub = counted if slice_ == "all" else [b for b in counted if b["source_id"] == slice_]
        tot = {k: sum(int(b[k]) for b in sub) for k in ("received", "accepted_unique", "duplicate", "quarantined", "deleted")}
        for k, v in tot.items():
            add(k, slice_, "complete_world", value=v, note="committed batches only" if slice_ == "all" and k == "received" else "")
        add("rejection_rate", slice_, "complete_world", tot["quarantined"], tot["received"], note="quarantined / received; the schema-quarantined batch is not in it")
        add("duplicate_rate", slice_, "complete_world", tot["duplicate"], tot["received"], note="duplicate / received")
    add("schema_quarantined_rows", "all", "complete_world", value=sum(int(b["schema_quarantined_rows"]) for b in batches if b["status"] == "quarantined"),
        note="rows of the batch refused whole for SCHEMA_CHANGED; listed apart from every rate")
    add("runs", "all", "complete_world", value=len(runs))
    reached = [r for r in runs if r["gate_decision"] != "not_reached"]
    add("reached_gate", "all", "complete_world", value=len(reached))
    add("allowed", "all", "complete_world", value=sum(r["gate_decision"] == "allowed" for r in runs))
    add("blocked_at_gate", "all", "complete_world", value=sum(r["gate_decision"] == "blocked" for r in runs))
    add("failed_before_gate", "all", "complete_world", value=sum(r["stage"] == "failed_before_gate" for r in runs))
    for k in sorted({r["failure_kind"] for r in runs if r["failure_kind"]}):
        add("failed_runs", f"kind: {k}", "complete_world", value=sum(r["failure_kind"] == k for r in runs))
    add("task_success_rate", "all", "complete_world", sum(int(r["tasks_successful"]) for r in runs), sum(int(r["tasks_terminal"]) for r in runs), note="successful terminal tasks / terminal tasks")
    add("attempt_success_rate", "all", "complete_world", sum(int(r["attempts_successful"]) for r in runs), sum(int(r["attempts"]) for r in runs), note="attempts are not tasks")
    for f in fresh:
        add("ingestion_age_seconds", f["source_id"], f["ingestion_age_scope"], value=int(f["ingestion_age_seconds"]))
        add("freshness_seconds", f["source_id"], f["freshness_scope"], value=int(f["freshness_seconds"]), note="seconds recomputed from the recorded latest accepted event")
        add("silent", f["source_id"], f["freshness_scope"], value=f["silent"], note="freshness above two declared cadences (display rule)")
        add("completeness", f["source_id"], f["completeness_scope"], int(f["accepted_records"]), int(f["expected_records"]), note="accepted unique / expected over all partitions")
    add("silent_sources", "all", "recorded", value=sum(t(f["silent"]) for f in fresh))
    inc = csvs["fact_incident"]
    add("incidents", "all", "complete_world", value=len(inc))
    add("mean_recovery_minutes", "all", "complete_world", value=ps.rnd(F(sum(int(i["recovery_seconds"]) for i in inc), len(inc) * 60), 4), note="verified recovery minus detection")
    for k in sorted({i["failure_kind"] for i in inc}):
        sub = [i for i in inc if i["failure_kind"] == k]
        add("mean_recovery_minutes", f"kind: {k}", "complete_world", value=ps.rnd(F(sum(int(i["recovery_seconds"]) for i in sub), len(sub) * 60), 4))
    parts = csvs["fact_backfill_partition"]
    cov = [p for p in parts if t(p["in_coverage"])]
    add("backfill_coverage", "all", "complete_world", sum(t(p["verified"]) for p in cov), len(cov), note="verified / requested partitions of the accepted requests")
    add("refused_backfill_partitions", "all", "complete_world", value=sum(not t(p["in_coverage"]) for p in parts), note="beside the coverage, never inside it")
    fetch = csvs["fact_fetch"]
    rl = [f for f in fetch if f["status"] == "rate_limited" and f["retry_waited_seconds"] != ""]
    add("retries_honoured", "all", "complete_world", sum(t(f["retry_honoured"]) for f in rl), len(rl), note="retries that waited at least the retry-after hint / retries")
    for st in sorted({f["status"] for f in fetch}):
        add("fetches", f"status: {st}", "complete_world", value=sum(f["status"] == st for f in fetch))
    # what the published files cannot show: stated, never left out and never 0
    add("late_events", "complete world", "recorded", value="", status="recorded_only",
        note=f"the generator records {facts['late_recorded']} (manifest stats.late_events: {facts['late_causes']}), all included in the next publication, none lost; the published files cannot recompute it")
    add("late_events", "2,000-row sample", "sample", value="", status="sample_only", note=f"the reference SQL and the domain both count {facts['late_sample']} over the sample; it describes the sample, not the world")
    add("reconciliation_residual", "all publications", "recorded", value="", status="recorded_only",
        note=f"needs the amount of every raw row: the manifest records {facts['recon_publications_nonzero']} of {facts['recon_publications']} publications and {facts['recon_candidates_nonzero']} of {facts['recon_candidates']} candidates with a residual other than 0.00 (DR-05); only that one candidate is recomputed (investigation 06)")
    add("publication_content_hash_ok", "complete world", "recorded", value="", status="recorded_only", note=f"the manifest records {facts['hash_recorded']} of {facts['recon_publications']} (stats.publications.content_hash_ok)")
    add("publication_content_hash_ok", "2,000-row sample", "sample", value="", status="not_verifiable_from_the_sample",
        note=f"{facts['hash_verifiable']} of {facts['recon_publications']} publications have every included batch in the sample, so the recomputed check is false for all of them (investigation 10)")
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
    bi: dict[str, list[dict]] = {}
    ref: dict[str, dict] = {}
    scalar: dict[str, object] = {}
    with psycopg.connect(snap_url, row_factory=dict_row, autocommit=True, options="-c timezone=UTC") as c:
        run_script(c, HERE / "00_definitions.sql")
        print("the as-of, the gate result and stage of every run and the verified recovery of every incident built (po_p, po_gate_result, po_run, po_incident)")
        for prefix in SNAPSHOT_FILES:
            f = next(HERE.glob(f"{prefix}_*.sql"))
            R.update(run_file(c, f))
            print(f"ran {f.name}")
        for name in BI_FILES:
            for k, rows in run_file(c, HERE / f"{name}.sql").items():
                bi[k.split("__")[-1] if "__" in k else k.removeprefix("bi_")] = rows
        print("ran the BI dimension and fact queries")
        for as_of in (AS_OF, EARLIER):
            ref[as_of] = reference(c, as_of)
        print("reference_metrics.sql at the as-of and at an earlier instant")
        scalar["counts"] = {t: c.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"] for t in
                            ("source_contracts", "source_expectations", "ingestion_batches", "raw_records", "quarantine_records", "checkpoints", "model_definitions", "pipeline_runs", "task_runs",
                             "quality_results", "publications", "incidents", "backfill_requests", "fetch_log", "artifact_batch_summaries", "artifact_model_output_totals", "accepted_records")}
        scalar["rejected_backfills"] = c.execute("SELECT count(*) AS n FROM rejected_records WHERE entity = 'backfill_requests'").fetchone()["n"]
        scalar["version_hash"] = c.execute("SELECT dataset_version, dataset_hash FROM dataset_versions").fetchone()
        scalar["pointer"] = c.execute("SELECT publication_id FROM publication_pointer").fetchone()["publication_id"]
        scalar["runs_before_dr02"] = c.execute("SELECT count(*) AS n FROM pipeline_runs WHERE started_at < (SELECT started_at FROM pipeline_runs WHERE run_id = 'run-1187')").fetchone()["n"]
        scalar["q_b0405"] = c.execute("SELECT quarantine_id, source_key, reason_code FROM quarantine_records WHERE batch_id = 'b-0405' AND source_key IS NULL").fetchall()
        scalar["candidates"] = c.execute("SELECT count(*) AS n FROM artifact_model_output_totals").fetchone()["n"]
    with psycopg.connect(gold_url, row_factory=dict_row, autocommit=True, options="-c timezone=UTC") as c:
        run_script(c, HERE / "00_definitions.sql")
        G = run_file(c, HERE / "09_golden_known_answer.sql")
        g_inputs = json.loads((GOLDEN_DIR / "inputs.json").read_text())
        ref_g = reference(c, g_inputs["cutoff"])
    R.update(G)

    # ---- A: golden fixture ---------------------------------------------------------------------------------------------------------------------------
    exp = json.loads((GOLDEN_DIR / "expected.json").read_text())
    dom_g = run_pipeline(g_inputs)
    for k in METRIC_KEYS:
        rec.add(f"A golden metric {k}: reference SQL = Python domain = expected.json (digest)", digest(ref_g[k]), digest(exp["metrics"][k]), digest(dom_g.metrics[k]))
    rec.add("A golden empty_population (reference SQL vs expected.json vs domain)", ref_g["empty_population"], exp["empty_population"], dom_g.empty_population)
    rec.add("A golden whole shape of expected.json (domain result.golden vs the file, digest)", digest(dom_g.golden), digest(exp))
    m = exp["metrics"]
    gb = {r["batch_id"]: r for r in G["09_golden_known_answer__batches"]}
    for bid in ("b-001", "b-002", "b-003", "b-101"):
        e = m["ingestion"]["sources"]["src-orders" if bid != "b-101" else "src-refunds"]["batches"][bid]
        rec.add(f"A golden batch {bid}: status | written | received | accepted | duplicate | quarantined | rejection rate | duplicate rate (09 vs expected.json)",
                "|".join(fmt(gb[bid][k]) for k in ("status", "written_rows", "received", "accepted_unique", "duplicate", "quarantined", "rejection_rate", "duplicate_rate")),
                "|".join(fmt(e[k]) for k in ("status", "written_rows", "received", "accepted_unique", "duplicate", "quarantined", "rejection_rate", "duplicate_rate")))
    rec.add("A golden P08-GOLD-01 hand answer: 10 received | 8 accepted unique | 1 duplicate | 1 quarantined | 0.100000 | 0.100000 (09 b-001 vs the spec sentence)",
            "|".join(fmt(gb["b-001"][k]) for k in ("received", "accepted_unique", "duplicate", "quarantined", "rejection_rate", "duplicate_rate")), "10|8|1|1|0.100000|0.100000")
    gs = {r["source_id"]: r for r in G["09_golden_known_answer__sources"]}
    for s in ("src-orders", "src-refunds"):
        e = m["ingestion"]["sources"][s]
        rec.add(f"A golden source {s}: received | accepted | duplicate | quarantined | distinct keys | rates | checkpoint version (09 vs expected.json)",
                "|".join(fmt(gs[s][k]) for k in ("received", "accepted_unique", "duplicate", "quarantined", "quarantined_distinct_keys", "rejection_rate", "duplicate_rate", "checkpoint_version")),
                "|".join(fmt(e[k]) for k in ("received", "accepted_unique", "duplicate", "quarantined", "quarantined_distinct_keys", "rejection_rate", "duplicate_rate")) + f"|{e['checkpoint']['committed_version']}")
    rc = G["09_golden_known_answer__replay_and_crash"][0]
    e = m["ingestion"]["sources"]["src-orders"]
    rec.add("A golden replay and crash: accepted keys | accepted by the replay | rows the crashed batch wrote | its checkpoints | new keys | checkpoint version (09 vs expected.json vs the hand answer 8, 0, 10, 0, 0, 2)",
            f"{rc['accepted_keys']}|{rc['accepted_by_the_replay']}|{rc['rows_written_by_the_crashed_batch']}|{rc['checkpoints_of_the_crashed_batch']}|{rc['new_keys_in_the_crashed_batch']}|{rc['checkpoint_version']}",
            f"{e['accepted_unique']}|{e['batches']['b-002']['accepted_unique']}|{e['batches']['b-003']['written_rows']}|{e['checkpoint']['uncommitted_batches_with_checkpoint']}|0|{e['checkpoint']['committed_version']}", "8|0|10|0|0|2")
    for r in G["09_golden_known_answer__freshness"]:
        e = m["freshness"][r["source_id"]]
        rec.add(f"A golden freshness {r['source_id']}: latest event | freshness | last ingestion | ingestion age (09 vs expected.json" + ("; the hand answer 52,200 s and 42,900 s)" if r["source_id"] == "src-orders" else ")"),
                f"{r['latest_accepted_event_at']}|{r['freshness_seconds']}|{r['last_successful_ingestion_at']}|{r['ingestion_age_seconds']}",
                f"{e['latest_accepted_event_at']}|{e['freshness_seconds']}|{e['last_successful_ingestion_at']}|{e['ingestion_age_seconds']}",
                "2026-10-04T09:30:00Z|52200|2026-10-04T12:05:00Z|42900" if r["source_id"] == "src-orders" else None)
    for r in G["09_golden_known_answer__completeness"]:
        e = m["completeness"][r["source_id"]][r["partition"]]
        rec.add(f"A golden completeness {r['source_id']} {r['partition']}: expected | accepted | value (09 vs expected.json)", f"{r['expected_records']}|{r['accepted_records']}|{fmt(r['completeness'])}",
                f"{e['expected_records']}|{e['accepted_records']}|{e['value']}")
    for r in G["09_golden_known_answer__runs"]:
        e = m["runs"]["runs"][r["run_id"]]
        rec.add(f"A golden {r['run_id']}: status | duration | tasks | tasks successful | task success | attempts | successful | attempt success (09 vs expected.json)",
                "|".join(fmt(r[k]) for k in ("status", "duration_seconds", "tasks_terminal", "tasks_successful", "task_success_rate", "attempts", "attempts_successful", "attempt_success_rate")),
                f"{e['status']}|{e['duration_seconds']}|{e['tasks_terminal']}|{e['tasks_successful']}|{e['task_success_rate']}|{e['attempts']}|{e['attempts_successful']}|{e['attempt_success_rate']}")
    ro = G["09_golden_known_answer__runs_overall"][0]
    e = m["runs"]["overall"]
    rec.add("A golden tasks against attempts overall: 11 | 10 | 0.909091 | 12 | 10 | 0.833333 (09 vs expected.json)", "|".join(fmt(ro[k]) for k in ("tasks_terminal", "tasks_successful", "task_success_rate", "attempts", "attempts_successful", "attempt_success_rate")),
            "|".join(fmt(e[k]) for k in ("tasks_terminal", "tasks_successful", "task_success_rate", "attempts", "attempts_successful", "attempt_success_rate")))
    ph = m["publications"]["pointer_history"]
    gp = G["09_golden_known_answer__gate_pointer"]
    rec.add("A golden gate and pointer: allowed, blocked, allowed with the pointer on pub-001, pub-001, pub-003 (09 vs expected.json vs the hand answer)", "|".join(f"{r['gate_decision']}:{r['pointer_after']}" for r in gp),
            "|".join(f"{h['gate_decision']}:{h['pointer_after']}" for h in ph), "allowed:pub-001|blocked:pub-001|allowed:pub-003")
    qg = m["quality_gate"]
    rec.add("A golden gate failures per run: critical | non-critical (09 vs expected.json)", "|".join(f"{r['critical_failures']}:{r['noncritical_failures']}" for r in gp), "|".join(f"{qg[r['run_id']]['critical_failures']}:{qg[r['run_id']]['noncritical_failures']}" for r in gp))
    for r in G["09_golden_known_answer__publications"]:
        e = m["publications"]["publications"][r["publication_id"]]
        rec.add(f"A golden {r['publication_id']}: published at | watermark | batches | records | latest event | lag (09 vs expected.json)",
                f"{r['published_at']}|{r['watermark']}|{r['included_batches']}|{r['published_records']}|{r['latest_included_event_at']}|{r['lag_seconds']}",
                f"{e['published_at']}|{e['watermark']}|{','.join(e['included_batches'])}|{e['published_records']}|{e['latest_included_event_at']}|{e['lag_seconds']}")
    le = m["late_events"]["events"][0]
    lr = G["09_golden_known_answer__late_event"][0]
    rec.add("A golden late event REF-2001: arrival | behind | watermark | included in (09 vs expected.json); count 1, none lost", "|".join(fmt(lr[k]) for k in ("source_key", "event_at", "arrival_at", "behind_publication_id", "watermark", "included_in_publication_id")) + f"|{len(G['09_golden_known_answer__late_event'])}",
            "|".join(fmt(le[k]) for k in ("source_key", "event_at", "arrival_at", "behind_publication_id", "watermark", "included_in_publication_id")) + f"|{m['late_events']['count']}")
    for r in G["09_golden_known_answer__reconciliation"]:
        e = m["reconciliation"][r["publication_id"]]
        rec.add(f"A golden {r['publication_id']} reconciliation: source | published | quarantined | duplicates | residual (09 vs expected.json" + ("; the hand answer 289.94, 289.97, -30.00, 29.97, 0.00)" if r["publication_id"] == "pub-001" else ")"),
                f"{r['source_total']}|{r['published_total']}|{r['quarantined']}|{r['duplicates']}|{r['residual']}",
                f"{e['source_total']}|{e['published_total']}|{e['exclusions']['quarantined']}|{e['exclusions']['duplicates']}|{e['residual']}", "289.94|289.97|-30.00|29.97|0.00" if r["publication_id"] == "pub-001" else None)
    rv = G["09_golden_known_answer__recovery"][0]
    ei = m["incidents"]["incidents"]["inc-001"]
    rec.add("A golden recovery inc-001: detected | recovery run | verified | seconds | minutes (09 vs expected.json vs the hand answer 28,500 s = 475.0000 minutes)",
            f"{rv['detected_at']}|{rv['recovery_run_id']}|{rv['verified_at']}|{rv['recovery_seconds']}|{fmt(rv['recovery_minutes'])}", f"{ei['detected_at']}|{ei['recovery_run_id']}|{ei['verified_at']}|{ei['recovery_seconds']}|{ei['recovery_minutes']}",
            "2026-10-04T12:20:00Z|run-003|2026-10-04T20:15:00Z|28500|475.0000")
    bp = G["09_golden_known_answer__backfill_processing"][0]
    eb, ep = m["backfills"]["requests"]["bf-001"], m["processing_rate"]
    rec.add("A golden backfill and processing: requested | verified | coverage | accepted records | records per second (09 vs expected.json vs the hand answer 3, 2, 0.666667, 8, 0.666667)",
            f"{bp['requested_partitions']}|{bp['verified_partitions']}|{fmt(bp['coverage'])}|{bp['accepted_records']}|{fmt(bp['records_per_second'])}",
            f"{eb['requested_partitions']}|{eb['verified_partitions']}|{eb['coverage']}|{ep['accepted_records']}|{ep['records_per_second']}", "3|2|0.666667|8|0.666667")

    # ---- B: the loaded snapshot -----------------------------------------------------------------------------------------------------------------------
    inputs_dom = {**inputs}
    dom: dict[str, object] = {AS_OF: run_pipeline(inputs_dom), EARLIER: run_pipeline({**inputs_dom, "cutoff": EARLIER, "as_of": EARLIER})}
    d0 = dom[AS_OF]
    cnt, rcn = scalar["counts"], manifest["row_counts"]
    want = {k: rcn[k] for k in ("source_contracts", "source_expectations", "ingestion_batches", "raw_records", "quarantine_records", "checkpoints", "model_definitions", "pipeline_runs", "task_runs",
                                 "quality_results", "publications", "incidents", "backfill_requests", "fetch_log")}
    got = {**{k: cnt[k] for k in want if k != "backfill_requests"}, "backfill_requests": cnt["backfill_requests"] + scalar["rejected_backfills"]}
    rec.add("B loaded row counts equal the manifest row_counts (14 entities; backfill_requests = 13 loaded + 2 kept refused)", digest(sorted(got.items())), digest(sorted(want.items())))
    rec.add("B artifact tables: batch summaries | model output totals equal the manifest row_counts", f"{cnt['artifact_batch_summaries']}|{cnt['artifact_model_output_totals']}", f"{rcn['batch_summaries']}|{rcn['model_output_totals']}")
    rec.add("B dataset hash: recomputed from the sixteen entity files | the manifest | dataset_versions | the hash this package cites", ps.dataset_hash(), manifest["dataset_hash"], scalar["version_hash"]["dataset_hash"], DATASET_HASH)
    rec.add("B dataset version | contract version (loaded vs the manifest)", f"{scalar['version_hash']['dataset_version']}|1", f"{manifest['dataset_version']}|{manifest['contract_version']}")
    rec.add("B scope: the loaded raw_records are the 2,000-row sample of 62 batches (sample rows | sampled batches | sampled batches with rows vs manifest.sample)",
            f"{R['10_sample_scope_reconciliation__scope_total'][0]['sample_rows']}|{R['10_sample_scope_reconciliation__scope_total'][0]['sampled_batches']}|{R['10_sample_scope_reconciliation__scope_total'][0]['sampled_batches_with_rows']}",
            f"{manifest['sample']['raw_records_published']}|{manifest['sample']['batches_sampled']}|50", f"{cnt['raw_records']}|62|50")
    # The reference SQL does not model delete events (README "Not implemented", D-06): it reads the 10 rows of the sample whose payload carries an op other than upsert (1 delete of an
    # accepted key, 6 deletes of keys the sample never accepted, 3 unknown ops) as ordinary rows. So three metric keys are compared exactly only where no delete event is involved, and
    # the difference on the others is asserted to be EXACTLY what those rows explain.
    KNOWN_GAP = {"ingestion", "publications", "reconciliation"}
    for as_of in (AS_OF, EARLIER):
        for k in METRIC_KEYS:
            if k in KNOWN_GAP and digest(ref[as_of][k]) != digest(dom[as_of].metrics[k]):
                continue
            rec.add(f"B reference SQL equals the Python domain over the sample on {k} at {as_of} (digest)", digest(ref[as_of][k]), digest(dom[as_of].metrics[k]))
    with psycopg.connect(snap_url, row_factory=dict_row, autocommit=True, options="-c timezone=UTC") as c:
        for as_of in (AS_OF, EARLIER):
            op = c.execute("""SELECT count(*) FILTER (WHERE r.disposition = 'deleted') AS deleted,
                                     count(*) FILTER (WHERE EXISTS (SELECT 1 FROM raw_records o JOIN checkpoints ko ON ko.batch_id = o.batch_id
                                                       WHERE o.disposition = 'accepted' AND o.source_key = r.source_key AND ko.source_id = ck.source_id
                                                         AND (ko.version_number, o.raw_record_id COLLATE "C") < (ck.version_number, r.raw_record_id COLLATE "C"))) AS on_accepted_keys
                              FROM raw_records r JOIN checkpoints ck ON ck.batch_id = r.batch_id
                              WHERE r.payload_json ->> 'op' IS NOT NULL AND r.payload_json ->> 'op' <> 'upsert' AND ck.committed_at < %(cutoff)s::timestamptz""", {"cutoff": as_of}).fetchone()
            ri, di = ref[as_of]["ingestion"]["overall"], dom[as_of].metrics["ingestion"]["overall"]
            rec.add(f"B known gap at {as_of}: the reference SQL does not model delete events; its difference from the domain over the sample is exactly what the sample's op rows explain "
                    f"(op rows on a key already accepted are duplicates to it, the deleted ones leave the domain's deleted class: duplicate + those rows | quarantined - (those rows - deleted rows) | received and accepted equal)",
                    f"{ri['duplicate'] - di['duplicate']}|{ri['quarantined'] - di['quarantined']}|{ri['received'] - di['received']}|{ri['accepted_unique'] - di['accepted_unique']}",
                    f"{op['on_accepted_keys']}|{-(op['on_accepted_keys'] - op['deleted'])}|0|0")
    delete_batches = {pid for pid, p in dom[AS_OF].metrics["publications"]["publications"].items() if "b-1022" in p["included_batches"]}
    differing = sorted(pid for pid in dom[AS_OF].metrics["publications"]["publications"] if digest(dom[AS_OF].metrics["publications"]["publications"][pid]) != digest(ref[AS_OF]["publications"]["publications"][pid]))
    rec.add("B known gap: the publications and reconciliation entries that differ between the reference SQL and the domain are exactly those that include b-1022, the batch of the one delete the sample propagates (publications | reconciliation)",
            f"{','.join(differing)}|{','.join(sorted(pid for pid in dom[AS_OF].metrics['reconciliation'] if digest(dom[AS_OF].metrics['reconciliation'][pid]) != digest(ref[AS_OF]['reconciliation'][pid])))}",
            f"{','.join(sorted(delete_batches))}|{','.join(sorted(delete_batches))}")
    ov = d0.metrics["ingestion"]["overall"]
    s3 = R["10_sample_scope_reconciliation__rates_by_scope"][2]
    rec.add("B sample scope: the domain over the sample | investigation 10 | the manifest: received | accepted | duplicate | quarantined | rejection rate | duplicate rate",
            "|".join(fmt(s3[k]) for k in ("received", "accepted_unique", "duplicate", "quarantined", "rejection_rate", "duplicate_rate")),
            "|".join(fmt(ov[k]) for k in ("received", "accepted_unique", "duplicate", "quarantined", "rejection_rate", "duplicate_rate")),
            "|".join(fmt(manifest["sample"]["published_world"]["ingestion_overall"][k]) for k in ("received", "accepted_unique", "duplicate", "quarantined", "rejection_rate", "duplicate_rate")))
    for r in R["10_sample_scope_reconciliation__classes_by_source"]:
        ds = d0.metrics["ingestion"]["sources"][r["source_id"]]
        rec.add(f"B sample classification {r['source_id']}: accepted | duplicate | quarantined (investigation 10 vs the domain over the sample)", f"{r['sample_accepted']}|{r['sample_duplicate']}|{r['sample_quarantined']}",
                f"{ds['accepted_unique']}|{ds['duplicate']}|{ds['quarantined']}")
    for r in R["04_freshness_vs_ingestion_age__ingestion_age"]:
        f = d0.metrics["freshness"][r["source_id"]]
        rc_ = manifest["stats"]["freshness_at_as_of"][r["source_id"]]
        rec.add(f"B ingestion age {r['source_id']}: last successful ingestion | seconds (04 from the checkpoints vs the domain vs the manifest's record; complete world)",
                f"{r['last_successful_ingestion_at']}|{r['ingestion_age_seconds']}", f"{f['last_successful_ingestion_at']}|{f['ingestion_age_seconds']}", f"{rc_['last_successful_ingestion_at']}|{rc_['ingestion_age_seconds']}")
    for r in R["10_sample_scope_reconciliation__freshness_on_the_sample"]:
        f = d0.metrics["freshness"][r["source_id"]]
        rec.add(f"B freshness over the sample {r['source_id']}: latest event | seconds (10 vs the domain over the sample; SAMPLE scope, not the pipeline's freshness)", f"{r['sample_latest_accepted_event_at']}|{r['sample_freshness_seconds']}",
                f"{f['latest_accepted_event_at']}|{f['freshness_seconds']}")
    pr = R["10_sample_scope_reconciliation__processing_batch"][0]
    pw = manifest["stats"]["processing_rate"]
    rec.add("B processing rate: the world (101 accepted, recorded) | the sample (102, the domain over the sample): records per second (10 vs the manifest vs the domain)",
            f"{pr['world_accepted']}|{fmt(pr['world_records_per_second'])}|{pr['sample_accepted']}|{fmt(pr['sample_records_per_second'])}", f"{pw['accepted_records']}|{pw['records_per_second']}|{d0.metrics['processing_rate']['accepted_records']}|{d0.metrics['processing_rate']['records_per_second']}")
    pubs = d0.metrics["publications"]["publications"]
    pv = R["10_sample_scope_reconciliation__publications"][0]
    rec.add("B publications: content-hash checks that pass over the sample (the domain) | publications verifiable from the sample (10) | the manifest's recorded count over the complete world",
            f"{sum(1 for p in pubs.values() if p['content_hash_ok'])}|{manifest['stats']['publications']['content_hash_ok']}", f"{pv['verifiable_from_the_sample']}|{pv['publications']}", f"0|{len(pubs)}")
    rec.add("B late events: reference SQL | domain over the sample (SAMPLE scope; the recorded complete-world count is 757 and is not recomputable)", ref[AS_OF]["late_events"]["count"], d0.metrics["late_events"]["count"], 141)
    qg0 = d0.metrics["quality_gate"]
    reached = {r: v for r, v in qg0.items() if v["results"]}
    fn = R["02_run_funnel_by_failure_kind__funnel"][0]
    q = manifest["stats"]["quality_gate"]
    rec.add("B run funnel: runs | reached the gate | allowed | blocked at the gate | failed before it (02 vs the domain's gate results vs the manifest's computed funnel)",
            f"{fn['runs']}|{fn['reached_gate']}|{fn['allowed']}|{fn['blocked_at_gate']}|{fn['failed_before_gate']}",
            f"{len(qg0)}|{len(reached)}|{sum(v['decision'] == 'allowed' for v in reached.values())}|{sum(v['decision'] == 'blocked' for v in reached.values())}|{len(qg0) - len(reached)}",
            f"{q['runs']}|{q['reached_gate']}|{q['allowed']}|{q['blocked_at_gate']}|{q['failed_before_gate']}", "1343|1328|1318|10|15")
    phd = d0.metrics["publications"]["pointer_history"]
    um = R["05_publication_pointer_and_blocked_runs__unmoved_runs"]
    rec.add("B pointer history: the 25 runs that never moved it and the publication it stayed on (05 vs the domain's pointer_history, digest)", digest([(r["run_id"], r["pointer_after"]) for r in um]),
            digest([(h["run_id"], h["pointer_after"]) for h in phd if d0.metrics["runs"]["runs"][h["run_id"]]["status"] == "failed"]))
    rec.add("B pointer history: the domain calls 25 runs blocked (10 at the gate + 15 that never reached it: a run with no critical result is not allowed); the funnel separates them (domain 'blocked' | 05 stages)",
            f"{sum(h['gate_decision'] == 'blocked' for h in phd)}|{sum(h['gate_decision'] == 'allowed' for h in phd)}", f"{sum(r['stage'] in ('blocked_at_gate', 'failed_before_gate') for r in um)}|{fn['published']}", "25|1318")
    rec.add("B pointer: the loaded pointer | the latest publication | the domain's current publication | the manifest", R["05_publication_pointer_and_blocked_runs__summary"][0]["pointer"], scalar["pointer"],
            d0.metrics["publications"]["current_publication_id"], manifest["stats"]["publications"]["current_publication_id"])
    ro_ = d0.metrics["runs"]["overall"]
    to = R["03_task_vs_attempt_success__overall"][0]
    mr = manifest["stats"]["runs"]["overall"]
    rec.add("B tasks against attempts: terminal | successful | task success | attempts | successful | attempt success (03 vs the domain vs the manifest)",
            "|".join(fmt(to[k]) for k in ("tasks_terminal", "tasks_successful", "task_success_rate", "attempts", "attempts_successful", "attempt_success_rate")),
            "|".join(fmt(ro_[k]) for k in ("tasks_terminal", "tasks_successful", "task_success_rate", "attempts", "attempts_successful", "attempt_success_rate")),
            "|".join(fmt(mr[k]) for k in ("tasks_terminal", "tasks_successful", "task_success_rate", "attempts", "attempts_successful", "attempt_success_rate")))
    du = R["02_run_funnel_by_failure_kind__durations"]
    mdur = manifest["stats"]["runs"]
    rec.add("B run durations: failed runs | mean minutes | successful runs | mean minutes (02 vs the domain vs the manifest)", f"{du[0]['runs']}|{fmt(du[0]['mean_minutes'])}|{du[1]['runs']}|{fmt(du[1]['mean_minutes'])}",
            f"{d0.metrics['runs']['durations']['failed']['count']}|{d0.metrics['runs']['durations']['failed']['mean_minutes']}|{d0.metrics['runs']['durations']['successful']['count']}|{d0.metrics['runs']['durations']['successful']['mean_minutes']}",
            f"{mdur['failed']['count']}|{mdur['failed']['mean_minutes']}|{mdur['successful']['count']}|{mdur['successful']['mean_minutes']}")
    inc_dom = d0.metrics["incidents"]["incidents"]
    inc_sql = R["06_incidents_and_verified_recovery__incidents"]
    rec.add("B incidents: recovery run | verified instant | seconds | minutes for all 25 (06 vs the domain, digest)", digest([(i["incident_id"], i["recovery_run_id"], i["verified_at"], i["recovery_seconds"], fmt(i["recovery_minutes"])) for i in inc_sql]),
            digest([(k, v["recovery_run_id"], v["verified_at"], v["recovery_seconds"], v["recovery_minutes"]) for k, v in sorted(inc_dom.items())]))
    sm = R["06_incidents_and_verified_recovery__summary"][0]
    mi = manifest["stats"]["incidents"]
    di = d0.metrics["incidents"]
    rec.add("B incident summary: total | open | closed | verified | mean recovery minutes (06 vs the domain vs the manifest)", f"{sm['incidents']}|{sm['open']}|{sm['closed']}|{sm['verified']}|{fmt(sm['mean_recovery_minutes'])}",
            f"{di['total']}|{di['open']}|{di['closed']}|{di['verified']}|{di['mean_recovery_minutes']}", f"{mi['total']}|{mi['open']}|{mi['closed']}|{mi['verified']}|{mi['mean_recovery_minutes']}")
    rec.add("B incidents by failure kind (06 vs the manifest's by_type)", digest({r["failure_kind"]: r["incidents"] for r in R["06_incidents_and_verified_recovery__by_failure_kind"]}), digest(mi["by_type"]))
    rec.add("B every closure consistent: closed at the verified instant by the first verified run (06 vs the domain vs the manifest)", sm["closures_consistent"], sum(v["closure_consistent"] for v in inc_dom.values()), 25 if mi["all_closures_consistent"] else 0)
    cs = R["07_backfill_coverage_and_refused_overlaps__coverage_summary"][0]
    bd = d0.metrics["backfills"]
    mb = manifest["stats"]["backfills"]
    rec.add("B backfill coverage: requested | verified | coverage | refused requests | refused partitions (07 vs the domain vs the manifest)", f"{cs['requested_partitions']}|{cs['verified_partitions']}|{fmt(cs['coverage'])}|{cs['refused_requests']}|{cs['refused_partitions']}",
            f"{bd['overall']['requested_partitions']}|{bd['overall']['verified_partitions']}|{bd['overall']['coverage']}|{len(bd['refused'])}|{mb['refused_partitions']}",
            f"{mb['overall']['requested_partitions']}|{mb['overall']['verified_partitions']}|{mb['overall']['coverage']}|{mb['refused_requests']}|{mb['refused_partitions']}")
    rq = {r["backfill_id"]: r for r in R["07_backfill_coverage_and_refused_overlaps__requests"] if r["outcome"] == "accepted"}
    rec.add("B backfill requests: source | requested | verified | coverage for all 13 accepted (07 vs the domain vs the manifest, digest)", digest([(k, v["source_id"], v["requested_partitions"], v["verified_partitions"], fmt(v["coverage"])) for k, v in sorted(rq.items())]),
            digest([(k, v["source_id"], v["requested_partitions"], v["verified_partitions"], v["coverage"]) for k, v in sorted(bd["requests"].items())]),
            digest([(k, v["source_id"], v["requested_partitions"], v["verified_partitions"], v["coverage"]) for k, v in sorted(mb["requests"].items())]))
    rec.add("B refused requests: ids (07 vs the domain vs the manifest)", ",".join(r["refused_request"] for r in R["07_backfill_coverage_and_refused_overlaps__refused_overlaps"]), ",".join(bd["refused"]), ",".join(mb["refused"]))
    ing = {r["source_id"]: r for r in R["01_ingestion_by_source__by_source"]}
    dq = {r["source_id"]: r for r in R["01_ingestion_by_source__quarantine_distinct_keys"]}
    mis = manifest["stats"]["ingestion"]["sources"]
    ver = {r["source_id"]: r["checkpoint_version"] for r in R["04_freshness_vs_ingestion_age__ingestion_age"]}
    for s in sorted(ing):
        e = mis[s]
        rec.add(f"B ingestion {s} (complete world): received | accepted | duplicate | quarantined | distinct keys | rejection rate | duplicate rate | checkpoint version (01 and 04 vs the manifest's record)",
                "|".join(fmt(ing[s][k]) for k in ("received", "accepted_unique", "duplicate", "quarantined")) + f"|{dq[s]['distinct_keys']}|{fmt(ing[s]['rejection_rate'])}|{fmt(ing[s]['duplicate_rate'])}|{ver[s]}",
                "|".join(fmt(e[k]) for k in ("received", "accepted_unique", "duplicate", "quarantined", "quarantined_distinct_keys", "rejection_rate", "duplicate_rate", "checkpoint_version")))
    o = R["01_ingestion_by_source__overall"][0]
    mo = manifest["stats"]["ingestion"]["overall"]
    rec.add("B ingestion overall (complete world): received | accepted | duplicate | quarantined | rejection rate | duplicate rate (01 vs the manifest); 123 delete events beside them", "|".join(fmt(o[k]) for k in ("received", "accepted_unique", "duplicate", "quarantined", "rejection_rate", "duplicate_rate")) + f"|{o['deleted']}",
            "|".join(fmt(mo[k]) for k in ("received", "accepted_unique", "duplicate", "quarantined", "rejection_rate", "duplicate_rate")) + "|123")
    qr = {r["reason_code"]: r for r in R["01_ingestion_by_source__quarantine_by_reason"]}
    rec.add("B quarantine by reason inside the committed batches (01 vs the manifest)", digest({k: v["in_committed_batches"] for k, v in qr.items() if v["in_committed_batches"]}), digest(manifest["stats"]["quarantine_by_reason_committed_batches"]))
    rec.add("B all quarantine rows by reason, the schema-quarantined batch included (01 vs the manifest)", digest({k: v["all_rows"] for k, v in qr.items()}), digest(manifest["stats"]["quarantine_rows_by_reason"]))
    rec.add("B quarantine scope: rows listed separately | rows in all (01 vs the manifest)", f"{qr['SCHEMA_CHANGED']['in_schema_quarantined_batch']}|{sum(v['all_rows'] for v in qr.values())}", f"{manifest['stats']['quarantine_scope']['rows_listed_separately']}|{manifest['row_counts']['quarantine_records']}")
    kb = {r["kind"]: r["batches"] for r in R["01_ingestion_by_source__by_batch_kind"]}
    rec.add("B batches by kind (01 vs the manifest)", digest(kb), digest(manifest["stats"]["batches_by_kind"]))
    cm = {r["source_id"]: r for r in R["04_freshness_vs_ingestion_age__completeness"]}
    rec.add("B completeness per source: partitions | expected | accepted | value (04 vs the manifest)", digest([(s, r["partitions"], r["expected_records"], r["accepted_records"], fmt(r["completeness"])) for s, r in sorted(cm.items())]),
            digest([(s, v["partitions"], v["expected_records"], v["accepted_records"], v["value"]) for s, v in sorted(manifest["stats"]["completeness_by_source"].items())]))
    fv = {r["source_id"]: r for r in R["04_freshness_vs_ingestion_age__freshness_vs_age"]}
    rec.add("B freshness and ingestion age per source from the recorded instants (04 vs the manifest's recorded seconds)", digest([(s, r["freshness_seconds"], r["ingestion_age_seconds"]) for s, r in sorted(fv.items())]),
            digest([(s, v["freshness_seconds"], v["ingestion_age_seconds"]) for s, v in sorted(manifest["stats"]["freshness_at_as_of"].items())]))
    rec.add("B publications: count | first published | last published | the pointer (05 vs the manifest)",
            f"{R['05_publication_pointer_and_blocked_runs__summary'][0]['publications']}|{R['05_publication_pointer_and_blocked_runs__summary'][0]['first_published_at']}|{R['05_publication_pointer_and_blocked_runs__summary'][0]['last_published_at']}|{scalar['pointer']}",
            f"{manifest['stats']['publications']['count']}|{manifest['stats']['publications']['first_published_at']}|{manifest['stats']['publications']['last_published_at']}|{manifest['stats']['publications']['current_publication_id']}")
    rs = R["08_fetch_log_retry_after__retry_summary"][0]
    mr_ = manifest["stats"]["retry"]
    st = {r["status"]: r["fetches"] for r in R["08_fetch_log_retry_after__statuses"]}
    rec.add("B fetch log: statuses | rows (08 vs the manifest)", f"{canon(st)}|{sum(st.values())}", f"{canon(mr_['fetch_log_statuses'])}|{mr_['fetch_rows']}")
    rec.add("B retry-after: responses | retries | honouring | too soon | min slack | max slack | sessions | source (08 vs the manifest)",
            "|".join(fmt(rs[k]) for k in ("rate_limited_responses", "retries", "retries_honouring_retry_after", "retries_too_soon", "min_slack_seconds", "max_slack_seconds", "sessions_rate_limited", "source_id")),
            "|".join(fmt(mr_[k]) for k in ("rate_limited_responses", "retries", "retries_honouring_retry_after", "retries_too_soon", "min_slack_seconds", "max_slack_seconds", "sessions_rate_limited", "source_id")))

    # ---- C: every result set against the independent Python side ----------------------------------------------------------------------------------------
    P = ps.results()
    for key in sorted(P):
        rec.add(f"C {key}: SQL result set equals the plain-Python recomputation cell by cell ({len(P[key])} rows, digest)", digest(ps.normalised(R[key])), digest(ps.normalised(P[key])))
    rec.add("C the SQL result sets of investigations 01..08 and 10 are exactly the sets python_side.py returns", len([k for k in R if not k.startswith("09_")]), len(P))

    # ---- D: designed relationships, injected defects, manifest statistics ---------------------------------------------------------------------------------
    dr = {d["id"]: d["realised"] for d in manifest["designed_relationships"]}
    ss = R["04_freshness_vs_ingestion_age__silent_source"][0]
    fr = fv["src-refunds"]
    r1 = dr["DR-01"]
    rec.add("D DR-01 a source stale for three days while its jobs stay green (complete world; freshness recorded): runs | succeeded | allowed by the gate | batches in the window | with no accepted record | accepted | duplicates | freshness | ingestion age (04 vs the manifest)",
            "|".join(fmt(x) for x in (ss["runs_since"], ss["runs_succeeded"], ss["runs_allowed_by_the_gate"], ss["committed_batches_since"], ss["batches_with_no_accepted_record"], ss["accepted_since"], ss["duplicates_since"], fr["freshness_seconds"], fr["ingestion_age_seconds"])),
            "|".join(fmt(x) for x in (r1["runs_in_window"], r1["runs_succeeded"], r1["runs_allowed_by_the_gate"], r1["committed_batches_in_window"], r1["batches_with_no_accepted_record"], r1["accepted_in_window"], r1["duplicates_in_window"], r1["freshness_seconds"], r1["ingestion_age_seconds"])))
    rec.add("D DR-01 the gate cannot see it: the 7-day target against the silence, freshness checks passed in every silent run, silent source | over target (04 vs the manifest parameters)",
            f"{fr['freshness_target_seconds']}|{ss['freshness_checks_passed']}|{ss['source_id']}|{fmt(fr['over_target'])}", f"{manifest['designed_relationships'][0]['parameters']['freshness_target_seconds']}|{r1['runs_in_window']}|src-refunds|false")
    sp = R["04_freshness_vs_ingestion_age__silent_partitions"]
    rec.add("D DR-01 the three empty days: the partitions the silent source was expected to fill (04) against the days the generator records at completeness 0.000000", ",".join(p["partition"] for p in sp), ",".join(sorted(r1["completeness"])))
    r2 = dr["DR-02"]
    d2 = R["05_publication_pointer_and_blocked_runs__designed_blocked_run"][0]
    ic = {i["incident_id"]: i for i in inc_sql}[r2["incident_id"]]
    rec.add("D DR-02 a failed run that never replaces the publication: run | decision | pointer before | after | publication exists | critical failures | incident | recovery run | recovery minutes | history index (05 and 06 vs the manifest)",
            f"{d2['run_id']}|{d2['gate_decision']}|{d2['pointer_before']}|{d2['pointer_after']}|{fmt(d2['publication_exists'])}|{d2['relationships_failed']}|{d2['incident_id']}|{d2['recovery_run_id']}|{fmt(ic['recovery_minutes'])}|{scalar['runs_before_dr02']}",
            f"{r2['run_id']}|{r2['gate_decision']}|{r2['pointer_before']}|{r2['pointer_after']}|{fmt(r2['publication_exists'])}|{r2['critical_failures']}|{r2['incident_id']}|{r2['recovery_run_id']}|{r2['recovery_minutes']}|{r2['pointer_history_index']}")
    r3 = dr["DR-03"]
    rec.add("D DR-03 a rate-limited source whose retries honour retry-after (04.. 08 vs the manifest): rate limited | retries | honouring | too soon | min slack | max slack | sessions | loops | rows",
            "|".join(fmt(x) for x in (rs["rate_limited_responses"], rs["retries"], rs["retries_honouring_retry_after"], rs["retries_too_soon"], rs["min_slack_seconds"], rs["max_slack_seconds"], rs["sessions_rate_limited"], st["cursor_loop"], sum(st.values()))),
            "|".join(fmt(x) for x in (r3["rate_limited_responses"], r3["retries"], r3["retries_honouring_retry_after"], r3["retries_too_soon"], r3["min_slack_seconds"], r3["max_slack_seconds"], r3["sessions_rate_limited"], r3["cursor_loops"], r3["fetch_rows"])))
    rec.add("D DR-03 the retry-after hints used (30, 60, 90, 120 s) and every hint honoured (08 vs the manifest parameters)", ",".join(f"{r['retry_after_seconds']}:{r['honoured']}/{r['responses']}" for r in R["08_fetch_log_retry_after__retry_by_hint"]),
            ",".join(f"{h}:{n}/{n}" for h, n in zip(manifest["designed_relationships"][2]["parameters"]["retry_after_choices_seconds"], [16, 9, 13, 11])))
    r4 = dr["DR-04"]
    rec.add("D DR-04 late events behind the watermark (RECORDED; not recomputable from the published files): the causes sum to the count, all included in the next publication, none lost",
            f"{sum(r4['by_cause'].values())}|{r4['included_in_next_publication']}|{r4['lost']}|{manifest['stats']['late_events']['count']}", f"{r4['late_events_in_all']}|{r4['late_events_in_all']}|0|757")
    r5 = dr["DR-05"]
    rcn_ = R["06_incidents_and_verified_recovery__residual_candidate"][0]
    cand = r5["candidates_with_nonzero_residual"][0]
    rec.add("D DR-05 every publication reconciles to 0.00 but one candidate: run | day | source total | exclusions | stored candidate total | residual | incident | recovery minutes (06 vs the manifest)",
            f"{rcn_['run_id']}|{rcn_['day']}|{fmt(rcn_['source_total'])}|{fmt(rcn_['exclusions_total'])}|{fmt(rcn_['stored_candidate_total'])}|{fmt(rcn_['residual'])}|{rcn_['incident_id']}|{fmt({i['incident_id']: i for i in inc_sql}[r5['incident_id']]['recovery_minutes'])}",
            f"{cand['run_id']}|{cand['day']}|{cand['source_total']}|{cand['exclusions_total']}|{cand['published_total']}|{cand['residual']}|{r5['incident_id']}|{r5['recovery_minutes']}")
    rec.add("D DR-05 candidates | publications (the loaded candidate totals and publications vs the manifest's recorded reconciliation)", f"{scalar['candidates']}|{cnt['publications']}",
            f"{manifest['stats']['reconciliation']['candidates']}|{manifest['stats']['reconciliation']['publications']}")
    inj = {x["id"]: x for x in json.loads((SNAP_DIR / "injection-manifest.json").read_text())["injections"]}
    cr = {r["aborted_batch"]: r for r in R["01_ingestion_by_source__crash_replay"]}
    ev = inj["INJ-01"]["evidence"]
    c0 = cr[ev["aborted_batch"]]
    rec.add("D INJ-01 crash after the data write, before the checkpoint (b-0596): rows written | checkpoints | replay batch | accepted by the replay | replay received | version step (01 vs the injection manifest)",
            f"{c0['aborted_rows']}|{c0['aborted_checkpoints']}|{c0['replay_batch']}|{c0['replay_accepted']}|{c0['replay_received']}|{c0['version_step']}", f"{ev['rows_written']}|0|{ev['replay_batch']}|{ev['accepted_by_the_replay']}|71|1")
    rec.add("D INJ-01 at scale: every one of the 8 aborted batches was replayed from the same cursor with the next checkpoint version and its rows classified exactly once (01)", f"{len(cr)}|{sum(r['rows_classified_once'] for r in cr.values())}|{sum(r['version_step'] == 1 for r in cr.values())}|{sum(r['aborted_checkpoints'] for r in cr.values())}", "8|8|8|0")
    ref_ = R["07_backfill_coverage_and_refused_overlaps__refused_overlaps"]
    rec.add("D INJ-02 overlapping backfills: refused ids | accepted | rejected (07 vs the injection manifest)", f"{','.join(r['refused_request'] for r in ref_)}|{cs['accepted_requests']}|{cs['refused_requests']}", "bf-006,bf-012|13|2")
    rec.add("D INJ-02 each refusal overlapped a request still running: the overlapped ids and the partitions shared (07 vs the manifest's statement: bf-006 over bf-004, bf-012 over bf-010)", ",".join(f"{r['refused_request']}>{r['overlapped_request']}:{r['shared_partitions']}" for r in ref_), "bf-006>bf-004:1,bf-012>bf-010:1")
    sq = R["01_ingestion_by_source__schema_quarantined"]
    rec.add("D INJ-04 an unexpected required field: b-0847 status | rows written | refused rows | checkpoints; b-0848 accepted (01 vs the injection manifest)", f"{sq[0]['status']}|{sq[0]['written_rows']}|{sq[0]['schema_changed_rows']}|{sq[0]['checkpoints']}|{R['01_ingestion_by_source__crash_replay'] and next(b for b in bi['fact_batch'] if b['batch_id'] == 'b-0848')['accepted_unique']}", "quarantined|17|17|0|15")
    rec.add("D INJ-05 a malformed row that would vanish: the keyless row of b-0405 has a quarantine row (01 and the loaded rows vs the injection manifest)", f"{scalar['q_b0405'][0]['quarantine_id']}|{scalar['q_b0405'][0]['reason_code']}|{dq['src-orders']['rows_without_key']}", "q-b-0405-02|MISSING_FIELD|1")
    rec.add("D INJ-06 a green job on a stale source: freshness at least 259,200 s | ingestion age at most 21,600 s (04 vs the injection manifest bounds)", f"{fr['freshness_seconds'] >= 259200}|{fr['ingestion_age_seconds'] <= 21600}", "True|True")
    rec.add("D INJ-07 a failed run that would replace a publication: decision | critical failures | pointer after | publication of the run exists (05 vs the injection manifest)",
            f"{d2['gate_decision']}|{d2['relationships_failed']}|{d2['pointer_after']}|{fmt(d2['publication_exists'])}", "blocked|1|pub-1186|false")
    cl = R["08_fetch_log_retry_after__cursor_loop"][0]
    ev10 = inj["INJ-10"]["evidence"]
    rec.add("D INJ-10 a pagination token that repeats: fetch row | session | detected at | no batch created (08 vs the injection manifest)", f"{cl['loop_fetch']}|{cl['session_id']}|{cl['loop_detected_at']}|{fmt(cl['no_batch_created'])}", f"{ev10['fetch_log_row']}|{ev10['session_id']}|{ev10['fetched_at']}|true")
    rec.add("D INJ-03 retries that ignore retry-after: the recorded retries (08 vs the injection manifest's recorded_retries)", digest({k: rs[k] for k in ("rate_limited_responses", "retries", "retries_honouring_retry_after", "retries_too_soon")}),
            digest({k: inj["INJ-03"]["evidence"]["recorded_retries"][k] for k in ("rate_limited_responses", "retries", "retries_honouring_retry_after", "retries_too_soon")}))
    rv_ = {r["status"]: r for r in R["08_fetch_log_retry_after__refetch_check"]}
    rec.add("D R8-06 a refetch is not a loop: refetch rows whose cursor another session served or that re-poll the last committed cursor | refetch rows repeating inside their session | loop rows repeating inside theirs (08)",
            f"{rv_['refetch']['refetch_conditions_met']}|{rv_['refetch']['repeats_inside_its_session']}|{rv_['cursor_loop']['repeats_inside_its_session']}", "48|0|1")
    rec.add("D R8-07 the funnel is stated: 1,343 / 1,328 / 1,318 / 10 / 15 and the failure kinds sum to the failed runs (02)", f"{fn['runs']}/{fn['reached_gate']}/{fn['allowed']}/{fn['blocked_at_gate']}/{fn['failed_before_gate']}|{sum(r['runs'] for r in R['02_run_funnel_by_failure_kind__by_failure_kind'])}", "1343/1328/1318/10/15|25")
    rec.add("D R8-10 the quarantined count and rate are 'in committed batches'; the 17 schema-quarantined rows are listed separately and sit in no rate (01: 429 + 17 = 446 quarantine rows)", f"{o['quarantined']}|{qr['SCHEMA_CHANGED']['all_rows']}|{o['quarantined'] + qr['SCHEMA_CHANGED']['all_rows']}|{fmt(o['rejection_rate'])}", "429|17|446|0.010752")
    rec.add("D R8-11 backfill coverage is stated: 11 of 15 partitions of the 13 accepted requests (0.733333); 2 requests for 4 partitions refused (07 vs the manifest statement)", f"{cs['verified_partitions']} of {cs['requested_partitions']} partitions of the {cs['accepted_requests']} accepted requests ({fmt(cs['coverage'])}); {cs['refused_requests']} requests for {cs['refused_partitions']} partitions refused for overlap",
            mb["statement"])

    # ---- E: the BI package ------------------------------------------------------------------------------------------------------------------------------
    csvs = {k: [{c_: fmt(v) for c_, v in r.items()} for r in rows] for k, rows in bi.items()}
    rm = manifest["stats"]["reconciliation"]
    meas_rows = bi_measures(csvs, {"late_recorded": manifest["stats"]["late_events"]["count"], "late_causes": ", ".join(f"{k} {v}" for k, v in manifest["stats"]["late_events"]["by_cause"].items()),
                                   "late_sample": d0.metrics["late_events"]["count"], "recon_publications": rm["publications"], "recon_publications_nonzero": rm["residual_not_zero"],
                                   "recon_candidates": rm["candidates"], "recon_candidates_nonzero": rm["candidates_residual_not_zero"],
                                   "hash_recorded": manifest["stats"]["publications"]["content_hash_ok"], "hash_verifiable": pv["verifiable_from_the_sample"]})
    mv = {(m_["measure"], m_["slice"]): m_ for m_ in meas_rows}
    rec.add("E BI row counts: dim_source | dim_date | dim_failure_kind | dim_check | dim_scope | fact_batch | fact_run | fact_gate_check | fact_incident | fact_backfill_partition | fact_fetch | fact_freshness",
            "|".join(str(len(csvs[k])) for k in ("dim_source", "dim_date", "dim_failure_kind", "dim_check", "dim_scope", "fact_batch", "fact_run", "fact_gate_check", "fact_incident", "fact_backfill_partition", "fact_fetch", "fact_freshness")),
            f"{manifest['row_counts']['source_contracts']}|56|6|7|3|{manifest['row_counts']['ingestion_batches']}|{manifest['row_counts']['pipeline_runs']}|{manifest['row_counts']['quality_results']}|{manifest['row_counts']['incidents']}|19|{manifest['row_counts']['fetch_log']}|6")
    rec.add("E BI ingestion (all sources, complete world): received | accepted | duplicate | quarantined | deleted | rejection rate | duplicate rate (CSV facts vs 01 vs the manifest)",
            "|".join(mv[(k, "all")]["value"] for k in ("received", "accepted_unique", "duplicate", "quarantined", "deleted", "rejection_rate", "duplicate_rate")),
            "|".join(fmt(o[k]) for k in ("received", "accepted_unique", "duplicate", "quarantined", "deleted", "rejection_rate", "duplicate_rate")),
            "|".join(fmt(x) for x in (mo["received"], mo["accepted_unique"], mo["duplicate"], mo["quarantined"], 123, mo["rejection_rate"], mo["duplicate_rate"])))
    rec.add("E BI ingestion per source: rejection rate | duplicate rate for all six (CSV facts vs 01, digest)", digest([(s, mv[("rejection_rate", s)]["value"], mv[("duplicate_rate", s)]["value"]) for s in sorted(ing)]),
            digest([(s, fmt(ing[s]["rejection_rate"]), fmt(ing[s]["duplicate_rate"])) for s in sorted(ing)]))
    rec.add("E BI schema-quarantined rows listed apart (CSV facts vs 01 vs the manifest)", mv[("schema_quarantined_rows", "all")]["value"], qr["SCHEMA_CHANGED"]["in_schema_quarantined_batch"], manifest["stats"]["quarantine_scope"]["rows_listed_separately"])
    rec.add("E BI run funnel: runs | reached the gate | allowed | blocked at the gate | failed before it (CSV facts vs 02 vs the manifest)", "|".join(mv[(k, "all")]["value"] for k in ("runs", "reached_gate", "allowed", "blocked_at_gate", "failed_before_gate")),
            f"{fn['runs']}|{fn['reached_gate']}|{fn['allowed']}|{fn['blocked_at_gate']}|{fn['failed_before_gate']}", f"{q['runs']}|{q['reached_gate']}|{q['allowed']}|{q['blocked_at_gate']}|{q['failed_before_gate']}")
    rec.add("E BI failed runs by kind (CSV facts vs 02 vs the manifest's by_type)", digest({k.split(": ")[1]: int(v["value"]) for (m_, k), v in mv.items() if m_ == "failed_runs"}),
            digest({r["failure_kind"]: r["runs"] for r in R["02_run_funnel_by_failure_kind__by_failure_kind"]}), digest(mi["by_type"]))
    rec.add("E BI task success | attempt success (CSV facts vs 03 vs the domain vs the manifest)", f"{mv[('task_success_rate', 'all')]['value']}|{mv[('attempt_success_rate', 'all')]['value']}", f"{fmt(to['task_success_rate'])}|{fmt(to['attempt_success_rate'])}",
            f"{ro_['task_success_rate']}|{ro_['attempt_success_rate']}", f"{mr['task_success_rate']}|{mr['attempt_success_rate']}")
    rec.add("E BI ingestion age | freshness per source (CSV facts vs 04 vs the manifest's record, digest)", digest([(s, mv[("ingestion_age_seconds", s)]["value"], mv[("freshness_seconds", s)]["value"]) for s in sorted(fv)]),
            digest([(s, fmt(fv[s]["ingestion_age_seconds"]), fmt(fv[s]["freshness_seconds"])) for s in sorted(fv)]), digest([(s, fmt(v["ingestion_age_seconds"]), fmt(v["freshness_seconds"])) for s, v in sorted(manifest["stats"]["freshness_at_as_of"].items())]))
    rec.add("E BI silent sources | completeness per source (CSV facts vs 04 vs the manifest)", digest([mv[("silent_sources", "all")]["value"]] + [(s, mv[("completeness", s)]["value"]) for s in sorted(cm)]),
            digest([str(sum(1 for r in fv.values() if r["silent"]))] + [(s, fmt(cm[s]["completeness"])) for s in sorted(cm)]), digest([str(1)] + [(s, v["value"]) for s, v in sorted(manifest["stats"]["completeness_by_source"].items())]))
    rec.add("E BI incidents | mean recovery minutes | by kind (CSV facts vs 06 vs the domain vs the manifest)", f"{mv[('incidents', 'all')]['value']}|{mv[('mean_recovery_minutes', 'all')]['value']}|" + digest({k.split(": ")[1]: v["value"] for (m_, k), v in mv.items() if m_ == "mean_recovery_minutes" and k != "all"}),
            f"{sm['incidents']}|{fmt(sm['mean_recovery_minutes'])}|" + digest({r["failure_kind"]: fmt(r["mean_recovery_minutes"]) for r in R["06_incidents_and_verified_recovery__by_failure_kind"]}),
            f"{di['total']}|{di['mean_recovery_minutes']}|" + digest({r["failure_kind"]: fmt(r["mean_recovery_minutes"]) for r in R["06_incidents_and_verified_recovery__by_failure_kind"]}),
            f"{mi['total']}|{mi['mean_recovery_minutes']}|" + digest({r["failure_kind"]: fmt(r["mean_recovery_minutes"]) for r in R["06_incidents_and_verified_recovery__by_failure_kind"]}))
    rec.add("E BI backfill coverage | refused partitions (CSV facts vs 07 vs the domain vs the manifest)", f"{mv[('backfill_coverage', 'all')]['value']}|{mv[('refused_backfill_partitions', 'all')]['value']}", f"{fmt(cs['coverage'])}|{cs['refused_partitions']}",
            f"{bd['overall']['coverage']}|{mb['refused_partitions']}", f"{mb['overall']['coverage']}|{mb['refused_partitions']}")
    rec.add("E BI retries honoured | fetches by status (CSV facts vs 08 vs the manifest)", f"{mv[('retries_honoured', 'all')]['numerator']}/{mv[('retries_honoured', 'all')]['denominator']}|" + digest({k.split(': ')[1]: int(v['value']) for (m_, k), v in mv.items() if m_ == 'fetches'}),
            f"{rs['retries_honouring_retry_after']}/{rs['retries']}|" + digest(st), f"{mr_['retries_honouring_retry_after']}/{mr_['retries']}|" + digest(mr_["fetch_log_statuses"]))
    withheld = [m_ for m_ in meas_rows if m_["value"] == ""]
    rec.add("E BI nothing withheld silently: every measure row with an empty value carries a status other than 'value' (rows | empty values | empty values with a status)", f"{len(meas_rows)}|{len(withheld)}|{sum(1 for m_ in withheld if m_['status'] != 'value')}",
            f"{len(meas_rows)}|{len(withheld)}|{len(withheld)}")
    rec.add("E BI every measure carries a scope that dim_scope defines, and every measure is defined in dim_measure (rows with an unknown scope | with an unknown measure)",
            f"{sum(1 for m_ in meas_rows if m_['scope'] not in {s['scope'] for s in csvs['dim_scope']})}|{sum(1 for m_ in meas_rows if m_['measure'] not in {s['measure'] for s in csvs['dim_measure']})}", "0|0")

    # ---- results ---------------------------------------------------------------------------------------------------------------------------------------------
    equal = sum(1 for r in rec.rows if r["equal"])
    meta = {"dataset_hash": DATASET_HASH, "dataset_version": manifest["dataset_version"], "code_revision": CODE_REVISION, "contract_version": 1, "seed": manifest["generator"]["seed"], "as_of": AS_OF,
            "golden_dataset_hash": prep_g["dataset_hash"], "runs": manifest["row_counts"]["pipeline_runs"], "batches": manifest["row_counts"]["ingestion_batches"], "raw_rows_written": 40191,
            "sample_rows": manifest["sample"]["raw_records_published"], "reconciliation_rows": len(rec.rows), "reconciliation_equal": equal, "result_sets": len(R), "result_rows": sum(len(R[k]) for k in R)}
    for r in rec.rows:
        print(("OK   " if r["equal"] else "DIFF ") + r["check"] + (" | " + " | ".join(str(r[k]) for k in ("analysis_sql", "second_source", "third_source", "fourth_source") if r[k] != "") if not r["equal"] else ""))
    print(f"RESULT: {'OK' if rec.ok else 'FAILED'} ({len(rec.rows)} reconciliation rows, {equal} equal; {meta['result_sets']} result sets, {meta['result_rows']} rows)")
    if bi_out:
        for k, rows in csvs.items():
            export_csv(bi_out / f"{k}.csv", rows)
        export_csv(bi_out / "measures_recomputed.csv", meas_rows)
        print(f"wrote {len(csvs) + 1} CSV files to {bi_out}")
    if json_out:
        out = {"meta": [meta], **{k: ps.normalised(v) for k, v in R.items()}, "bi_measures": meas_rows, "bi_measures_headline": [m_ for m_ in meas_rows if m_["slice"] in ("all", "complete world", "2,000-row sample", "all publications")],
               "reconciliation": rec.rows}
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(out, indent=1, sort_keys=False) + "\n")
        print(f"wrote {json_out}")
    return 0 if rec.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
