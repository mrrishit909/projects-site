"""Writes scripts/snapshot-reference.json: what the PYTHON domain (domain/invoicebridge) computes over the published
snapshot in web/public/data, so CI can compare the TypeScript mirror without Python. Run once, from apps/invoicebridge:

    ../../.venv/bin/python web/scripts/make-snapshot-reference.py

Two reads of the same facts: "pipeline" (run_pipeline over the entity files: no stored exception ids, no assignments)
and "stored" (the API read path: stored exception ids and assignment history, ``Population.from_rows`` style).
"""
import hashlib, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "domain"))
from invoicebridge.pipeline import run_pipeline, validate_population  # noqa: E402
from invoicebridge.book import derive  # noqa: E402
from invoicebridge.metrics import compute_metrics  # noqa: E402
from invoicebridge.models import Assignment, ExceptionRecord  # noqa: E402
from invoicebridge.timeutil import parse_ts  # noqa: E402
from invoicebridge.ingest import validate_batch  # noqa: E402
from invoicebridge.contract import METRIC_KEYS  # noqa: E402

DATA = ROOT / "web" / "public" / "data"
manifest = json.loads((DATA / "manifest.json").read_text())
ENT = ["vendors", "purchase_orders", "po_lines", "receipts", "invoices", "invoice_lines", "credit_notes", "approval_policies",
       "approvals", "export_requests", "exceptions", "exception_assignments"]
rows = {e: json.loads((DATA / f"{e}.json").read_text())["rows"] for e in ENT}
inputs = {"contract_version": 1, "as_of": manifest["as_of"], "snapshot_cutoffs": manifest["snapshot_cutoffs"],
          "tolerances": manifest["tolerances"], **{e: rows[e] for e in ENT if e not in ("exceptions", "exception_assignments")}}


def canon(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"))


def digest(v):
    return hashlib.sha256(canon(v).encode()).hexdigest()


def summary(label, metrics, docs, book, ing):
    small = {k: metrics[k] for k in ("matched", "obligations", "duplicates", "quantities", "snapshots", "rates", "processing", "payable")}
    exc = metrics["exceptions"]
    exp = metrics["export"]
    status_counts = {}
    for s in book.status.values():
        status_counts[s] = status_counts.get(s, 0) + 1
    return {
        "metric_digests": {k: digest(metrics[k]) for k in METRIC_KEYS},
        "small_metrics": small,
        "exceptions": {"open_count": exc["open_count"], "unowned_count": exc["unowned_count"], "by_reason": exc["by_reason"]},
        "approvals": {"valid_count": metrics["approvals"]["valid_count"], "invalid_count": len(metrics["approvals"]["invalid_records"]),
                      "invalid_by_code": {c: sum(1 for r in metrics["approvals"]["invalid_records"] if r["reason_code"] == c)
                                          for c in sorted({r["reason_code"] for r in metrics["approvals"]["invalid_records"]})}},
        "export": {k: exp[k] for k in ("requests_received", "batches_created", "repeat_requests_returned_prior", "accepted_export_total",
                                       "eligible_approved_total", "difference")} | {"row_count": len(exp["rows"]), "exclusion_count": len(exp["exclusions"])},
        "status_counts": dict(sorted(status_counts.items())),
        "documents_digest": digest(docs),
        "ingest_counts": ing.counts,
        "rejected_count": len(ing.rejected),
        "merged_records_digest": digest(ing.merged_records),
    }


out = {"generated_by": "web/scripts/make-snapshot-reference.py (domain/invoicebridge, Python) run once over web/public/data",
       "dataset_hash": manifest["dataset_hash"], "dataset_version": manifest["dataset_version"], "as_of": manifest["as_of"]}
res = run_pipeline(inputs)
out["pipeline"] = summary("pipeline", res.metrics, res.documents(), res.book, res.ingest)

ing = validate_batch(inputs)
pop = validate_population(ing.population())
pop.exceptions = [ExceptionRecord(r["exception_id"], r["invoice_id"], r["exception_type"]) for r in rows["exceptions"]]
pop.assignments = [Assignment(r["exception_id"], r["owner_id"], parse_ts(r["assigned_at"])) for r in rows["exception_assignments"]]
as_of = parse_ts(manifest["as_of"])
cuts = [parse_ts(c) for c in manifest["snapshot_cutoffs"]]
book = derive(pop, as_of)
metrics = compute_metrics(pop, as_of, cuts)
from invoicebridge.pipeline import PipelineResult  # noqa: E402
pr = PipelineResult(ing, pop, metrics, [], book)
out["stored"] = summary("stored", metrics, pr.documents(), book, ing)
Path(__file__).with_name("snapshot-reference.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
print("written; open exceptions", metrics["exceptions"]["open_count"], "unowned", metrics["exceptions"]["unowned_count"])
