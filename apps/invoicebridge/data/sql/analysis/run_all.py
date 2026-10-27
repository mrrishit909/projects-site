"""Run every analysis investigation and reconcile it with the independent sources (P05-ART-04).

Usage (from apps/invoicebridge):
  ../../.venv/bin/python data/sql/analysis/run_all.py [--json artifacts/analysis-results.json] [--bi-out artifacts/bi] [--keep]

With no environment variables it creates two scratch databases (artifacts05_run_snapshot, artifacts05_run_golden) on the local PostgreSQL
named by ARTIFACTS_ADMIN_URL (default: the repository's local development login, 127.0.0.1:5432), loads the published snapshot
``web/public/data`` and the golden fixture through ``data/migrate.py`` and ``data/seed.py`` (prepare_snapshot.py), runs everything and
drops them again (``--keep`` leaves them). To use databases you prepared yourself, set ARTIFACTS_DATABASE_URL and
ARTIFACTS_GOLDEN_DATABASE_URL (names must start with artifacts05_; the shared invoicebridge database is never touched).
It takes about eight minutes: the book is a recursive query and the SQL reference is run at three as-of instants.

What runs, in order (exit code 0 only if every query ran and every reconciliation row is equal):
  00_book.sql (the book per cutoff, recomputed from facts, into temporary tables), 01..08 on the snapshot (files hold several blocks marked
  ``-- @@ name``), 09 on the golden database, bi_dimensions.sql and bi_fact_*.sql on the snapshot (written as CSV with --bi-out).
Reconciliation (the rows printed at the end, ``reconciliation`` in the JSON):
  A  golden fixture: data/sql/reference_metrics.sql, the Python domain and tests/fixtures/golden/expected.json agree on all eleven metric
     keys; the per-invoice amounts, the duplicate identity and the quantities of 09 equal the hand calculation of expected.json;
  B  snapshot headline figures: the investigations vs data/sql/reference_metrics.sql vs the Python domain (units of quantity may be added across
     currencies; money is compared per currency and never summed across currencies);
  C  every result set cell by cell against python_side.py (the domain's book and exact arithmetic, no SQL);
  D  groups and cutoffs: per vendor and per currency against the domain's group_metrics; the March and June month-ends against the SQL
     reference and the domain at those instants;
  E  the injection manifest and the designed relationships against what the SQL finds, and the BI measures recomputed from the CSV facts
     against the reference and the domain.
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
from fractions import Fraction
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / "domain"), str(ROOT), str(HERE)]

import python_side as ps  # noqa: E402
from prepare_snapshot import DEFAULT_ADMIN_URL, create_database, drop_database, prepare, with_db  # noqa: E402
from invoicebridge import compute_metrics, run_pipeline  # noqa: E402
from invoicebridge.match import quantities  # noqa: E402
from invoicebridge.metrics import window_metrics  # noqa: E402
from invoicebridge.contract import METRIC_KEYS  # noqa: E402
from invoicebridge.timeutil import parse_ts  # noqa: E402

REFERENCE = ROOT / "data" / "sql" / "reference_metrics.sql"
GOLDEN_DIR = ROOT / "tests" / "fixtures" / "golden"
CODE_REVISION = "2dcc460"
DATASET_HASH = "1f001a43a7031d4260f5abb3b9f7a83f6e1b48397e85cf8b04e0b4d9e052162e"
RUN_SNAPSHOT_DB, RUN_GOLDEN_DB = "artifacts05_run_snapshot", "artifacts05_run_golden"
C1, C2, ASOF = ps.C1, ps.C2, ps.ASOF
QTY_KEYS = ("ordered_quantity", "net_received_quantity", "accepted_invoiced_quantity", "open_to_receive_quantity", "open_to_invoice_quantity",
            "received_not_invoiced_quantity")
CURRENCIES = ("EUR", "GBP", "USD")


def fmt(v) -> str:
    return ps.norm(v)


def digest(rows: list[dict]) -> str:
    return hashlib.sha256(json.dumps([{k: fmt(v) for k, v in r.items()} for r in rows], sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


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
    """Execute every block of a file that creates temporary tables (00_book.sql); nothing is fetched."""
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


def reference(conn, as_of: str, cutoffs: list[str]) -> dict:
    row = conn.execute(REFERENCE.read_text(), {"as_of": parse_ts(as_of), "cutoffs": [parse_ts(c) for c in cutoffs]}).fetchone()
    return dict(row)


def export_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        cols = list(rows[0])
        w.writerow(cols)
        for r in rows:
            w.writerow([fmt(r[c]) for c in cols])


# ---- BI measures from the exported facts (no database, no domain) ---------------------------------------------------------
def bi_measures(invoice: list[dict], po_line: list[dict], exception: list[dict], export_row: list[dict]) -> list[dict]:
    """The measures of docs/bi-package.md evaluated over the CSV facts at the as-of; money per currency (never summed across currencies)."""
    D = Decimal
    rows: list[dict] = []

    def add(measure: str, currency: str, value) -> None:
        rows.append({"measure": measure, "currency": currency, "value": fmt(value)})

    def r(num: Fraction, places: int) -> Decimal:
        return ps.rnd(num, places)
    good = [i for i in invoice if i["status_at_asof"] in ("matched", "approved", "exported", "adjusted")]
    oblig = [i for i in good if i["status_at_asof"] in ("approved", "exported", "adjusted")]
    book = [i for i in invoice if i["in_book"] == "1"]
    add("matched_invoices", "", len(good))
    add("obligations", "", len(oblig))
    for cur in CURRENCIES:
        g = [i for i in good if i["currency"] == cur]
        o = [i for i in oblig if i["currency"] == cur]
        ct = sum((D(i["credit_total"]) for i in o), D(0))
        ot = sum((D(i["total"]) for i in o), D(0))
        ex = sum((D(x["amount"]) for x in export_row if x["currency"] == cur), D(0))
        add("matched_invoices", cur, len(g))
        add("matched_total", cur, ps.rnd(sum((D(i["total"]) for i in g), D(0)), 2))
        add("obligations", cur, len(o))
        add("approved_total", cur, ps.rnd(ot, 2))
        add("credit_total", cur, ps.rnd(ct, 2))
        add("approved_payable", cur, ps.rnd(ot - ct, 2))
        add("accepted_export_total", cur, ps.rnd(ex, 2))
        add("export_difference", cur, ps.rnd(ex - ot, 2))
        add("received_not_invoiced_value", cur, ps.rnd(sum((max(D(p["net_received_quantity"]) - D(p["accepted_invoiced_quantity"]), D(0)) * D(p["unit_price"])
                                                           for p in po_line if p["currency"] == cur), D(0)), 2))
    open_ex = [e for e in exception if e["open_at_asof"] == "1"]
    for reason in ps.REASONS:
        add("open_exceptions", reason, sum(1 for e in open_ex if e["reason_code"] == reason))
    add("open_exceptions", "", len(open_ex))
    add("unowned_exceptions", "", sum(1 for e in open_ex if e["owner_at_asof"] == ""))
    n = len(book)
    flagged = sum(1 for i in book if i["open_reasons"] != "")
    ever = sum(1 for i in book if i["ever_excepted"] == "1")
    add("eligible_invoices", "", n)
    add("exception_rate", "", r(Fraction(flagged, n), 6))
    add("straight_through_rate", "", r(Fraction(n - flagged, n), 6))
    add("ever_excepted_rate", "", r(Fraction(ever, n), 6))
    add("never_excepted_rate", "", r(Fraction(n - ever, n), 6))
    appr = [i for i in invoice if i["approved"] == "1"]
    add("approved_invoices", "", len(appr))
    add("mean_minutes_to_approval", "", r(Fraction(sum(int(i["seconds_to_approval"]) for i in appr), 60 * len(appr)), 4))
    add("pending_invoices", "", n - sum(1 for i in book if i["approved"] == "1"))
    add("duplicates_merged", "", sum(1 for i in invoice if i["status_at_asof"] == "merged"))
    for k, f in (("ordered_quantity", lambda p: D(p["ordered_quantity"])), ("net_received_quantity", lambda p: D(p["net_received_quantity"])),
                 ("accepted_invoiced_quantity", lambda p: D(p["accepted_invoiced_quantity"])),
                 ("open_to_receive_quantity", lambda p: max(D(p["ordered_quantity"]) - D(p["net_received_quantity"]), D(0))),
                 ("open_to_invoice_quantity", lambda p: max(D(p["ordered_quantity"]) - D(p["accepted_invoiced_quantity"]), D(0))),
                 ("received_not_invoiced_quantity", lambda p: max(D(p["net_received_quantity"]) - D(p["accepted_invoiced_quantity"]), D(0)))):
        add(k, "", ps.rnd(sum((f(p) for p in po_line), D(0)), 4))
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
    print(f"snapshot prepared: {prep_s['inserted']}, exceptions {prep_s['exceptions_loaded']}, assignments {prep_s['assignments_loaded']}")
    print(f"golden prepared:   {prep_g['inserted']}")
    ctx = ps.load()
    mains = [ASOF]
    cuts = [C1, C2, ASOF]
    bi: dict[str, list[dict]] = {}
    with psycopg.connect(snap_url, row_factory=dict_row, autocommit=True, options="-c timezone=UTC") as c:
        run_script(c, HERE / "00_book.sql")
        print("book recomputed from facts (ib_run, ib_facts)")
        for f in sorted(HERE.glob("0[1-8]_*.sql")):
            R.update(run_file(c, f))
            print(f"ran {f.name}")
        for f in [HERE / "bi_dimensions.sql"] + sorted(HERE.glob("bi_fact_*.sql")):
            for k, rows in run_file(c, f).items():
                bi[k.split("__")[-1] if "__" in k else k[3:]] = rows
        print("ran the BI dimension and fact queries")
        ref_main = reference(c, ASOF, cuts)
        print("reference_metrics.sql at the as-of")
        ref_c1, ref_c2 = reference(c, C1, [C1]), reference(c, C2, [C2])
        print("reference_metrics.sql at the two month-ends")
    with psycopg.connect(gold_url, row_factory=dict_row, autocommit=True, options="-c timezone=UTC") as c:
        G = run_file(c, HERE / "09_golden_known_answer.sql")
        g_inputs = json.loads((GOLDEN_DIR / "inputs.json").read_text())
        ref_g = reference(c, g_inputs["as_of"], g_inputs["snapshot_cutoffs"])
    R.update(G)

    # ---- A: golden fixture -------------------------------------------------------------------------------------------------
    exp = json.loads((GOLDEN_DIR / "expected.json").read_text())
    dom_g = run_pipeline(g_inputs)
    canon = lambda v: json.dumps(v, sort_keys=True, separators=(",", ":"))  # noqa: E731
    for k in METRIC_KEYS:
        d = hashlib.sha256(canon(exp["metrics"][k]).encode()).hexdigest()[:16]
        rec.add(f"A golden metric {k}: reference SQL = Python domain = expected.json (digest)",
                hashlib.sha256(canon(ref_g[k]).encode()).hexdigest()[:16], d, hashlib.sha256(canon(dom_g.metrics[k]).encode()).hexdigest()[:16])
    for r in R["09_golden_known_answer__golden_per_invoice"]:
        doc = exp["documents"]["invoices"][r["invoice_id"]]
        d2 = dom_g.documents()["invoices"][r["invoice_id"]]
        rec.add(f"A golden {r['invoice_id']}: subtotal|tax|total|declared|rounding difference (09 vs expected.json vs domain)",
                "|".join(fmt(r[k]) for k in ("subtotal", "tax", "total", "declared_total", "rounding_difference")),
                "|".join(doc[k] for k in ("subtotal", "tax", "total", "declared_total", "rounding_difference")),
                "|".join(d2[k] for k in ("subtotal", "tax", "total", "declared_total", "rounding_difference")))
    grp = [r for r in R["09_golden_known_answer__golden_identity_groups"] if int(r["invoices"]) > 1]
    rec.add("A golden duplicate identity group (09 vs expected.json merged record)", grp[0]["identity_key"] if grp else "none",
            exp["ingest"]["merged_records"][0]["group_key"], dom_g.ingest.merged_records[0]["group_key"])
    q = R["09_golden_known_answer__golden_quantities"][0]
    il2 = next(m for m in exp["documents"]["match_results"] if m["invoice_line_id"] == "il-002")
    dl2 = next(m for m in dom_g.documents()["match_results"] if m["invoice_line_id"] == "il-002")
    rec.add("A golden ordered | net received | available to the second invoice | quantity variance (09 vs expected.json vs domain)",
            f"{fmt(q['ordered_quantity'])}|{fmt(q['net_received_quantity'])}|{fmt(q['available_for_the_second_invoice'])}|{fmt(q['quantity_variance_of_the_second_invoice'])}",
            f"{exp['metrics']['quantities']['ordered_quantity']}|{exp['metrics']['quantities']['net_received_quantity']}|{il2['available_quantity']}|{il2['quantity_variance']}",
            f"{dom_g.metrics['quantities']['ordered_quantity']}|{dom_g.metrics['quantities']['net_received_quantity']}|{dl2['available_quantity']}|{dl2['quantity_variance']}")

    # ---- B: snapshot headline figures --------------------------------------------------------------------------------------
    pop = ctx.pop
    cut_dt = [parse_ts(x) for x in cuts]
    dm = compute_metrics(pop, ctx.asof, cut_dt)
    for k in METRIC_KEYS:
        rec.add(f"B reference SQL equals the Python domain on metric key {k} (snapshot, as-of, digest)",
                hashlib.sha256(canon(ref_main[k]).encode()).hexdigest()[:16], hashlib.sha256(canon(dm[k]).encode()).hexdigest()[:16])
    bycur = {r["currency"]: r for r in R[ps.F01 + "by_currency"]}
    pay = {r["currency"]: r for r in R[ps.F07 + "payable_by_currency"]}
    rcn = {r["currency"]: r for r in R[ps.F06 + "reconciliation_by_currency"]}
    rec.add("B matched.invoice_count", sum(int(r["matched_at_cutoff"]) for r in bycur.values()), ref_main["matched"]["invoice_count"], dm["matched"]["invoice_count"])
    for cur in CURRENCIES:
        rec.add(f"B matched.by_currency.{cur}.invoice_count", bycur[cur]["matched_at_cutoff"], ref_main["matched"]["by_currency"][cur]["invoice_count"],
                dm["matched"]["by_currency"][cur]["invoice_count"])
        rec.add(f"B matched.by_currency.{cur}.total", bycur[cur]["matched_total"], ref_main["matched"]["by_currency"][cur]["total"], dm["matched"]["by_currency"][cur]["total"])
        rec.add(f"B obligations.by_currency.{cur}.count", pay[cur]["obligations"], ref_main["obligations"]["by_currency"][cur]["count"],
                dm["obligations"]["by_currency"][cur]["count"], rcn[cur]["approved_invoices"])
        rec.add(f"B obligations.by_currency.{cur}.total", pay[cur]["approved_total"], ref_main["obligations"]["by_currency"][cur]["total"],
                dm["obligations"]["by_currency"][cur]["total"], rcn[cur]["eligible_approved_total"])
        for f in ("approved_total", "credit_total", "approved_payable"):
            rec.add(f"B payable.by_currency.{cur}.{f}", pay[cur][f], ref_main["payable"]["by_currency"][cur][f], dm["payable"]["by_currency"][cur][f])
        for f in ("accepted_export_total", "eligible_approved_total", "difference"):
            rec.add(f"B export.by_currency.{cur}.{f}", rcn[cur][f],
                    ref_main["export"]["by_currency"][cur][f], dm["export"]["by_currency"][cur][f])
    ex = {r["measure"]: r["n"] for r in R[ps.F06 + "batch_summary"]}
    for label, key in (("requests received", "requests_received"), ("batches created (non-repeat requests)", "batches_created"),
                       ("repeat requests answered with the prior batch", "repeat_requests_returned_prior")):
        rec.add(f"B export.{key}", ex[label], ref_main["export"][key], dm["export"][key])
    rec.add("B export rows", ex["export rows (invoices exported)"], len(ref_main["export"]["rows"]), len(dm["export"]["rows"]), ex["stored export_rows rows (cross-check)"])
    for code in ("EXCEPTION_OPEN", "NOT_APPROVED", "EXPORT_BEFORE_APPROVAL", "APPROVED_NOT_EXPORTED"):
        rec.add(f"B export.exclusions {code} (invoices)", sum(int(r["invoices"]) for r in R[ps.F06 + "exclusions_by_reason_and_currency"] if r["reason_code"] == code),
                sum(1 for e in ref_main["export"]["exclusions"] if e["reason_code"] == code), sum(1 for e in dm["export"]["exclusions"] if e["reason_code"] == code))
    back = {fmt(r["cutoff"]): r for r in R[ps.F05 + "backlog_at_cutoffs"]}
    rec.add("B exceptions.open_count", back[ASOF]["open_from_facts"], ref_main["exceptions"]["open_count"], dm["exceptions"]["open_count"], back[ASOF]["open_from_history"])
    rec.add("B exceptions.unowned_count", back[ASOF]["unowned_from_history"], ref_main["exceptions"]["unowned_count"], dm["exceptions"]["unowned_count"])
    reasons = {r["reason"]: r for r in R[ps.F01 + "reason_open_vs_ever"]}
    for reason in ps.REASONS:
        rec.add(f"B exceptions.by_reason.{reason}", reasons[reason]["open_at_cutoff"], ref_main["exceptions"]["by_reason"][reason], dm["exceptions"]["by_reason"][reason])
    merges = [r for r in R[ps.F03 + "merges_by_reason_and_cutoff"] if fmt(r["cutoff"]) == ASOF]
    rec.add("B duplicates.rows_merged", sum(int(r["rows_merged"]) for r in merges), ref_main["duplicates"]["rows_merged"], dm["duplicates"]["rows_merged"])
    rec.add("B duplicates.groups_detected", sum(int(r["canonical_invoices"]) for r in merges), ref_main["duplicates"]["groups_detected"], dm["duplicates"]["groups_detected"])
    tot = {(fmt(r["cutoff"]), r["currency"]): r for r in R[ps.F02 + "totals_by_cutoff"]}
    for k in QTY_KEYS:
        rec.add(f"B quantities.{k} (units, all currencies)", tot[(ASOF, "ALL")][k], ref_main["quantities"][k], dm["quantities"][k])
    for cut in cuts:
        for k in QTY_KEYS:
            rec.add(f"B snapshots.{cut}.{k} (units, all currencies)", tot[(cut, "ALL")][k], ref_main["snapshots"][cut][k], dm["snapshots"][cut][k])
    po_ids = {cur: {l.po_line_id for l in pop.po_lines if ctx.po_cur[l.po_id] == cur} for cur in CURRENCIES}
    for cut in cuts:
        for cur in CURRENCIES:       # the money of received-not-invoiced is per currency: compared with the domain only (the reference has one unconverted sum)
            rec.add(f"B received_not_invoiced_value {cur} at {cut} (own currency; SQL analysis vs domain)", tot[(cut, cur)]["received_not_invoiced_value"],
                    quantities(ctx.books[cut].run, po_ids[cur])["received_not_invoiced_value"])
    elig = sum(int(r["invoices_in_book"]) for r in bycur.values())
    open_inv = sum(int(r["with_open_exception"]) for r in bycur.values())
    rec.add("B rates.eligible_invoices", elig, ref_main["rates"]["eligible_invoices"], dm["rates"]["eligible_invoices"])
    rec.add("B rates.straight_through_rate (not blocked at the cutoff)", ps.rnd(Fraction(elig - open_inv, elig), 6), ref_main["rates"]["straight_through_rate"], dm["rates"]["straight_through_rate"])
    rec.add("B rates.exception_rate", ps.rnd(Fraction(open_inv, elig), 6), ref_main["rates"]["exception_rate"], dm["rates"]["exception_rate"])
    dec = R[ps.F04 + "decisions_by_policy_version"]
    n_app = sum(int(r["valid_approvals"]) for r in dec)
    rec.add("B processing.approved_count", n_app, ref_main["processing"]["approved_count"], dm["processing"]["approved_count"])
    rec.add("B approvals.valid_count", n_app, ref_main["approvals"]["valid_count"], dm["approvals"]["valid_count"])
    rec.add("B processing.pending_count", elig - n_app, ref_main["processing"]["pending_count"], dm["processing"]["pending_count"])
    invalid = sum(int(r["approve_decisions"]) - int(r["valid_approvals"]) + int(r["reject_decisions"]) - int(r["valid_rejections"]) for r in dec)
    rec.add("B approvals.invalid_records (count)", invalid, len(ref_main["approvals"]["invalid_records"]), len(dm["approvals"]["invalid_records"]))
    rec.add("B credit notes applied (count across currencies)", sum(int(r["credit_notes"]) for r in pay.values()), len(pop.credit_notes))

    # ---- C: every result set cell by cell against python_side.py ---------------------------------------------------------
    py = ps.compute(ctx)
    for key in ps.KEYS:
        a, b = [{k: fmt(v) for k, v in r.items()} for r in R[key]], ps.normalised(py[key])
        cols = len(a[0]) if a else 0
        diff = sum(1 for ra, rb in zip(a, b) for k in set(ra) | set(rb) if ra.get(k) != rb.get(k)) + abs(len(a) - len(b)) * cols
        rec.add(f"C {key}: {len(a)} rows, {sum(len(r) for r in a)} cells, cells differing from the Python side", diff, 0)

    # ---- D: groups and cutoffs -----------------------------------------------------------------------------------------------
    hi = ctx.asof + timedelta(microseconds=1)
    gv = {g["key"]: g["metrics"] for g in window_metrics(pop, (None, hi), cut_dt, "vendor")["groups"]}
    for r in R[ps.F01 + "by_vendor"]:
        m = gv.get(r["vendor_id"])
        want = (m["rates"]["eligible_invoices"], m["matched"]["invoice_count"], m["exceptions"]["open_count"]) if m else (0, 0, 0)
        rec.add(f"D vendor {r['vendor_id']}: invoices in the book | matched | open exceptions (SQL vs domain group_metrics)",
                f"{r['invoices_in_book']}|{r['matched_at_cutoff']}|{r['with_open_exception']}", "|".join(str(v) for v in want))
    gc = {g["key"]: g["metrics"] for g in window_metrics(pop, (None, hi), cut_dt, "currency")["groups"]}
    for cur in CURRENCIES:
        m = gc[cur]
        rec.add(f"D currency {cur}: in the book | matched | matched total | obligations | approved total (SQL vs domain group_metrics)",
                f"{bycur[cur]['invoices_in_book']}|{bycur[cur]['matched_at_cutoff']}|{fmt(bycur[cur]['matched_total'])}|{pay[cur]['obligations']}|{fmt(pay[cur]['approved_total'])}",
                f"{m['rates']['eligible_invoices']}|{m['matched']['invoice_count']}|{m['matched']['total']}|{m['obligations']['count']}|{m['obligations']['total']}")
    for cut, ref in ((C1, ref_c1), (C2, ref_c2)):
        dmc = compute_metrics(pop, parse_ts(cut), [])
        mr = [r for r in R[ps.F03 + "merges_by_reason_and_cutoff"] if fmt(r["cutoff"]) == cut]
        rec.add(f"D {cut}: duplicates.rows_merged (03 vs reference SQL vs domain)", sum(int(r["rows_merged"]) for r in mr), ref["duplicates"]["rows_merged"], dmc["duplicates"]["rows_merged"])
        rec.add(f"D {cut}: exceptions.open_count (05 facts vs reference SQL vs domain)", back[cut]["open_from_facts"], ref["exceptions"]["open_count"], dmc["exceptions"]["open_count"])
        for k in ("net_received_quantity", "accepted_invoiced_quantity", "received_not_invoiced_quantity"):
            rec.add(f"D {cut}: quantities.{k} (02 vs reference SQL vs domain)", tot[(cut, "ALL")][k], ref["quantities"][k], dmc["quantities"][k])
        rec.add(f"D {cut}: matched.invoice_count (the domain book's matched invoices vs reference SQL vs domain metric)",
                sum(1 for r in ctx.books[cut].run.invoices.values() if r.matched), ref["matched"]["invoice_count"], dmc["matched"]["invoice_count"])
    rec.add("D the stored exception history differs from the facts-derived backlog only at the March month-end (open_from_facts - open_from_history)",
            "|".join(str(back[c]["difference"]) for c in cuts), "1|0|0")

    # ---- E: the injection manifest, the designed relationships and the BI facts ------------------------------------------
    inj = {i["id"]: i for i in json.loads((ROOT / "web" / "public" / "data" / "injection-manifest.json").read_text())["injections"]}
    sig = {r["inj"]: r for r in R[ps.F08 + "injected_defect_signatures"]}
    rec.add("E INJ-01 same bytes under two ids: groups found | manifest", sig["INJ-01"]["found"], len(inj["INJ-01"]["detail"]))
    rec.add("E INJ-02 invoice number reused across vendors: groups found | manifest", sig["INJ-02"]["found"], len(inj["INJ-02"]["detail"]))
    out3 = {r["invoice_id"] for r in R[ps.F08 + "open_quantity_blocked_outside_02x"]}
    cum = {r["invoice_id"] for r in R[ps.F08 + "cumulative_blocked_candidates"]}
    rec.add("E INJ-03 partial receipts: injected invoices inside the SQL candidate set (of the manifest's)", sum(1 for d in inj["INJ-03"]["detail"] if d["invoice_id"] in out3),
            len(inj["INJ-03"]["detail"]))
    rec.add("E INJ-04 cumulative consumption: injected invoices inside the SQL candidate set (of the manifest's)", sum(1 for d in inj["INJ-04"]["detail"] if d["invoice_id"] in cum),
            len(inj["INJ-04"]["detail"]))
    rec.add("E INJ-05 rounding gap over tolerance: invoices found | manifest", sig["INJ-05"]["found"], len(inj["INJ-05"]["detail"]))
    rec.add("E INJ-09 foreign-currency lines: invoices found | manifest", sig["INJ-09"]["found"], len(inj["INJ-09"]["detail"]))
    rec.add("E INJ-11 repeated export requests: found | manifest", sig["INJ-11"]["found"], len(inj["INJ-11"]["detail"]))
    for i in ("INJ-06", "INJ-07", "INJ-08", "INJ-10", "INJ-12"):
        rec.add(f"E {i} replay-only: rows in the snapshot | manifest record_count (handling_kind replay_only)", f"{sig[i]['found']}|{fmt(sig[i]['replay_only'])}",
                f"{inj[i]['record_count']}|{fmt(inj[i]['handling_kind'] == 'replay_only')}")
    rec.add("E ingest rejections kept | manifest expected rejections", R[ps.F08 + "ingest_outcomes"][3]["n"], sum(len(v) if isinstance(v, list) else int(v) for v in (i.get("expected_rejections", 0) for i in inj.values())))
    rec.add("E INJ-01 merges by bytes at the as-of | manifest", sum(int(r["rows_merged"]) for r in merges if r["reason_code"] == "DUPLICATE_SOURCE_BYTES"), len(inj["INJ-01"]["detail"]))
    dr = {d["id"]: d["realised"] for d in json.loads((ROOT / "web" / "public" / "data" / "manifest.json").read_text())["designed_relationships"]}
    grp = {r["vendor_group"]: r for r in R[ps.F01 + "vendor_group_open_vs_ever"]}
    else_n = int(grp["other vendors"]["invoices_in_book"]) + int(grp["ven-007"]["invoices_in_book"])
    else_qb = int(grp["other vendors"]["quantity_blocked_open"]) + int(grp["ven-007"]["quantity_blocked_open"])
    rec.add("E DR-01 ven-02x invoices | quantity-blocked open | rate (4 dp)", f"{grp['ven-02x']['invoices_in_book']}|{grp['ven-02x']['quantity_blocked_open']}|{ps.rnd(Fraction(int(grp['ven-02x']['quantity_blocked_open']), int(grp['ven-02x']['invoices_in_book'])), 4)}",
            f"{dr['DR-01']['ven_02x_invoices']}|{dr['DR-01']['ven_02x_quantity_blocked']}|{dr['DR-01']['ven_02x_rate']}")
    rec.add("E DR-01 other invoices | quantity-blocked open | rate (4 dp)", f"{else_n}|{else_qb}|{ps.rnd(Fraction(else_qb, else_n), 4)}",
            f"{dr['DR-01']['other_invoices']}|{dr['DR-01']['other_quantity_blocked']}|{dr['DR-01']['other_rate']}")
    rec.add("E DR-01 ven-02x share of open quantity blocks (4 dp)", ps.rnd(Fraction(int(grp["ven-02x"]["quantity_blocked_open"]), int(reasons["QUANTITY_BLOCKED"]["open_at_cutoff"])), 4), dr["DR-01"]["ven_02x_share_of_blocked"])
    pv_all = int(reasons["PRICE_VARIANCE"]["open_at_cutoff"])
    rec.add("E DR-02 ven-007 open price variances | all open price variances | ven-007 invoices | share (4 dp)",
            f"{grp['ven-007']['price_variance_open']}|{pv_all}|{grp['ven-007']['invoices_in_book']}|{ps.rnd(Fraction(int(grp['ven-007']['price_variance_open']), pv_all), 4)}",
            f"{dr['DR-02']['price_variance_invoices']}|{dr['DR-02']['all_price_variance_invoices']}|{dr['DR-02']['vendor_invoices']}|{dr['DR-02']['vendor_share_of_price_variance']}")
    mec = {r["population"]: r for r in R[ps.F03 + "month_end_clustering"]}
    rec.add("E DR-03 re-sent PDFs | imported in the last three days | share | all-invoice share (4 dp)",
            f"{mec['merged by identity (re-sent PDFs)']['invoices']}|{mec['merged by identity (re-sent PDFs)']['imported_in_last_three_days']}|{fmt(mec['merged by identity (re-sent PDFs)']['share'])}|{fmt(mec['all invoices']['share'])}",
            f"{dr['DR-03']['resent_duplicates']}|{dr['DR-03']['in_last_three_days_of_month']}|{dr['DR-03']['share']}|{dr['DR-03']['all_invoices_in_last_three_days_share']}")
    rec.add("E DR-04 approvals between the two limits after the change (HYPOTHETICAL v1 counterfactual rows summed)", sum(int(r["approvals"]) for r in R[ps.F04 + "v1_counterfactual"]),
            dr["DR-04"]["approvals_between_limits_after_change"])

    csvs = {k: [{c: fmt(v) for c, v in r.items()} for r in rows] for k, rows in bi.items()}
    inv_status = {r["invoice_id"]: r["status_at_asof"] for r in csvs["fact_invoice"]}
    rec.add("E BI fact_invoice: 2,800 rows, status_at_asof equals the domain's derived status for every invoice (mismatches)",
            f"{len(inv_status)}|{sum(1 for k, v in inv_status.items() if ctx.book.status[k] != v)}", f"{len(ctx.pop.invoices)}|0")
    meas = bi_measures(csvs["fact_invoice"], csvs["fact_po_line"], csvs["fact_exception"], csvs["fact_export_row"])
    mv = {(m["measure"], m["currency"]): m["value"] for m in meas}
    rn = dm["rates"]
    for measure, ref_v, dom_v in (
            ("matched_invoices", ref_main["matched"]["invoice_count"], dm["matched"]["invoice_count"]),
            ("obligations", ref_main["obligations"]["count"], dm["obligations"]["count"]),
            ("open_exceptions", ref_main["exceptions"]["open_count"], dm["exceptions"]["open_count"]),
            ("unowned_exceptions", ref_main["exceptions"]["unowned_count"], dm["exceptions"]["unowned_count"]),
            ("eligible_invoices", ref_main["rates"]["eligible_invoices"], rn["eligible_invoices"]),
            ("exception_rate", ref_main["rates"]["exception_rate"], rn["exception_rate"]),
            ("straight_through_rate", ref_main["rates"]["straight_through_rate"], rn["straight_through_rate"]),
            ("ever_excepted_rate", ref_main["rates"]["ever_excepted_rate"], rn["ever_excepted_rate"]),
            ("never_excepted_rate", ref_main["rates"]["straight_through_never_excepted_rate"], rn["straight_through_never_excepted_rate"]),
            ("approved_invoices", ref_main["processing"]["approved_count"], dm["processing"]["approved_count"]),
            ("mean_minutes_to_approval", ref_main["processing"]["mean_minutes"], dm["processing"]["mean_minutes"]),
            ("pending_invoices", ref_main["processing"]["pending_count"], dm["processing"]["pending_count"]),
            ("duplicates_merged", ref_main["duplicates"]["rows_merged"], dm["duplicates"]["rows_merged"])):
        rec.add(f"E BI measure {measure} (CSV facts vs reference SQL vs domain)", mv[(measure, "")], ref_v, dom_v)
    for reason in ps.REASONS:
        rec.add(f"E BI measure open_exceptions {reason}", mv[("open_exceptions", reason)], ref_main["exceptions"]["by_reason"][reason], dm["exceptions"]["by_reason"][reason])
    for k in QTY_KEYS:
        rec.add(f"E BI measure {k} (units)", mv[(k, "")], ref_main["quantities"][k], dm["quantities"][k])
    for cur in CURRENCIES:
        rec.add(f"E BI measure matched_invoices {cur}", mv[("matched_invoices", cur)], ref_main["matched"]["by_currency"][cur]["invoice_count"])
        rec.add(f"E BI measure matched_total {cur}", mv[("matched_total", cur)], ref_main["matched"]["by_currency"][cur]["total"], dm["matched"]["by_currency"][cur]["total"])
        rec.add(f"E BI measure obligations {cur}", mv[("obligations", cur)], ref_main["obligations"]["by_currency"][cur]["count"])
        for f in ("approved_total", "credit_total", "approved_payable"):
            rec.add(f"E BI measure {f} {cur}", mv[(f, cur)], ref_main["payable"]["by_currency"][cur][f], dm["payable"]["by_currency"][cur][f])
        rec.add(f"E BI measure accepted_export_total {cur}", mv[("accepted_export_total", cur)], ref_main["export"]["by_currency"][cur]["accepted_export_total"])
        rec.add(f"E BI measure export_difference {cur}", mv[("export_difference", cur)], ref_main["export"]["by_currency"][cur]["difference"])
        rec.add(f"E BI measure received_not_invoiced_value {cur} (own currency; vs domain)", mv[("received_not_invoiced_value", cur)],
                quantities(ctx.books[ASOF].run, po_ids[cur])["received_not_invoiced_value"])

    # ---- results -------------------------------------------------------------------------------------------------------------
    equal = sum(1 for r in rec.rows if r["equal"])
    meta = {"dataset_hash": DATASET_HASH, "dataset_version": ctx.manifest["dataset_version"], "code_revision": CODE_REVISION, "contract_version": 1,
            "seed": ctx.manifest["generator"]["seed"], "as_of": ASOF, "snapshot_cutoffs": "|".join(cuts), "seed_input_hash": prep_s["dataset_hash"],
            "invoices": len(ctx.pop.invoices), "reconciliation_rows": len(rec.rows), "reconciliation_equal": equal, "result_sets": len(ps.KEYS) + 3,
            "result_rows": sum(len(R[k]) for k in R)}
    for r in rec.rows:
        print(("OK   " if r["equal"] else "DIFF ") + r["check"] + (" | " + " | ".join(str(r[k]) for k in ("analysis_sql", "second_source", "third_source", "fourth_source") if r[k] != "") if not r["equal"] else ""))
    print(f"RESULT: {'OK' if rec.ok else 'FAILED'} ({len(rec.rows)} reconciliation rows, {equal} equal; {meta['result_sets']} result sets, {meta['result_rows']} rows)")
    if bi_out:
        for k, rows in csvs.items():
            export_csv(bi_out / f"{k}.csv", rows)
        export_csv(bi_out / "measures_recomputed.csv", meas)
        print(f"wrote {len(csvs) + 1} CSV files to {bi_out}")
    if json_out:
        out = {"meta": [meta], **{k: ps.normalised(v) for k, v in R.items()}, "bi_measures": meas, "reconciliation": rec.rows}
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(out, indent=1, sort_keys=False) + "\n")
        print(f"wrote {json_out}")
    return 0 if rec.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
