"""Publication scope, reconciliation with signed exclusions, late events behind the watermark, verified recovery (D-02, D-03, D-P8-05/06/09)."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Any, Iterable

from .hashing import content_hash
from .numbers import m4, money, ratio
from .timeutil import iso_z, parse_ts, seconds_between


@dataclass
class Accepted:
    """An accepted record of a committed batch with its arrival (the checkpoint commit instant of its batch)."""
    source_id: str
    batch_id: str
    key: str
    event_at: str
    arrival: str | None
    raw_record_id: str
    payload_hash: str
    amount: Decimal
    deleted_in: str | None = None      # the batch whose delete event removed this record from the published snapshot


def published_records(accepted: Iterable[Accepted], included: Iterable[str]) -> list[Accepted]:
    """The records a publication shows: accepted records of its included batches, minus those a delete event of an included batch removed."""
    inc = set(included)
    return [a for a in accepted if a.batch_id in inc and not (a.deleted_in and a.deleted_in in inc)]


def reconcile(src_rows: list[tuple[str, Decimal]], pub: list[Accepted], delete_rows_amount: Decimal, removed: list[Accepted],
              published_total: Decimal | None = None) -> dict[str, Any]:
    """Residual = source total - published total - explained exclusions. ``src_rows`` is (disposition, amount) for every received row of the
    included batches. Exclusions are signed sums: quarantined, duplicates and deletes (the amounts of the delete rows plus the records
    they remove). ``published_total`` is the total of the stored published table when the caller has one (the API's ``model_outputs``);
    otherwise it is the sum of the published records."""
    zero = Decimal("0")
    src = sum((a for _, a in src_rows), zero)
    published = published_total if published_total is not None else sum((a.amount for a in pub), zero)
    q_amt = sum((a for k, a in src_rows if k == "quarantined"), zero)
    d_amt = sum((a for k, a in src_rows if k == "duplicate"), zero)
    del_amt = delete_rows_amount + sum((a.amount for a in removed), zero)
    total = q_amt + d_amt + del_amt
    return {"source_total": money(src), "published_total": money(published),
            "exclusions": {"quarantined": money(q_amt), "duplicates": money(d_amt), "deletes": money(del_amt)},
            "exclusions_total": money(total), "residual": money(src - published - total)}


def publication_view(pub: dict[str, Any], pubd: list[Accepted]) -> dict[str, Any]:
    latest = max((a.event_at for a in pubd), key=parse_ts, default=None)
    return {"latest": latest, "content_hash": content_hash(a.payload_hash for a in pubd),
            "lag_seconds": seconds_between(latest, pub["published_at"]) if latest else None}


def late_events(accepted: list[Accepted], pubs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """An accepted record whose batch committed after the published_at of the latest earlier publication covering its source, and whose
    event_at is not after that publication's watermark (D-P8-09). Next publication = the first later one that includes its batch."""
    ordered = sorted(pubs, key=lambda p: (parse_ts(p["published_at"]), p["publication_id"]))
    out = []
    for a in accepted:
        if a.arrival is None:
            continue
        arrived = parse_ts(a.arrival)
        before = [p for p in ordered if a.source_id in p["source_ids"] and parse_ts(p["published_at"]) < arrived]
        if not before:
            continue
        p = before[-1]
        if parse_ts(a.event_at) <= parse_ts(p["watermark"]):
            nxt = [q for q in ordered if parse_ts(q["published_at"]) > arrived and a.batch_id in q["included_batch_ids"]]
            out.append({"source_id": a.source_id, "source_key": a.key, "batch_id": a.batch_id, "event_at": iso_z(a.event_at),
                        "arrival_at": iso_z(a.arrival), "behind_publication_id": p["publication_id"], "watermark": iso_z(p["watermark"]),
                        "included_in_publication_id": nxt[0]["publication_id"] if nxt else None})
    out.sort(key=lambda x: (parse_ts(x["arrival_at"]), x["source_key"]))
    return out


def pending_late_events(accepted: list[Accepted], pubs: list[dict[str, Any]], until: Any) -> list[dict[str, Any]]:
    """The late events that arrived before ``until`` (the instant a run started) and are in no publication published after their arrival.
    ``pubs`` are the publications that exist when the gate runs. The ``late_events_included`` check fails for every one of them whose batch the
    candidate does not include (D-09, R8-02)."""
    hi = parse_ts(until)
    arrived = [a for a in accepted if a.arrival is not None and parse_ts(a.arrival) < hi]
    return [e for e in late_events(arrived, pubs) if e["included_in_publication_id"] is None]


def verified_recovery(opened_at: str, runs: list[dict[str, Any]], gate_of: dict[str, str], pub_of_run: dict[str, str],
                      residual_of_pub: dict[str, str]) -> dict[str, Any] | None:
    """The first run starting at or after ``opened_at`` that succeeded, passed its gate, published, and whose publication reconciles to
    0.00 (D-P8-06). Returns the run row and its publication id, or None."""
    for run in sorted(runs, key=lambda r: (parse_ts(r["started_at"]), r["run_id"])):
        pid = pub_of_run.get(run["run_id"])
        if (parse_ts(run["started_at"]) >= parse_ts(opened_at) and run["status"] == "success" and gate_of.get(run["run_id"]) == "allowed"
                and pid and residual_of_pub.get(pid) == "0.00"):
            return {"run": run, "publication_id": pid}
    return None


def recovery_minutes(seconds: int | None) -> str | None:
    return None if seconds is None else m4(ratio(seconds, 60))


def mean_minutes(total_seconds: int, n: int) -> str | None:
    return m4(ratio(total_seconds, 60 * n)) if n else None


def fraction_of(n: int, d: int) -> Fraction | None:
    return ratio(n, d)
