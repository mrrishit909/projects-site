"""Seeded random populations for the SQL-versus-domain tests: every rule type, filters, whitespace, duplicates, null foreign keys,
IANA zones (including days when the clocks change), inactive owners, runs of two rule versions, issues in every state, reopens,
lineage of all three evidence types, versioned metric definitions, candidates, merges, reversals and a partial synthetic truth.
Not every record is acceptable to the ingest (that is the point): the database holds what the ingest accepted, as the domain does."""
from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

from support_db import World, iso, ts

ZONES = ["UTC", "America/New_York", "Europe/London", "Asia/Kolkata", "Pacific/Auckland", "America/Sao_Paulo"]
AS_OFS = ["2026-10-05T00:00:00Z", "2026-10-25T01:30:00Z", "2026-10-25T02:10:00Z", "2026-03-29T01:30:00Z", "2026-11-01T06:30:00Z",
          "2026-11-01T07:20:00Z", "2026-03-08T07:30:00Z", "2026-12-31T23:59:59Z", "2026-04-04T14:00:00Z"]
EMAILS = ["a@b.co", "x.y@z.org", "bad", "no@dot", "a b@c.de", "two@@x.io", "  ", "", None, "\t", "ok@ok.ok", "ok@ok.o", "n@m.com\n"]


def random_world(seed: int) -> tuple[dict[str, Any], str | None]:
    rnd = random.Random(seed)
    as_of = rnd.choice(AS_OFS)
    t0 = ts(as_of)
    w = World(as_of)
    owners = []
    for i in range(rnd.randint(2, 6)):
        dead = rnd.random() < 0.3
        when = iso(t0 + timedelta(days=rnd.randint(-40, 40))) if dead else None
        owners.append(w.owner(f"own-{i}", rnd.choice(["analyst", "steward", "admin"]), active=not dead or rnd.random() < 0.3, deactivated_at=when))
    if rnd.random() < 0.1:
        w.d["owners"] = []
        owners = []
    keys = [f"K{n}" for n in range(1, 40)]
    dsids = []
    for i in range(rnd.randint(1, 5)):
        did = f"ds-{i}"
        mon = rnd.random() < 0.7
        zone = rnd.choice(ZONES)
        local = f"{rnd.choice([0, 1, 2, 3, 5, 6, 12, 23]):02d}:{rnd.choice([0, 15, 30, 45]):02d}"
        grace = rnd.choice([0, 1, 30, 60, 120, 600])
        rows = []
        for r in range(rnd.choice([0, 1, 5, 20, 60])):
            row = {"row_id": f"{did}-{r}", "k": rnd.choice(keys + [None, "", "  ", "K1", "K1"]), "email": rnd.choice(EMAILS), "n": rnd.choice([1, 2, 3, None, True, 0]),
                   "kind": rnd.choice(["a", "b", "c"])}
            row["fk"] = rnd.choice(keys[:20] + [None, "", " ", "ZZ", "k1"]) if i > 0 else None
            rows.append(row)
        owner = rnd.choice(owners + [None, "own-nope"]) if owners else None
        sched_t = ts(as_of) + timedelta(days=-1, minutes=rnd.randint(-900, 900))
        w.dataset(did, owner, rows, monitored=mon, registered_at=iso(t0 + timedelta(days=rnd.randint(-100, 3))),
                  refresh_timezone=zone if mon else None, refresh_local_time=local if mon else None, refresh_grace_minutes=grace if mon else None,
                  last_refreshed_at=rnd.choice([None, iso(sched_t), iso(sched_t.replace(hour=int(local[:2]), minute=int(local[3:])))]) if mon else None)
        if owner is None and rnd.random() < 0.5:
            w.d["datasets"][-1]["owner_id"] = rnd.choice(["", "  ", None])
        dsids.append(did)
    rules = []
    for n, did in enumerate(dsids):
        for t in rnd.sample(["completeness", "validity", "uniqueness", "relationship", "timeliness"], rnd.randint(1, 5)):
            d: dict[str, Any] = {"field": {"completeness": "email", "validity": "email", "uniqueness": "k", "relationship": "fk"}.get(t, "k")}
            if t == "validity":
                d["pattern"] = rnd.choice([r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$", r"^[a-z]+$", r"@", r"^a"])
            if t == "relationship":
                d.update(parent_dataset_id=rnd.choice(dsids), parent_field=rnd.choice(["k", "email"]))
            if rnd.random() < 0.25 and t != "timeliness":
                d["filter"] = {"field": "kind", "equals": rnd.choice(["a", "b"])}
            if t == "timeliness":
                d = {"target": "dataset_schedule"}
            extra: dict[str, Any] = {}
            if rnd.random() < 0.2:
                extra = {"status": "disabled", "disabled_at": iso(t0 + timedelta(days=rnd.randint(-20, 20))), "disabled_reason": "r"}
            rid = f"r-{did}-{t[:3]}"
            rules.append(w.rule(rid, did, t, d, severity=rnd.choice(["low", "medium", "high", "critical"]), version=rnd.choice([1, 1, 2]), **extra))
    runs = []
    for rid in rules:
        for k in range(rnd.randint(0, 3)):
            rule = next(r for r in w.d["quality_rules"] if r["rule_id"] == rid)
            el = rnd.randint(1, 60)
            runs.append((w.run(f"{rid}-run{k}", rid, iso(t0 + timedelta(days=-rnd.randint(1, 30), minutes=rnd.randint(0, 600))), el, rnd.randint(0, el),
                               version=rnd.choice([rule["version_number"], 1, 2])), rid))
    for n, (run, rid) in enumerate(runs):
        if rnd.random() < 0.5:
            continue
        run_row = next(r for r in w.d["rule_runs"] if r["rule_run_id"] == run)
        det = ts(run_row["run_at"])
        iid = f"iss-{n}"
        status = rnd.choice(["open", "investigating", "closed", "closed"])
        issue: dict[str, Any] = {"issue_id": iid, "rule_run_id": run, "owner_id": rnd.choice(owners) if owners else "own-0", "status": status,
                                 "detected_at": iso(det), "due_at": None, "closed_at": None, "verification_run_id": None, "reopened_at": []}
        if status == "closed" or rnd.random() < 0.2:
            issue["closed_at"] = iso(det + timedelta(hours=rnd.randint(1, 300)))
            if rnd.random() < 0.7:
                ver = w.run(f"{run}-rerun", rid, iso(ts(issue["closed_at"]) - timedelta(minutes=rnd.randint(0, 120))), rnd.randint(1, 5), rnd.choice([0, 0, 0, 1]),
                            version=run_row["rule_version"] if rnd.random() < 0.9 else 3, kind="rerun", for_issue=iid)
                issue["verification_run_id"] = ver
        if rnd.random() < 0.3:
            issue["reopened_at"] = sorted(iso(det + timedelta(hours=rnd.randint(1, 400))) for _ in range(rnd.randint(1, 2)))
        w.d["issues"].append(issue)
    for k in range(rnd.randint(0, 12)):
        a, b = rnd.sample(dsids + ["ds-ghost"], 2) if len(dsids) > 1 else (dsids[0], "ds-ghost")
        ev = rnd.choice(["declared", "observed", "observed", "inferred"])
        w.d["lineage_edges"].append({"edge_id": f"e-{k}", "source_dataset_id": a, "target_dataset_id": b, "evidence_type": ev,
                                     "observed_at": iso(t0 + timedelta(days=rnd.randint(-5, 5))) if ev == "observed" else None})
    for m in range(rnd.randint(0, 5)):
        for v in range(1, rnd.randint(1, 3) + 1):
            blank = lambda x: rnd.choice([x, "", None, "  "])  # noqa: E731
            w.d["metric_versions"].append({
                "metric_version_id": f"mv-{m}-{v}", "metric_id": f"m-{m}", "metric_name": f"M{m}", "version_number": v, "definition": blank("d"), "grain": blank("g"),
                "source_fields": rnd.choice([["a"], [], ["a", " "], None]), "owner_id": rnd.choice(owners + ["own-nope"]) if owners else "own-nope",
                "refresh": blank("daily"), "valid_from": iso(t0 + timedelta(days=rnd.randint(-60, 5))), "status": rnd.choice(["published", "published", "draft", "superseded"])})
    recs = []
    for r in range(rnd.randint(0, 8)):
        recs.append({"record_id": f"rec-{r}", "source_system": "s", "source_customer_id": f"S{r}", "normalized_name": rnd.choice(["a b", "c d"]), "address_key": rnd.choice(["x", "y"])})
    w.d["customer_records"] = recs
    truth = {}
    for r in recs:
        if rnd.random() < 0.9:
            truth[r["record_id"]] = rnd.choice(["E1", "E2", "E3"])
    w.d["synthetic_truth"]["true_entity"] = truth
    cands, appr = [], {}
    for c in range(rnd.randint(0, 8)):
        if len(recs) < 2:
            break
        a, b = sorted(rnd.sample([r["record_id"] for r in recs], 2))
        if rnd.random() < 0.15:
            a, b = b, a
        cands.append({"candidate_id": f"cand-{c}", "left_record_id": a, "right_record_id": b, "score": rnd.choice(["0.500000", "0.970000", "1.000000"]),
                      "features": {"f": "1.000000"}, "explanation": "x", "uncertainty": None, "proposed_by": rnd.choice(owners + ["x"]) if owners else "x",
                      "proposed_at": iso(t0 + timedelta(days=rnd.randint(-30, 3)))})
    w.d["match_candidates"] = cands
    mds = []
    good = [o for o in w.d["owners"] if o["role"] in ("steward", "admin") and o["active"]]

    def reviewer(c: dict[str, Any]) -> str:
        pool = [o["owner_id"] for o in good if o["owner_id"] != c["proposed_by"]]
        return rnd.choice(pool) if pool and rnd.random() < 0.85 else (rnd.choice(owners) if owners else "y")

    for n, c in enumerate(cands):
        if rnd.random() < 0.7:
            kind = rnd.choice(["approve", "approve", "reject"])
            mid = f"md-{n}"
            mds.append({"merge_id": mid, "candidate_id": c["candidate_id"], "reviewer_id": reviewer(c), "decision": kind,
                        "decided_at": iso(t0 + timedelta(days=rnd.randint(-20, 3))), "reverses_merge_id": None, "reason": None})
            if kind == "approve" and rnd.random() < 0.4:
                mds.append({"merge_id": f"md-r{n}", "candidate_id": c["candidate_id"], "reviewer_id": reviewer(c), "decision": "reverse",
                            "decided_at": iso(t0 + timedelta(days=rnd.randint(-10, 5))), "reverses_merge_id": mid, "reason": rnd.choice(["because", "because", " "])})
    w.d["merge_decisions"] = mds
    return w.data(), rnd.choice([None, "w1", "w2"])
