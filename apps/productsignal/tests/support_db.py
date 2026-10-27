"""Shared helpers for the tests (imported, not auto-collected): fixtures, the DB fixtures, a small-world builder and the driver
that replays a fixture's ``inputs.json`` through the API commands.

Every database test gets a clean schema: ``migrate.reset`` drops the project's tables and ``apply_migrations`` recreates
them. Tests skip cleanly when DATABASE_URL is unset (the pure-domain tests never need it).
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "domain", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from api.app import PREFIX, create_app  # noqa: E402
from data import migrate, seed  # noqa: E402
from productsignal.models import plan_hash  # noqa: E402

GOLDEN = ROOT / "tests" / "fixtures" / "golden"
ANALYST = {"X-Actor-Id": "usr-analyst01", "X-Actor-Role": "analyst"}
EXPERIMENTER = {"X-Actor-Id": "usr-exp01", "X-Actor-Role": "experimenter"}
ADMIN = {"X-Actor-Id": "usr-adm01", "X-Actor-Role": "admin"}
VARIANTS = ["", "variant-rejected", "variant-empty"]


def golden_inputs(sub: str = "") -> dict[str, Any]:
    return copy.deepcopy(json.loads((GOLDEN / sub / "inputs.json").read_text()))


def golden_expected(sub: str = "") -> dict[str, Any]:
    return json.loads((GOLDEN / sub / "expected.json").read_text())


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def flat(x: Any, path: str = "") -> dict[str, Any]:
    """Every leaf of a JSON value by path (empty list as one leaf)."""
    if isinstance(x, dict):
        out: dict[str, Any] = {}
        for k, v in x.items():
            out.update(flat(v, f"{path}.{k}" if path else k))
        return out
    if isinstance(x, list):
        if not x:
            return {path + "[]": "empty"}
        out = {}
        for i, v in enumerate(x):
            out.update(flat(v, f"{path}[{i}]"))
        return out
    return {path: x}


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ts(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------------------------------------- small worlds
PLAN_BODY = {
    "experiment_version_id": "xv-001", "primary_metric": "activation_7d", "unit_type": "account",
    "allocation": {"control": "0.500000", "treatment": "0.500000"}, "planned_end": "2026-10-15T00:00:00Z",
    "activation_window_days": 7, "guardrail": {"metric": "product_error_rate", "window_days": 7},
    "revenue_window": {"from": "2026-10-01T00:00:00Z", "to": "2026-10-15T00:00:00Z"}, "confidence": "0.95", "z": "1.959964",
    "srm": {"p_threshold": "0.001", "min_expected_cell": 5}, "frozen_at": "2026-09-30T12:00:00Z"}


class World:
    """A small dataset builder for rule tests (the shape of inputs.json): accounts with one user each, signups, assignments,
    exposures, activations, sessions and subscriptions, a frozen plan and the standard windows."""

    def __init__(self, cutoff: str = "2026-10-26T00:00:00Z", plan: dict[str, Any] | None = None, **plan_kw: Any) -> None:
        body = copy.deepcopy(plan or PLAN_BODY)
        body.update(plan_kw)
        self.cutoff = cutoff
        self.d: dict[str, Any] = {
            "contract_version": 1, "as_of": cutoff, "cutoff": cutoff,
            "analysis_plan": {**body, "config_hash": plan_hash(body)},
            "metric_windows": {
                "signup_conversion": {"from": "2026-10-05T00:00:00Z", "to": "2026-10-12T00:00:00Z"},
                "funnel": {"definition_id": "fun-001", "version": 1, "steps": ["visit", "signup", "onboarding_step_1", "activated"],
                           "max_gap_hours": 48, "from": "2026-10-05T00:00:00Z", "to": "2026-10-12T00:00:00Z"},
                "activation": {"from": "2026-10-01T00:00:00Z", "to": "2026-10-26T00:00:00Z", "window_days": 7},
                "retention": {"signup_from": "2026-09-14", "signup_to": "2026-09-21"},
                "feature_adoption": {"from": "2026-09-21T00:00:00Z", "to": "2026-09-28T00:00:00Z", "feature": "export",
                                     "eligible_plans": ["team", "business"]}},
            "accounts": [], "users": [], "identity_links": [], "sessions": [], "events": [], "event_properties": [],
            "subscriptions": [], "experiment_versions": [
                {"experiment_version_id": "xv-001", "name": "Onboarding checklist", "unit_type": "account",
                 "primary_metric": "activation_7d", "planned_end": body["planned_end"]}],
            "assignments": [], "exposures": [], "metric_observations": [], "analysis_runs": []}
        self.n = {"ev": 0, "pr": 0, "ss": 0, "sub": 0, "as": 0, "ex": 0, "il": 0, "run": 0}

    # -- entities
    def account(self, aid: str, plan: str = "team", segment: str = "smb", tz: str = "UTC", internal: bool = False,
                bot: bool = False, created: str = "2026-09-01T00:00:00Z") -> str:
        self.d["accounts"].append({"account_id": aid, "plan": plan, "segment": segment, "created_at": created, "internal": internal, "timezone": tz})
        self.d["users"].append({"user_id": f"u-{aid}", "account_id": aid, "created_at": created, "timezone": tz, "bot_flag": bot})
        return aid

    def user(self, uid: str, aid: str, bot: bool = False) -> str:
        acc = next(a for a in self.d["accounts"] if a["account_id"] == aid)
        self.d["users"].append({"user_id": uid, "account_id": aid, "created_at": acc["created_at"], "timezone": acc["timezone"], "bot_flag": bot})
        return uid

    def event(self, name: str, at: str, user: str | None = None, anon: str | None = None, recv: str | None = None,
              props: dict[str, str] | None = None, eid: str | None = None) -> str:
        self.n["ev"] += 1
        eid = eid or f"ev-{self.n['ev']:05d}"
        self.d["events"].append({"event_id": eid, "user_id": user, "anonymous_id": anon, "event_name": name, "event_at": at,
                                 "received_at": recv or iso(ts(at) + timedelta(seconds=5))})
        for k, v in (props or {}).items():
            self.n["pr"] += 1
            self.d["event_properties"].append({"property_id": f"pr-{self.n['pr']:05d}", "event_id": eid, "property_key": k,
                                               "property_value": v, "value_type": "string"})
        return eid

    def signup(self, aid: str, at: str, user: str | None = None, recv: str | None = None) -> str:
        return self.event("signup", at, user=user or f"u-{aid}", recv=recv)

    def activate(self, aid: str, at: str, recv: str | None = None) -> str:
        return self.event("activated", at, user=f"u-{aid}", recv=recv)

    def session(self, aid: str, at: str, user: str | None = None) -> str:
        self.n["ss"] += 1
        sid = f"s-{self.n['ss']:04d}"
        self.d["sessions"].append({"session_id": sid, "user_id": user or f"u-{aid}", "started_at": at,
                                   "ended_at": iso(ts(at) + timedelta(minutes=10)), "device_type": "web"})
        return sid

    def link(self, anon: str, uid: str, at: str) -> str:
        self.n["il"] += 1
        lid = f"il-{self.n['il']:03d}"
        self.d["identity_links"].append({"identity_link_id": lid, "anonymous_id": anon, "user_id": uid, "linked_at": at, "rule_version": "v1"})
        return lid

    def sub(self, aid: str, starts: str, amount: str, status: str = "active") -> str:
        self.n["sub"] += 1
        sid = f"sub-{self.n['sub']:03d}"
        self.d["subscriptions"].append({"subscription_id": sid, "account_id": aid, "starts_at": starts, "ends_at": None,
                                        "status": status, "amount_usd": amount})
        return sid

    def assign(self, aid: str, variant: str, at: str, xv: str = "xv-001", asid: str | None = None) -> str:
        self.n["as"] += 1
        asid = asid or f"as-{self.n['as']:04d}"
        self.d["assignments"].append({"assignment_id": asid, "experiment_version_id": xv, "unit_id": aid, "variant": variant, "assigned_at": at})
        return asid

    def expose(self, asid: str, at: str, exid: str | None = None) -> str:
        self.n["ex"] += 1
        exid = exid or f"ex-{self.n['ex']:04d}"
        self.d["exposures"].append({"exposure_id": exid, "assignment_id": asid, "exposed_at": at, "surface": "onboarding_checklist", "event_id": None})
        return exid

    def run(self, cutoff: str, created: str, rid: str | None = None, xv: str = "xv-001") -> str:
        self.n["run"] += 1
        rid = rid or f"an-{self.n['run']:03d}"
        self.d["analysis_runs"].append({"analysis_id": rid, "experiment_version_id": xv, "cutoff_at": cutoff,
                                        "config_hash": self.d["analysis_plan"]["config_hash"], "created_at": created})
        return rid

    def arm(self, variant: str, n: int, activated: int, prefix: str | None = None, start: str = "2026-10-01T09:00:00Z",
            exposed: int | None = None) -> list[str]:
        """``n`` accounts assigned to ``variant``, signing up a minute apart from ``start``; the first ``activated`` activate 2 h
        after signup; the first ``exposed`` (default all) are exposed one minute after assignment."""
        prefix = prefix or variant[0]
        ids = []
        for i in range(n):
            aid = self.account(f"acc-{prefix}-{i + 1:03d}")
            t0 = ts(start) + timedelta(minutes=i)
            self.signup(aid, iso(t0))
            asid = self.assign(aid, variant, iso(t0 + timedelta(minutes=1)))
            if i < (n if exposed is None else exposed):
                self.expose(asid, iso(t0 + timedelta(minutes=2)))
            if i < activated:
                self.activate(aid, iso(t0 + timedelta(hours=2)))
            ids.append(aid)
        return ids

    def data(self) -> dict[str, Any]:
        return copy.deepcopy(self.d)


def small_experiment(c: tuple[int, int] = (20, 4), t: tuple[int, int] = (20, 10), **kw: Any) -> World:
    """control and treatment arms of the given (size, activated); all mature at the default cutoff."""
    w = World(**kw)
    w.arm("control", *c)
    w.arm("treatment", *t, start="2026-10-01T11:00:00Z")
    return w


# ---------------------------------------------------------------------------------------------------------- fixtures
@pytest.fixture
def db_url() -> Iterator[str]:
    import psycopg
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is not set")
    with psycopg.connect(url) as conn:
        migrate.reset(conn)
        migrate.apply_migrations(conn)
    yield url


@pytest.fixture
def conn(db_url: str) -> Iterator[Any]:
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(db_url, row_factory=dict_row, autocommit=True) as c:
        yield c


@pytest.fixture
def client(db_url: str):
    from fastapi.testclient import TestClient
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        yield c


def load(conn, inputs: dict[str, Any], **kw: Any) -> dict[str, Any]:
    """seed.seed in ONE transaction (the test connection autocommits: a commit per row would take seconds)."""
    with conn.transaction():
        return seed.seed(conn, inputs, **kw)


def count(conn, table: str, where: str = "true") -> int:
    return conn.execute(f"SELECT count(*) AS n FROM {table} WHERE {where}").fetchone()["n"]  # table and where are test constants


_seq = {"n": 0}


def set_clock(at: str) -> None:
    """Move the (frozen) API clock: a cutoff, a fact or a decision cannot be dated after it (D-10). The autouse fixture restores it."""
    from api import clock  # noqa: PLC0415
    clock.freeze(ts(at))


def current_dataset_version() -> str:
    """The dataset_version the database names now ("ds-test" when none): commands carry the current version, as a client that
    has just read the data would (a stale version is 409)."""
    import psycopg
    url = os.environ.get("DATABASE_URL")
    if not url:
        return "ds-test"
    with psycopg.connect(url) as c:
        row = c.execute("SELECT dataset_version FROM dataset_versions ORDER BY created_at DESC, dataset_version DESC LIMIT 1").fetchone()
    return row[0] if row else "ds-test"


def command(client, name: str, input_: dict[str, Any], key: str | None = None, headers: dict[str, str] | None = None,
            request_id: str = "req-test", dataset_version: str | None = None):
    """POST one command with a fresh idempotency key unless ``key`` is given (default actor: the experimenter)."""
    if key is None:
        _seq["n"] += 1
        key = f"key-{os.getpid()}-{_seq['n']}"
    body = {"request_id": request_id, "dataset_version": dataset_version or current_dataset_version(),
            "idempotency_key": key, "input": input_}
    return client.post(f"{PREFIX}/commands/{name}", json=body, headers=EXPERIMENTER if headers is None else headers)


def rule_ids(response) -> list[str]:
    return [d["rule_id"] for d in response.json()["error"]["details"]]


def get(client, path: str, **params):
    return client.get(f"{PREFIX}{path}", params={k: v for k, v in params.items() if v is not None})


def plan_input(plan: dict[str, Any]) -> dict[str, Any]:
    """C06 input from a plan object (the plan without config_hash)."""
    return {k: v for k, v in plan.items() if k != "config_hash"}


def drive(client, conn, inputs: dict[str, Any]) -> dict[str, Any]:
    """Replay ``inputs`` through the API commands: reference data by the data load, then C06 (plan), C03 (funnel), C01 (events with
    their properties, as an admin backfill), C02 (links), C04 (assignments) and C05 (exposures), both as an admin backfill (D-10), and C07 (observations at the cutoff);
    the logged runs are loaded as history. Returns the HTTP status of every call by name."""
    load(conn, inputs, reference_only=True)
    log: dict[str, Any] = {}
    plan = inputs["analysis_plan"]
    if inputs["experiment_versions"]:
        log["plan"] = command(client, "freeze-analysis-plan", plan_input(plan)).status_code
    fn = inputs["metric_windows"]["funnel"]
    log["funnel"] = command(client, "define-funnel", {"definition_id": fn["definition_id"], "steps": fn["steps"], "max_gap_hours": fn["max_gap_hours"],
                                                      "window": {"from": fn["from"], "to": fn["to"]}}, headers=ANALYST).status_code
    props: dict[str, list] = {}
    for p in inputs["event_properties"]:
        props.setdefault(p["event_id"], []).append(p)
    evs = inputs["events"]
    for i in range(0, len(evs), 400):
        chunk = evs[i:i + 400]
        r = command(client, "validate-tracking", {"events": chunk, "properties": [p for e in chunk for p in props.get(e["event_id"], [])]}, headers=ADMIN)
        log[f"events:{i}"] = r.status_code
    for l in inputs["identity_links"]:
        r = command(client, "resolve-identity", {"anonymous_id": l["anonymous_id"], "user_id": l["user_id"], "linked_at": l["linked_at"],
                                                 "rule_version": l["rule_version"], "identity_link_id": l["identity_link_id"]}, headers=ANALYST)
        log[f"link:{l['identity_link_id']}"] = r.status_code
    for a in sorted(inputs["assignments"], key=lambda a: (a["assigned_at"], a["assignment_id"])):
        r = command(client, "assign-experiment", {"experiment_version_id": a["experiment_version_id"], "unit_id": a["unit_id"], "variant": a["variant"],
                                                   "assignment_id": a["assignment_id"], "assigned_at": a["assigned_at"], "backfill": True}, headers=ADMIN)
        log[f"assign:{a['assignment_id']}"] = r.status_code
    for x in sorted(inputs["exposures"], key=lambda x: (x["exposed_at"], x["exposure_id"])):
        r = command(client, "record-exposure", {"assignment_id": x["assignment_id"], "exposed_at": x["exposed_at"], "surface": x["surface"],
                                                "exposure_id": x["exposure_id"], "event_id": x["event_id"], "backfill": True}, headers=ADMIN)
        log[f"expose:{x['exposure_id']}"] = r.status_code
    if inputs["experiment_versions"]:
        log["maturity"] = command(client, "check-maturity", {"experiment_version_id": plan["experiment_version_id"], "cutoff": inputs["cutoff"]},
                                  headers=ANALYST).status_code
    for r in inputs["analysis_runs"]:
        conn.execute("INSERT INTO analysis_runs (analysis_id, experiment_version_id, cutoff_at, config_hash, created_at, created_by) "
                     "VALUES (%s,%s,%s,%s,%s,'history')", (r["analysis_id"], r["experiment_version_id"], r["cutoff_at"], r["config_hash"], r["created_at"]))
    return log


def random_world(seed: int) -> dict[str, Any]:
    """A seeded random population that exercises every rule and contains no rejectable row: three timezones, plans and segments,
    bots, internal accounts, anonymous visitors with links, duplicates, late and unknown-identity events, sessions on every day
    index, subscriptions in every status, an assignment and exposure per account, activations around the 7-day edge and logged runs."""
    import random
    rnd = random.Random(seed)
    cutoff = rnd.choice(["2026-10-26T00:00:00Z", "2026-10-14T12:00:00Z", "2026-11-20T00:00:00Z"])
    w = World(cutoff=cutoff, planned_end=rnd.choice(["2026-10-15T00:00:00Z", "2026-11-01T00:00:00Z"]),
              allocation=rnd.choice([{"control": "0.500000", "treatment": "0.500000"}, {"control": "0.600000", "treatment": "0.400000"}]))
    w.d["experiment_versions"][0]["planned_end"] = w.d["analysis_plan"]["planned_end"]
    tzs = ["UTC", "America/New_York", "America/Los_Angeles", "Asia/Kolkata"]
    base = ts("2026-09-10T00:00:00Z")
    accounts = []
    for i in range(rnd.randint(10, 60)):
        aid = f"acc-{i:03d}"
        w.account(aid, plan=rnd.choice(["free", "team", "business"]), segment=rnd.choice(["smb", "mid", "enterprise"]), tz=rnd.choice(tzs),
                  internal=rnd.random() < 0.06, bot=rnd.random() < 0.05)
        accounts.append(aid)
        t0 = base + timedelta(minutes=rnd.randint(0, 60 * 24 * 40))
        w.signup(aid, iso(t0))
        if rnd.random() < 0.15:                                                           # a second user signs up earlier or later
            w.user(f"u-{aid}-b", aid)
            w.event("signup", iso(t0 + timedelta(hours=rnd.randint(-30, 30))), user=f"u-{aid}-b")
        for _ in range(rnd.choice([0, 0, 1, 2])):
            edge = rnd.choice([timedelta(hours=1), timedelta(days=7) - timedelta(seconds=1), timedelta(days=7), timedelta(days=3)])
            w.activate(aid, iso(t0 + edge), recv=iso(t0 + edge + timedelta(hours=rnd.choice([0, 0, 30, 24 * 20]))))
        for _ in range(rnd.randint(0, 5)):
            w.session(aid, iso(t0 + timedelta(hours=rnd.randint(0, 24 * 40), minutes=rnd.randint(0, 59))))
        if rnd.random() < 0.3:
            w.sub(aid, iso(ts("2026-10-01T00:00:00Z") + timedelta(days=rnd.randint(-3, 16))), rnd.choice(["19.00", "49.00", "99.50", "149.99"]),
                  status=rnd.choice(["active", "ended", "trial", "refunded"]))
        if rnd.random() < 0.3:
            w.event("product_error", iso(t0 + timedelta(days=rnd.randint(0, 9), hours=rnd.randint(0, 23))), user=f"u-{aid}")
        if rnd.random() < 0.3:
            fe = iso(ts("2026-09-21T00:00:00Z") + timedelta(hours=rnd.randint(-5, 24 * 7 + 5)))
            props = {"feature": rnd.choice(["export", "import"])}
            w.event("feature_used", fe, user=f"u-{aid}", props=props, eid=f"ev-fu-{i}")
            if rnd.random() < 0.4:
                w.event("feature_used", fe, user=f"u-{aid}", props=props, eid=f"ev-fu-{i}-dup", recv=iso(ts(fe) + timedelta(seconds=7)))
        if rnd.random() < 0.8 and not w.d["accounts"][-1]["internal"]:
            variant = rnd.choice(["control", "treatment"])
            at = t0 + timedelta(minutes=rnd.randint(0, 600))
            asid = w.assign(aid, variant, iso(at))
            if rnd.random() < 0.7:
                w.expose(asid, iso(at + timedelta(minutes=rnd.randint(0, 120))))
    for j in range(rnd.randint(0, 25)):                                                    # anonymous visitors and links
        anon = f"a-{j:03d}"
        t0 = ts("2026-10-04T00:00:00Z") + timedelta(hours=rnd.randint(0, 24 * 9))
        w.event("visit", iso(t0), anon=anon)
        if rnd.random() < 0.7:
            aid = rnd.choice(accounts)
            at = t0 + timedelta(minutes=rnd.randint(-10, 200))
            w.link(anon, f"u-{aid}", iso(at)) if not any(l["anonymous_id"] == anon for l in w.d["identity_links"]) else None
            w.event("signup", iso(at), anon=anon)
            if rnd.random() < 0.6:
                w.event("onboarding_step_1", iso(at + timedelta(hours=rnd.choice([1, 40, 48, 49]))), user=f"u-{aid}")
        if rnd.random() < 0.3:
            w.event("visit", iso(t0 + timedelta(hours=rnd.randint(1, 80))), anon=anon)
    for _ in range(rnd.randint(0, 6)):
        w.event(rnd.choice(["visit", "signup", "activated"]), iso(ts("2026-10-06T00:00:00Z") + timedelta(hours=rnd.randint(0, 100))), user="u-ghost")
    xs = [e for e in w.d["events"]]
    for e in rnd.sample(xs, min(len(xs), 4)):                                              # re-sent events under new ids
        dup = dict(e, event_id=e["event_id"] + "-r", received_at=iso(ts(e["received_at"]) + timedelta(seconds=rnd.randint(1, 30))))
        w.d["events"].append(dup)
        for p in [p for p in w.d["event_properties"] if p["event_id"] == e["event_id"]]:
            w.d["event_properties"].append(dict(p, property_id=p["property_id"] + "-r", event_id=dup["event_id"]))
    for k in range(rnd.randint(0, 3)):
        w.run(iso(ts("2026-10-05T00:00:00Z") + timedelta(days=rnd.randint(0, 25))), iso(ts("2026-10-05T01:00:00Z") + timedelta(days=rnd.randint(0, 25))))
    return w.data()


class Lab:
    """An API session over a seeded world: the reference data and the assignments as facts, then the commands drive the rest
    (plan, maturity, runs, reviews, decisions). ``plan=False`` leaves the plan unfrozen so C06 can freeze it."""

    def __init__(self, client, conn, world: World | None = None, plan: bool = True, facts: bool = True) -> None:
        self.client, self.conn = client, conn
        self.w = world or small_experiment((50, 10), (50, 25))
        d = self.w.data()
        if not plan:
            d["analysis_plan"] = None
        if not facts:
            load(conn, d, reference_only=True)
        else:
            load(conn, d)

    def post(self, name: str, input_: dict[str, Any], who: dict[str, str] | None = None, **kw):
        return command(self.client, name, input_, headers=who, **kw)

    def analyze(self, cutoff: str | None = None, who: dict[str, str] | None = None, **kw):
        body = {"experiment_version_id": "xv-001", **({"cutoff": cutoff} if cutoff else {}), **kw}
        return self.post("analyze-experiment", body, who or ANALYST)

    def review(self, analysis_id: str, who: dict[str, str] | None = None):
        return self.post("review-guardrails", {"analysis_id": analysis_id}, who or ANALYST)

    def decide(self, analysis_id: str, review_id: str, decision: str = "ship", who: dict[str, str] | None = None, **kw):
        return self.post("record-decision", {"experiment_version_id": "xv-001", "analysis_id": analysis_id, "review_id": review_id,
                                             "decision": decision, "rationale": "because the evidence says so", **kw}, who or EXPERIMENTER)

    def final(self) -> tuple[str, str]:
        """A final run (cutoff after planned_end) and its guardrail review: (analysis_id, review_id)."""
        a = self.analyze("2026-10-26T00:00:00Z")
        assert a.status_code == 200, a.text
        aid = a.json()["result"]["analysis_id"]
        r = self.review(aid)
        assert r.status_code == 200, r.text
        return aid, r.json()["result"]["review_id"]


def table_digest(conn, tables: list[str]) -> dict[str, str]:
    """A hash of every row of each table: proof that a command left a table untouched."""
    out = {}
    for t in tables:
        rows = conn.execute(f"SELECT to_jsonb(x) AS j FROM {t} x ORDER BY 1").fetchall()       # table names are test constants
        out[t] = sha(json.dumps([r["j"] for r in rows], sort_keys=True, default=str))
    return out
