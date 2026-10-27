"""The independent Python side of the analysis (P07-ART-04): every result set of investigations 01..08 and 10 recomputed from the RAW published JSON.

Standard library only (``json``, ``re``, ``zoneinfo``, ``fractions``, ``decimal``): no SQL, no psycopg, no ``trustledger`` domain code, no reference SQL. It reads
``web/public/data/*.json`` (the wrapped entity files and the manifest's configuration) and returns, for each result set that ``run_all.py`` also runs in SQL, the same rows
(``<file>__<block>`` keys, same columns, same order) so that the two sides are compared cell by cell. Ratios are ``Fraction``s rounded once, half away from zero, to the
places the SQL rounds to. Rules are measured the way D-01..D-10 say (see 00_measure_rules.sql); this file is a second, separately written statement of them.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction as F
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "web" / "public" / "data"
DIMS = ("completeness", "validity", "uniqueness", "relationship", "timeliness")
SEV_RANK = {"critical": 1, "high": 2, "medium": 3, "low": 4}
UTC = timezone.utc


def ts(s: str | None) -> datetime | None:
    return None if s is None else datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def iso(t: datetime | None) -> str | None:
    return None if t is None else t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def rnd(x: F | None, places: int) -> Decimal | None:
    """Round half away from zero (what PostgreSQL's round(numeric) does) and keep the trailing zeros."""
    return None if x is None else _round_fraction(x, places)


def _round_fraction(x: F, places: int) -> Decimal:
    scale = 10 ** places
    scaled = x * scale
    n = scaled.numerator * 2 + scaled.denominator * (1 if scaled >= 0 else -1)
    q = n // (2 * scaled.denominator) if scaled >= 0 else -((-n) // (2 * scaled.denominator))
    return Decimal(q).scaleb(-places).quantize(Decimal(1).scaleb(-places))


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


def wrapped(name: str) -> list[dict]:
    return json.loads((DATA / f"{name}.json").read_text())["rows"]


class Ctx:
    def __init__(self) -> None:
        self.manifest = json.loads((DATA / "manifest.json").read_text())
        cfg = self.manifest["config"]
        self.as_of = ts(cfg["as_of"])
        self.chars = cfg["whitespace_policy"]["trim_characters"]
        self.owners = {o["owner_id"]: o for o in wrapped("owners")}
        self.datasets = {d["dataset_id"]: d for d in wrapped("datasets") if ts(d["registered_at"]) <= self.as_of}
        rows: dict[str, list[dict]] = {}
        for r in wrapped("dataset_rows"):
            rows.setdefault(r["dataset_id"], []).append(r)
        self.rows = rows
        self.rules = {r["rule_id"]: r for r in wrapped("quality_rules")}
        self.runs = {r["rule_run_id"]: r for r in wrapped("rule_runs")}
        self.issues = wrapped("issues")
        self.edges = [e for e in wrapped("lineage_edges") if e["observed_at"] is None or ts(e["observed_at"]) <= self.as_of]
        self.metrics = wrapped("metric_versions")
        self.changes = wrapped("definition_changes")
        self.candidates = {c["candidate_id"]: c for c in wrapped("match_candidates")}
        self.decisions = wrapped("merge_decisions")
        self.weights = {w["weight_version"]: w for w in sorted(wrapped("weight_versions"), key=lambda w: w["valid_from"])}
        self.rule_versions = wrapped("quality_rule_versions")
        self.truth = self.manifest["synthetic_truth"]["true_entity"]
        self.ms = self.measure_all()
        self.tstates = {p: self.timeliness(at) for p, at in self.probes().items()}
        self.issue_rows = self.classify_issues()

    # ---- cells -------------------------------------------------------------------------------------------------------------------------------------
    @staticmethod
    def text(v) -> str | None:
        if v is None:
            return None
        if isinstance(v, bool):
            return "true" if v else "false"
        return str(v)

    def missing(self, v) -> bool:
        t = self.text(v)
        return t is None or t.strip(self.chars) == ""

    def eligible_rows(self, rule: dict) -> list[dict]:
        rows = self.rows.get(rule["dataset_id"], [])
        flt = rule["definition"].get("filter")
        if not flt:
            return rows
        return [r for r in rows if self.text(r.get(flt["field"])) == flt["equals"]]

    # ---- rule measurement ----------------------------------------------------------------------------------------------------------------------------------
    def active_rules(self) -> list[dict]:
        out = []
        for r in self.rules.values():
            if r["dataset_id"] not in self.datasets:
                continue
            if not (r["status"] == "active" or ts(r["disabled_at"]) > self.as_of):
                continue
            if r["rule_type"] == "validity" and not r["definition"].get("pattern"):
                continue
            out.append(r)
        return sorted(out, key=lambda r: r["rule_id"])

    def measure_all(self) -> dict[str, dict]:
        t0 = self.timeliness(self.as_of)
        out: dict[str, dict] = {}
        for r in self.active_rules():
            d, typ = r["definition"], r["rule_type"]
            m = {"rule_id": r["rule_id"], "dataset_id": r["dataset_id"], "dimension": typ, "severity": r["severity"], "populated": None}
            if typ == "timeliness":
                st = t0.get(r["dataset_id"])
                m.update(eligible=0 if st is None or st["state"] == "pending" else 1, failing=1 if st and st["state"] == "late" else 0,
                         score=None if st is None or st["state"] == "pending" else (F(1) if st["state"] == "on_time" else F(0)))
            else:
                rows = self.eligible_rows(r)
                vals = [row.get(d["field"]) for row in rows]
                miss = [self.missing(v) for v in vals]
                if typ == "completeness":
                    el, mi = len(rows), sum(miss)
                    m.update(eligible=el, populated=el - mi, failing=mi, score=F(el - mi, el) if el else None)
                elif typ == "validity":
                    pat = d["pattern"]
                    py = (pat[:-1] + r"\Z") if pat.endswith("$") and not pat.endswith("\\$") else pat
                    rx = re.compile(py)
                    el = len(rows)
                    pop = sum(1 for x in miss if not x)
                    ok = sum(1 for v, x in zip(vals, miss) if not x and isinstance(v, str) and rx.search(v))
                    m.update(eligible=el, populated=pop, failing=el - ok, score=F(ok, pop) if pop else None)
                elif typ == "uniqueness":
                    el, nulls = len(rows), sum(miss)
                    seen: dict[str, int] = {}
                    for v, x in zip(vals, miss):
                        if not x:
                            seen[self.text(v)] = seen.get(self.text(v), 0) + 1
                    dups = sum(n - 1 for n in seen.values() if n > 1)
                    m.update(eligible=el, failing=nulls + dups, score=F(el - nulls - dups, el) if el else None, _groups=sum(1 for n in seen.values() if n > 1), _keys=len(seen))
                else:   # relationship
                    parent = {self.text(p.get(d["parent_field"])) for p in self.rows.get(d["parent_dataset_id"], []) if not self.missing(p.get(d["parent_field"]))}
                    tot, nulls = len(rows), sum(miss)
                    matched = sum(1 for v, x in zip(vals, miss) if not x and self.text(v) in parent)
                    el = tot - nulls
                    m.update(eligible=el, failing=el - matched, score=F(matched, el) if el else None)
            out[r["rule_id"]] = m
        return out

    def dim_scores(self) -> dict[str, dict[str, tuple[int, F]]]:
        acc: dict[tuple[str, str], list[F]] = {}
        for m in self.ms.values():
            if m["score"] is not None:
                acc.setdefault((m["dataset_id"], m["dimension"]), []).append(m["score"])
        out: dict[str, dict[str, tuple[int, F]]] = {}
        for (ds, dim), xs in acc.items():
            out.setdefault(ds, {})[dim] = (len(xs), sum(xs, F(0)) / len(xs))
        return out

    def weighted(self, ds: str, wv: str) -> tuple[list[str], F, F] | None:
        dims = self.dim_scores().get(ds)
        if not dims:
            return None
        w = {k: F(v) for k, v in self.weights[wv]["weights"].items()}
        order = [d for d in DIMS if d in dims]
        wsum = sum((w[d] for d in order), F(0))
        return order, wsum, sum((w[d] * dims[d][1] for d in order), F(0)) / wsum

    # ---- timeliness ----------------------------------------------------------------------------------------------------------------------------------------
    def probes(self) -> dict[int, datetime]:
        a = self.as_of
        return {0: a, 1: a + timedelta(hours=10, minutes=30), 2: a + timedelta(hours=13), 3: a + timedelta(hours=25)}

    def timeliness(self, at: datetime) -> dict[str, dict]:
        out = {}
        for ds in self.datasets.values():
            if not ds["monitored"]:
                continue
            zone = ZoneInfo(ds["refresh_timezone"])
            hh, mm = (int(x) for x in ds["refresh_local_time"].split(":"))
            local_today = at.astimezone(zone).date()
            best = None
            for back in range(0, 7):
                day = local_today - timedelta(days=back)
                s = datetime(day.year, day.month, day.day, hh, mm, tzinfo=zone, fold=1).astimezone(UTC)     # a repeated local time is the later instant
                if s <= at and (best is None or s > best):
                    best = s
            dl = best + timedelta(minutes=ds["refresh_grace_minutes"])
            lr = ts(ds["last_refreshed_at"])
            lr = lr if lr is not None and lr <= at else None
            state = "on_time" if lr is not None and best <= lr < dl else ("pending" if dl > at else "late")
            out[ds["dataset_id"]] = {"dataset_id": ds["dataset_id"], "tz": ds["refresh_timezone"], "local_time": ds["refresh_local_time"], "grace": ds["refresh_grace_minutes"],
                                     "occurrence": best, "deadline": dl, "last_refresh": lr, "state": state}
        return out

    # ---- issues --------------------------------------------------------------------------------------------------------------------------------------------
    def classify_issues(self) -> list[dict]:
        out = []
        for i in self.issues:
            det = ts(i["detected_at"])
            base = self.runs[i["rule_run_id"]]
            rule = self.rules[base["rule_id"]]
            if det > self.as_of or ts(base["run_at"]) > self.as_of or rule["dataset_id"] not in self.datasets:
                continue
            reopen = [ts(t) for t in i["reopened_at"] if ts(t) <= self.as_of]
            closed = i["status"] == "closed" and ts(i["closed_at"]) <= self.as_of
            v = self.runs.get(i["verification_run_id"]) if i["verification_run_id"] else None
            verified = bool(v and ts(v["run_at"]) <= self.as_of and v["kind"] == "rerun" and v["rerun_for_issue"] == i["issue_id"] and v["rule_id"] == base["rule_id"]
                            and v["rule_version"] == base["rule_version"] and v["failure_count"] == 0 and ts(v["run_at"]) >= det and (not reopen or ts(v["run_at"]) >= max(reopen)))
            cls = "resolved" if closed and verified else ("claimed" if closed else "open")
            end = ts(v["run_at"]) if cls == "resolved" else (ts(i["closed_at"]) if cls == "claimed" else self.as_of)
            out.append({"issue_id": i["issue_id"], "dataset_id": rule["dataset_id"], "rule_id": rule["rule_id"], "severity": rule["severity"], "status": i["status"], "owner_id": i["owner_id"],
                        "dataset_owner_id": self.datasets[rule["dataset_id"]]["owner_id"], "detected_at": det, "class": cls, "cycles": len(reopen),
                        "hours": F(int((end - det).total_seconds()), 3600), "verification_run_id": i["verification_run_id"]})
        return out

    def accountable(self, owner_id: str) -> bool:
        o = self.owners[owner_id]
        return self.as_of < ts(o["deactivated_at"]) if o["deactivated_at"] else bool(o["active"])


def avg(xs: list[F]) -> F | None:
    return sum(xs, F(0)) / len(xs) if xs else None


def share(n: int, d: int, places: int = 6) -> Decimal | None:
    return _round_fraction(F(n, d), places) if d else None


# ================================================================================================ result sets
def results() -> dict[str, list[dict]]:
    c = Ctx()
    R: dict[str, list[dict]] = {}
    ms, ds_scores = c.ms, c.dim_scores()

    # ---- 01 ds-customers ------------------------------------------------------------------------------------------------------------------------------
    cust = sorted((m for m in ms.values() if m["dataset_id"] == "ds-customers"), key=lambda m: m["rule_id"])
    R["01_ds_customers_override_both_weights__rules"] = [{"rule_id": m["rule_id"], "dimension": m["dimension"], "severity": m["severity"], "eligible": m["eligible"], "populated": m["populated"],
                                                          "failing": m["failing"], "score": rnd(m["score"], 6)} for m in cust]
    R["01_ds_customers_override_both_weights__dimensions"] = [{"dimension": d, "rules": ds_scores["ds-customers"][d][0], "score": rnd(ds_scores["ds-customers"][d][1], 6)} for d in DIMS if d in ds_scores["ds-customers"]]
    wrows = []
    for wv, w in c.weights.items():
        order, wsum, score = c.weighted("ds-customers", wv)
        wrows.append({"weight_version": wv, "valid_from": date.fromisoformat(w["valid_from"][:10]), "measured_dimensions": ",".join(order), "weight_sum": rnd(wsum, 6),
                      "weighted_score": rnd(score, 6), "above_0_95": score > F(95, 100)})
    R["01_ds_customers_override_both_weights__weighted"] = wrows
    crit_f = sum(m["failing"] for m in cust if m["severity"] == "critical")
    crit_i = [i for i in c.issue_rows if i["dataset_id"] == "ds-customers" and i["severity"] == "critical" and i["class"] != "resolved"]
    R["01_ds_customers_override_both_weights__critical"] = [{"dataset_id": "ds-customers", "critical_failures": crit_f, "critical_open_issues": len(crit_i), "critical_override": crit_f > 0 or bool(crit_i)}]
    R["01_ds_customers_override_both_weights__critical_issue"] = [{"issue_id": i["issue_id"], "rule_id": i["rule_id"], "severity": i["severity"], "status": i["status"], "class": i["class"],
                                                                   "detected_at": iso(i["detected_at"]), "owner_id": i["owner_id"], "age_hours": rnd(i["hours"], 4)}
                                                                  for i in sorted(c.issue_rows, key=lambda i: i["issue_id"]) if i["dataset_id"] == "ds-customers" and i["severity"] == "critical"]
    over = {m["dataset_id"] for m in ms.values() if m["severity"] == "critical"
            and sum(x["failing"] for x in ms.values() if x["dataset_id"] == m["dataset_id"] and x["severity"] == "critical") > 0}
    over |= {i["dataset_id"] for i in c.issue_rows if i["severity"] == "critical" and i["class"] != "resolved"}
    R["01_ds_customers_override_both_weights__portfolio_override"] = [{"datasets_overridden": len(over)}]

    # ---- 02 ownership --------------------------------------------------------------------------------------------------------------------------------
    cov = {d: c.accountable(x["owner_id"]) for d, x in c.datasets.items()}
    R["02_ownership_coverage__summary"] = [{"datasets": len(cov), "covered": sum(cov.values()), "uncovered": len(cov) - sum(cov.values()), "coverage": share(sum(cov.values()), len(cov))}]
    unresolved = [i for i in c.issue_rows if i["class"] != "resolved"]
    R["02_ownership_coverage__uncovered"] = [{
        "dataset_id": d, "dataset_name": c.datasets[d]["dataset_name"], "classification": c.datasets[d]["classification"], "monitored": bool(c.datasets[d]["monitored"]),
        "owner_id": c.datasets[d]["owner_id"], "owner_team": c.owners[c.datasets[d]["owner_id"]]["team"], "owner_deactivated_at": c.owners[c.datasets[d]["owner_id"]]["deactivated_at"],
        "unresolved_issues": sum(1 for i in unresolved if i["dataset_id"] == d), "active_rules": sum(1 for m in ms.values() if m["dataset_id"] == d)}
        for d in sorted(cov) if not cov[d]]
    teams: dict[str, list[bool]] = {}
    for d, x in c.datasets.items():
        o = c.owners[x["owner_id"]]
        teams.setdefault(o["team"], []).append(bool(o["active"]))
    R["02_ownership_coverage__by_team"] = [{"team": t, "datasets": len(v), "covered": sum(v), "uncovered": len(v) - sum(v), "coverage": share(sum(v), len(v))} for t, v in sorted(teams.items())]
    R["02_ownership_coverage__inactive_owners"] = [{"owner_id": o["owner_id"], "owner_name": o["owner_name"], "team": o["team"], "deactivated_at": o["deactivated_at"],
                                                   "datasets_owned": sum(1 for x in c.datasets.values() if x["owner_id"] == o["owner_id"]),
                                                   "unresolved_issues_assigned": sum(1 for i in unresolved if i["owner_id"] == o["owner_id"])}
                                                  for o in sorted(c.owners.values(), key=lambda o: o["owner_id"]) if not o["active"]]

    # ---- 03 weight shift -----------------------------------------------------------------------------------------------------------------------------
    R["03_weight_shift_dr03__weights"] = [{"weight_version": wv, "valid_from": date.fromisoformat(w["valid_from"][:10]), **{k: w["weights"][k] for k in DIMS}} for wv, w in c.weights.items()]
    sc = {}
    for d in sorted(ds_scores):
        sc[d] = (c.weighted(d, "w1")[2], c.weighted(d, "w2")[2])
    R["03_weight_shift_dr03__shift_by_dataset"] = [{"dataset_id": d, "score_w1": rnd(a, 6), "score_w2": rnd(b, 6), "shift": rnd(b - a, 6), "differs": a != b, "moved_at_least_0_005": abs(b - a) >= F(5, 1000)}
                                                  for d, (a, b) in sc.items()]
    big = sorted(sc.items(), key=lambda kv: (-abs(kv[1][1] - kv[1][0]), kv[0]))[0]
    R["03_weight_shift_dr03__summary"] = [{"datasets_scored": len(sc), "datasets_with_different_score": sum(1 for a, b in sc.values() if a != b),
                                           "datasets_moved_at_least_0_005": sum(1 for a, b in sc.values() if abs(b - a) >= F(5, 1000)),
                                           "mean_score_w1": rnd(avg([a for a, _ in sc.values()]), 6), "mean_score_w2": rnd(avg([b for _, b in sc.values()]), 6),
                                           "largest_move": rnd(big[1][1] - big[1][0], 6), "largest_move_dataset": big[0]}]
    byw: dict[str, list[datetime]] = {}
    for r in c.runs.values():
        byw.setdefault(r["weight_version"], []).append(ts(r["run_at"]))
    R["03_weight_shift_dr03__runs_by_weight_version"] = [{"weight_version": wv, "runs": len(v), "first_run": iso(min(v)), "last_run": iso(max(v))} for wv, v in sorted(byw.items())]
    wchg = ts(list(c.weights.values())[-1]["valid_from"])
    later = [v for v in c.rule_versions if v["version_number"] > 1 and v["valid_from"]]
    days = [abs(F(int((ts(v["valid_from"]) - wchg).total_seconds()), 86400)) for v in later]
    disabled = [r for r in c.rules.values() if r["disabled_at"] and abs(F(int((ts(r["disabled_at"]) - wchg).total_seconds()), 86400)) <= 14]
    nearest = min(days)
    R["03_weight_shift_dr03__rule_changes_near_the_weight_change"] = [{"rule_versions_after_the_first": len(later), "within_14_days_of_the_weight_change": sum(1 for d in days if d <= 14),
                                                                      "nearest_days": int(_round_fraction(nearest, 0)), "rules_disabled_within_14_days": len(disabled)}]

    r1 = {d: i + 1 for i, (d, _) in enumerate(sorted(sc.items(), key=lambda kv: (kv[1][0], kv[0])))}
    r2 = {d: i + 1 for i, (d, _) in enumerate(sorted(sc.items(), key=lambda kv: (kv[1][1], kv[0])))}
    R["03_weight_shift_dr03__lowest_scores"] = [{"dataset_id": d, "score_w1": rnd(sc[d][0], 6), "rank_w1": r1[d], "score_w2": rnd(sc[d][1], 6), "rank_w2": r2[d]} for d in sorted(sc, key=lambda d: r2[d])[:8]]

    # ---- 04 issues -----------------------------------------------------------------------------------------------------------------------------------
    ir = c.issue_rows
    n = len(ir)
    R["04_issue_classes_and_resolution__classes"] = [{"class": k, "issues": sum(1 for i in ir if i["class"] == k), "share_of_issues": share(sum(1 for i in ir if i["class"] == k), n),
                                                     "reopened": sum(1 for i in ir if i["class"] == k and i["cycles"] > 0)} for k in ("resolved", "claimed", "open")]
    R["04_issue_classes_and_resolution__class_by_severity"] = [{"severity": s, "resolved": sum(1 for i in ir if i["severity"] == s and i["class"] == "resolved"),
                                                               "claimed": sum(1 for i in ir if i["severity"] == s and i["class"] == "claimed"), "open": sum(1 for i in ir if i["severity"] == s and i["class"] == "open"),
                                                               "issues": sum(1 for i in ir if i["severity"] == s), "unresolved": sum(1 for i in ir if i["severity"] == s and i["class"] != "resolved")}
                                                              for s in ("critical", "high", "medium", "low") if any(i["severity"] == s for i in ir)]
    reruns_for: dict[str, list[dict]] = {}
    for r in c.runs.values():
        if r["kind"] == "rerun" and r["rerun_for_issue"]:
            reruns_for.setdefault(r["rerun_for_issue"], []).append(r)
    claimed = [i for i in ir if i["class"] == "claimed"]
    unres = sorted((i for i in ir if i["class"] != "resolved"), key=lambda i: (i["detected_at"], i["issue_id"]))
    R["04_issue_classes_and_resolution__claimed_split"] = [{
        "claimed": len(claimed), "claimed_with_a_failed_rerun": sum(1 for i in claimed if any(r["failure_count"] > 0 for r in reruns_for.get(i["issue_id"], []))),
        "claimed_without_a_rerun": sum(1 for i in claimed if not reruns_for.get(i["issue_id"])), "unresolved": len(unres), "oldest_unresolved_detected_at": iso(unres[0]["detected_at"]),
        "oldest_unresolved_issue": unres[0]["issue_id"], "claimed_among_the_oldest_25_unresolved": sum(1 for i in unres[:25] if i["class"] == "claimed"),
        "leading_claimed_run": next(k for k, i in enumerate(unres) if i["class"] != "claimed"), "first_not_claimed": next(i["issue_id"] for i in unres if i["class"] != "claimed")}]
    res = [i for i in ir if i["class"] == "resolved"]
    tm: dict[str, list[F]] = {}
    for i in res:
        tm.setdefault(c.owners[i["owner_id"]]["team"], []).append(i["hours"])
    R["04_issue_classes_and_resolution__resolution_by_team"] = [{"team": t, "resolved": len(v), "mean_hours": rnd(avg(v), 4)} for t, v in sorted(tm.items())]
    fast = [i["hours"] for i in res if c.owners[i["owner_id"]]["team"] == "Data Platform"]
    other = [i["hours"] for i in res if c.owners[i["owner_id"]]["team"] != "Data Platform"]
    R["04_issue_classes_and_resolution__fast_team_vs_others"] = sorted(
        [{"group_name": "Data Platform", "resolved": len(fast), "mean_hours": rnd(avg(fast), 4)}, {"group_name": "all other teams", "resolved": len(other), "mean_hours": rnd(avg(other), 4)}], key=lambda r: r["group_name"])
    R["04_issue_classes_and_resolution__resolution_overall"] = [{"resolved": len(res), "mean_hours": rnd(avg([i["hours"] for i in res]), 4), "fast_team_ratio": rnd(avg(fast) / avg(other), 6),
                                                                "open_count": sum(1 for i in ir if i["class"] == "open"), "reopened_issues": sum(1 for i in ir if i["cycles"] > 0), "reopen_cycles": sum(i["cycles"] for i in ir)}]

    runs_of: dict[str, int] = {}
    for rr in c.runs.values():
        runs_of[rr["rule_id"]] = runs_of.get(rr["rule_id"], 0) + 1
    R["04_issue_classes_and_resolution__disabled_rules"] = [
        {"rule_id": rid, "dataset_id": x["dataset_id"], "disabled_at": x["disabled_at"], "disabled_reason": x["disabled_reason"], "runs_retained": runs_of.get(rid, 0),
         "issues_retained": sum(1 for i in ir if i["rule_id"] == rid), "issues_still_unresolved": sum(1 for i in ir if i["rule_id"] == rid and i["class"] != "resolved")}
        for rid, x in sorted(c.rules.items()) if x["status"] == "disabled"]

    # ---- 05 lineage ----------------------------------------------------------------------------------------------------------------------------------
    kinds = ("declared", "observed", "inferred")
    R["05_lineage_coverage_evidence__evidence_kinds"] = [{"evidence_type": k, "edge_rows": sum(1 for e in c.edges if e["evidence_type"] == k),
                                                         "distinct_pairs": len({(e["source_dataset_id"], e["target_dataset_id"]) for e in c.edges if e["evidence_type"] == k}),
                                                         "rows_with_observed_at": sum(1 for e in c.edges if e["evidence_type"] == k and e["observed_at"])} for k in kinds]
    pairs = {k: {(e["source_dataset_id"], e["target_dataset_id"]) for e in c.edges if e["evidence_type"] == k} for k in kinds}
    dec, obs, inf = pairs["declared"], pairs["observed"], pairs["inferred"]
    R["05_lineage_coverage_evidence__coverage"] = [{"declared_pairs": len(dec), "observed_pairs": len(obs), "observed_matching_declared": len(dec & obs), "coverage": share(len(dec & obs), len(dec)),
                                                   "undeclared_observed": len(obs - dec), "declared_not_observed": len(dec - obs), "inferred_pairs": len(inf),
                                                   "inferred_on_declared_unobserved": len((inf & dec) - obs), "inferred_also_observed": len(inf & obs)}]
    R["05_lineage_coverage_evidence__undeclared_observed"] = [{"source_dataset_id": s, "target_dataset_id": t} for s, t in sorted(obs - dec)]
    R["05_lineage_coverage_evidence__declared_not_observed"] = [{"source_dataset_id": s, "target_dataset_id": t, "an_inferred_edge_covers_it": (s, t) in inf} for s, t in sorted(dec - obs)]
    R["05_lineage_coverage_evidence__inferred"] = [{"source_dataset_id": s, "target_dataset_id": t, "declared": (s, t) in dec, "observed": (s, t) in obs} for s, t in sorted(inf)]

    # ---- 06 definitions ------------------------------------------------------------------------------------------------------------------------------
    def missing_items(m: dict) -> list[str]:
        out = []
        for k in ("definition", "grain"):
            if m[k] is None or m[k].strip(c.chars) == "":
                out.append(k)
        sf = m["source_fields"]
        if not isinstance(sf, list) or not sf or any(str(x).strip(c.chars) == "" for x in sf):
            out.append("source_fields")
        if m["owner_id"] not in c.owners:
            out.append("owner")
        if m["refresh"] is None or m["refresh"].strip(c.chars) == "":
            out.append("refresh")
        return out
    vis = [m for m in c.metrics if ts(m["valid_from"]) <= c.as_of]
    eff: dict[str, dict] = {}
    for m in sorted(vis, key=lambda m: (m["metric_id"], ts(m["valid_from"]), m["version_number"])):
        if m["status"] == "published":
            eff[m["metric_id"]] = m
    comp = [m for m in eff.values() if not missing_items(m)]
    R["06_definition_coverage__summary"] = [{"checklist_version": c.manifest["config"]["checklist_version"], "published_metrics": len(eff), "complete_metrics": len(comp),
                                            "incomplete_metrics": len(eff) - len(comp), "coverage": share(len(comp), len(eff))}]
    byid = {(m["metric_id"], m["version_number"]): m for m in vis}
    inc = []
    for mid in sorted(eff):
        m = eff[mid]
        miss = missing_items(m)
        if miss:
            prev = byid.get((mid, m["version_number"] - 1))
            hist = "single version" if prev is None else (f"broken by version {m['version_number']}" if not missing_items(prev) else "previous version incomplete too")
            inc.append({"metric_id": mid, "metric_name": m["metric_name"], "version_number": m["version_number"], "missing_items": ",".join(miss), "owner_id": m["owner_id"] or "(none)", "history": hist})
    R["06_definition_coverage__incomplete"] = inc
    allm = c.metrics
    R["06_definition_coverage__versions"] = [{"metrics": len({m["metric_id"] for m in allm}), "versions": len(allm), "metrics_with_more_than_one_version": len({m["metric_id"] for m in allm if m["version_number"] >= 2}),
                                             "change_records": len(c.changes), "versions_without_change_record": sum(1 for m in allm if m["version_number"] >= 2 and not any(x["metric_version_id"] == m["metric_version_id"] for x in c.changes)),
                                             "published_versions": sum(1 for m in allm if m["status"] == "published"), "superseded_versions": sum(1 for m in allm if m["status"] == "superseded")}]
    mv = {m["metric_version_id"]: m for m in allm}
    R["06_definition_coverage__regressions"] = [{"change_id": ch["change_id"], "metric_id": mv[ch["metric_version_id"]]["metric_id"], "version_number": mv[ch["metric_version_id"]]["version_number"],
                                                 "missing_after": ",".join(missing_items(mv[ch["metric_version_id"]])), "approved_by": ch["approved_by"], "changed_at": ch["changed_at"]}
                                                for ch in sorted(c.changes, key=lambda x: x["change_id"])
                                                if not missing_items(mv[ch["previous_metric_version_id"]]) and missing_items(mv[ch["metric_version_id"]])]

    # ---- 07 matching ---------------------------------------------------------------------------------------------------------------------------------
    cand = c.candidates

    def same(cid: str) -> bool:
        k = cand[cid]
        return c.truth[k["left_record_id"]] == c.truth[k["right_record_id"]]
    rev = [d for d in c.decisions if d["decision"] in ("approve", "reject") and ts(d["decided_at"]) <= c.as_of]
    ap = [d for d in rev if d["decision"] == "approve"]
    apc = sum(1 for d in ap if same(d["candidate_id"]))
    truesame = sum(1 for d in rev if same(d["candidate_id"]))
    agree = sum(1 for d in rev if (d["decision"] == "approve") == same(d["candidate_id"]))
    R["07_match_precision__precision"] = [{"approved": len(ap), "approved_correct": apc, "precision": share(apc, len(ap)), "reviewed": len(rev), "rejected": len(rev) - len(ap),
                                          "reviewed_correct": truesame, "reviewed_correct_share": share(truesame, len(rev)), "decisions_agreeing_with_truth": agree,
                                          "decision_agreement_share": share(agree, len(rev))}]
    mat: dict[tuple[str, bool], int] = {}
    for d in rev:
        mat[(d["decision"], same(d["candidate_id"]))] = mat.get((d["decision"], same(d["candidate_id"])), 0) + 1
    R["07_match_precision__review_matrix"] = [{"decision": k[0], "truth": "same entity" if k[1] else "different entities", "decisions": v,
                                              "verdict": "agrees with the truth" if (k[0] == "approve") == k[1] else "disagrees"}
                                             for k, v in sorted(mat.items(), key=lambda kv: (kv[0][0], not kv[0][1]))]
    revs = [d for d in c.decisions if d["decision"] == "reverse"]
    R["07_match_precision__candidates"] = [{"candidates": len(cand), "canonical_distinct_pairs": len({(k["left_record_id"], k["right_record_id"]) for k in cand.values() if k["left_record_id"] < k["right_record_id"]}), "reviewed": len({d["candidate_id"] for d in c.decisions if d["decision"] in ("approve", "reject")}),
                                           "unreviewed": sum(1 for k in cand if not any(d["candidate_id"] == k for d in c.decisions)), "reversals": len(revs),
                                           "candidates_flagged_shared_name_and_address": sum(1 for k in cand.values() if k["uncertainty"]),
                                           "reviews_by_the_proposer": sum(1 for d in rev if d["reviewer_id"] == cand[d["candidate_id"]]["proposed_by"])}]
    by_merge = {d["merge_id"]: d for d in c.decisions}
    R["07_match_precision__wrong_approvals"] = [{"candidate_id": d["candidate_id"], "left_record_id": cand[d["candidate_id"]]["left_record_id"], "right_record_id": cand[d["candidate_id"]]["right_record_id"],
                                                 "score": cand[d["candidate_id"]]["score"], "flagged_possible_household": bool(cand[d["candidate_id"]]["uncertainty"]), "reviewer_id": d["reviewer_id"],
                                                 "reversed_afterwards": any(r["reverses_merge_id"] == d["merge_id"] for r in revs)}
                                                for d in sorted(ap, key=lambda d: d["candidate_id"]) if not same(d["candidate_id"])]
    R["07_match_precision__reversals"] = [{"reversals": len(revs), "approvals_reversed": len({r["reverses_merge_id"] for r in revs}),
                                          "reversals_of_wrong_approvals": sum(1 for r in revs if not same(by_merge[r["reverses_merge_id"]]["candidate_id"])),
                                          "reversals_without_a_reason": sum(1 for r in revs if not r["reason"] or not r["reason"].strip())}]

    # ---- 08 timeliness -------------------------------------------------------------------------------------------------------------------------------
    t0 = c.tstates[0]
    R["08_timeliness_states__at_the_as_of"] = [{"dataset_id": d, "timezone": s["tz"], "scheduled_local": s["local_time"], "grace_minutes": s["grace"], "evaluated_occurrence_utc": iso(s["occurrence"]),
                                                "deadline_utc": iso(s["deadline"]), "last_refreshed_at": iso(s["last_refresh"]), "state": s["state"], "owner_team": c.owners[c.datasets[d]["owner_id"]]["team"],
                                                "owner_active": bool(c.owners[c.datasets[d]["owner_id"]]["active"])} for d, s in sorted(t0.items())]

    def tsum(states: dict) -> dict:
        on = sum(1 for s in states.values() if s["state"] == "on_time")
        pe = sum(1 for s in states.values() if s["state"] == "pending")
        la = sum(1 for s in states.values() if s["state"] == "late")
        return {"monitored_datasets": len(states), "on_time": on, "pending": pe, "late": la, "evaluated": len(states) - pe, "timeliness": share(on, len(states) - pe)}
    R["08_timeliness_states__summary"] = [tsum(t0)]
    labels = {0: "as-of", 1: "as-of + 10h30m", 2: "as-of + 13h", 3: "as-of + 25h"}
    R["08_timeliness_states__by_read_instant"] = [{"read_no": k, "label": labels[k], "read_at": iso(c.probes()[k]), **tsum(c.tstates[k])} for k in range(4)]
    late = []
    for d, s in sorted(t0.items()):
        if s["state"] == "late":
            rl = sorted(r for r in c.rules.values() if r["dataset_id"] == d and r["rule_type"] == "timeliness")
            late.append({"dataset_id": d, "deadline_utc": iso(s["deadline"]), "last_refreshed_at": iso(s["last_refresh"]),
                         "minutes_after_deadline": _round_fraction(F(int((s["last_refresh"] - s["deadline"]).total_seconds()), 60), 0) if s["last_refresh"] else None,
                         "timeliness_rule": ", ".join(f"{r['rule_id']} ({r['status']})" for r in sorted(rl, key=lambda r: r["rule_id"])) or "none"})
    R["08_timeliness_states__late_with_rules"] = late

    # ---- 10 fix-first queue ---------------------------------------------------------------------------------------------------------------------------
    un = [i for i in ir if i["class"] != "resolved"]
    R["10_fix_first_queue__unresolved_by_severity_and_class"] = [{"severity": s, "open": sum(1 for i in un if i["severity"] == s and i["class"] == "open"),
                                                                 "claimed": sum(1 for i in un if i["severity"] == s and i["class"] == "claimed"), "unresolved": sum(1 for i in un if i["severity"] == s)}
                                                                for s in ("critical", "high", "medium", "low") if any(i["severity"] == s for i in un)]
    io = lambda i: c.accountable(i["owner_id"])            # noqa: E731
    do = lambda i: c.accountable(i["dataset_owner_id"])    # noqa: E731
    R["10_fix_first_queue__accountability"] = [{"unresolved": len(un), "issue_owner_inactive": sum(1 for i in un if not io(i)), "dataset_owner_inactive": sum(1 for i in un if not do(i)),
                                               "either_owner_inactive": sum(1 for i in un if not io(i) or not do(i)), "critical_or_high": sum(1 for i in un if i["severity"] in ("critical", "high")),
                                               "critical_or_high_with_an_inactive_owner": sum(1 for i in un if i["severity"] in ("critical", "high") and (not io(i) or not do(i)))}]
    tt: dict[str, list[dict]] = {}
    for i in un:
        tt.setdefault(c.owners[i["owner_id"]]["team"], []).append(i)
    R["10_fix_first_queue__by_team"] = [{"team": t, "unresolved": len(v), "claimed": sum(1 for i in v if i["class"] == "claimed"), "critical_or_high": sum(1 for i in v if i["severity"] in ("critical", "high")),
                                        "owner_inactive": sum(1 for i in v if not io(i)), "oldest_detected_at": iso(min(i["detected_at"] for i in v))}
                                       for t, v in sorted(tt.items(), key=lambda kv: (-len(kv[1]), kv[0]))]
    ordered = sorted(un, key=lambda i: (SEV_RANK[i["severity"]], 1 if io(i) else 0, i["detected_at"], i["issue_id"]))
    R["10_fix_first_queue__queue_top"] = [{"rank": k + 1, "issue_id": i["issue_id"], "dataset_id": i["dataset_id"], "rule_id": i["rule_id"], "severity": i["severity"], "class": i["class"], "status": i["status"],
                                          "age_days": _round_fraction(i["hours"] / 24, 1), "owner_id": i["owner_id"], "owner_team": c.owners[i["owner_id"]]["team"], "owner_active": io(i), "dataset_owner_active": do(i)}
                                         for k, i in enumerate(ordered[:15])]
    by_sev_age = sorted(un, key=lambda i: (SEV_RANK[i["severity"]], i["detected_at"], i["issue_id"]))
    by_age = sorted(un, key=lambda i: (i["detected_at"], i["issue_id"]))
    st15, sa15, ag15 = ({i["issue_id"] for i in lst[:15]} for lst in (ordered, by_sev_age, by_age))
    R["10_fix_first_queue__ordering_sensitivity"] = [{"first_n": 15, "overlap_with_severity_then_age": len(st15 & sa15), "overlap_with_age_only": len(st15 & ag15),
                                                      "stated_with_an_inactive_owner": sum(1 for i in ordered[:15] if not io(i)), "severity_then_age_with_an_inactive_owner": sum(1 for i in by_sev_age[:15] if not io(i)),
                                                      "age_only_with_an_inactive_owner": sum(1 for i in by_age[:15] if not io(i))}]
    dd: dict[str, list[dict]] = {}
    for i in un:
        if i["severity"] in ("critical", "high"):
            dd.setdefault(i["dataset_id"], []).append(i)
    R["10_fix_first_queue__datasets_with_the_most_unresolved_serious_issues"] = [
        {"dataset_id": d, "unresolved_critical_or_high": len(v), "claimed": sum(1 for i in v if i["class"] == "claimed"), "dataset_owner_team": c.owners[c.datasets[d]["owner_id"]]["team"],
         "dataset_owner_active": bool(c.owners[c.datasets[d]["owner_id"]]["active"])} for d, v in sorted(dd.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:10]]
    return R


if __name__ == "__main__":
    out = results()
    print(json.dumps({k: len(v) for k, v in out.items()}, indent=1))
