"""The independent Python side of the analysis (P09-ART-04): every result set of investigations 01..09, 11 (snapshot) and 10 (golden) recomputed from the RAW JSON.

Standard library only (``json``, ``re``, ``fractions``, ``decimal``, ``datetime``): no SQL, no psycopg, no ``changeworks`` domain code, no reference SQL. It reads
``web/public/data/*.json`` (the entity files and the manifest's configuration) or ``tests/fixtures/golden/inputs.json`` and returns, for each result set that ``run_all.py`` also runs in
SQL, the same rows (``<file>__<block>`` keys, same columns, same order) so that the two sides are compared cell by cell. Money, hours, rates, discount factors and NPVs are ``Fraction``s
(never a float) rounded once, half away from zero, to the places the SQL rounds to. The rules are those of docs/contracts.md D-01..D-09 (see 00_portfolio_model.sql); this file is a second,
separately written statement of them, in a different shape (per-scenario dictionaries and lists instead of set-based tables).
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction as F
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "web" / "public" / "data"
GOLDEN = ROOT / "tests" / "fixtures" / "golden" / "inputs.json"
UTC = timezone.utc
ENTITIES = ("initiatives", "process_baselines", "assumption_versions", "resources", "scenario_versions", "cost_items", "benefit_items", "dependencies", "stakeholder_groups",
            "impact_mappings", "resource_allocations", "readiness_assessments", "adoption_observations", "training_completions", "benefit_observations", "risk_items", "forecast_versions")
MONEY_CLASSES = ("cash", "revenue", "avoided_cost_realised", "capacity_converted")


def ts(s: str | None) -> datetime | None:
    return None if s is None else datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def iso(t: datetime | None) -> str | None:
    return None if t is None else t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def dec(s) -> F:
    if isinstance(s, float):
        raise TypeError("float is not allowed")
    return F(Decimal(s))


def rnd(x: F | None, places: int) -> Decimal | None:
    """Round half away from zero (what PostgreSQL's round(numeric) does) and keep the trailing zeros."""
    if x is None:
        return None
    x = F(x)
    scaled = abs(x) * 10 ** places
    n = (scaled.numerator * 2 + scaled.denominator) // (2 * scaled.denominator)
    q = Decimal(n).scaleb(-places).quantize(Decimal(1).scaleb(-places))
    return -q if x < 0 and n else q


def norm(v) -> str:
    """One text for a cell, whichever side produced it (None is the empty text; Decimals keep their places)."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, Decimal):
        return format(v, "f")
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return str(v)


def normalised(rows: list[dict]) -> list[dict]:
    return [{k: norm(v) for k, v in r.items()} for r in rows]


def nonblank(s) -> bool:
    return isinstance(s, str) and bool(s.strip(" \t\r\n\f\v"))


def add_months(d: date, n: int) -> date:
    m = d.year * 12 + d.month - 1 + n
    return date(m // 12, m % 12 + 1, d.day)


def fraction_text(x: F) -> str:
    return str(F(x))


def cstr(rows: list[str]) -> list[str]:
    """Code-point order (the "C" collation): what Python's sort of ASCII ids does."""
    return sorted(rows)


class Ctx:
    def __init__(self, rows: dict[str, list[dict]], config: dict):
        self.rows = {e: rows.get(e, []) for e in ENTITIES}
        self.basis = config["period_basis"]
        self.start = date.fromisoformat(config["period_start"])
        self.as_of = ts(config["as_of"])
        self.ini = {i["initiative_id"]: i for i in self.rows["initiatives"]}
        self.scn = {s["scenario_id"]: s for s in self.rows["scenario_versions"]}
        self.assump = {a["assumption_id"]: a for a in self.rows["assumption_versions"]}
        maxh = max((s["horizon_periods"] for s in self.scn.values()), default=1)
        self.matured = sum(1 for t in range(maxh) if self.period_end(t) <= self.as_of)
        self._flows: dict[str, dict] = {}

    # ---- calendar
    def period_end(self, t: int) -> datetime:
        d = add_months(self.start, (t + 1) * (12 if self.basis == "annual" else 1))
        return datetime(d.year, d.month, d.day, tzinfo=UTC)

    # ---- scenario inputs
    def rate(self, sid: str) -> F:
        s = self.scn[sid]
        if s["rate_basis"] == self.basis:
            return dec(s["discount_rate"])
        return dec(self.assump[s["rate_conversion_assumption_id"]]["value"])

    def rate_source(self, sid: str) -> str:
        s = self.scn[sid]
        return "declared" if s["rate_basis"] == self.basis else "conversion:" + s["rate_conversion_assumption_id"]

    def pick(self, sid: str, iid: str, name: str) -> dict | None:
        s = self.scn[sid]
        pins = set(s["pinned_assumption_ids"])
        created = ts(s["created_at"])
        cands = [a for a in self.rows["assumption_versions"] if a["initiative_id"] == iid and a["name"] == name and (a["assumption_id"] in pins or ts(a["created_at"]) <= created)]
        cands.sort(key=lambda a: (a["assumption_id"] not in pins, -a["version_number"]))
        return cands[0] if cands else None

    def model(self, sid: str, iid: str) -> dict:
        ramp_a = self.pick(sid, iid, "adoption_ramp")
        ramp = [dec(v) for v in ramp_a["values"]] if ramp_a and ramp_a.get("values") is not None else None
        conv = self.pick(sid, iid, "capacity_hourly_rate")
        rate_cap = dec(conv["value"]) if conv and conv.get("value") is not None and nonblank(conv.get("staffing_change_evidence_ref")) else None
        tgt = self.pick(sid, iid, "target_minutes_per_case")
        return {"ramp": ramp, "ramp_id": ramp_a["assumption_id"] if ramp else None, "rate_cap": rate_cap,
                "target": dec(tgt["value"]) if tgt and tgt.get("value") is not None else None}

    def recorded(self, row: dict, created: datetime) -> bool:
        return row.get("recorded_at") is None or ts(row["recorded_at"]) <= created

    def flow(self, sid: str) -> dict:
        """Everything a scenario fixes: cost rows by initiative and period, benefit rows with their class, the flows, NPV and paybacks (exact)."""
        if sid in self._flows:
            return self._flows[sid]
        s = self.scn[sid]
        h, created, r = s["horizon_periods"], ts(s["created_at"]), self.rate(sid)
        q = 1 + r
        out: dict = {"h": h, "r": r, "q": q, "members": sorted(set(s["initiative_ids"])), "costs": {}, "ben": [], "init": {}}
        for iid in out["members"]:
            m = self.model(sid, iid)
            crow = []
            for c in self.rows["cost_items"]:
                if c["initiative_id"] != iid or not self.recorded(c, created):
                    continue
                ps = [c["period_index"]] if c["cost_type"] == "one_time" else list(range(c["start_period"], c["end_period"]))
                crow += [{"cost_id": c["cost_id"], "cost_type": c["cost_type"], "basis": c["cost_basis"], "baseline_version": c.get("baseline_version"), "t": p, "amount": dec(c["amount"])}
                         for p in ps if p < h]
            out["costs"][iid] = crow
            for b in self.rows["benefit_items"]:
                if b["initiative_id"] != iid or b["period_index"] >= h or not self.recorded(b, created):
                    continue
                factor = m["ramp"][min(max(b["period_index"] - b["starts_period"], 0), len(m["ramp"]) - 1)] if m["ramp"] else F(1)
                ramped = dec(b["amount"]) * factor
                realised = b.get("cash_realisation") is True and nonblank(b.get("evidence_ref"))
                if b["benefit_type"] in ("cash", "revenue"):
                    cls = b["benefit_type"]
                elif b["benefit_type"] == "avoided_cost":
                    cls = "avoided_cost_realised" if realised else "avoided_cost_beside"
                else:
                    cls = "capacity_converted" if m["rate_cap"] is not None else "capacity_hours"
                money = None if cls == "capacity_hours" else (ramped * m["rate_cap"] if cls == "capacity_converted" else ramped)
                out["ben"].append({"iid": iid, "benefit_id": b["benefit_id"], "type": b["benefit_type"], "t": b["period_index"], "key": b.get("benefit_source_key"), "ramped": ramped,
                                   "class": cls, "money": money, "enters": cls in MONEY_CLASSES, "trend": dec(b["baseline_trend_per_period"]) if b.get("baseline_trend_per_period") is not None else None})
            costs = [F(0)] * h
            ben = [F(0)] * h
            for c in crow:
                if c["basis"] == "planned":
                    costs[c["t"]] += c["amount"]
            for b in out["ben"]:
                if b["iid"] == iid and b["enters"]:
                    ben[b["t"]] += b["money"]
            net = [ben[t] - costs[t] for t in range(h)]
            cum, cumd, c1, c2 = [], [], F(0), F(0)
            for t in range(h):
                c1 += net[t]
                c2 += net[t] / q ** t
                cum.append(c1)
                cumd.append(c2)
            has_rows = any(c["basis"] == "planned" for c in crow) or any(b["iid"] == iid and b["enters"] for b in out["ben"])
            out["init"][iid] = {"model": m, "costs": costs, "ben": ben, "net": net, "cum": cum, "cumd": cumd, "has_rows": has_rows,
                                "npv": cumd[-1] if has_rows else None, "simple": payback(cum, has_rows), "disc": payback(cumd, has_rows)}
        # double count: money claims and hours
        claims = [b for b in out["ben"] if b["money"] is not None and b["key"] is not None]
        groups: dict[tuple, list] = {}
        for b in claims:
            groups.setdefault((b["key"], b["t"]), []).append(b)
        out["claim_groups"] = {}
        for k, g in groups.items():
            if len({b["iid"] for b in g}) >= 2:
                g = sorted(g, key=lambda b: (-b["money"], not b["enters"], b["iid"], b["benefit_id"]))
                out["claim_groups"][k] = g
        hours = [b for b in out["ben"] if b["type"] == "capacity" and b["key"] is not None]
        hg: dict[tuple, list] = {}
        for b in hours:
            hg.setdefault((b["key"], b["t"]), []).append(b)
        out["hour_groups"] = {k: sorted(g, key=lambda b: (-b["ramped"], b["iid"], b["benefit_id"])) for k, g in hg.items() if len({b["iid"] for b in g}) >= 2}
        out["planned"] = sum((b["money"] for b in out["ben"] if b["money"] is not None), F(0))
        out["removed"] = sum((b["money"] for g in out["claim_groups"].values() for b in g[1:]), F(0))
        out["pv"] = sum((b["money"] / q ** b["t"] for g in out["claim_groups"].values() for b in g[1:] if b["enters"]), F(0))
        out["hours_planned"] = sum((b["ramped"] for b in out["ben"] if b["type"] == "capacity"), F(0))
        out["hours_removed"] = sum((b["ramped"] for g in out["hour_groups"].values() for b in g[1:]), F(0))
        with_flows = [i for i in out["init"].values() if i["has_rows"]]
        out["sum_npv"] = sum((i["npv"] for i in with_flows), F(0))
        out["with_flows"] = len(with_flows)
        out["attributable"] = out["sum_npv"] - out["pv"]
        self._flows[sid] = out
        return out


def payback(cum: list[F], has_rows: bool) -> dict:
    """The last crossing (R9-12): the first period after the last negative cumulative; null with a reason otherwise."""
    h = len(cum)
    if not has_rows:
        return {"t": None, "i": None, "reason": "NO_FLOWS"}
    neg = [t for t, v in enumerate(cum) if v < 0]
    if not neg:
        return {"t": None, "i": None, "reason": "NO_INVESTMENT"}
    last = neg[-1]
    if last == h - 1:
        return {"t": None, "i": None, "reason": "NOT_RECOVERED"}
    t = last + 1
    return {"t": t, "i": (t - 1) + (-cum[t - 1]) / (cum[t] - cum[t - 1]), "reason": None}


def exact_text(x: F | None) -> str | None:
    return None if x is None else str(F(x))


def load_snapshot() -> Ctx:
    manifest = json.loads((DATA / "manifest.json").read_text())
    rows = {e: json.loads((DATA / f"{e}.json").read_text())["rows"] for e in ENTITIES}
    return Ctx(rows, manifest["config"])


def load_golden() -> Ctx:
    inputs = json.loads(GOLDEN.read_text())
    return Ctx({e: inputs.get(e, []) for e in ENTITIES}, {"period_basis": inputs["period_basis"], "period_start": inputs["period_start"], "as_of": inputs["as_of"]})


# ---------------------------------------------------------------------------------------------------------------------------------------------
# people, observations, calendar
# ---------------------------------------------------------------------------------------------------------------------------------------------
def visible_adoption(c: Ctx) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for iid in c.ini:
        rows = [a for a in c.rows["adoption_observations"] if a["initiative_id"] == iid and ts(a["observed_at"]) <= c.as_of and ts(a.get("recorded_at") or a["observed_at"]) <= c.as_of]
        if rows:
            out[iid] = max(rows, key=lambda a: (ts(a["observed_at"]), ts(a.get("recorded_at") or a["observed_at"]), a["observation_id"]))
    return out


def visible_training(c: Ctx) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for iid in c.ini:
        rows = [t for t in c.rows["training_completions"] if t["initiative_id"] == iid and ts(t["recorded_at"]) <= c.as_of and ts(t.get("entered_at") or t["recorded_at"]) <= c.as_of]
        if rows:
            out[iid] = max(rows, key=lambda t: (ts(t["recorded_at"]), ts(t.get("entered_at") or t["recorded_at"]), t["training_id"]))
    return out


def latest_obs(c: Ctx) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for bid in {o["benefit_id"] for o in c.rows["benefit_observations"]}:
        rows = [o for o in c.rows["benefit_observations"] if o["benefit_id"] == bid and ts(o["observed_at"]) <= c.as_of and ts(o.get("recorded_at") or o["observed_at"]) <= c.as_of]
        if rows:
            out[bid] = max(rows, key=lambda o: (ts(o["observed_at"]), ts(o.get("recorded_at") or o["observed_at"]), o["benefit_observation_id"]))
    return out


def feasible_starts(c: Ctx) -> dict[str, dict]:
    deps = c.rows["dependencies"]
    memo: dict[str, int] = {}

    def fs(iid: str) -> int:
        if iid in memo:
            return memo[iid]
        best = c.ini[iid]["requested_start_period"]
        for d in deps:
            if d["initiative_id"] == iid:
                pre = d["prerequisite_id"]
                best = max(best, fs(pre) + (c.ini[pre]["duration_periods"] if d["dependency_type"] == "finish_to_start" else 0) + d["lag_periods"])
        memo[iid] = best
        return best
    out = {}
    for iid, i in c.ini.items():
        f = fs(iid)
        bind = None
        if f > i["requested_start_period"]:
            ids = [d["dependency_id"] for d in deps if d["initiative_id"] == iid
                   and fs(d["prerequisite_id"]) + (c.ini[d["prerequisite_id"]]["duration_periods"] if d["dependency_type"] == "finish_to_start" else 0) + d["lag_periods"] == f]
            bind = min(ids) if ids else None
        out[iid] = {"requested_start": i["requested_start_period"], "duration_periods": i["duration_periods"], "deployment_period": i["deployment_period"], "feasible_start": f,
                    "delay": f - i["requested_start_period"], "binding": bind}
    return out


# ---------------------------------------------------------------------------------------------------------------------------------------------
# the result sets
# ---------------------------------------------------------------------------------------------------------------------------------------------
def r2(x):
    return rnd(x, 2)


def class_total(fl: dict, cls: str, iid: str | None = None) -> F:
    return sum((b["money"] for b in fl["ben"] if b["class"] == cls and (iid is None or b["iid"] == iid)), F(0))


def planned_costs(fl: dict, iid: str | None = None) -> F:
    return sum((x["amount"] for i, rows in fl["costs"].items() if iid is None or i == iid for x in rows if x["basis"] == "planned"), F(0))


def r01(c: Ctx) -> dict:
    by, ident, ini25 = [], [], []
    for sid in sorted(c.scn):
        fl = c.flow(sid)
        cash, rev = class_total(fl, "cash"), class_total(fl, "revenue")
        avr, cap, bes = class_total(fl, "avoided_cost_realised"), class_total(fl, "capacity_converted"), class_total(fl, "avoided_cost_beside")
        hrs_nc = sum((b["ramped"] for b in fl["ben"] if b["class"] == "capacity_hours"), F(0))
        by.append({"scenario_id": sid, "initiatives": len(fl["members"]), "horizon_periods": fl["h"], "rate_basis": c.scn[sid]["rate_basis"],
                   "declared_rate": rnd(dec(c.scn[sid]["discount_rate"]), 6), "period_rate": rnd(fl["r"], 6), "planned_costs": r2(planned_costs(fl)),
                   "cash": r2(cash), "revenue": r2(rev), "avoided_cost_realised": r2(avr), "capacity_converted": r2(cap), "avoided_cost_beside": r2(bes),
                   "planned_benefits": r2(fl["planned"]), "double_counted_amount": r2(fl["removed"]), "attributable_benefits": r2(fl["planned"] - fl["removed"]),
                   "capacity_hours_planned": r2(fl["hours_planned"]), "hours_residual": r2(fl["hours_removed"]), "capacity_hours_attributable": r2(fl["hours_planned"] - fl["hours_removed"]),
                   "capacity_hours_not_converted": r2(hrs_nc)})
        entering = sum((b["money"] for b in fl["ben"] if b["enters"]), F(0))
        ident.append({"scenario_id": sid, "entering_the_cash_flow": r2(entering), "beside_the_cash_flow": r2(bes), "planned_benefits": r2(fl["planned"]),
                      "identity_holds_exactly": fl["planned"] == entering + bes, "hour_rows_never_added_to_dollars": sum(1 for b in fl["ben"] if b["class"] == "capacity_hours")})
    fl = c.flow("scn-025")
    for iid in sorted(c.ini):
        ini25.append({"initiative_id": iid, "planned_costs": r2(planned_costs(fl, iid) if iid in fl["members"] else F(0)), "cash": r2(class_total(fl, "cash", iid)),
                      "revenue": r2(class_total(fl, "revenue", iid)), "avoided_cost_realised": r2(class_total(fl, "avoided_cost_realised", iid)),
                      "capacity_converted": r2(class_total(fl, "capacity_converted", iid)), "avoided_cost_beside": r2(class_total(fl, "avoided_cost_beside", iid)),
                      "capacity_hours_not_converted": r2(sum((b["ramped"] for b in fl["ben"] if b["class"] == "capacity_hours" and b["iid"] == iid), F(0)))})
    return {"01_portfolio_ledger__by_scenario": by, "01_portfolio_ledger__class_identity": ident, "01_portfolio_ledger__scn025_by_initiative": ini25}


def r02(c: Ctx) -> dict:
    fl = c.flow("scn-025")
    rows, exact = [], []
    for iid in sorted(fl["init"]):
        i = fl["init"][iid]
        rows.append({"initiative_id": iid, "planned_costs": r2(sum(i["costs"], F(0))), "cash_benefits_entering": r2(sum(i["ben"], F(0))), "undiscounted_net": r2(sum(i["net"], F(0))),
                     "has_flows": i["has_rows"], "npv": r2(i["npv"]) if i["has_rows"] else None})
        exact.append({"initiative_id": iid, "npv_exact": exact_text(i["npv"]) if i["has_rows"] else None})
    port = {"scenario_id": "scn-025", "initiatives_with_flows": fl["with_flows"], "sum_of_initiatives": r2(fl["sum_npv"]), "double_counted_pv": r2(fl["pv"]),
            "attributable_npv": r2(fl["attributable"]), "plain_sum_overstates_by": r2(fl["pv"])}
    by, byx = [], []
    for sid in sorted(c.scn):
        f = c.flow(sid)
        by.append({"scenario_id": sid, "initiatives_with_flows": f["with_flows"], "sum_of_initiatives": r2(f["sum_npv"]), "double_counted_pv": r2(f["pv"]), "attributable_npv": r2(f["attributable"])})
        if f["with_flows"] > 0:
            byx.append({"scenario_id": sid, "attributable_exact": exact_text(f["attributable"])})
    return {"02_initiative_npv__scn025": rows, "02_initiative_npv__scn025_exact": exact, "02_initiative_npv__portfolio_scn025": [port], "02_initiative_npv__by_scenario": by,
            "02_initiative_npv__by_scenario_exact": byx}


def r03(c: Ctx) -> dict:
    fl = c.flow("scn-025")
    keys = sorted({k for (k, _) in fl["claim_groups"]})
    src = []
    for k in keys:
        g = [(p, grp) for (kk, p), grp in sorted(fl["claim_groups"].items()) if kk == k]
        ps = [p for p, _ in g]
        inis = cstr(sorted({b["iid"] for _, grp in g for b in grp}))
        claimed = sum((b["money"] for _, grp in g for b in grp), F(0))
        once = sum((grp[0]["money"] for _, grp in g), F(0))
        src.append({"rule": "money (USD)", "benefit_source_key": k, "overlapping_periods": len(ps), "first_period": min(ps), "last_period": max(ps), "initiatives": ",".join(inis),
                    "claimed": r2(claimed), "counted_once": r2(once), "residual": r2(claimed - once)})
    for k in sorted({k for (k, _) in fl["hour_groups"]}):
        g = [(p, grp) for (kk, p), grp in sorted(fl["hour_groups"].items()) if kk == k]
        ps = [p for p, _ in g]
        inis = cstr(sorted({b["iid"] for _, grp in g for b in grp}))
        claimed = sum((b["ramped"] for _, grp in g for b in grp), F(0))
        once = sum((grp[0]["ramped"] for _, grp in g), F(0))
        src.append({"rule": "hours", "benefit_source_key": k, "overlapping_periods": len(ps), "first_period": min(ps), "last_period": max(ps), "initiatives": ",".join(inis),
                    "claimed": r2(claimed), "counted_once": r2(once), "residual": r2(claimed - once)})
    src.sort(key=lambda r: (r["rule"] == "hours", r["benefit_source_key"]))
    per = []
    for (k, p), grp in sorted(fl["claim_groups"].items()):
        hrs = [b["ramped"] for b in fl["ben"] if b["type"] == "capacity" and b["key"] == k and b["t"] == p]
        hc, ho = sum(hrs, F(0)), (max(hrs) if hrs else F(0))
        claimed = sum((b["money"] for b in grp), F(0))
        per.append({"benefit_source_key": k, "period_index": p, "claims": " + ".join(f"{b['iid']}:{b['benefit_id']}" for b in sorted(grp, key=lambda b: (b["iid"], b["benefit_id"]))),
                    "money_claimed": r2(claimed), "money_counted_once": r2(grp[0]["money"]), "money_residual": r2(claimed - grp[0]["money"]),
                    "hours_claimed": r2(hc), "hours_counted_once": r2(ho), "hours_residual": r2(hc - ho)})
    per.sort(key=lambda r: (r["benefit_source_key"], r["period_index"]))
    pvr = {"scenario_id": "scn-025", "double_counted_amount": r2(fl["removed"]), "double_counted_pv": r2(fl["pv"]), "npv_sum_of_initiatives": r2(fl["sum_npv"]), "npv_attributable": r2(fl["attributable"]),
           "planned_benefits": r2(fl["planned"]), "attributable_benefits": r2(fl["planned"] - fl["removed"]), "planned_hours": r2(fl["hours_planned"]),
           "attributable_hours": r2(fl["hours_planned"] - fl["hours_removed"]), "hours_residual": r2(fl["hours_removed"])}
    bys = []
    for sid in sorted(c.scn):
        f = c.flow(sid)
        need = ("money,hours" if f["removed"] != 0 and f["hours_removed"] != 0 else "money" if f["removed"] != 0 else "hours" if f["hours_removed"] != 0 else "")
        bys.append({"scenario_id": sid, "residual": r2(f["removed"]), "hours_residual": r2(f["hours_removed"]), "double_counted_pv": r2(f["pv"]),
                    "explanation_required": f["removed"] != 0 or f["hours_removed"] != 0, "explanation_required_for": need})
    sids = sorted(c.scn)
    outc = {"scenarios_with_a_money_residual": sum(1 for s in sids if c.flow(s)["removed"] != 0), "scenarios_with_no_money_residual": sum(1 for s in sids if c.flow(s)["removed"] == 0),
            "scenarios_with_an_hours_residual": sum(1 for s in sids if c.flow(s)["hours_removed"] != 0),
            "money_residual_scenarios": ",".join(s for s in sids if c.flow(s)["removed"] != 0) or None,
            "hours_residual_scenarios": ",".join(s for s in sids if c.flow(s)["hours_removed"] != 0) or None}
    return {"03_double_count__by_source_key": src, "03_double_count__by_period": per, "03_double_count__present_value_scn025": [pvr], "03_double_count__by_scenario": bys, "03_double_count__outcome": [outc]}


def r04(c: Ctx) -> dict:
    fl = c.flow("scn-025")
    scn = []
    for iid in sorted(fl["init"]):
        i = fl["init"][iid]
        scn.append({"initiative_id": iid, "npv": r2(i["npv"]) if i["has_rows"] else None, "simple_payback_period": i["simple"]["t"], "simple_interpolated": rnd(i["simple"]["i"], 4),
                    "simple_reason": i["simple"]["reason"], "discounted_payback_period": i["disc"]["t"], "discounted_interpolated": rnd(i["disc"]["i"], 4), "discounted_reason": i["disc"]["reason"]})
    allp = [(sid, iid, i) for sid in sorted(c.scn) for iid, i in sorted(c.flow(sid)["init"].items())]
    reasons: dict[tuple, int] = {}
    for _, _, i in allp:
        k = (i["simple"]["reason"] or "RECOVERED", i["disc"]["reason"] or "RECOVERED")
        reasons[k] = reasons.get(k, 0) + 1
    rr = [{"simple": a, "discounted": b, "series": n} for (a, b), n in sorted(reasons.items())]
    never = []
    for iid in sorted({iid for _, iid, _ in allp}):
        rows = [i for _, x, i in allp if x == iid]
        sn, dn = sum(1 for i in rows if i["simple"]["t"] is None), sum(1 for i in rows if i["disc"]["t"] is None)
        if sn > 0 or dn > 0:
            npvs = [i["npv"] for i in rows]
            never.append({"initiative_id": iid, "scenarios": len(rows), "scenarios_simple_null": sn, "scenarios_discounted_null": dn, "never_in_any_scenario": sn == len(rows),
                          "npv_lowest": r2(min(npvs)), "npv_highest": r2(max(npvs)), "simple_reasons": ",".join(sorted({i["simple"]["reason"] or "RECOVERED" for i in rows}))})
    d15 = []
    for sid in sorted(c.scn):
        f = c.flow(sid)
        if "init-015" in f["init"]:
            i = f["init"]["init-015"]
            cost, ben = sum(i["costs"], F(0)), sum(i["ben"], F(0))
            d15.append({"scenario_id": sid, "ramp_assumption_id": i["model"]["ramp_id"], "planned_cost": r2(cost), "benefits_entering_the_cash_flow": r2(ben), "benefit_to_cost": rnd(ben / cost, 6),
                        "npv": r2(i["npv"]), "simple_payback_period": i["simple"]["t"], "discounted_payback_period": i["disc"]["t"], "simple_reason": i["simple"]["reason"]})
    series = recovered = differ = nneg = noinv = noflows = 0
    for _, _, i in allp:
        series += 1
        cum = i["cum"]
        neg = [t for t, v in enumerate(cum) if v < 0]
        if neg:
            nneg += 1
        if i["simple"]["t"] is not None:
            recovered += 1
            after = [t for t, v in enumerate(cum) if v >= 0 and neg and t > neg[0]]
            if (min(after) if after else None) != i["simple"]["t"]:
                differ += 1
        noinv += i["simple"]["reason"] == "NO_INVESTMENT"
        noflows += i["simple"]["reason"] == "NO_FLOWS"
    lc = {"series": series, "series_that_went_negative": nneg, "series_that_recovered": recovered, "recovered_series_where_first_and_last_crossing_differ": differ, "never_negative": noinv, "no_flows": noflows}
    return {"04_payback__scn025": scn, "04_payback__reasons": rr, "04_payback__never_pays_back": never, "04_payback__init015_by_scenario": d15, "04_payback__last_crossing_rule": [lc]}


def r05(c: Ctx) -> dict:
    items = c.rows["cost_items"]

    def n_exp(x):
        return 1 if x["cost_type"] == "one_time" else x["end_period"] - x["start_period"]
    bt: dict[tuple, list] = {}
    for x in items:
        bt.setdefault((x["cost_type"], x["cost_basis"]), []).append(x)
    by_type = [{"cost_type": k[0], "cost_basis": k[1], "items": len(v), "expanded_rows": sum(n_exp(x) for x in v), "expanded_total": r2(sum((dec(x["amount"]) * n_exp(x) for x in v), F(0))),
                "item_amount_total": r2(sum((dec(x["amount"]) for x in v), F(0)))} for k, v in sorted(bt.items())]
    rec = [x for x in items if x["cost_type"] == "recurring"]
    rbi = []
    for iid in sorted({x["initiative_id"] for x in rec}):
        v = [x for x in rec if x["initiative_id"] == iid]
        rbi.append({"initiative_id": iid, "recurring_items": len(v), "expanded_rows": sum(n_exp(x) for x in v), "first_period": min(x["start_period"] for x in v), "last_period": max(x["end_period"] - 1 for x in v),
                    "first_period_after_the_last_range": max(x["end_period"] for x in v), "expanded_total": r2(sum((dec(x["amount"]) * n_exp(x) for x in v), F(0)))})

    def stem(k):
        return re.sub(r"-s[0-9]+$", "", k)
    pairs = [(a, b) for a in rec for b in rec if b["initiative_id"] == a["initiative_id"] and b["cost_basis"] == a["cost_basis"] and b["start_period"] == a["end_period"]
             and stem(b["cost_key"]) == stem(a["cost_key"]) and b["cost_id"] != a["cost_id"]]

    def carrying(a):
        return sum(1 for x in rec if x["initiative_id"] == a["initiative_id"] and x["cost_basis"] == a["cost_basis"] and stem(x["cost_key"]) == stem(a["cost_key"])
                   and x["start_period"] <= a["end_period"] <= x["end_period"] - 1)
    hob = {"adjacent_range_pairs": len(pairs), "boundary_periods_with_exactly_one_row": sum(1 for a, _ in pairs if carrying(a) == 1),
           "ranges_that_do_not_contain_their_own_end": sum(1 for a, _ in pairs if not (a["start_period"] <= a["end_period"] <= a["end_period"] - 1))}
    one = [x for x in items if x["cost_type"] == "one_time"]
    keyc: dict[tuple, int] = {}
    kinds: dict[tuple, set] = {}
    for x in one:
        keyc[(x["initiative_id"], x["cost_key"], x["cost_basis"])] = keyc.get((x["initiative_id"], x["cost_key"], x["cost_basis"]), 0) + 1
    for x in items:
        kinds.setdefault((x["initiative_id"], x["cost_key"], x["cost_basis"]), set()).add(x["cost_type"])
    otr = {"one_time_items": len(one), "with_exactly_one_period": sum(1 for x in one if x.get("period_index") is not None and x.get("start_period") is None and x.get("end_period") is None),
           "with_no_period": sum(1 for x in one if x.get("period_index") is None), "cost_keys_in_more_than_one_period": sum(1 for v in keyc.values() if v > 1),
           "cost_keys_of_two_kinds": sum(1 for v in kinds.values() if len(v) > 1)}
    c42 = next(x for x in items if x["cost_id"] == "c-0042")
    same = [x for x in items if x["initiative_id"] == c42["initiative_id"] and x["cost_key"] == c42["cost_key"] and x["cost_basis"] == c42["cost_basis"]]
    inj = {"cost_id": c42["cost_id"], "initiative_id": c42["initiative_id"], "cost_key": c42["cost_key"], "cost_type": c42["cost_type"], "amount": r2(dec(c42["amount"])), "period_index": c42["period_index"],
           "rows_with_this_key": len(same), "rows_in_period_5": sum(1 for x in same if x.get("period_index") == 5)}
    fl = c.flow("scn-025")
    s25 = []
    for iid in sorted(c.ini):
        rows = [x for x in fl["costs"].get(iid, []) if x["basis"] == "planned"]
        s25.append({"initiative_id": iid, "one_time_total": r2(sum((x["amount"] for x in rows if x["cost_type"] == "one_time"), F(0))),
                    "recurring_total": r2(sum((x["amount"] for x in rows if x["cost_type"] == "recurring"), F(0))), "planned_costs": r2(sum((x["amount"] for x in rows), F(0))),
                    "expanded_planned_rows": len(rows)})
    return {"05_cost_expansion__by_type": by_type, "05_cost_expansion__recurring_by_initiative": rbi, "05_cost_expansion__half_open_boundaries": [hob], "05_cost_expansion__one_time_rule": [otr],
            "05_cost_expansion__inj11_key": [inj], "05_cost_expansion__scn025_by_initiative": s25}


def realisation(c: Ctx, sid: str) -> dict[tuple, dict]:
    """(initiative, type) -> compared rows, unobserved matured rows, planned, observed, trend, trend rows."""
    fl, obs = c.flow(sid), latest_obs(c)
    out: dict[tuple, dict] = {}
    for b in fl["ben"]:
        k = (b["iid"], b["type"])
        x = out.setdefault(k, {"compared": 0, "unobserved": 0, "planned": F(0), "observed": F(0), "trend": F(0), "trend_rows": 0})
        if b["t"] < c.matured:
            o = obs.get(b["benefit_id"])
            if o is None:
                x["unobserved"] += 1
            else:
                x["compared"] += 1
                x["planned"] += b["ramped"]
                x["observed"] += dec(o["measured_value"])
                if b["trend"] is not None:
                    x["trend"] += b["trend"]
                    x["trend_rows"] += 1
    return out


def r06(c: Ctx) -> dict:
    fl = c.flow("scn-025")
    mat = {"as_of": c.as_of.isoformat(), "period_basis": c.basis, "matured_periods": c.matured, "last_matured_period": c.matured - 1, "first_unmatured_period": c.matured,
           "first_unmatured_period_starts": add_months(c.start, c.matured * (12 if c.basis == "annual" else 1)), "first_unmatured_period_ends": add_months(c.start, (c.matured + 1) * (12 if c.basis == "annual" else 1))}
    var, vsum = [], []
    for iid in sorted(c.ini):
        if iid not in fl["members"]:
            continue
        i = c.ini[iid]
        wend = min(fl["h"], c.matured)
        approved = i.get("baseline_version")
        rows = fl["costs"][iid]
        planned = sum((x["amount"] for x in rows if x["basis"] == "planned" and x["baseline_version"] == approved and x["t"] < wend), F(0)) if approved else F(0)
        act = [x for x in rows if x["basis"] == "actual" and x["t"] < wend]
        actual = sum((x["amount"] for x in act), F(0))
        ok = approved is not None and wend > 0
        var.append({"initiative_id": iid, "window_to_period": wend, "approved_baseline_version": approved,
                    "approved_baseline_cost": r2(planned) if ok else None, "actual_cost": r2(actual) if ok and act else None, "variance": r2(actual - planned) if ok and act else None,
                    "reason": "NO_APPROVED_BASELINE" if approved is None else "NO_MATURED_PERIOD" if wend == 0 else "NO_ACTUALS" if not act else None,
                    "_p": planned, "_a": actual, "_ok": ok and bool(act), "_approved": approved is not None, "_nact": len(act)})
    has = [v for v in var if v["_approved"] and v["_nact"] > 0]
    vsum = [{"initiatives_with_a_variance": len(has), "over_baseline": sum(1 for v in has if v["_a"] > v["_p"]), "under_baseline": sum(1 for v in has if v["_a"] < v["_p"]),
             "on_baseline": sum(1 for v in has if v["_a"] == v["_p"]), "initiatives_with_no_variance": sum(1 for v in var if not v["_approved"] or v["_nact"] == 0),
             "net_variance": r2(sum((v["_a"] - v["_p"] for v in has), F(0))) if has else None}]
    var = [{k: v for k, v in r.items() if not k.startswith("_")} for r in var]
    real = realisation(c, "scn-025")
    rr, share = [], []
    for (iid, typ) in sorted(real):
        x = real[(iid, typ)]
        if x["compared"] == 0 and x["unobserved"] == 0:
            continue
        cmp_ = x["compared"] > 0
        rr.append({"initiative_id": iid, "benefit_type": typ, "unit": "hours" if typ == "capacity" else "USD", "compared_rows": x["compared"], "matured_unobserved_rows": x["unobserved"],
                   "planned_comparable": r2(x["planned"]) if cmp_ else None, "observed_comparable": r2(x["observed"]) if cmp_ else None,
                   "realisation": rnd(x["observed"] / x["planned"], 6) if cmp_ and x["planned"] != 0 else None,
                   "baseline_trend": r2(x["trend"]) if x["trend_rows"] > 0 else None,
                   "observed_above_trend": r2(x["observed"] - x["trend"]) if x["trend_rows"] > 0 and cmp_ and x["trend_rows"] == x["compared"] else None,
                   "trend_share_of_observed": rnd(x["trend"] / x["observed"], 6) if x["trend_rows"] > 0 and cmp_ and x["observed"] != 0 else None, "attribution": "observed, not attributed"})
    cands = [(iid, x) for (iid, typ), x in real.items() if typ == "cash" and x["compared"] > 0 and x["trend_rows"] == x["compared"] and x["observed"] != 0 and x["planned"] != 0]
    cands.sort(key=lambda t: (-(t[1]["trend"] / t[1]["observed"]), t[0]))
    for iid, x in cands[:5]:
        share.append({"initiative_id": iid, "observed_comparable": r2(x["observed"]), "baseline_trend": r2(x["trend"]), "observed_above_trend": r2(x["observed"] - x["trend"]),
                      "trend_share_of_observed": rnd(x["trend"] / x["observed"], 6), "realisation": rnd(x["observed"] / x["planned"], 6)})
    comp = [x for x in real.values() if x["compared"] > 0]
    cov = {"comparisons": len(comp), "with_complete_trend_coverage": sum(1 for x in comp if x["trend_rows"] == x["compared"]), "with_partial_trend_coverage": sum(1 for x in comp if x["trend_rows"] < x["compared"]),
           "rows_compared": sum(x["compared"] for x in comp), "matured_rows_with_no_observation": sum(x["unobserved"] for x in comp)}
    return {"06_variance_realisation__matured": [mat], "06_variance_realisation__cost_variance_scn025": var, "06_variance_realisation__variance_summary_scn025": vsum,
            "06_variance_realisation__realisation_scn025": rr, "06_variance_realisation__trend_beside_raw": share, "06_variance_realisation__coverage": [cov]}


def month_index(t: datetime) -> int:
    return t.year * 12 + t.month - 1


def r07(c: Ctx) -> dict:
    ad, tr = visible_adoption(c), visible_training(c)
    by = []
    for iid in sorted(c.ini):
        a, t = ad.get(iid), tr.get(iid)
        ar = rnd(F(a["adopted_count"], a["eligible_count"]), 6) if a and a["eligible_count"] > 0 else None
        tc = rnd(F(t["completed"], t["eligible_trainees"]), 6) if t and t["eligible_trainees"] > 0 else None
        both = bool(a and a["eligible_count"] > 0 and t and t["eligible_trainees"] > 0)
        by.append({"initiative_id": iid, "eligibility_rule_version": c.ini[iid]["eligibility_rule_version"], "adoption_eligible": a["eligible_count"] if a else None,
                   "adopted": a["adopted_count"] if a else None, "adoption_rate": ar, "training_eligible": t["eligible_trainees"] if t else None, "training_completed": t["completed"] if t else None,
                   "training_completion": tc, "training_minus_adoption": rnd(F(t["completed"], t["eligible_trainees"]) - F(a["adopted_count"], a["eligible_count"]), 6) if both else None,
                   "has_both_series": both if both else None})
    A = [a for a in ad.values() if a["eligible_count"] > 0]
    T = [t for t in tr.values() if t["eligible_trainees"] > 0]
    pooled = {"initiatives_with_adoption": len(A), "adopted": sum(a["adopted_count"] for a in A), "adoption_eligible": sum(a["eligible_count"] for a in A),
              "adoption_rate_pooled": rnd(F(sum(a["adopted_count"] for a in A), sum(a["eligible_count"] for a in A)), 6), "initiatives_with_training": len(T),
              "training_completed": sum(t["completed"] for t in T), "training_eligible": sum(t["eligible_trainees"] for t in T),
              "training_completion_pooled": rnd(F(sum(t["completed"] for t in T), sum(t["eligible_trainees"] for t in T)), 6)}
    both_ids = sorted(i for i in c.ini if i in ad and ad[i]["eligible_count"] > 0 and i in tr and tr[i]["eligible_trainees"] > 0)
    Ab, Tb = [ad[i] for i in both_ids], [tr[i] for i in both_ids]
    common = {"initiatives_with_both_series": len(both_ids), "adopted": sum(a["adopted_count"] for a in Ab), "adoption_eligible": sum(a["eligible_count"] for a in Ab),
              "adoption_rate_pooled": rnd(F(sum(a["adopted_count"] for a in Ab), sum(a["eligible_count"] for a in Ab)), 6), "training_completed": sum(t["completed"] for t in Tb),
              "training_eligible": sum(t["eligible_trainees"] for t in Tb), "training_completion_pooled": rnd(F(sum(t["completed"] for t in Tb), sum(t["eligible_trainees"] for t in Tb)), 6),
              "reached_half_adoption": sum(1 for a in Ab if a["adopted_count"] * 2 >= a["eligible_count"]), "not_yet_half_adoption": sum(1 for a in Ab if a["adopted_count"] * 2 < a["eligible_count"])}
    lag_rows, lags = [], []
    for iid in sorted(c.ini):
        trs = sorted((t for t in c.rows["training_completions"] if t["initiative_id"] == iid and t["completed"] * 100 >= t["eligible_trainees"] * 90 and ts(t["recorded_at"]) <= c.as_of),
                     key=lambda t: (ts(t["recorded_at"]), t["training_id"]))
        if not trs or iid not in ad or ad[iid]["eligible_count"] <= 0 or iid not in tr:
            continue
        t90 = ts(trs[0]["recorded_at"])
        a50s = sorted((a for a in c.rows["adoption_observations"] if a["initiative_id"] == iid and a["eligible_count"] > 0 and a["adopted_count"] * 2 >= a["eligible_count"] and ts(a["observed_at"]) <= c.as_of),
                      key=lambda a: (ts(a["observed_at"]), a["observation_id"]))
        a50 = ts(a50s[0]["observed_at"]) if a50s else None
        lag = month_index(a50) - month_index(t90) if a50 else None
        lags.append((iid, lag))
        lag_rows.append({"initiative_id": iid, "training_90_percent_on": iso(t90), "adoption_50_percent_on": iso(a50), "lag_periods": lag,
                         "periods_since_training_90_percent": month_index(c.as_of) - month_index(t90),
                         "training_completion_now": rnd(F(tr[iid]["completed"], tr[iid]["eligible_trainees"]), 6), "adoption_rate_now": rnd(F(ad[iid]["adopted_count"], ad[iid]["eligible_count"]), 6)})
    reached = sorted(l for _, l in lags if l is not None)
    summ = {"initiatives_with_both_series": len(lags), "reached_half_adoption": len(reached), "not_yet_half_adoption": len(lags) - len(reached),
            "lag_periods_sorted": ",".join(map(str, reached)) if reached else None, "never_reached_half_adoption": ",".join(i for i, l in lags if l is None) or None}
    return {"07_adoption_training__by_initiative": by, "07_adoption_training__pooled": [pooled], "07_adoption_training__common_population": [common],
            "07_adoption_training__lag_to_half_adoption": lag_rows, "07_adoption_training__lag_summary": [summ]}


def r08(c: Ctx) -> dict:
    fv = c.rows["forecast_versions"]
    vers: dict[tuple, list] = {}
    for f in fv:
        vers.setdefault((f["initiative_id"], f["version_number"]), []).append(f)
    versions = []
    for (iid, v), rows in sorted(vers.items()):
        versions.append({"initiative_id": iid, "version_number": v, "created_at": iso(min(ts(f["created_at"]) for f in rows)), "periods": len(rows), "first_period": min(f["period_index"] for f in rows),
                         "last_period": max(f["period_index"] for f in rows), "total": r2(sum((dec(f["amount"]) for f in rows), F(0))), "reason": min(f["reason"] for f in rows)})
    orig = []
    for iid in sorted({i for i, _ in vers}):
        vs = sorted(v for i, v in vers if i == iid)
        if 1 not in vs:
            continue
        o = {f["period_index"] for f in vers[(iid, 1)]}
        tot1 = sum((dec(f["amount"]) for f in vers[(iid, 1)]), F(0))
        totl = sum((dec(f["amount"]) for f in vers[(iid, vs[-1])]), F(0))
        orig.append({"initiative_id": iid, "versions": len(vs), "original_rows": len(vers[(iid, 1)]), "original_version": 1,
                     "every_version_covers_the_original_periods": all(o <= {f["period_index"] for f in vers[(iid, v)]} for v in vs), "original_total": r2(tot1), "latest_minus_original": r2(totl - tot1)})
    i3 = sorted(v for i, v in vers if i == "init-003")
    tot = {v: sum((dec(f["amount"]) for f in vers[("init-003", v)]), F(0)) for v in i3}
    v3 = [{"version_number": v, "created_at": iso(min(ts(f["created_at"]) for f in vers[("init-003", v)])), "total": r2(tot[v]), "change_vs_original": r2(tot[v] - tot[1]),
           "change_vs_previous": r2(tot[v] - (tot[v - 1] if v - 1 in tot else tot[v])), "reason": min(f["reason"] for f in vers[("init-003", v)])} for v in i3]
    obs = latest_obs(c)
    ben3 = {b["benefit_id"]: b for b in c.rows["benefit_items"] if b["initiative_id"] == "init-003" and b["benefit_type"] == "cash"}
    obsp = {ben3[bid]["period_index"]: dec(o["measured_value"]) for bid, o in obs.items() if bid in ben3}
    byp = []
    for p in sorted({f["period_index"] for f in fv if f["initiative_id"] == "init-003"}):
        amt = {v: dec(next(f["amount"] for f in vers[("init-003", v)] if f["period_index"] == p)) for v in i3}
        byp.append({"period_index": p, "v1": r2(amt.get(1)), "v2": r2(amt.get(2)), "v3": r2(amt.get(3)), "latest_observed": r2(obsp[p]) if p in obsp else None,
                    "observed_over_v1": rnd(obsp[p] / amt[1], 6) if p in obsp else None})

    def known(iid: str, at: datetime) -> dict[int, F]:
        out: dict[int, F] = {}
        for b in c.rows["benefit_items"]:
            if b["initiative_id"] != iid or b["benefit_type"] != "cash":
                continue
            rows = [o for o in c.rows["benefit_observations"] if o["benefit_id"] == b["benefit_id"] and ts(o["observed_at"]) <= at and ts(o.get("recorded_at") or o["observed_at"]) <= at]
            if rows:
                o = max(rows, key=lambda o: (ts(o["observed_at"]), o["benefit_observation_id"]))
                out[b["period_index"]] = dec(o["measured_value"])
        return out
    trig = []
    for (iid, v), rows in sorted(vers.items()):
        if v - 1 < 1 or (iid, v - 1) not in vers:
            continue
        at, prev_at = min(ts(f["created_at"]) for f in rows), min(ts(f["created_at"]) for f in vers[(iid, v - 1)])
        k, kp = known(iid, at), known(iid, prev_at)
        chk = [(f["period_index"], dec(f["amount"]), k[f["period_index"]]) for f in sorted(vers[(iid, v - 1)], key=lambda f: f["period_index"]) if f["period_index"] in k and f["period_index"] not in kp]
        if not chk:
            continue
        below = [p for p, a, o in chk if o * 10 < a * 9]
        trig.append({"initiative_id": iid, "revision": v, "revises_version": v - 1, "created_at": iso(at), "periods_checked": ",".join(str(p) for p, _, _ in chk),
                     "periods_more_than_10_percent_below": ",".join(map(str, below)) or None, "lowest_observed_over_forecast": rnd(min(o / a for _, a, o in chk), 6),
                     "highest_observed_over_forecast": rnd(max(o / a for _, a, o in chk), 6)})
    return {"08_forecast_revisions__versions": versions, "08_forecast_revisions__original_preserved": orig, "08_forecast_revisions__init003_versions": v3,
            "08_forecast_revisions__init003_by_period": byp, "08_forecast_revisions__revision_triggers": trig}


def r09(c: Ctx) -> dict:
    fs = feasible_starts(c)
    dd, dbfs = [], []
    for iid in sorted(fs):
        f = fs[iid]
        dd.append({"initiative_id": iid, "requested_start": f["requested_start"], "duration_periods": f["duration_periods"], "dependency_feasible_start": f["feasible_start"], "dependency_delay": f["delay"],
                   "binding_dependency_id": f["binding"], "finish": f["feasible_start"] + f["duration_periods"], "deployment_period": f["deployment_period"],
                   "deployment_before_feasible_start": f["deployment_period"] < f["feasible_start"]})
        if f["deployment_period"] < f["feasible_start"]:
            dbfs.append({"initiative_id": iid, "deployment_period": f["deployment_period"], "dependency_feasible_start": f["feasible_start"], "periods_early": f["feasible_start"] - f["deployment_period"],
                         "binding_dependency_id": f["binding"]})
    deps = c.rows["dependencies"]
    summ = {"initiatives": len(fs), "delayed": sum(1 for f in fs.values() if f["delay"] > 0), "not_delayed": sum(1 for f in fs.values() if f["delay"] == 0), "longest_delay": max(f["delay"] for f in fs.values()),
            "dependencies": len(deps), "finish_to_start": sum(1 for d in deps if d["dependency_type"] == "finish_to_start"), "start_to_start": sum(1 for d in deps if d["dependency_type"] == "start_to_start"),
            "delayed_without_a_binding_dependency": sum(1 for f in fs.values() if f["delay"] > 0 and f["binding"] is None)}
    # paths along the stored dependencies (prerequisite -> dependent), counting every path and every revisit of an initiative already on the path
    paths = cycles = 0
    longest = 0
    stack = [([d["prerequisite_id"], d["initiative_id"]], d["prerequisite_id"] == d["initiative_id"]) for d in deps]
    while stack:
        path, cyc = stack.pop()
        paths += 1
        cycles += cyc
        longest = max(longest, len(path))
        if cyc or len(path) >= 40:
            continue
        for d in deps:
            if d["prerequisite_id"] == path[-1]:
                stack.append((path + [d["initiative_id"]], d["initiative_id"] in path))
    cyc_row = {"dependencies": len(deps), "paths_walked": paths, "cycles_found": cycles, "self_dependencies": sum(1 for d in deps if d["initiative_id"] == d["prerequisite_id"]), "longest_chain_of_initiatives": longest}
    # the refused edge (typed from the replay event EV-07): the shortest stored path from the edge's initiative (as a prerequisite) to its prerequisite
    ev = next(e for e in json.loads((DATA / "injection-manifest.json").read_text())["events"] if e["event_id"] == "EV-07")
    edge = ev["steps"][0]["row"]
    best = None
    stack2 = [([d["prerequisite_id"], d["initiative_id"]], [d["dependency_id"]]) for d in deps if d["prerequisite_id"] == edge["initiative_id"]]
    while stack2:
        path, edges = stack2.pop()
        if path[-1] == edge["prerequisite_id"]:
            key = (len(path), ",".join(path))
            if best is None or key < best[0]:
                best = (key, path, edges)
        if len(path) < 40:
            for d in deps:
                if d["prerequisite_id"] == path[-1]:
                    stack2.append((path + [d["initiative_id"]], edges + [d["dependency_id"]]))
    refused = [{"rejected_edge_initiative": edge["initiative_id"], "rejected_edge_prerequisite": edge["prerequisite_id"],
                "cycle_it_would_close": " -> ".join([edge["initiative_id"]] + list(reversed(best[1]))), "stored_edges_on_the_path": ",".join(best[2])}]
    cap = {r["resource_id"]: dec(r["capacity_per_period"]) for r in c.rows["resources"]}
    alloc: dict[tuple, F] = {}
    inis: dict[tuple, set] = {}
    for a in c.rows["resource_allocations"]:
        k = (a["resource_id"], a["period_index"])
        alloc[k] = alloc.get(k, F(0)) + dec(a["amount"])
        inis.setdefault(k, set()).add(a["initiative_id"])
    r03rows = [{"resource_id": "res-03", "capacity": r2(cap["res-03"]), "period_index": p, "allocated": r2(v), "headroom": r2(cap["res-03"] - v), "initiatives": ",".join(sorted(inis[(rid, p)]))}
               for (rid, p), v in sorted(alloc.items()) if rid == "res-03" and v >= cap[rid]]
    res = []
    for r in sorted(c.rows["resources"], key=lambda r: r["resource_id"]):
        rid = r["resource_id"]
        ps = {p: v for (x, p), v in alloc.items() if x == rid}
        at = [p for p, v in ps.items() if v == cap[rid]]
        res.append({"resource_id": rid, "name": r["name"], "capacity": r2(cap[rid]), "unit": r["unit"], "allocation_rows": sum(1 for a in c.rows["resource_allocations"] if a["resource_id"] == rid),
                    "periods_exactly_at_capacity": len(at), "periods_over_capacity": sum(1 for v in ps.values() if v > cap[rid]), "first_period_at_capacity": min(at) if at else None,
                    "last_period_at_capacity": max(at) if at else None})
    ev9 = next(e for e in json.loads((DATA / "injection-manifest.json").read_text())["events"] if e["event_id"] == "EV-09")
    reqs = sorted(((s["row"]["resource_id"], s["row"]["initiative_id"], s["row"]["period_index"], dec(s["row"]["amount"])) for s in ev9["steps"] if s.get("reason_code") == "RESOURCE_OVERALLOCATED"), key=lambda t: t[2])
    ref = [{"resource_id": rid, "initiative_id": iid, "period_index": p, "requested": r2(q), "allocated_before": r2(alloc.get((rid, p), F(0))), "capacity": r2(cap[rid]),
            "would_be": r2(alloc.get((rid, p), F(0)) + q), "refused_overallocated": alloc.get((rid, p), F(0)) + q > cap[rid]} for rid, iid, p, q in reqs]
    return {"09_roadmap_capacity__dependency_delay": dd, "09_roadmap_capacity__delay_summary": [summ], "09_roadmap_capacity__deployment_before_feasible_start": dbfs,
            "09_roadmap_capacity__cycle_check": [cyc_row], "09_roadmap_capacity__refused_cycle": refused, "09_roadmap_capacity__resource_at_capacity": r03rows,
            "09_roadmap_capacity__resources": res, "09_roadmap_capacity__refused_requests": ref}


def ancestors(c: Ctx) -> dict[str, set]:
    deps = c.rows["dependencies"]
    memo: dict[str, set] = {}

    def anc(i: str) -> set:
        if i not in memo:
            s: set = set()
            for d in deps:
                if d["initiative_id"] == i:
                    s |= {d["prerequisite_id"]} | anc(d["prerequisite_id"])
            memo[i] = s
        return memo[i]
    return {i: anc(i) for i in c.ini}


def r11(c: Ctx) -> dict:
    fl = c.flow("scn-025")
    fs = feasible_starts(c)
    ad = visible_adoption(c)
    real = realisation(c, "scn-025")
    risk: dict[str, F] = {}
    for r in c.rows["risk_items"]:
        risk[r["initiative_id"]] = risk.get(r["initiative_id"], F(0)) + dec(r["probability"]) * dec(r["impact"])
    carries = {}
    for iid, i in fl["init"].items():
        carries[iid] = i["has_rows"] and i["npv"] > 0 and i["simple"]["t"] is not None and i["disc"]["t"] is not None
    screen, waiting = [], []
    for iid in sorted(fl["init"]):
        i = fl["init"][iid]
        ben, cost = sum(i["ben"], F(0)), sum(i["costs"], F(0))
        hrs = sum((b["ramped"] for b in fl["ben"] if b["iid"] == iid and b["class"] == "capacity_hours"), F(0))
        bes = sum((b["money"] for b in fl["ben"] if b["iid"] == iid and b["class"] == "avoided_cost_beside"), F(0))
        a = ad.get(iid)
        rc = real.get((iid, "cash"))
        wend = min(fl["h"], c.matured)
        rows = fl["costs"][iid]
        approved = c.ini[iid].get("baseline_version")
        planned = sum((x["amount"] for x in rows if x["basis"] == "planned" and x["baseline_version"] == approved and x["t"] < wend), F(0)) if approved else F(0)
        act = [x for x in rows if x["basis"] == "actual" and x["t"] < wend]
        screen.append({"initiative_id": iid, "npv": r2(i["npv"]), "simple_payback_period": i["simple"]["t"], "discounted_payback_period": i["disc"]["t"], "cash_benefit_to_cost": rnd(ben / cost, 6),
                       "capacity_hours_not_converted": r2(hrs), "avoided_cost_beside": r2(bes),
                       "adoption_rate": rnd(F(a["adopted_count"], a["eligible_count"]), 6) if a and a["eligible_count"] > 0 else None,
                       "cash_realisation": rnd(rc["observed"] / rc["planned"], 6) if rc and rc["compared"] > 0 and rc["planned"] != 0 else None,
                       "cost_variance": r2(sum((x["amount"] for x in act), F(0)) - planned) if approved is not None and act else None,
                       "risk_exposure": r2(risk.get(iid)) if iid in risk else None, "dependency_delay": fs[iid]["delay"], "screen": "CARRIES" if carries[iid] else "WAITS"})
        if not carries[iid]:
            waiting.append({"initiative_id": iid, "npv": r2(i["npv"]), "cash_benefit_to_cost": rnd(ben / cost, 6), "planned_costs": r2(cost), "capacity_hours_not_converted": r2(hrs),
                            "avoided_cost_beside": r2(bes), "reason": "NO_BENEFIT_ENTERS_THE_CASH_FLOW" if ben == 0 else "BENEFITS_ENTER_BUT_STAY_BELOW_COST"})
    anc = ancestors(c)
    ids = sorted(fl["init"])
    carry = [i for i in ids if carries[i]]
    members = {"A": ids, "B": carry, "C": sorted(set(carry) | {a for i in carry for a in anc[i]}), "D": [i for i in carry if all(carries.get(a, False) for a in anc[i])]}
    labels = {"A": ("all 24 initiatives of scn-025", "stored scenario"), "B": ("the initiatives that carry a cash case", "constructed"),
              "C": ("the carrying initiatives and the prerequisites they depend on", "constructed"), "D": ("the carrying initiatives that need no waiting prerequisite", "constructed")}
    opts = []
    deps = c.rows["dependencies"]
    groups = fl["claim_groups"]
    for o in "ABCD":
        m = set(members[o])
        sumn = sum((fl["init"][i]["npv"] for i in m), F(0))
        pv = sum((b["money"] / fl["q"] ** b["t"] for g in groups.values() for b in g[1:] if b["enters"] and b["iid"] in m), F(0))
        outside = sum(1 for d in deps if d["initiative_id"] in m and d["prerequisite_id"] not in m)
        crossing = sum(1 for g in groups.values() if 1 <= sum(1 for b in g if b["iid"] in m) <= len(g) - 1)
        opts.append({"option_id": o, "label": labels[o][0], "kind": labels[o][1], "initiatives": len(m), "planned_costs": r2(sum((sum(fl["init"][i]["costs"], F(0)) for i in m), F(0))),
                     "sum_of_initiatives": r2(sumn), "double_counted_pv": r2(pv), "attributable_npv": r2(sumn - pv), "prerequisites_outside_the_option": outside,
                     "shared_claims_crossing_the_boundary": crossing, "initiatives_with_a_negative_npv": sum(1 for i in m if fl["init"][i]["npv"] < 0),
                     "members": ",".join(sorted(m)) if o != "A" else None})
    ties = []
    for d in sorted(deps, key=lambda d: d["dependency_id"]):
        if carries[d["initiative_id"]] and not carries[d["prerequisite_id"]]:
            ties.append({"dependency_id": d["dependency_id"], "initiative_id": d["initiative_id"], "prerequisite_id": d["prerequisite_id"], "dependency_type": d["dependency_type"],
                         "lag_periods": d["lag_periods"], "initiative_npv": r2(fl["init"][d["initiative_id"]]["npv"]), "prerequisite_npv": r2(fl["init"][d["prerequisite_id"]]["npv"])})
    return {"11_proposal_screen__initiative_screen": screen, "11_proposal_screen__waiting": waiting, "11_proposal_screen__options": opts, "11_proposal_screen__dependency_ties": ties}


def r10(g: Ctx) -> dict:
    fl = g.flow("scn-001")
    i1 = fl["init"]["init-001"]
    q = fl["q"]
    cf = [{"period_index": t, "costs": r2(i1["costs"][t]), "cash_benefits": r2(i1["ben"][t]), "net_cash_flow": r2(i1["net"][t]), "cumulative": r2(i1["cum"][t]), "discount_factor": rnd(1 / q ** t, 6),
           "discounted_cash_flow": r2(i1["net"][t] / q ** t), "cumulative_discounted": r2(i1["cumd"][t])} for t in range(fl["h"])]

    def answer(iid: str) -> dict:
        i = fl["init"][iid]
        return {"initiative_id": iid, "npv": r2(i["npv"]), "npv_exact": exact_text(i["npv"]), "simple_payback_period": i["simple"]["t"], "simple_payback_interpolated": rnd(i["simple"]["i"], 4),
                "discounted_payback_period": i["disc"]["t"], "discounted_payback_interpolated": rnd(i["disc"]["i"], 4),
                "capacity_hours_excluded": r2(sum((b["ramped"] for b in fl["ben"] if b["iid"] == iid and b["class"] == "capacity_hours"), F(0)))}
    a1 = answer("init-001")
    inis = []
    for iid in sorted(fl["init"]):
        i = fl["init"][iid]
        inis.append({"initiative_id": iid, "npv": r2(i["npv"]), "npv_exact": exact_text(i["npv"]), "simple_payback_period": i["simple"]["t"], "simple_payback_interpolated": rnd(i["simple"]["i"], 4),
                     "simple_reason": i["simple"]["reason"], "discounted_payback_period": i["disc"]["t"], "discounted_payback_interpolated": rnd(i["disc"]["i"], 4), "discounted_reason": i["disc"]["reason"]})
    port = {"scenario_id": "scn-001", "sum_of_initiatives": r2(fl["sum_npv"]), "double_counted_pv": r2(fl["pv"]), "attributable_npv": r2(fl["attributable"]), "attributable_exact": exact_text(fl["attributable"]),
            "planned_benefits": r2(fl["planned"]), "residual": r2(fl["removed"]), "attributable_benefits": r2(fl["planned"] - fl["removed"]), "planned_hours": r2(fl["hours_planned"]),
            "hours_residual": r2(fl["hours_removed"])}
    return {"10_golden_known_answer__cash_flow_init001": cf, "10_golden_known_answer__init001_answer": [a1], "10_golden_known_answer__initiatives": inis, "10_golden_known_answer__portfolio": [port]}


def results() -> dict[str, list[dict]]:
    """The snapshot result sets (investigations 01..09 and 11) from the raw published JSON."""
    c = load_snapshot()
    out: dict[str, list[dict]] = {}
    for fn in (r01, r02, r03, r04, r05, r06, r07, r08, r09, r11):
        out.update(fn(c))
    return out


def golden_results() -> dict[str, list[dict]]:
    return r10(load_golden())


class Context(Ctx):      # alias kept for readers: the test file imports ``Ctx``
    pass
