#!/usr/bin/env python3
"""Onboard Studio synthetic data generator (P02-WORK-03, docs/data-generator.md).

Stdlib only. Deterministic: one ``random.Random(seed)`` stream and integer minutes since 2025-04-01T00:00Z, so
the same seed and parameters give byte-identical entity files and the same ``dataset_hash``.

    python data/generate.py --seed 20261026 --out web/public/data
    python data/generate.py --profile golden-shape-check

Writes ``<entity>.json`` (``{"entity", "dataset_version", "rows"}``) and ``manifest.json`` to ``--out``;
``injection-manifest.json`` and ``injection-events.json`` to ``--data-dir`` (default ``data/``) and a copy of the
injection manifest to ``--out``. Nothing is imported from ``domain/``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
import time
from bisect import bisect_right
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED = 20261026
DATE_TAG = "20261026"
CONTRACT_VERSION = "v1"
BASE = datetime(2025, 4, 1, tzinfo=timezone.utc)
WINDOW_START = date(2025, 4, 1)
WINDOW_END = date(2026, 9, 30)  # inclusive; the snapshot is cut at 23:59 that day
CAL_END = date(2027, 2, 28)     # the simulation calendar runs past the cut so open cases can be simulated
CASES = 740
DAY = 1440

ENTITIES = ("organizations", "cases", "workflow_versions", "step_definitions", "dependencies", "step_instances",
            "assignments", "document_versions", "approvals", "sla_rules", "calendar_intervals",
            "waiting_intervals", "case_events", "workflow_requirements")
REGIONS = ("reg-north", "reg-south", "reg-east", "reg-west")
SEGMENTS = {"smb": 22, "mid_market": 12, "enterprise": 6}
SEGMENT_WEIGHT = {"smb": 1.0, "mid_market": 1.6, "enterprise": 2.0}
PAUSE_POLICY = ["customer_info_requested", "external_verification"]
SLA_MINUTES = 480
V2_PUBLISHED = date(2025, 10, 1)
V2_SHARE = 0.60  # share of cases opened from V2_PUBLISHED on that bind version 2
HOLIDAYS = (  # (date, name); 2026-02-14 and 2026-07-04 are Saturdays and subtract nothing
    (date(2025, 5, 26), "Memorial Day"), (date(2025, 9, 1), "Labor Day"), (date(2025, 11, 27), "Thanksgiving"),
    (date(2025, 12, 25), "Christmas Day"), (date(2026, 2, 14), "Founders Day (Saturday)"),
    (date(2026, 7, 4), "Independence Day (Saturday)"))

# step name -> (role_key, sequence); version 1 has verify_identity, version 2 a parallel collect_address_proof
V1_STEPS = (("collect_documents", "ops", 1), ("verify_identity", "ops", 2), ("compliance_review", "compliance", 3),
            ("approve_account", "reviewer", 4), ("activate_account", "ops", 5))
V2_STEPS = (("collect_documents", "ops", 1), ("collect_address_proof", "ops", 2), ("compliance_review", "compliance", 3),
            ("approve_account", "reviewer", 4), ("activate_account", "ops", 5))
V1_DEPS = ((2, 1), (3, 2), (4, 3), (5, 4))       # (sequence, prerequisite sequence)
V2_DEPS = ((3, 1), (3, 2), (4, 3), (5, 4))
REQUIRED_DOCS = {1: ["business_registration", "identity_proof"],
                 2: ["address_proof", "business_registration", "identity_proof"]}
STEP_DOCS = {"collect_documents": ("identity_proof", "business_registration"),
             "collect_address_proof": ("address_proof",), "approve_account": ()}
OPTIONAL_DOC = ("approval_form", 0.35)           # submitted at approve_account, never required

# median business minutes: (queue = ready -> started, work = started -> documents/hand-over, review = -> decision)
PROFILE = {
    1: {"collect_documents": (25, 55, 25), "verify_identity": (32, 50, 28), "compliance_review": (36, 58, 28),
        "approve_account": (36, 36, 32), "activate_account": (20, 26, 15)},
    2: {"collect_documents": (22, 40, 20), "collect_address_proof": (22, 32, 20), "compliance_review": (30, 46, 22),
        "approve_account": (30, 30, 28), "activate_account": (18, 22, 14)},
}
PROFILE_SCALE = {1: 0.86, 2: 0.82}  # tuned so version 2 shows about 35 % lower active elapsed time
PROFILE = {v: {k: tuple(max(2, round(x * PROFILE_SCALE[v])) for x in t) for k, t in p.items()}
           for v, p in PROFILE.items()}
HANDOFF_P = {1: {"collect_documents": .20, "verify_identity": .35, "compliance_review": .15, "approve_account": .20,
                 "activate_account": .10},
             2: {"collect_documents": .19, "collect_address_proof": .12, "compliance_review": .15,
                 "approve_account": .20, "activate_account": .10}}
BOTTLENECK = {"reviewer": "rev-004", "queue_factor": 3.6, "review_factor": 3.4, "share": 0.40}
REVIEWERS = {"ops": ["rev-001", "rev-002", "rev-003"], "reviewer": ["rev-004", "rev-005", "rev-006"],
             "compliance": ["rev-007", "rev-008"]}
ASSIGNEES = {"ops": [f"ops-{i:03d}" for i in range(1, 17)], "compliance": [f"cmp-{i:03d}" for i in range(1, 5)],
             "reviewer": [f"acc-{i:03d}" for i in range(1, 5)]}
REJECT_P = {"identity_proof": {"enterprise": 0.20, "other": 0.11}, "business_registration": 0.03,
            "address_proof": 0.05}
INFO_WAITS = {"reg-north": ((0, .20), (1, .40), (2, .30), (3, .10)),
              "other": ((0, .45), (1, .40), (2, .15))}
EXT_VERIFY_P = {"reg-north": 0.30, "other": 0.18}
WAIT_MEDIAN = {"info": 1500, "verify": 1100, "rework": 1200}   # real minutes
WAIT_REGION_FACTOR = {"reg-north": 1.4, "other": 1.0}
STALL_P = 0.035

NAME_A = ("Marlowe", "Alder", "Cinder", "Dunmore", "Elmstead", "Fenwick", "Garnet", "Halbrook", "Ironvale", "Juniper",
          "Kestrel", "Lindenhurst", "Moorfield", "Norvale", "Oakhollow", "Pinegate", "Quarry", "Ridgemont",
          "Stonebrook", "Thornley", "Umberfield", "Valewood", "Whitcombe", "Yarrow", "Ashgrove", "Brindle",
          "Copperfield", "Dellwood", "Eastmere", "Foxhollow", "Greystone", "Hartwell", "Inglenook", "Jasperton",
          "Kingsmoor", "Larkspur", "Millbrook", "Northgate", "Orchard", "Pemberton")
NAME_B = ("Logistics", "Health", "Foods", "Energy", "Software", "Media", "Retail", "Construction", "Textiles",
          "Analytics")
NAME_C = ("Ltd", "LLC", "Inc", "Group", "Partners", "GmbH", "Co")
LONG_NAMES = (
    "Consolidated Regional Wholesale Distribution and Industrial Supply Partnership of the Great Lakes Limited",
    "International Association of Municipal Facilities Maintenance and Public Works Procurement Cooperatives",
    "Northern Territories Mining, Forestry and Heavy Equipment Contractors Purchasing Consortium Limited",
    "Metropolitan Hospital and Educational Campus Facilities Services Shared Procurement Authority Inc")


def iso(minute: int) -> str:
    return (BASE + timedelta(minutes=minute)).strftime("%Y-%m-%dT%H:%M:%SZ")


def day_minute(d: date, hh: int = 0, mm: int = 0) -> int:
    return (d - WINDOW_START).days * DAY + hh * 60 + mm


CUTOFF = day_minute(WINDOW_END, 23, 59)


class BusinessCalendar:
    """Monday-Friday 09:00-17:00 UTC minus holidays, as sorted minute intervals (the simulation's clock)."""

    def __init__(self) -> None:
        hol = {d for d, _ in HOLIDAYS}
        self.starts: list[int] = []
        self.ends: list[int] = []
        d = WINDOW_START
        while d <= CAL_END:
            if d.weekday() < 5 and d not in hol:
                self.starts.append(day_minute(d, 9))
                self.ends.append(day_minute(d, 17))
            d += timedelta(days=1)

    def snap(self, t: int) -> int:
        """t when it is a working minute, else the start of the next working interval."""
        i = bisect_right(self.starts, t) - 1
        if i >= 0 and t < self.ends[i]:
            return t
        return self.starts[i + 1]

    def add(self, t: int, minutes: int) -> int:
        """The instant ``minutes`` business minutes after t (always a working minute, strictly inside an interval)."""
        i = bisect_right(self.starts, t) - 1
        if i < 0 or t >= self.ends[i]:
            i += 1
            t = self.starts[i]
        while True:
            avail = self.ends[i] - t
            if minutes < avail:
                return t + minutes
            minutes -= avail
            i += 1
            t = self.starts[i]


def default_parameters(seed: int) -> dict[str, Any]:
    return {
        "seed": seed, "window_start": WINDOW_START.isoformat(), "window_end": WINDOW_END.isoformat(),
        "snapshot_cut": iso(CUTOFF), "months": 18, "cases": CASES, "organizations": sum(SEGMENTS.values()),
        "segments": SEGMENTS, "regions": list(REGIONS),
        "calendar": {"calendar_id": "cal-001", "timezone": "UTC", "working": "Monday-Friday 09:00-17:00",
                     "holidays": [{"date": d.isoformat(), "name": n, "weekday": d.strftime("%A")}
                                  for d, n in HOLIDAYS]},
        "workflow": {"template_id": "tpl-001", "v1_steps": [s[0] for s in V1_STEPS],
                     "v2_steps": [s[0] for s in V2_STEPS], "v2_published": V2_PUBLISHED.isoformat(),
                     "v2_share_after_publication": V2_SHARE, "required_documents": REQUIRED_DOCS},
        "sla": {"business_minutes": SLA_MINUTES, "pause_policy": PAUSE_POLICY},
        "step_profile_business_minutes": {str(v): {k: list(t) for k, t in p.items()} for v, p in PROFILE.items()},
        "handoff_probability_per_step": {str(v): p for v, p in HANDOFF_P.items()},
        "rejection_probability": {"identity_proof_enterprise": REJECT_P["identity_proof"]["enterprise"],
                                  "identity_proof_other": REJECT_P["identity_proof"]["other"],
                                  "business_registration": 0.03, "address_proof": 0.05},
        "customer_waits": {"info_requests_per_case": {"reg-north": INFO_WAITS["reg-north"],
                                                      "other": INFO_WAITS["other"]},
                           "external_verification_probability": EXT_VERIFY_P,
                           "median_real_minutes": WAIT_MEDIAN, "region_factor": WAIT_REGION_FACTOR},
        "bottleneck": BOTTLENECK, "reviewers_by_role": REVIEWERS,
        "stalled_case_probability": STALL_P,
        "injections": {"completed_missing_document": 2, "conflicting_decision_pairs": 2,
                       "pauses_outside_working": 3, "wrong_reason_code_waits": 3, "self_approvals": 2,
                       "weekend_holidays": 2, "event_only": ["published_version_edit", "draft_dependency_cycle",
                                                             "document_overwrite x2", "dropped_assignment x2",
                                                             "reopen_after_completion", "migration_drops_document"]},
    }


def definition_hash(steps: list[dict], deps: list[dict]) -> str:
    """D-05: sha256 of compact sorted-key JSON of the ordered steps and the dependencies."""
    rows = sorted(steps, key=lambda s: s["sequence"])
    ids = {s["step_definition_id"] for s in rows}
    payload = {"steps": [[s["step_definition_id"], s["step_name"], s["required"], s["role_key"], s["sequence"]]
                         for s in rows],
               "dependencies": [[d["step_definition_id"], d["prerequisite_id"], d["dependency_type"]]
                                for d in sorted(deps, key=lambda d: d["dependency_id"])
                                if d["step_definition_id"] in ids]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Generator:
    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.rng = random.Random(seed)
        self.cal = BusinessCalendar()
        self.P = default_parameters(seed)

    # ---- helpers -----------------------------------------------------------------------------
    def ln(self, median: float, sigma: float = 0.45) -> int:
        return max(1, round(self.rng.lognormvariate(math.log(median), sigma)))

    def pick(self, seq: list) -> Any:
        return seq[self.rng.randrange(len(seq))]

    def weighted(self, options: tuple) -> int:
        u = self.rng.random()
        acc = 0.0
        for value, p in options:
            acc += p
            if u < acc:
                return value
        return options[-1][0]

    # ---- reference data -----------------------------------------------------------------------
    def organizations(self) -> list[dict]:
        rng = self.rng
        segs = ["enterprise"] * SEGMENTS["enterprise"] + ["mid_market"] * SEGMENTS["mid_market"] + \
               ["smb"] * SEGMENTS["smb"]
        order = {"enterprise": ["reg-south", "reg-east", "reg-west", "reg-north", "reg-south", "reg-east"]}
        counters = {s: 0 for s in SEGMENTS}
        names = [(a, b) for a in NAME_A for b in NAME_B]
        rng.shuffle(names)
        longs = list(LONG_NAMES)
        rows = []
        for i, seg in enumerate(segs):
            n = counters[seg]
            counters[seg] += 1
            region = order[seg][n] if seg in order else REGIONS[(n + (1 if seg == "mid_market" else 2)) % 4]
            a, b = names[i]
            name = f"{a} {b} {NAME_C[i % len(NAME_C)]}"
            rows.append({"organization_id": "", "organization_name": name, "segment": seg, "region": region,
                         "created_at": ""})
        rng.shuffle(rows)
        long_slots = rng.sample(range(len(rows)), len(longs))
        for slot, ln_ in zip(long_slots, longs):
            rows[slot]["organization_name"] = ln_
        for i, r in enumerate(rows, 1):
            r["organization_id"] = f"org-{i:04d}"
            r["created_at"] = iso(day_minute(date(2025, 1, 6) + timedelta(days=rng.randrange(0, 80)), 9))
        return rows

    def definitions(self) -> dict[str, list[dict]]:
        v_rows, s_rows, d_rows, sla_rows, req_rows = [], [], [], [], []
        sd_n = dep_n = 0
        published = {1: iso(day_minute(date(2025, 3, 10), 9)), 2: iso(day_minute(V2_PUBLISHED, 9) - 3 * DAY * 0)}
        self.step_ids: dict[int, dict[int, str]] = {1: {}, 2: {}}
        for vn, steps, deps in ((1, V1_STEPS, V1_DEPS), (2, V2_STEPS, V2_DEPS)):
            wid = f"wfv-{vn:03d}"
            vs = []
            for name, role, seq in steps:
                sd_n += 1
                sid = f"sd-{sd_n:03d}"
                self.step_ids[vn][seq] = sid
                vs.append({"step_definition_id": sid, "workflow_version_id": wid, "step_name": name,
                           "required": True, "role_key": role, "sequence": seq})
            vd = []
            for seq, pre in deps:
                dep_n += 1
                vd.append({"dependency_id": f"dep-{dep_n:03d}", "step_definition_id": self.step_ids[vn][seq],
                           "prerequisite_id": self.step_ids[vn][pre], "dependency_type": "mandatory",
                           "created_at": published[vn]})
            v_rows.append({"workflow_version_id": wid, "template_id": "tpl-001", "version_number": vn,
                           "published_at": published[vn], "definition_hash": definition_hash(vs, vd)})
            s_rows += vs
            d_rows += vd
            sla_rows.append({"sla_rule_id": f"sla-{vn:03d}", "workflow_version_id": wid,
                             "business_minutes": SLA_MINUTES, "pause_policy": list(PAUSE_POLICY),
                             "calendar_id": "cal-001"})
            req_rows.append({"workflow_version_id": wid, "required_document_types": list(REQUIRED_DOCS[vn])})
        # version 2 is published a few days before its first case, version 1 before the window
        self.published_min = {1: day_minute(date(2025, 3, 10), 9), 2: day_minute(V2_PUBLISHED, 9)}
        return {"workflow_versions": v_rows, "step_definitions": s_rows, "dependencies": d_rows,
                "sla_rules": sla_rows, "workflow_requirements": req_rows}

    def calendar_rows(self) -> list[dict]:
        rows = []
        d = WINDOW_START
        n = 0
        while d <= WINDOW_END:
            if d.weekday() < 5:
                n += 1
                rows.append({"calendar_interval_id": f"ci-{n:04d}", "calendar_id": "cal-001",
                             "starts_at": iso(day_minute(d, 9)), "ends_at": iso(day_minute(d, 17)),
                             "timezone": "UTC", "kind": "working"})
            d += timedelta(days=1)
        for hd, _ in HOLIDAYS:
            n += 1
            rows.append({"calendar_interval_id": f"ci-{n:04d}", "calendar_id": "cal-001",
                         "starts_at": iso(day_minute(hd, 0)), "ends_at": iso(day_minute(hd, 0) + DAY),
                         "timezone": "UTC", "kind": "holiday"})
        return rows

    # ---- case simulation ----------------------------------------------------------------------
    def opened_instant(self) -> int:
        rng = self.rng
        days = (WINDOW_END - WINDOW_START).days + 1
        if rng.random() < 0.06:  # submitted outside working hours (evening, night or weekend)
            return rng.randrange(0, days * DAY)
        while True:
            d = rng.randrange(0, days)
            t = d * DAY + 9 * 60 + rng.randrange(0, 8 * 60)
            if self.cal.snap(t) == t:
                return t

    def place_wait(self, c: dict, step_idx: int, start: int, duration: int, reason: str) -> int:
        """Record a customer wait that starts at a working minute and overlaps no other wait of the case;
        returns the instant work resumes."""
        s = start
        e = s + duration
        moved = True
        while moved:
            moved = False
            for w in c["waits"]:
                if s < w["e"] and e > w["s"]:
                    s = self.cal.snap(w["e"] + 1)
                    e = s + duration
                    moved = True
        c["waits"].append({"reason": reason, "s": s, "e": e, "step": step_idx})
        return self.cal.snap(e)

    def run_step(self, c: dict, idx: int, ready: int) -> dict:
        rng, cal = self.rng, self.cal
        name, role, seq = c["steps_def"][idx]
        fam = c["fam"]
        q0, w0, r0 = PROFILE[fam][name]
        pool = ASSIGNEES[role]
        if name == "approve_account":
            ap = rng.random()
            approver = BOTTLENECK["reviewer"] if ap < BOTTLENECK["share"] else self.pick(
                [r for r in REVIEWERS["reviewer"] if r != BOTTLENECK["reviewer"]])
        else:
            approver = self.pick(REVIEWERS[role])
        q, w, r = self.ln(q0), self.ln(w0), self.ln(r0)
        if approver == BOTTLENECK["reviewer"] and name == "approve_account":
            q = round(q * BOTTLENECK["queue_factor"])
            r = round(r * BOTTLENECK["review_factor"])
        start = cal.add(ready, q)
        t = start
        plan = c["wait_plan"].get(idx, [])
        seg = max(1, w // (len(plan) + 1))
        for reason, kind in plan:
            t = cal.add(t, seg)
            t = self.place_wait(c, idx, t, self.wait_duration(c, kind), reason)
        t = cal.add(t, seg)
        docs: list[dict] = []
        rejections = 0
        types = list(STEP_DOCS.get(name, ()))
        if name == "approve_account" and rng.random() < OPTIONAL_DOC[1]:
            types.append(OPTIONAL_DOC[0])
        done = t
        for i, dtype in enumerate(types):
            sub = cal.add(t, 2 + 3 * i + rng.randrange(0, 4))
            rev = cal.add(sub, self.ln(max(2, r0 * 0.6)))
            if dtype == "identity_proof":
                p = REJECT_P["identity_proof"]["enterprise" if c["segment"] == "enterprise" else "other"]
            else:
                p = REJECT_P.get(dtype, 0.0)
            if rng.random() < p:
                docs.append({"type": dtype, "ver": 1, "sub": sub, "rev": rev, "status": "rejected", "step": idx})
                ws = cal.add(rev, 1 + rng.randrange(0, 4))
                resume = self.place_wait(c, idx, ws, self.wait_duration(c, "rework"), "customer_info_requested")
                sub2 = cal.add(resume, 5 + rng.randrange(0, 20))
                rev2 = cal.add(sub2, self.ln(max(2, r0 * 0.5)))
                docs.append({"type": dtype, "ver": 2, "sub": sub2, "rev": rev2, "status": "accepted", "step": idx})
                rejections += 1
                done = max(done, rev2)
            else:
                docs.append({"type": dtype, "ver": 1, "sub": sub, "rev": rev, "status": "accepted", "step": idx})
                done = max(done, rev)
        approve_at = cal.add(done, max(1, round(r * 0.4)) if types else r)
        assign = [pool[rng.randrange(len(pool))]]
        extra = 0
        hp = HANDOFF_P[fam][name]
        if rng.random() < hp:
            extra = 1
            if rng.random() < hp / 3:
                extra = 2
        times = [ready]
        if extra:
            fr = sorted(rng.uniform(0.15, 0.85) for _ in range(extra))
            prev = ready
            for f in fr:
                th = min(cal.snap(start + int((approve_at - start) * f)), approve_at - 1)
                th = max(th, prev + 1)
                times.append(th)
                prev = th
                nxt = self.pick([a for a in pool if a != assign[-1]])
                assign.append(nxt)
        chain = []
        for k, who in enumerate(assign):
            end = times[k + 1] if k + 1 < len(times) else approve_at
            chain.append({"who": who, "t0": times[k], "t1": end})
        return {"idx": idx, "name": name, "role": role, "seq": seq, "ready": ready, "start": start,
                "inrev": done, "approve": approve_at, "approver": approver, "version": 1 + rejections, "chain": chain,
                "docs": docs, "status": "approved"}

    def wait_duration(self, c: dict, kind: str) -> int:
        f = WAIT_REGION_FACTOR["reg-north" if c["region"] == "reg-north" else "other"]
        d = self.ln(WAIT_MEDIAN[kind] * f, 0.6)
        return max(120, min(d, 10080))

    def simulate_case(self, org: dict) -> dict:
        rng, cal = self.rng, self.cal
        opened = self.opened_instant()
        if opened >= day_minute(V2_PUBLISHED, 9):
            fam = 2 if rng.random() < V2_SHARE else 1
        else:
            fam = 1
        region = org["region"]
        c = {"org": org["organization_id"], "segment": org["segment"], "region": region, "fam": fam,
             "opened": opened, "steps_def": V1_STEPS if fam == 1 else V2_STEPS, "waits": [], "wait_plan": {},
             "deps": V1_DEPS if fam == 1 else V2_DEPS}
        facing = [0, 1, 2]  # indexes of the customer-facing steps (documents, verification, compliance)
        k = self.weighted(INFO_WAITS["reg-north" if region == "reg-north" else "other"])
        for _ in range(k):
            r = rng.random()
            idx = 0 if r < 0.5 else (1 if r < 0.75 else 2)
            c["wait_plan"].setdefault(facing[idx], []).append(("customer_info_requested", "info"))
        if rng.random() < EXT_VERIFY_P["reg-north" if region == "reg-north" else "other"]:
            c["wait_plan"].setdefault(2, []).append(("external_verification", "verify"))
        done: dict[int, dict] = {}
        steps = []
        for idx, (name, role, seq) in enumerate(c["steps_def"]):
            pre = [pseq - 1 for s2, pseq in c["deps"] if s2 == seq]
            ready = opened if not pre else max(done[p]["approve"] for p in pre)
            st = self.run_step(c, idx, ready)
            done[idx] = st
            steps.append(st)
        c["steps"] = steps
        c["completed"] = max(s["approve"] for s in steps)
        c["final_approver"] = steps[-1]["approver"]
        c["stall"] = None
        if rng.random() < STALL_P:
            if c["waits"] and rng.random() < 0.6:  # the customer never answers
                w = c["waits"][rng.randrange(len(c["waits"]))]
                c["stall"] = w["s"] + 30
            else:  # the work waits for a reviewer's decision that does not come
                c["stall"] = steps[rng.randrange(len(steps))]["inrev"]
        return c

    # ---- truncation at the snapshot cut (or a stall) -> the materialised case ---------------------
    def materialise(self, c: dict, case_no: int) -> dict:
        cut = CUTOFF if c["stall"] is None else min(CUTOFF, c["stall"])
        completed = c["completed"] if c["completed"] <= cut else None
        steps = []
        for s in c["steps"]:
            if s["ready"] > cut:
                st = {"status": "blocked", "version": 1, "ready": None, "start": None, "approved": None,
                      "chain": [], "approval": None, "approver": s["approver"]}
            else:
                chain = [{"who": a["who"], "t0": a["t0"], "t1": (a["t1"] if a["t1"] <= cut else None)}
                         for a in s["chain"] if a["t0"] <= cut]
                started = s["start"] if s["start"] <= cut else None
                if s["approve"] <= cut:
                    status, approved, approval = "approved", s["approve"], {"reviewer": s["approver"],
                                                                            "t": s["approve"]}
                else:
                    approved, approval = None, None
                    sub = [d for d in s["docs"] if d["sub"] <= cut]
                    rejected_open = any(d["status"] == "rejected" and d["rev"] <= cut and not any(
                        e["type"] == d["type"] and e["ver"] == 2 and e["sub"] <= cut for e in s["docs"])
                        for d in s["docs"])
                    if started is None:
                        status = "ready"
                    elif rejected_open:
                        status = "changes_requested"
                    elif cut >= s["inrev"]:
                        status = "in_review"
                    else:
                        status = "in_progress"
                rej_seen = sum(1 for d in s["docs"] if d["status"] == "rejected" and d["rev"] <= cut)
                version = 1 + rej_seen
                st = {"status": status, "version": version, "ready": s["ready"], "start": started,
                      "approved": approved, "chain": chain, "approval": approval, "approver": s["approver"]}
            st.update({"name": s["name"], "role": s["role"], "seq": s["seq"], "idx": s["idx"], "extra_approvals": []})
            steps.append(st)
        docs = []
        for s in c["steps"]:
            for d in s["docs"]:
                if d["sub"] > cut:
                    continue
                reviewed = d["rev"] if d["rev"] <= cut else None
                status = d["status"] if reviewed is not None else "submitted"
                docs.append({"type": d["type"], "ver": d["ver"], "sub": d["sub"], "rev": reviewed, "status": status,
                             "step": d["step"]})
        waits = []
        for w in c["waits"]:
            if w["s"] > cut:
                continue
            waits.append({"reason": w["reason"], "s": w["s"], "e": w["e"] if w["e"] <= cut else None,
                          "step": w["step"], "pause_requested": False})
        return {"case_no": case_no, "org": c["org"], "segment": c["segment"], "region": c["region"],
                "fam": c["fam"], "opened": c["opened"], "completed": completed, "steps": steps, "docs": docs,
                "waits": waits, "final_approver": c["final_approver"], "tags": []}

    # ---- defect injection (entity-file defects) -------------------------------------------------
    def inject(self, ms: list[dict]) -> dict[str, list]:
        rng = self.rng
        done = [m for m in ms if m["completed"] is not None and not m["tags"]]
        used: set[int] = set()
        out: dict[str, list] = {}

        def take(pred, n: int, tag: str) -> list[dict]:
            cand = [m for m in done if m["case_no"] not in used and pred(m)]
            rng.shuffle(cand)
            if len(cand) < n:
                raise RuntimeError(f"not enough cases for {tag}: {len(cand)} < {n}")
            got = cand[:n]
            for m in got:
                used.add(m["case_no"])
                m["tags"].append(tag)
            return got

        # 1. completed with a required document missing
        a = take(lambda m: m["fam"] == 1, 1, "missing_document")[0]
        a["docs"] = [d for d in a["docs"] if d["type"] != "business_registration"]
        b = take(lambda m: m["fam"] == 2, 1, "missing_document")[0]
        for d in b["docs"]:
            if d["type"] == "business_registration":
                d["status"], d["rev"] = "submitted", None
        out["missing_document"] = [a, b]

        # 2. pauses outside the working intervals (a Saturday, a Sunday, a weekday holiday)
        def window_for(kind: str, m: dict):
            lo, hi = m["opened"] + 60, m["completed"] - 60
            day0 = lo // DAY
            for dnum in range(day0, hi // DAY + 1):
                dd = WINDOW_START + timedelta(days=dnum)
                if kind == "saturday" and dd.weekday() == 5 and dd not in {h for h, _ in HOLIDAYS}:
                    s, e = day_minute(dd, 6), day_minute(dd, 20)
                elif kind == "sunday" and dd.weekday() == 6 and dd not in {h for h, _ in HOLIDAYS}:
                    s, e = day_minute(dd, 7), day_minute(dd, 22)
                elif kind == "holiday" and dd in {h for h, _ in HOLIDAYS if h.weekday() < 5}:
                    s, e = day_minute(dd, 10), day_minute(dd, 15)
                else:
                    continue
                if s >= lo and e <= hi and not any(s < w["e"] and e > w["s"] for w in m["waits"] if w["e"]):
                    return s, e
            return None

        pauses = []
        for kind in ("saturday", "sunday", "holiday"):
            m = take(lambda m, k=kind: window_for(k, m) is not None, 1, "pause_outside_working")[0]
            s, e = window_for(kind, m)
            w = {"reason": "customer_info_requested", "s": s, "e": e, "step": 0, "pause_requested": False,
                 "injected": kind}
            m["waits"].append(w)
            pauses.append((m, w))
        out["pause_outside_working"] = pauses

        # 3. customer waits labelled as work
        labels = ["internal_processing", "document_review", "manual_check"]
        wrong = []
        for label in labels:
            m = take(lambda m: any(w["reason"] == "customer_info_requested" and w["e"] for w in m["waits"]),
                     1, "wrong_reason_code")[0]
            w = next(w for w in m["waits"] if w["reason"] == "customer_info_requested" and w["e"])
            w["reason"] = label
            w["pause_requested"] = True
            w["injected"] = "wrong_reason_code"
            wrong.append((m, w))
        out["wrong_reason"] = wrong

        # 4. self-approvals: the reviewer of approve_account was an assignee of the step
        selfs = []
        for _ in range(2):
            m = take(lambda m: True, 1, "self_approval")[0]
            st = next(s for s in m["steps"] if s["name"] == "approve_account")
            st["chain"][-1]["who"] = st["approval"]["reviewer"]
            selfs.append((m, st))
        out["self_approval"] = selfs

        # 5. conflicting decisions: a second decision on the same step version by another reviewer
        conflicts = []
        for step_name in ("approve_account", "compliance_review"):
            m = take(lambda m: True, 1, "decision_conflict")[0]
            st = next(s for s in m["steps"] if s["name"] == step_name)
            other = self.pick([r for r in REVIEWERS[st["role"]] if r != st["approval"]["reviewer"]]
                              if len(REVIEWERS[st["role"]]) > 1 else REVIEWERS[st["role"]])
            st["extra_approvals"].append({"reviewer": other, "t": st["approval"]["t"] + 7, "decision": "rejected",
                                          "reason": "conflicting decision on the same step version"})
            conflicts.append((m, st))
        out["conflict"] = conflicts
        return out

    # ---- rows -----------------------------------------------------------------------------------
    def events_for(self, m: dict, case_id: str) -> list[tuple]:
        ev = []

        def who(step: dict, t: int) -> str:
            chain = step["chain"]
            for a in chain:
                if a["t0"] <= t and (a["t1"] is None or t <= a["t1"]):
                    return a["who"]
            return chain[0]["who"] if chain else "ops-001"

        steps = m["steps"]
        first = steps[0]["chain"][0]["who"] if steps[0]["chain"] else "ops-001"
        ev.append((m["opened"], 0, "case_opened", first))
        for s in steps:
            if s["start"] is not None:
                ev.append((s["start"], 3, "step_started", who(s, s["start"])))
            if s["approval"] is not None:
                ev.append((s["approval"]["t"], 6, "step_approved", s["approval"]["reviewer"]))
        for d in m["docs"]:
            st = steps[d["step"]]
            ev.append((d["sub"], 2, "document_submitted", who(st, d["sub"])))
            if d["rev"] is not None and d["status"] == "rejected":  # acceptances are on document_versions
                ev.append((d["rev"], 2, "document_rejected", st["approver"]))
        for w in m["waits"]:
            st = steps[w["step"]]
            ev.append((w["s"], 4, "waiting_started", who(st, w["s"])))
            if w["e"] is not None:
                ev.append((w["e"], 1, "waiting_ended", who(st, w["e"])))
        if m["completed"] is not None:
            ev.append((m["completed"], 9, "case_completed", m["final_approver"]))
        ev.sort(key=lambda e: (e[0], e[1]))
        return ev

    def build(self) -> dict[str, Any]:
        rng = self.rng
        orgs = self.organizations()
        defs = self.definitions()
        weights = [SEGMENT_WEIGHT[o["segment"]] for o in orgs]
        sims = []
        for _ in range(CASES):
            org = rng.choices(orgs, weights)[0]
            sims.append(self.simulate_case(org))
        sims.sort(key=lambda c: (c["opened"], c["org"]))
        ms = [self.materialise(c, i) for i, c in enumerate(sims, 1)]
        for i, m in enumerate(ms, 1):
            m["case_id"] = f"case-{i:06d}"
        inj = self.inject(ms)

        ents: dict[str, list[dict]] = {name: [] for name in ENTITIES}
        ents["organizations"] = orgs
        for k in ("workflow_versions", "step_definitions", "dependencies", "sla_rules", "workflow_requirements"):
            ents[k] = defs[k]
        ents["calendar_intervals"] = self.calendar_rows()
        sd_ids = {1: {s[0]: self.step_ids[1][s[2]] for s in V1_STEPS}, 2: {s[0]: self.step_ids[2][s[2]]
                                                                           for s in V2_STEPS}}
        n_si = n_asg = n_dv = n_apr = n_wi = n_ev = 0
        ids: dict[int, dict] = {}
        for m in ms:
            cid = m["case_id"]
            ents["cases"].append({"case_id": cid, "organization_id": m["org"],
                                  "workflow_version_id": f"wfv-{m['fam']:03d}",
                                  "status": "completed" if m["completed"] is not None else "open",
                                  "opened_at": iso(m["opened"]),
                                  "completed_at": iso(m["completed"]) if m["completed"] is not None else None})
            rec = {"steps": {}, "approvals": {}, "extra": {}, "waits": {}}
            for s in m["steps"]:
                n_si += 1
                sid = f"si-{n_si:06d}"
                rec["steps"][s["name"]] = sid
                ents["step_instances"].append({
                    "step_instance_id": sid, "case_id": cid, "step_definition_id": sd_ids[m["fam"]][s["name"]],
                    "status": s["status"], "version_number": s["version"],
                    "ready_at": iso(s["ready"]) if s["ready"] is not None else None,
                    "started_at": iso(s["start"]) if s["start"] is not None else None,
                    "approved_at": iso(s["approved"]) if s["approved"] is not None else None})
                s["_id"] = sid
                s["_asg"] = []
                for a in s["chain"]:
                    n_asg += 1
                    aid = f"asg-{n_asg:06d}"
                    s["_asg"].append(aid)
                    ents["assignments"].append({"assignment_id": aid, "step_instance_id": sid,
                                                "assignee_id": a["who"], "assigned_at": iso(a["t0"]),
                                                "ended_at": iso(a["t1"]) if a["t1"] is not None else None})
            for d in sorted(m["docs"], key=lambda d: (d["sub"], d["type"], d["ver"])):
                n_dv += 1
                h = hashlib.sha256(f"{cid}|{d['type']}|{d['ver']}".encode()).hexdigest()
                d["_id"] = f"dv-{n_dv:06d}"
                ents["document_versions"].append({
                    "document_version_id": d["_id"], "case_id": cid, "document_type": d["type"],
                    "version_number": d["ver"], "content_hash": f"sha256:{h}", "review_status": d["status"],
                    "submitted_at": iso(d["sub"]), "reviewed_at": iso(d["rev"]) if d["rev"] is not None else None})
            for s in m["steps"]:
                if s["approval"] is not None:
                    n_apr += 1
                    s["_apr"] = f"apr-{n_apr:06d}"
                    ents["approvals"].append({"approval_id": s["_apr"], "step_instance_id": s["_id"],
                                              "reviewer_id": s["approval"]["reviewer"], "decision": "approved",
                                              "decided_at": iso(s["approval"]["t"]), "reason": None})
                    s["_apr_extra"] = []
                    for x in s["extra_approvals"]:
                        n_apr += 1
                        aid = f"apr-{n_apr:06d}"
                        s["_apr_extra"].append(aid)
                        ents["approvals"].append({"approval_id": aid, "step_instance_id": s["_id"],
                                                  "reviewer_id": x["reviewer"], "decision": x["decision"],
                                                  "decided_at": iso(x["t"]), "reason": x["reason"]})
            for w in sorted(m["waits"], key=lambda w: w["s"]):
                n_wi += 1
                w["_id"] = f"wi-{n_wi:05d}"
                row = {"waiting_interval_id": w["_id"], "case_id": cid, "reason_code": w["reason"],
                       "starts_at": iso(w["s"]), "ends_at": iso(w["e"]) if w["e"] is not None else None}
                if w["pause_requested"]:
                    row["pause_requested"] = True
                ents["waiting_intervals"].append(row)
            for t, _p, typ, actor in self.events_for(m, cid):
                n_ev += 1
                ents["case_events"].append({"event_id": f"ev-{n_ev:06d}", "case_id": cid, "event_type": typ,
                                            "actor_id": actor, "occurred_at": iso(t)})
        injections = self.injection_manifest(ms, inj)
        events = self.injection_events(ms, injections)
        return {"entities": ents, "injections": injections["list"], "events": events,
                "parameters": self.P, "designed": self.designed(), "materialised": ms}

    # ---- designed relationships ------------------------------------------------------------------
    def designed(self) -> list[str]:
        return [
            "workflow version 2 (published 2025-10-01, 60 % of later cases) removes the verify_identity handoff and "
            "adds a parallel collect_address_proof step: about 35 % lower active elapsed time and about 20 % fewer "
            "handoffs per case than version 1 (synthetic).",
            "enterprise organizations have about 2x the rework rate: identity_proof rejection probability 0.20 vs "
            "0.11 (synthetic).",
            "region reg-north has longer customer waiting: more customer_info_requested / external_verification "
            "pauses per case (mean 1.65 vs 0.9) and each about 1.4x longer, so paused_time_hours is highest "
            "(synthetic).",
            "bottleneck at step approve_account for reviewer rev-004: 40 % of reviews, queue x3.6 and review x3.4 "
            "slower than rev-005 / rev-006 (synthetic).",
        ]

    # ---- injection manifest ----------------------------------------------------------------------
    def injection_manifest(self, ms: list[dict], inj: dict[str, list]) -> dict[str, Any]:
        mk = []
        mk.append({"id": "INJ-01", "test": "P02-TEST-01", "entity": "cases", "location": "entity_files",
                   "record_ids": [m["case_id"] for m in inj["missing_document"]],
                   "description": "2 cases completed with a required document missing: "
                                  f"{inj['missing_document'][0]['case_id']} has no business_registration version; "
                                  f"{inj['missing_document'][1]['case_id']} has a business_registration version "
                                  "that was never accepted.",
                   "expected_handling": "ingest rejects each case and every row hanging off it with "
                                        "MISSING_REQUIRED_DOCUMENT; raw rows are kept; none enters the population."})
        mk.append({"id": "INJ-02", "test": "P02-TEST-02", "entity": "approvals", "location": "entity_files+events",
                   "record_ids": [s["_apr_extra"][0] for _, s in inj["conflict"]],
                   "step_instance_ids": [s["_id"] for _, s in inj["conflict"]],
                   "case_ids": [m["case_id"] for m, _ in inj["conflict"]],
                   "first_decision_ids": [s["_apr"] for _, s in inj["conflict"]],
                   "description": "2 pairs of conflicting decisions on one step version: an approval followed 7 "
                                  "minutes later by a 'rejected' decision from another reviewer, no version number.",
                   "expected_handling": "ingest keeps the earlier decision and rejects the later approval row "
                                        "with DECISION_CONFLICT (only that row); the replay events show the same "
                                        "conflict through approve-step."})
        mk.append({"id": "INJ-03", "test": "P02-TEST-03", "entity": "waiting_intervals", "location": "entity_files",
                   "record_ids": [w["_id"] for _, w in inj["pause_outside_working"]],
                   "case_ids": [m["case_id"] for m, _ in inj["pause_outside_working"]],
                   "kinds": [w["injected"] for _, w in inj["pause_outside_working"]],
                   "description": "3 customer_info_requested pauses that lie wholly outside every working "
                                  "interval (a Saturday, a Sunday and a weekday holiday) inside completed cases.",
                   "expected_handling": "the pipeline accepts them, deducts 0 business hours and returns a "
                                        "PAUSE_OUTSIDE_WORKING_INTERVAL flag for each."})
        mk.append({"id": "INJ-04", "test": "P02-TEST-04", "entity": "workflow_versions", "location": "events",
                   "record_ids": ["wfv-001"],
                   "description": "an attempted edit of the published workflow version wfv-001 (publish again; a "
                                  "direct UPDATE of a step definition).",
                   "expected_handling": "409 ALREADY_PUBLISHED; the UPDATE is refused by the immutability trigger."})
        mk.append({"id": "INJ-05", "test": "P02-TEST-05", "entity": "workflow_versions", "location": "events",
                   "record_ids": ["wfv-003"],
                   "description": "a draft version wfv-003 whose dependencies form a cycle (sd-901 -> sd-902 -> "
                                  "sd-903 -> sd-901); it is not in the entity files because the seed would reject it.",
                   "expected_handling": "publish-workflow-version rejects it with DEPENDENCY_CYCLE (Kahn)."})
        mk.append({"id": "INJ-06", "test": "P02-TEST-06", "entity": "document_versions", "location": "events",
                   "record_ids": [], "description": "2 resubmissions that would overwrite an accepted document "
                                                    "version (resubmit-document on an accepted type; a direct "
                                                    "UPDATE of a document_versions row).",
                   "expected_handling": "resubmit-document is refused with NOT_IN_CHANGES_REQUESTED; the UPDATE is "
                                        "refused by the append-only trigger; the prior row stays intact."})
        mk.append({"id": "INJ-07", "test": "P02-TEST-07", "entity": "assignments", "location": "events",
                   "record_ids": [], "description": "2 reassignments that drop the prior assignment interval "
                                                    "instead of closing it.",
                   "expected_handling": "reassign-work is an extension command (501 NOT_IMPLEMENTED now); when it "
                                        "ships the prior interval must be closed with ended_at, never deleted."})
        hol = [d.isoformat() for d, _ in HOLIDAYS if d.weekday() >= 5]
        mk.append({"id": "INJ-08", "test": "P02-TEST-08", "entity": "calendar_intervals", "location": "entity_files",
                   "record_ids": [r["calendar_interval_id"] for r in self._cal if r["kind"] == "holiday"
                                  and r["starts_at"][:10] in hol],
                   "dates": hol,
                   "description": "2 of the 6 holidays fall on a weekend (2026-02-14 Saturday, 2026-07-04 "
                                  "Saturday).",
                   "expected_handling": "a holiday on a weekend subtracts nothing from the working set."})
        mk.append({"id": "INJ-09", "test": "P02-TEST-09", "entity": "waiting_intervals", "location": "entity_files",
                   "record_ids": [w["_id"] for _, w in inj["wrong_reason"]],
                   "case_ids": [m["case_id"] for m, _ in inj["wrong_reason"]],
                   "reason_codes": [w["reason"] for _, w in inj["wrong_reason"]],
                   "description": "3 customer waits labelled as work: reason_code internal_processing / "
                                  "document_review / manual_check with pause_requested true.",
                   "expected_handling": "ingest rejects each case and its rows with PAUSE_REASON_NOT_CONFIGURED."})
        mk.append({"id": "INJ-10", "test": "P02-TEST-10", "entity": "approvals", "location": "entity_files",
                   "record_ids": [s["_apr"] for _, s in inj["self_approval"]],
                   "case_ids": [m["case_id"] for m, _ in inj["self_approval"]],
                   "description": "2 self-approvals: the approve_account reviewer was also the last assignee of "
                                  "the step.",
                   "expected_handling": "ingest rejects each case and its rows with SELF_APPROVAL."})
        mk.append({"id": "INJ-11", "test": "P02-TEST-11", "entity": "cases", "location": "events",
                   "record_ids": [], "description": "a reopen of a completed case.",
                   "expected_handling": "reopen-case is refused with 409 CASE_REOPEN_FORBIDDEN; a linked "
                                        "correction case is opened with create-case (corrects_case_id)."})
        mk.append({"id": "INJ-12", "test": "P02-TEST-12", "entity": "document_versions", "location": "events",
                   "record_ids": [], "description": "a workflow migration whose step mapping drops an accepted "
                                                    "document.",
                   "expected_handling": "migrate-workflow is an extension command (501 NOT_IMPLEMENTED now); "
                                        "accepted documents must be carried by document_type, never dropped."})
        return {"list": mk}

    # ---- replay-only events ----------------------------------------------------------------------
    def injection_events(self, ms: list[dict], manifest: dict[str, Any]) -> list[dict]:
        ev: list[dict] = []
        by_inj = {i["id"]: i for i in manifest["list"]}
        open_cases = [m for m in ms if m["completed"] is None and not m["tags"]]
        ADMIN = {"X-Actor-Id": "adm-001", "X-Actor-Role": "admin"}

        # INJ-02: two in-review steps of open cases get two decisions
        want = ["compliance_review", "approve_account"]
        for step_name in want:
            m = next(m for m in open_cases if any(s["name"] == step_name and s["status"] == "in_review"
                                                  for s in m["steps"]))
            s = next(s for s in m["steps"] if s["name"] == step_name and s["status"] == "in_review")
            pool = [r for r in REVIEWERS[s["role"]] if r not in {a["who"] for a in s["chain"]}]
            first, second = pool[0], pool[-1] if len(pool) > 1 else pool[0]
            for who, expect in ((first, None), (second, "DECISION_CONFLICT")):
                e = {"injection": "INJ-02", "command": "approve-step",
                     "headers": {"X-Actor-Id": who,
                                 "X-Actor-Role": s["role"] if s["role"] in ("ops", "reviewer") else "admin"},
                     "input": {"step_instance_id": s["_id"], "expected_version": s["version"],
                               "occurred_at": iso(CUTOFF + 60 if expect is None else CUTOFF + 67),
                               "reason": "first decision" if expect is None else "conflicting second decision"},
                     "case_id": m["case_id"]}
                if expect is None:
                    e["expected_status"] = 200
                    e["expected_handling"] = "the first decision is accepted (200)"
                else:
                    e["expected_error_code"] = expect
                    e["expected_handling"] = ("a second decision on the same step version is refused with 409 "
                                              "DECISION_CONFLICT; the first stands")
                ev.append(e)
        # INJ-04 published version edit
        ev.append({"injection": "INJ-04", "command": "publish-workflow-version", "headers": ADMIN,
                   "input": {"workflow_version_id": "wfv-001", "occurred_at": iso(CUTOFF + 120)},
                   "expected_error_code": "ALREADY_PUBLISHED",
                   "expected_handling": "409; a published workflow version is immutable and keeps its definition_hash"})
        ev.append({"injection": "INJ-04", "command": "sql",
                   "statement": "UPDATE step_definitions SET step_name = 'collect_documents_v1_edited' "
                                "WHERE step_definition_id = 'sd-001'",
                   "expected_error_code": "integrity_constraint_violation",
                   "expected_handling": "refused by the step_definitions_immutable trigger (published version)"})
        # INJ-05 dependency cycle in a draft version
        ev.append({"injection": "INJ-05", "command": "publish-workflow-version", "headers": ADMIN,
                   "input": {"workflow_version_id": "wfv-003", "template_id": "tpl-001", "version_number": 3,
                             "occurred_at": iso(CUTOFF + 180),
                             "steps": [{"step_definition_id": "sd-901", "step_name": "collect_documents",
                                        "required": True, "role_key": "ops", "sequence": 1},
                                       {"step_definition_id": "sd-902", "step_name": "compliance_review",
                                        "required": True, "role_key": "compliance", "sequence": 2},
                                       {"step_definition_id": "sd-903", "step_name": "approve_account",
                                        "required": True, "role_key": "reviewer", "sequence": 3}],
                             "dependencies": [
                                 {"dependency_id": "dep-901", "step_definition_id": "sd-902",
                                  "prerequisite_id": "sd-901", "dependency_type": "mandatory"},
                                 {"dependency_id": "dep-902", "step_definition_id": "sd-903",
                                  "prerequisite_id": "sd-902", "dependency_type": "mandatory"},
                                 {"dependency_id": "dep-903", "step_definition_id": "sd-901",
                                  "prerequisite_id": "sd-903", "dependency_type": "mandatory"}],
                             "required_document_types": ["identity_proof"],
                             "sla_rule": {"sla_rule_id": "sla-903", "business_minutes": SLA_MINUTES,
                                          "pause_policy": list(PAUSE_POLICY), "calendar_id": "cal-001"}},
                   "expected_error_code": "DEPENDENCY_CYCLE",
                   "expected_handling": "422; the version is not published and nothing is written"})
        # INJ-06 overwriting a document version (two open cases with an accepted document)
        picks = [m for m in open_cases if any(d["status"] == "accepted" and d["type"] == "identity_proof"
                                              for d in m["docs"])][:2]
        for m in picks:
            d = next(d for d in m["docs"] if d["type"] == "identity_proof" and d["status"] == "accepted")
            ev.append({"injection": "INJ-06", "command": "resubmit-document",
                       "headers": {"X-Actor-Id": "ops-001", "X-Actor-Role": "ops"},
                       "input": {"case_id": m["case_id"], "document_type": "identity_proof",
                                 "occurred_at": iso(CUTOFF + 240)},
                       "expected_error_code": "NOT_IN_CHANGES_REQUESTED",
                       "expected_handling": "an accepted document version cannot be overwritten; a new version needs "
                                            "a prior rejection and the prior row stays intact",
                       "document_version_id": d["_id"]})
        ev.append({"injection": "INJ-06", "command": "sql",
                   "statement": "UPDATE document_versions SET content_hash = 'sha256:' || repeat('0', 64) "
                                f"WHERE document_version_id = '{next(d for d in picks[0]['docs'] if d['type'] == 'identity_proof')['_id']}'",
                   "expected_error_code": "integrity_constraint_violation",
                   "expected_handling": "refused by the document_versions_append_only trigger"})
        # INJ-07 reassignment that drops the prior interval
        multi = [m for m in open_cases if any(s["status"] in ("ready", "in_progress", "in_review") and s["chain"]
                                              for s in m["steps"])][:2]
        for m in multi:
            s = next(s for s in m["steps"] if s["status"] in ("ready", "in_progress", "in_review") and s["chain"])
            ev.append({"injection": "INJ-07", "command": "reassign-work",
                       "headers": {"X-Actor-Id": "ops-001", "X-Actor-Role": "ops"},
                       "input": {"step_instance_id": s["_id"], "assignee_id": "ops-016", "drop_prior_interval": True,
                                 "occurred_at": iso(CUTOFF + 300)},
                       "expected_error_code": "NOT_IMPLEMENTED",
                       "expected_handling": "501 in this milestone; once implemented the prior assignment gets "
                                            "ended_at and is never deleted, so waiting time is preserved",
                       "prior_assignment_ids": s["_asg"]})
        # INJ-11 reopen after completion
        done = next(m for m in ms if m["completed"] is not None and not m["tags"])
        ev.append({"injection": "INJ-11", "command": "reopen-case",
                   "headers": {"X-Actor-Id": "adm-001", "X-Actor-Role": "admin"},
                   "input": {"case_id": done["case_id"]}, "expected_error_code": "CASE_REOPEN_FORBIDDEN",
                   "expected_handling": "409; a completed case cannot be reopened, open a linked correction case"})
        # INJ-12 migration dropping an accepted document
        om = next(m for m in open_cases if m["fam"] == 1 and any(d["status"] == "accepted" for d in m["docs"]))
        ev.append({"injection": "INJ-12", "command": "migrate-workflow", "headers": ADMIN,
                   "input": {"case_id": om["case_id"], "from_workflow_version_id": "wfv-001",
                             "to_workflow_version_id": "wfv-002", "step_mapping": {"sd-002": None},
                             "drop_document_types": ["identity_proof"], "occurred_at": iso(CUTOFF + 360)},
                   "expected_error_code": "NOT_IMPLEMENTED",
                   "expected_handling": "501 in this milestone; once implemented accepted documents are carried by "
                                        "document_type and never dropped, unresolved steps are listed"})
        # fill record ids that are only known now
        by_inj["INJ-06"]["record_ids"] = [e["document_version_id"] for e in ev if e.get("document_version_id")]
        by_inj["INJ-07"]["record_ids"] = [a for e in ev if e.get("prior_assignment_ids") for a in e["prior_assignment_ids"]]
        by_inj["INJ-11"]["record_ids"] = [done["case_id"]]
        by_inj["INJ-12"]["record_ids"] = [om["case_id"]]
        for e in ev:
            e.pop("document_version_id", None)
            e.pop("prior_assignment_ids", None)
        return ev


def canonical_rows(rows: list[dict]) -> str:
    return json.dumps(rows, sort_keys=True, separators=(",", ":"))


def dataset_hash(entities: dict[str, list[dict]]) -> str:
    h = hashlib.sha256()
    for name in sorted(entities):
        h.update(canonical_rows(entities[name]).encode())
    return h.hexdigest()


def entity_text(name: str, version: str, rows: list[dict]) -> str:
    body = ",\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in rows)
    return f'{{"entity":{json.dumps(name)},"dataset_version":{json.dumps(version)},"rows":[\n{body}\n]}}\n'


def build(seed: int) -> dict[str, Any]:
    g = Generator(seed)
    g._cal = g.calendar_rows()
    return g.build()


def write_all(seed: int, out: Path, data_dir: Path) -> dict[str, Any]:
    built = build(seed)
    ents = built["entities"]
    version = f"os-{seed}-{DATE_TAG}"
    dhash = dataset_hash(ents)
    out.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in ENTITIES:
        (out / f"{name}.json").write_text(entity_text(name, version, ents[name]))
    inj_manifest = {"dataset_version": version, "dataset_hash": dhash, "seed": seed,
                    "contract_version": CONTRACT_VERSION, "injections": built["injections"],
                    "designed_relationships": built["designed"], "events_file": "data/injection-events.json"}
    inj_text = json.dumps(inj_manifest, indent=2, sort_keys=True) + "\n"
    (data_dir / "injection-manifest.json").write_text(inj_text)
    (out / "injection-manifest.json").write_text(inj_text)
    (data_dir / "injection-events.json").write_text(json.dumps(
        {"dataset_version": version, "events": built["events"]}, indent=2, sort_keys=True) + "\n")
    manifest = {
        "dataset_version": version, "dataset_hash": dhash,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "contract_version": CONTRACT_VERSION,
        "generator": {"name": "generate.py", "seed": seed, "parameters": built["parameters"]},
        "row_counts": {name: len(ents[name]) for name in ENTITIES},
        "designed_relationships": built["designed"],
        "injection_manifest": "injection-manifest.json",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def shape_check(seed: int) -> int:
    golden = json.loads((APP_ROOT / "tests" / "fixtures" / "golden" / "inputs.json").read_text())
    ents = build(seed)["entities"]
    bad = 0
    for name, g_rows in golden.items():
        if not isinstance(g_rows, list) or name not in ents or not g_rows or not isinstance(g_rows[0], dict):
            continue
        want = set(g_rows[0])
        for row in ents[name]:
            if not want <= set(row) <= want | {"kind", "pause_requested"}:
                print(f"SHAPE MISMATCH {name}: {sorted(set(row) ^ want)}")
                bad += 1
                break
        else:
            print(f"ok {name}: {sorted(want)}")
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--out", type=Path, default=APP_ROOT / "web" / "public" / "data")
    ap.add_argument("--data-dir", type=Path, default=APP_ROOT / "data",
                    help="where injection-manifest.json and injection-events.json go")
    ap.add_argument("--profile", choices=("default", "golden-shape-check"), default="default")
    args = ap.parse_args(argv)
    if args.profile == "golden-shape-check":
        return shape_check(args.seed)
    t0 = time.perf_counter()
    m = write_all(args.seed, args.out, args.data_dir)
    total = sum(p.stat().st_size for p in args.out.glob("*.json"))
    print(json.dumps({"dataset_version": m["dataset_version"], "dataset_hash": m["dataset_hash"],
                      "row_counts": m["row_counts"], "bytes": total,
                      "elapsed_seconds": round(time.perf_counter() - t0, 2)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
