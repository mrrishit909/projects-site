"""Synthetic data generator: determinism, shapes, sizes, spec ranges, designed relationships, injected defects.

The generator (data/generate.py) is stdlib only and shares no code with the domain; these tests run the domain over its
output (ingest, metrics, disclosures, the simulator) to show that every designed relationship and every injected defect is
detectable, and, when DATABASE_URL is set, that data/seed.py loads the dataset, data/sql/reference_metrics.sql agrees
with the domain on the full window and the training window, and every replay-only event behaves as recorded.
"""
from __future__ import annotations

import collections
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "domain", ROOT, ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_spec = importlib.util.spec_from_file_location("sf_generate", ROOT / "data" / "generate.py")
gen = importlib.util.module_from_spec(_spec)
sys.modules["sf_generate"] = gen
_spec.loader.exec_module(gen)

from serviceflow import compute_metrics, run_pipeline, simulate  # noqa: E402
from serviceflow.metrics import disclosures, histories, staffed_minutes  # noqa: E402
from serviceflow.models import Population, Shift  # noqa: E402
from serviceflow.simulation import holdout_report  # noqa: E402
from serviceflow.timeutil import local_to_utc, nearest_rank, parse_ts  # noqa: E402
from fractions import Fraction  # noqa: E402

SEED = 20261026
VERSION = f"sf-{SEED}-20261026"
GOLDEN = ROOT / "tests" / "fixtures" / "golden"
BUDGET = 5_000_000
WINDOW = (parse_ts("2026-07-06T00:00:00Z"), parse_ts("2026-09-28T00:00:00Z"))
TRAIN = (parse_ts("2026-07-06T00:00:00Z"), parse_ts("2026-08-31T00:00:00Z"))
HOLDOUT = (parse_ts("2026-08-31T00:00:00Z"), parse_ts("2026-09-28T00:00:00Z"))
STAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("gen")
    out, meta = tmp / "out", tmp / "meta"
    manifest = gen.write_all(SEED, out, meta)
    rows = {}
    for name in gen.ENTITIES:
        doc = json.loads((out / f"{name}.json").read_text())
        assert doc["entity"] == name and doc["dataset_version"] == VERSION and list(doc) == ["entity", "dataset_version", "rows"]
        rows[name] = doc["rows"]
    inj_doc = json.loads((meta / "injection-manifest.json").read_text())
    return {"out": out, "meta": meta, "manifest": manifest, "rows": rows, "inj_doc": inj_doc,
            "inj": {i["id"]: i for i in inj_doc["injections"]},
            "events": {e["event_id"]: e for e in json.loads((meta / "injection-events.json").read_text())["events"]}}


@pytest.fixture(scope="module")
def inputs(built):
    return {"contract_version": 1, "window_start": "2026-07-06T00:00:00Z", "window_end": "2026-09-28T00:00:00Z",
            "backlog_cutoffs": ["2026-09-27T23:59:59Z"], "abandonable_channels": ["chat", "phone"],
            **{k: v for k, v in built["rows"].items() if k in gen.DOMAIN_ENTITIES}}


@pytest.fixture(scope="module")
def result(inputs):
    return run_pipeline(inputs)


def _expected_rejections(built) -> set[tuple[str, str, str]]:
    return {(r["entity"], r["id"], r["reason_code"]) for i in built["inj"].values() for r in i.get("expected_rejections", [])}


# --- determinism, files, manifest -------------------------------------------------------------------------------
def test_deterministic_across_runs_and_hash_seeds(built, tmp_path):
    again = gen.write_all(SEED, tmp_path / "out", tmp_path / "meta")
    assert again["dataset_hash"] == built["manifest"]["dataset_hash"]
    for name in gen.ENTITIES:
        assert (tmp_path / "out" / f"{name}.json").read_bytes() == (built["out"] / f"{name}.json").read_bytes()
    assert (tmp_path / "meta" / "injection-events.json").read_bytes() == (built["meta"] / "injection-events.json").read_bytes()
    assert (tmp_path / "meta" / "injection-manifest.json").read_bytes() == (built["meta"] / "injection-manifest.json").read_bytes()
    other = gen.write_all(SEED + 1, tmp_path / "o2", tmp_path / "m2")
    assert other["dataset_hash"] != again["dataset_hash"]
    for hash_seed in ("0", "1", "2"):         # a fresh interpreter per PYTHONHASHSEED: nothing depends on set order
        out, meta = tmp_path / f"h{hash_seed}", tmp_path / f"hm{hash_seed}"
        proc = subprocess.run([sys.executable, str(ROOT / "data" / "generate.py"), "--seed", str(SEED), "--out", str(out),
                               "--data-dir", str(meta)], capture_output=True, text=True,
                              env={**os.environ, "PYTHONHASHSEED": hash_seed})
        assert proc.returncode == 0, proc.stderr
        for name in gen.ENTITIES:
            assert (out / f"{name}.json").read_bytes() == (built["out"] / f"{name}.json").read_bytes(), (hash_seed, name)
        assert (meta / "injection-events.json").read_bytes() == (built["meta"] / "injection-events.json").read_bytes()
        assert json.loads((out / "manifest.json").read_text())["dataset_hash"] == built["manifest"]["dataset_hash"]


def test_committed_snapshot_is_the_generator_output(built):
    pub = ROOT / "web" / "public" / "data"
    if not (pub / "tickets.json").exists():
        pytest.skip("web/public/data not generated")
    for name in gen.ENTITIES:
        assert (pub / f"{name}.json").read_bytes() == (built["out"] / f"{name}.json").read_bytes(), name
    assert json.loads((pub / "manifest.json").read_text())["dataset_hash"] == built["manifest"]["dataset_hash"]
    assert (pub / "injection-manifest.json").read_bytes() == (built["out"] / "injection-manifest.json").read_bytes()
    assert (ROOT / "data" / "injection-manifest.json").read_bytes() == (built["out"] / "injection-manifest.json").read_bytes()


def test_manifest_shape_and_hash(built):
    m = built["manifest"]
    assert m["dataset_version"] == VERSION and m["contract_version"] == "v1"
    assert set(m) >= {"dataset_version", "dataset_hash", "generated_at", "contract_version", "generator", "row_counts",
                      "designed_relationships", "injection_manifest", "stats"}
    assert re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", m["generated_at"])
    assert m["generator"]["seed"] == SEED and m["generator"]["name"] == "generate.py"
    assert m["generator"]["parameters"]["days"] == 84 and m["generator"]["parameters"]["holdout_intensity_uplift"] == 1.2
    assert m["row_counts"] == {n: len(built["rows"][n]) for n in gen.ENTITIES}
    assert json.loads((built["out"] / "manifest.json").read_text())["dataset_hash"] == m["dataset_hash"]
    h = hashlib.sha256()
    for name in sorted(gen.ENTITIES):
        h.update(json.dumps(built["rows"][name], sort_keys=True, separators=(",", ":")).encode())
    assert h.hexdigest() == m["dataset_hash"]
    assert len(m["designed_relationships"]) == 4
    assert m["stats"]["holdout_relative_change"] == pytest.approx(0.20, abs=0.02)
    assert (built["out"] / "injection-manifest.json").read_bytes() == (built["meta"] / "injection-manifest.json").read_bytes()
    assert built["inj_doc"]["dataset_hash"] == m["dataset_hash"]
    assert {e["injection"] for e in built["events"].values()} <= set(built["inj"])


def _seed_columns() -> dict[str, tuple[str, ...]]:
    from data import seed
    return {**seed.COLUMNS, "shift_breaks": gen.SHIFT_BREAK_COLUMNS}


def test_field_names_equal_the_fixture_and_seed_columns(built):
    columns = _seed_columns()
    golden = json.loads((GOLDEN / "inputs.json").read_text())
    for name in gen.ENTITIES:
        rows = built["rows"][name]
        assert rows, name
        if name in golden and golden[name]:
            want = set(golden[name][0])
            if name != "simulation_runs":
                assert want == set(columns[name]), name              # the fixture and the table columns agree
        else:
            want = set(columns[name])
        assert all(set(r) == want for r in rows), name
    assert subprocess.run([sys.executable, str(ROOT / "data" / "generate.py"), "--profile", "golden-shape-check"],
                          capture_output=True).returncode == 0


def test_timestamps_are_iso_utc_with_z_at_second_precision(built):
    fields = {"customers": ("created_at",), "skills": ("created_at",), "agent_skills": ("effective_from",),
              "tickets": ("created_at",), "ticket_events": ("occurred_at",), "shifts": ("starts_at", "ends_at"),
              "surveys": ("response_at", "invited_at"), "shift_breaks": ("starts_at", "ends_at")}
    for name, cols in fields.items():
        for r in built["rows"][name]:
            for c in cols:
                assert r[c] is None or (STAMP.match(r[c]) and parse_ts(r[c]).tzinfo is not None), (name, c, r[c])


# --- size and the volume cap --------------------------------------------------------------------------------------
def test_size_under_five_megabytes_and_one_row_per_state_change(built):
    total = sum(p.stat().st_size for p in built["out"].glob("*.json"))
    assert total < BUDGET, total
    assert built["manifest"]["stats"]["events_per_ticket"] < 6.5
    ev = built["rows"]["ticket_events"]
    assert len({e["event_id"] for e in ev}) == len(ev)
    assert len({(e["ticket_id"], e["event_type"], e["occurred_at"]) for e in ev}) == len(ev)    # no duplicate state change
    assert [e["event_id"] for e in ev] == sorted(e["event_id"] for e in ev)


# --- spec ranges --------------------------------------------------------------------------------------------------
def test_counts_within_spec_ranges(built):
    r = built["rows"]
    assert [q["queue_id"] for q in r["queues"]] == ["q-001", "q-002", "q-003"]
    assert {q["queue_name"] for q in r["queues"]} == {"Billing", "Technical", "Onboarding"}
    assert {q["priority_policy"] for q in r["queues"]} == {"fifo_within_priority", "fifo"}
    assert {t["priority"] for t in r["tickets"]} == {"P1", "P2", "P3"}
    assert {p["priority"] for p in r["sla_policies"]} == {"P1", "P2", "P3"}
    assert len(r["agents"]) == 18 and {a["timezone"] for a in r["agents"]} == {"Europe/Berlin", "America/Santiago"}
    assert {a["employment_type"] for a in r["agents"]} == {"full_time", "part_time", "contractor"}
    assert all(a["max_concurrent"] == 1 for a in r["agents"])
    # the spec says about 6,000; the 5 MB cap with every field present allows about 3,800 (README-generator.md)
    assert 3500 <= len(r["tickets"]) <= 6500
    days = {t["created_at"][:10] for t in r["tickets"]}
    assert min(days) == "2026-07-06" and max(days) == "2026-09-27" and len(days) == 84
    assert all(b["ends_at"] > b["starts_at"] for b in r["shift_breaks"])
    assert {(parse_ts(b["ends_at"]) - parse_ts(b["starts_at"])).total_seconds() for b in r["shift_breaks"]} == {1800}
    assert {s["break_minutes"] for s in r["shifts"]} == {0, 30}
    assert sum(1 for s in r["shifts"] if s["break_minutes"] == 0) == 3                    # INJ-05 only
    evs = collections.Counter(e["event_type"] for e in r["ticket_events"])
    n = len(r["tickets"])
    assert set(evs) == {"created", "acknowledged_bot", "service_started", "replied_human", "paused", "resumed",
                        "transferred", "resolved", "reopened", "queued", "abandoned"}
    assert 0.06 <= (evs["transferred"]) / n <= 0.10                                       # about 8 % transfers
    assert 0.045 <= evs["reopened"] / n <= 0.075                                          # about 6 % reopens
    done = len({e["ticket_id"] for e in r["ticket_events"] if e["event_type"] == "resolved"})
    assert 0.55 <= len(r["surveys"]) / done <= 0.65                                       # invited on 60 % of resolutions
    answered = sum(1 for s in r["surveys"] if s["score"] is not None)
    assert 0.30 <= answered / len(r["surveys"]) <= 0.40                                   # 35 % respond
    assert len(r["customers"]) >= 900 and all(c["synthetic"] is True for c in r["customers"])
    assert {s["break_minutes"] for s in r["shifts"] if s["break_minutes"]} == {30}


def test_holdout_intensity_is_twenty_percent_higher(result, inputs):
    arrivals = [t.created_at for t in result.population.tickets]
    rep = holdout_report(arrivals, TRAIN, HOLDOUT)
    change = float(rep["relative_change"])
    assert 0.15 <= change <= 0.25, rep
    assert rep["intensity_changed"] is True and rep["estimated_on"] == "training window only"
    # the same ratio from the raw ticket rows
    tr = sum(1 for t in inputs["tickets"] if t["created_at"] < "2026-08-31") / 8
    ho = sum(1 for t in inputs["tickets"] if t["created_at"] >= "2026-08-31") / 4
    assert ho / tr == pytest.approx(1.2, abs=0.05)


def test_bot_acknowledgement_on_every_ticket(built):
    r = built["rows"]
    acks = {}
    for e in r["ticket_events"]:
        if e["event_type"] == "acknowledged_bot":
            assert e["actor_id"].startswith("bot-") and e["agent_id"] is None
            assert e["ticket_id"] not in acks
            acks[e["ticket_id"]] = e["occurred_at"]
    created = {e["ticket_id"]: e["occurred_at"] for e in r["ticket_events"] if e["event_type"] == "created"}
    assert set(acks) == set(created) == {t["ticket_id"] for t in r["tickets"]}
    assert all(0 < (parse_ts(acks[t]) - parse_ts(created[t])).total_seconds() < 30 for t in acks)
    firsts = {}
    for e in r["ticket_events"]:
        if e["event_type"] in ("service_started", "replied_human") and not e["actor_id"].startswith("bot-"):
            firsts.setdefault(e["ticket_id"], e["occurred_at"])
    assert all(acks[t] <= firsts[t] for t in firsts)           # the bot answers before a human does


def test_late_arrivals_keep_their_occurred_at(built):
    last: dict[str, str] = {}
    late = 0
    for e in built["rows"]["ticket_events"]:
        if e["ticket_id"] in last and e["occurred_at"] < last[e["ticket_id"]]:
            late += 1
        last[e["ticket_id"]] = max(last.get(e["ticket_id"], ""), e["occurred_at"])
    assert late >= 5


# --- the domain on the generated world ----------------------------------------------------------------------------
def test_pipeline_runs_and_rejects_exactly_the_injected_rows(built, result):
    got = {(r["entity"], r["id"], r["reason_code"]) for r in result.rejected}
    assert got == _expected_rejections(built)
    assert {r for _, _, r in got} == {"BOT_AS_HUMAN_REPLY", "AGENT_NOT_QUALIFIED", "CONCURRENCY_EXCEEDED",
                                      "TRANSFER_RESETS_ARRIVAL", "TICKET_REJECTED"}
    counts = result.counts
    assert counts["tickets"]["rejected"] == 9 and counts["ticket_events"]["rejected"] == 4 + 51
    for ent in gen.DOMAIN_ENTITIES:
        assert counts[ent]["accepted"] + counts[ent]["rejected"] == len(built["rows"][ent]), ent
    m = result.metrics
    assert m["arrival_count"] == len(built["rows"]["tickets"]) - 9 and m["empty_population"] is False
    assert m["backlog"] == {"2026-09-27T23:59:59Z": 0}
    assert len(result.simulations) == 3 and all(s.mean_wait is not None for s in result.simulations)


def _res_minutes(pop: Population, window=WINDOW) -> dict[str, Fraction]:
    from serviceflow.timeutil import minutes_between
    hist = histories(pop)
    return {t.ticket_id: minutes_between(t.created_at, hist[t.ticket_id].final_resolution) for t in pop.tickets
            if hist[t.ticket_id].final_resolution is not None and window[0] <= hist[t.ticket_id].final_resolution < window[1]}


def test_technical_p1_tail_is_long(result):
    pop = result.population
    q = {t.ticket_id: t for t in pop.tickets}
    p1 = [t for t in pop.tickets if t.queue_id == "q-002" and t.priority == "P1"]
    sub = Population(tickets=p1, ticket_events=[e for e in pop.ticket_events if e.ticket_id in {t.ticket_id for t in p1}])
    res = [float(v) for k, v in _res_minutes(sub).items()]
    assert len(res) >= 100
    mean = sum(res) / len(res)
    p90 = float(nearest_rank([Fraction(x).limit_denominator(1000) for x in res], Fraction(9, 10)))
    assert p90 > 2 * mean, (p90, mean)
    # the other P1 queues do not have it: the tail belongs to technical
    for qid in ("q-001", "q-003"):
        other = [t for t in pop.tickets if t.queue_id == qid and t.priority == "P1"]
        o = Population(tickets=other, ticket_events=[e for e in pop.ticket_events if e.ticket_id in {t.ticket_id for t in other}])
        vals = [float(v) for v in _res_minutes(o).values()]
        if len(vals) >= 20:
            assert float(nearest_rank([Fraction(x).limit_denominator(1000) for x in vals], Fraction(9, 10))) / (sum(vals) / len(vals)) < p90 / mean


def test_monday_09_to_11_utc_is_the_capacity_bind(inputs):
    arr = collections.Counter()
    for t in inputs["tickets"]:
        d = parse_ts(t["created_at"])
        arr[(d.weekday(), d.hour)] += 1
    cap: dict[tuple[int, int], float] = collections.defaultdict(float)
    for s in inputs["shifts"]:
        a, b = parse_ts(s["starts_at"]), parse_ts(s["ends_at"])
        keep = ((b - a).total_seconds() - 60 * s["break_minutes"]) / (b - a).total_seconds()
        t = a
        while t < b:
            nxt = min(t.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1), b)
            cap[(t.weekday(), t.hour)] += (nxt - t).total_seconds() / 3600 * keep
            t = nxt
    ratio = {}
    for d in range(7):
        for h in range(24):
            keys = [(d, h), ((d + (h + 1) // 24) % 7, (h + 1) % 24)]
            c = sum(cap[k] for k in keys)
            if c >= 24:                                  # at least two staffed agent-hours a week on average
                ratio[(d, h)] = sum(arr[k] for k in keys) / c
    top = sorted(ratio.items(), key=lambda kv: -kv[1])
    assert top[0][0] == (0, 9), top[:3]                  # the 2-hour block Monday 09-11 UTC
    assert top[0][1] > 1.2 * top[1][1] and top[0][1] > 2 * sorted(ratio.values())[len(ratio) // 2]
    single = {(d, h): arr[(d, h)] / cap[(d, h)] for (d, h) in cap if cap[(d, h)] >= 12}
    assert {k for k, _ in sorted(single.items(), key=lambda kv: -kv[1])[:2]} == {(0, 9), (0, 10)}


def test_proficiency_four_or_more_resolves_faster(result, built):
    pop = result.population
    prof = {(s.agent_id, s.skill_id): s.proficiency for s in pop.agent_skills}
    queue_skill = {q.queue_id: q.skill_id for q in pop.queue_skills}
    tix = {t.ticket_id: t for t in pop.tickets}
    hi, lo, ratios = [], [], collections.defaultdict(list)
    cell = collections.defaultdict(list)
    rows = []
    for tid, h in histories(pop).items():
        t = tix[tid]
        for iv in h.intervals:
            if iv.end is None:
                continue
            m = float((iv.end - iv.start).total_seconds() / 60)
            q = next((e.queue_id for e in sorted(pop.ticket_events, key=lambda e: e.occurred_at)[:0]), None)
            rows.append((tid, iv.agent_id, m, t))
    # the queue of the interval: the ticket's current queue unless it was transferred (then use the agent's skill row)
    for tid, agent, m, t in rows:
        p = prof.get((agent, queue_skill[t.queue_id]))
        if p is None:                                    # a transferred ticket's first interval: any skill the agent holds
            p = max(v for (a, _), v in prof.items() if a == agent)
        (hi if p >= 4 else lo).append(m)
        cell[(t.queue_id, t.priority, p >= 4)].append(m)
    assert sum(hi) / len(hi) < sum(lo) / len(lo)
    # relative to the queue and priority mean the effect is still there (the raw gap is not a queue-mix artefact)
    both = collections.defaultdict(list)
    for (q, pr, high), v in cell.items():
        both[(q, pr)] += v
    mean_cell = {k: sum(v) / len(v) for k, v in both.items()}
    nh = [m / mean_cell[(t.queue_id, t.priority)] for tid, a, m, t in rows
          if (prof.get((a, queue_skill[t.queue_id])) or 0) >= 4]
    nl = [m / mean_cell[(t.queue_id, t.priority)] for tid, a, m, t in rows
          if 0 < (prof.get((a, queue_skill[t.queue_id])) or 0) < 4]
    assert sum(nh) / len(nh) < 0.95 < 1.0 < sum(nl) / len(nl) + 0.05
    # per agent: the agents whose best proficiency is >= 4 have the lower mean handling per interval
    by_agent = collections.defaultdict(list)
    for _, a, m, _ in rows:
        by_agent[a].append(m)
    best = {a: max(v for (x, _), v in prof.items() if x == a) for a in by_agent}
    g_hi = [sum(by_agent[a]) / len(by_agent[a]) for a in by_agent if best[a] >= 4]
    g_lo = [sum(by_agent[a]) / len(by_agent[a]) for a in by_agent if best[a] < 4]
    assert sum(g_hi) / len(g_hi) < sum(g_lo) / len(g_lo)


def test_designed_relationship_numbers_are_published_and_realised(built):
    d = built["manifest"]["stats"]["designed"]
    assert d["technical_p1"]["p90_over_mean"] > 2.0
    assert d["monday_block"]["top"] == "Mon 09-11" and d["monday_block"]["ratio"] > d["monday_block"]["next_best"]["ratio"]
    assert d["proficiency"]["mean_handling_ge4_minutes"] < d["proficiency"]["mean_handling_le3_minutes"]
    for line in built["manifest"]["designed_relationships"]:
        assert "synthetic" in line


# --- the nine injected defects -------------------------------------------------------------------------------------
def test_injection_manifest_lists_nine_defects_with_the_required_fields(built):
    assert sorted(built["inj"]) == [f"INJ-0{i}" for i in range(1, 10)]
    for i in built["inj"].values():
        assert {"id", "test", "entity", "record_ids", "description", "expected_handling"} <= set(i)
        assert i["record_ids"] and i["test"].startswith("P04-TEST-")
    assert sorted(built["events"]) == [f"EV-0{i}" for i in range(1, 8)]
    for e in built["events"].values():
        assert {"event_id", "injection", "steps", "expected_status", "expected_reason", "expected_handling"} <= set(e)


def test_every_injection_record_id_exists(built):
    r = built["rows"]
    ids = {"ticket_events": {x["event_id"] for x in r["ticket_events"]}, "tickets": {x["ticket_id"] for x in r["tickets"]},
           "shifts": {x["shift_id"] for x in r["shifts"]}, "surveys": {x["survey_id"] for x in r["surveys"]},
           "customers": {x["customer_id"] for x in r["customers"]}}
    for inj in built["inj"].values():
        if inj["id"] == "INJ-07":
            assert inj["record_ids"][0] == built["events"]["EV-07"]["steps"][0]["input"]["input"]["simulation_id"]
            continue
        if inj["id"] == "INJ-02":
            for pair in inj["detail"]:
                assert {pair["original_ticket"], pair["duplicate_ticket"]} <= ids["tickets"]
                assert {pair["original_customer"], pair["duplicate_customer"]} <= ids["customers"]
        for rid in inj["record_ids"]:
            assert any(rid in s for s in ids.values()), (inj["id"], rid)
        if "expected_rejections" in inj:
            for rej in inj["expected_rejections"]:
                assert rej["id"] in ids[rej["entity"]], rej
    for ev in built["events"].values():                  # every replay input refers to rows that exist
        for step in ev["steps"]:
            inp = step["input"]["input"]
            if "ticket_id" in inp and not inp["ticket_id"].startswith("t-ev"):
                assert inp["ticket_id"] in ids["tickets"]
            if "agent_id" in inp:
                assert inp["agent_id"] in {a["agent_id"] for a in r["agents"]}


def test_inj01_bot_labelled_human_is_refused_and_first_response_ignores_it(built, result, inputs):
    inj = built["inj"]["INJ-01"]
    got = {(r["id"], r["reason_code"]) for r in result.rejected if r["entity"] == "ticket_events"
           and r["reason_code"] == "BOT_AS_HUMAN_REPLY"}
    assert got == {(e, "BOT_AS_HUMAN_REPLY") for e in inj["record_ids"]}
    rows = {e["event_id"]: e for e in inputs["ticket_events"]}
    assert all(rows[e]["event_type"] == "replied_human" and rows[e]["actor_id"].startswith("bot-") for e in inj["record_ids"])
    metrics_fr = result.metrics["first_response_minutes"]
    for t in inj["tickets"]:
        bot = next(parse_ts(rows[e]["occurred_at"]) for e in inj["record_ids"] if rows[e]["ticket_id"] == t)
        created = next(parse_ts(x["created_at"]) for x in inputs["tickets"] if x["ticket_id"] == t)
        assert (bot - created).total_seconds() < 120                       # the bot "reply" is a minute after arrival
        assert float(metrics_fr[t]) >= 90                                  # the domain measures from the real human reply


def test_inj02_reopen_recorded_as_a_new_customer(built, result, inputs):
    inj = built["inj"]["INJ-02"]
    tickets = {t["ticket_id"]: t for t in inputs["tickets"]}
    custs = {c["customer_id"]: c for c in inputs["customers"]}
    uses = collections.Counter(t["customer_id"] for t in inputs["tickets"])
    ev_by = collections.defaultdict(list)
    for e in inputs["ticket_events"]:
        ev_by[e["ticket_id"]].append(e)
    reopened = disclosures(result.population, WINDOW)["reopened_tickets"]
    assert len(inj["detail"]) == 4
    for d in inj["detail"]:
        o, n = tickets[d["original_ticket"]], tickets[d["duplicate_ticket"]]
        oc, nc = custs[d["original_customer"]], custs[d["duplicate_customer"]]
        assert nc["customer_id"] == n["customer_id"] and oc["customer_id"] == o["customer_id"]
        assert nc["customer_id"] != oc["customer_id"] and uses[nc["customer_id"]] == 1
        assert nc["created_at"] == n["created_at"] == d["duplicate_created_at"]            # a "new" customer born with the ticket
        assert (nc["segment"], nc["timezone"]) == (oc["segment"], oc["timezone"])
        assert (n["queue_id"], n["priority"], n["channel"]) == (o["queue_id"], o["priority"], o["channel"])
        res = max(e["occurred_at"] for e in ev_by[o["ticket_id"]] if e["event_type"] == "resolved")
        assert not any(e["event_type"] == "reopened" for e in ev_by[o["ticket_id"]])
        assert res < n["created_at"] <= (parse_ts(res) + timedelta(hours=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
    # the domain accepts both tickets and counts them as two arrivals: the reopen disclosure does not see the link
    accepted = {t.ticket_id for t in result.population.tickets}
    assert all(d["original_ticket"] in accepted and d["duplicate_ticket"] in accepted for d in inj["detail"])
    own = sum(1 for t, evs in ev_by.items() if any(e["event_type"] == "reopened" for e in evs) and t in accepted)
    assert reopened == own


def test_inj03_unqualified_agent_is_rejected(built, result, inputs):
    inj = built["inj"]["INJ-03"]
    skills = collections.defaultdict(set)
    for s in inputs["agent_skills"]:
        skills[s["agent_id"]].add(s["skill_id"])
    qskill = {q["queue_id"]: q["skill_id"] for q in inputs["queue_skills"]}
    assert {d["queue_id"] for d in inj["detail"]} == {"q-001", "q-002", "q-003"}
    for d in inj["detail"]:
        assert qskill[d["queue_id"]] not in skills[d["agent_id"]]
        assert ("tickets", d["ticket"], "AGENT_NOT_QUALIFIED") in {(r["entity"], r["id"], r["reason_code"]) for r in result.rejected}


def test_inj04_two_simultaneous_services_for_one_agent(built, result, inputs):
    inj = built["inj"]["INJ-04"]
    hist = histories(Population.from_rows({"tickets": inputs["tickets"], "ticket_events": inputs["ticket_events"]}))
    for d in inj["detail"]:
        a = hist[d["first_ticket"]].intervals[0]
        b = hist[d["rejected_ticket"]].intervals[0]
        assert a.agent_id == b.agent_id == d["agent_id"] and a.start < b.start < a.end and a.end is not None
        assert ("tickets", d["rejected_ticket"], "CONCURRENCY_EXCEEDED") in {(r["entity"], r["id"], r["reason_code"]) for r in result.rejected}
        assert d["first_ticket"] in {t.ticket_id for t in result.population.tickets}     # the earlier start wins


def test_inj05_break_counted_as_available(built, inputs):
    inj = built["inj"]["INJ-05"]
    breaks = {b["break_id"]: b for b in built["rows"]["shift_breaks"]}
    shifts = {s["shift_id"]: s for s in inputs["shifts"]}
    for d in inj["detail"]:
        s = shifts[d["shift_id"]]
        assert s["break_minutes"] == 0 and (parse_ts(s["ends_at"]) - parse_ts(s["starts_at"])).total_seconds() == 8 * 3600
        b = breaks[d["break_recorded_in_shift_breaks"]]
        assert b["shift_id"] == s["shift_id"] and b["agent_id"] == s["agent_id"]
        assert s["starts_at"] < b["starts_at"] and b["ends_at"] < s["ends_at"]
        shift = Shift(s["shift_id"], s["agent_id"], parse_ts(s["starts_at"]), parse_ts(s["ends_at"]), s["break_minutes"])
        fixed = Shift(s["shift_id"], s["agent_id"], parse_ts(s["starts_at"]), parse_ts(s["ends_at"]), 30)
        counted, _ = staffed_minutes([shift], WINDOW)
        correct, _ = staffed_minutes([fixed], WINDOW)
        assert counted - correct == 30                                       # the break is counted as available
    # every other shift's break is on record exactly once
    per = collections.Counter(b["shift_id"] for b in breaks.values())
    assert max(per.values()) == 1 and len(per) >= len(shifts) - 3


def test_inj06_transfer_that_resets_arrival(built, result, inputs):
    inj = built["inj"]["INJ-06"]
    first = {}
    for e in inputs["ticket_events"]:
        first[e["ticket_id"]] = min(first.get(e["ticket_id"], e["occurred_at"]), e["occurred_at"])
    rows = {t["ticket_id"]: t for t in inputs["tickets"]}
    for tid in inj["record_ids"]:
        assert rows[tid]["created_at"] > first[tid]
        assert ("tickets", tid, "TRANSFER_RESETS_ARRIVAL") in {(r["entity"], r["id"], r["reason_code"]) for r in result.rejected}
    # a correct transfer keeps the arrival: no other transferred ticket is rejected
    xfer = {e["ticket_id"] for e in inputs["ticket_events"] if e["event_type"] == "transferred"}
    ok = [t for t in xfer if t not in inj["record_ids"]]
    assert len(ok) >= 200 and all(rows[t]["created_at"] == first[t] for t in ok)


def test_inj07_warm_up_included_biases_the_wait_low(built):
    ev = built["events"]["EV-07"]["steps"][0]["input"]["input"]
    base = next(r for r in built["rows"]["simulation_runs"] if r["simulation_id"] == "sim-001")
    assert ev["warmup_minutes"] == 0 and base["warmup_minutes"] == 120 and ev["config"] == base["config"] and ev["seed"] == base["seed"]
    warm = simulate(base["config"], base["seed"], base["warmup_minutes"], base["horizon_minutes"], "w")
    cold = simulate(ev["config"], ev["seed"], 0, ev["horizon_minutes"], "c")
    assert cold.statistics()["warmup_excluded"] == 0 and warm.statistics()["warmup_excluded"] > 0
    assert cold.mean_wait < warm.mean_wait
    runs = {r["simulation_id"]: r for r in built["rows"]["simulation_runs"]}
    assert runs["sim-002"]["config"]["agents"] == base["config"]["agents"] + 1
    assert runs["sim-003"]["config"]["arrival_rate_per_hour"] > base["config"]["arrival_rate_per_hour"]
    sims = {k: simulate(r["config"], r["seed"], r["warmup_minutes"], r["horizon_minutes"], k) for k, r in runs.items()}
    assert sims["sim-002"].mean_wait < sims["sim-001"].mean_wait < sims["sim-003"].mean_wait


def test_inj08_dst_weekend_shift_arithmetic(built, inputs):
    """America/Santiago moves from UTC-04 to UTC-03 at 2026-09-06T04:00Z; shifts are declared in local time."""
    inj = built["inj"]["INJ-08"]
    agents = {a["agent_id"]: a for a in inputs["agents"]}
    zi = ZoneInfo("America/Santiago")
    assert datetime(2026, 9, 5, 12, tzinfo=timezone.utc).astimezone(zi).utcoffset() == timedelta(hours=-4)
    assert datetime(2026, 9, 6, 12, tzinfo=timezone.utc).astimezone(zi).utcoffset() == timedelta(hours=-3)
    night = [s for s in inputs["shifts"] if s["starts_at"] == "2026-09-05T22:00:00Z"]
    assert {s["agent_id"] for s in night} == {"agt-017", "agt-018"}
    by_agent = {s["agent_id"]: s for s in night}
    assert (parse_ts(by_agent["agt-017"]["ends_at"]) - parse_ts(by_agent["agt-017"]["starts_at"])).total_seconds() == 420 * 60
    assert by_agent["agt-017"]["ends_at"] == "2026-09-06T05:00:00Z" == iso(local_to_utc(date(2026, 9, 6), datetime.min.time().replace(hour=2), "America/Santiago"))
    bad = by_agent["agt-018"]
    assert bad["shift_id"] == inj["record_ids"][0] and bad["ends_at"] == "2026-09-06T06:00:00Z"
    assert (parse_ts(bad["ends_at"]) - parse_ts(bad["starts_at"])).total_seconds() == 480 * 60
    # detection: the end recomputed from the agent's zone differs from the recorded end for exactly this shift
    mismatched = []
    for s in inputs["shifts"]:
        zone = ZoneInfo(agents[s["agent_id"]]["timezone"])
        local = parse_ts(s["starts_at"]).astimezone(zone)
        wall = datetime.combine(local.date(), local.time())               # naive local wall clock of the start
        ends = {iso((wall + timedelta(hours=h)).replace(tzinfo=zone)) for h in (6, 8)}      # the roster: 6 or 8 hours
        if s["ends_at"] not in ends:
            mismatched.append(s["shift_id"])
    assert mismatched == [bad["shift_id"]]
    # the DST jump moves Santiago shifts one hour earlier in UTC: 08:00 local is 12:00Z before and 11:00Z after
    sd = [s for s in inputs["shifts"] if s["agent_id"] == "agt-010"]
    assert {s["starts_at"][11:16] for s in sd if s["starts_at"] < "2026-09-06"} == {"12:00"}
    assert {s["starts_at"][11:16] for s in sd if s["starts_at"] >= "2026-09-06"} == {"11:00"}
    be = [s for s in inputs["shifts"] if s["agent_id"] == "agt-001"]
    assert len({s["starts_at"][11:16] for s in be}) == 1                      # Berlin does not change in the window
    # the staffed time of the recorded shift is 60 minutes more than the real one
    shift = Shift(bad["shift_id"], bad["agent_id"], parse_ts(bad["starts_at"]), parse_ts(bad["ends_at"]), bad["break_minutes"])
    real = Shift(bad["shift_id"], bad["agent_id"], parse_ts(bad["starts_at"]), parse_ts("2026-09-06T05:00:00Z"), bad["break_minutes"])
    assert staffed_minutes([shift], WINDOW)[0] - staffed_minutes([real], WINDOW)[0] == 60


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_inj09_survey_nonresponse_skews_csat(built, result):
    st = built["manifest"]["stats"]
    assert st["response_rate_after_poor_experience"] < 0.8 * st["response_rate_after_good_experience"]
    assert st["csat_among_responders"] > st["csat_latent_all_invited"] + 0.05
    inj = built["inj"]["INJ-09"]
    surveys = {s["survey_id"]: s for s in built["rows"]["surveys"]}
    assert inj["record_count"] > 30 and all(surveys[i]["score"] is None and surveys[i]["invited_at"] for i in inj["record_ids"])
    d = disclosures(result.population, WINDOW)["csat"]
    assert d["nonresponse"] > d["valid_responses"] and "not random" in d["note"]
    m = result.metrics
    assert float(m["csat"]) == pytest.approx(st["csat_among_responders"], abs=0.02)
    assert float(m["survey_invitation_rate"]) == pytest.approx(0.60, abs=0.03)
    assert float(m["survey_response_rate"]) == pytest.approx(0.35, abs=0.04)


def test_golden_copy_for_the_web_app(built):
    g = built["out"] / "golden"
    fixture = json.loads((GOLDEN / "inputs.json").read_text())
    for name in gen.DOMAIN_ENTITIES:
        doc = json.loads((g / f"{name}.json").read_text())
        assert doc["entity"] == name and doc["dataset_version"] == "golden-v1" and doc["rows"] == fixture.get(name, [])
    man = json.loads((g / "manifest.json").read_text())
    assert man["dataset_version"] == "golden-v1" and man["dataset_hash"] == json.loads((GOLDEN / "HASHES.json").read_text())["sha256"]["inputs.json"]
    assert man["generator"]["seed"] == 0 and man["designed_relationships"] == [] and man["backlog_cutoffs"] == fixture["backlog_cutoffs"]
    assert man["row_counts"]["tickets"] == 3 and man["row_counts"]["shift_breaks"] == 0
    assert json.loads((g / "expected.json").read_text()) == json.loads((GOLDEN / "expected.json").read_text())


# --- PostgreSQL (needs DATABASE_URL) ---------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def loaded(inputs, built):
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is not set")
    import psycopg
    from psycopg.rows import dict_row
    from data import migrate, seed
    with psycopg.connect(url) as c:
        migrate.reset(c)
        migrate.apply_migrations(c)
    with psycopg.connect(url, row_factory=dict_row, autocommit=True) as c:
        out = seed.seed(c, inputs)
        yield c, out


def test_seed_loads_the_generated_files(loaded, inputs, result):
    conn, out = loaded
    rejected = collections.Counter(r["entity"] for r in result.rejected)
    assert out["skipped"] == len(result.rejected)
    for name in gen.DOMAIN_ENTITIES:
        accepted = len(inputs[name]) - rejected.get(name, 0)
        assert out["inserted"][name] == accepted, name
        assert conn.execute(f"SELECT count(*) AS n FROM {name}").fetchone()["n"] == accepted, name
    assert conn.execute("SELECT count(*) AS n FROM rejected_records").fetchone()["n"] == len(result.rejected)
    reasons = {r["reason_code"]: r["n"] for r in conn.execute(
        "SELECT reason_code, count(*) AS n FROM rejected_records GROUP BY reason_code").fetchall()}
    assert reasons == {"BOT_AS_HUMAN_REPLY": 4, "AGENT_NOT_QUALIFIED": 3, "CONCURRENCY_EXCEEDED": 3,
                       "TRANSFER_RESETS_ARRIVAL": 3, "TICKET_REJECTED": 57}


@pytest.mark.parametrize("window", [WINDOW, TRAIN, HOLDOUT], ids=["full-12-weeks", "training-weeks-1-8", "holdout-weeks-9-12"])
def test_sql_reference_agrees_with_the_domain(loaded, inputs, result, window):
    from serviceflow.contract import METRIC_KEYS
    conn, _ = loaded
    sql = (ROOT / "data" / "sql" / "reference_metrics.sql").read_text()
    cut = [window[1]]
    iso_cut = [c.strftime("%Y-%m-%dT%H:%M:%SZ") for c in cut]
    row = conn.execute(sql, {"w0": window[0].strftime("%Y-%m-%dT%H:%M:%SZ"), "w1": window[1].strftime("%Y-%m-%dT%H:%M:%SZ"),
                             "cutoffs": iso_cut, "abandonable": ["chat", "phone"]}).fetchone()
    want = compute_metrics(result.population, window, cut, ["chat", "phone"])
    assert set(row) == set(want) == set(METRIC_KEYS)
    for k in METRIC_KEYS:
        assert row[k] == want[k], (k, str(row[k])[:120], str(want[k])[:120])
    assert want["arrival_count"] > 500 and want["empty_population"] is False


def test_replay_events_behave_as_recorded(loaded, inputs, built):
    from fastapi.testclient import TestClient
    from api.app import PREFIX, create_app
    conn, _ = loaded
    for b in built["rows"]["shift_breaks"]:                      # data-load-only table (data/seed.py does not load it)
        conn.execute("INSERT INTO shift_breaks (break_id, shift_id, agent_id, starts_at, ends_at) VALUES (%s,%s,%s,%s,%s) "
                     "ON CONFLICT DO NOTHING", [b[c] for c in gen.SHIFT_BREAK_COLUMNS])
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        for eid, ev in sorted(built["events"].items()):
            responses = []
            for step in ev["steps"]:
                # R4-05: the replay carries the dataset_version a client has just read from the API (meta), not the
                # generator's label: a stale version is 409.
                body = {**step["input"], "dataset_version": conn.execute(
                    "SELECT dataset_version FROM dataset_versions ORDER BY created_at DESC LIMIT 1").fetchone()["dataset_version"]}
                responses.append(client.post(f"{PREFIX}/commands/{step['command']}", json=body, headers=step["headers"]))
            for r in responses[:-1]:
                assert r.status_code == 200, (eid, r.text)
            last = responses[-1]
            assert last.status_code == ev["expected_status"], (eid, last.text)
            body = last.json()
            if ev["expected_status"] == 422:
                assert ev["expected_reason"] in [d["rule_id"] for d in body["error"]["details"]], (eid, body)
                continue
            res = body["result"]
            exp = ev.get("expected", {})
            if "rejected_records" in exp:
                assert res["rejected_records"] == exp["rejected_records"], eid
                assert ev["expected_reason"] in {r["reason_code"] for r in res["rejected_records"]}
            elif eid == "EV-02":
                for k, v in exp.items():
                    assert res[k] == v, (eid, k)
            elif eid == "EV-07":
                assert res["statistics"]["warmup_excluded"] == exp["statistics.warmup_excluded"] == 0
                warm = conn.execute("SELECT 1 FROM simulation_runs WHERE simulation_id = %s", [exp["mean_wait_lower_than"]]).fetchone()
                assert warm is not None
                base = next(r for r in built["rows"]["simulation_runs"] if r["simulation_id"] == exp["mean_wait_lower_than"])
                w = simulate(base["config"], base["seed"], base["warmup_minutes"], base["horizon_minutes"], "w")
                assert Fraction(res["mean_wait_minutes"]) < w.mean_wait
