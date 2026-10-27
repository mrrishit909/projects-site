"""Writes scripts/snapshot-reference.json: what the PYTHON domain (domain/productsignal) computes over the published snapshot in
web/public/data, so CI can compare the TypeScript mirror without Python. Run once, from apps/productsignal:

    ../../.venv/bin/python web/scripts/make-snapshot-reference.py

Contents: sha256 digests (canonical JSON, sorted keys, compact) of every metric block at the as-of and at the cutoffs of the analysis
runs (the D-08 cutoff rule is visible at 2026-05-18, 2026-06-15, 2026-07-13), the complete experiment block, guardrail review and
segment analyses of each analysis run, the complete as-of metrics (the figures the pages show), the retention grid by local signup
week, and a digest of the local calendar date of every session (the zoneinfo-equivalent conversion the browser must reproduce).

Windows: at the as-of the manifest's own metric_windows (asserted equal to default_windows(as_of)); at any other cutoff the defaults
for that cutoff (README assumption 3), with the funnel window [cutoff - 7 d, cutoff).
"""
import hashlib, json, sys
from collections import defaultdict
from datetime import timedelta
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "domain"))
from productsignal.contract import ENTITIES, METRIC_KEYS  # noqa: E402
from productsignal.ingest import validate_batch  # noqa: E402
from productsignal.metrics import Ctx, compute, guardrail_review, segment_analysis, retention_grid, _matured, _day_indices  # noqa: E402
from productsignal.events import canonicalise  # noqa: E402
from productsignal.stats import q6  # noqa: E402
from productsignal.models import default_windows, parse_funnel, parse_plan, parse_windows  # noqa: E402
from productsignal.timeutil import local_date, parse_ts  # noqa: E402

DATA = ROOT / "web" / "public" / "data"
manifest = json.loads((DATA / "manifest.json").read_text())
rows = {e: json.loads((DATA / f"{e}.json").read_text())["rows"] for e in ENTITIES}
plans = {k: parse_plan(v) for k, v in manifest["analysis_plans"].items()}
for k, p in plans.items():
    assert p.hash_valid, k
inputs = {**rows}
ing = validate_batch(inputs, plans)
fd = parse_funnel(manifest["metric_windows"]["funnel"])
w_manifest = parse_windows(manifest["metric_windows"])
pop = ing.population(plans, funnels=[fd], windows=w_manifest)
as_of = parse_ts(manifest["as_of"])
assert w_manifest == default_windows(as_of), "the manifest windows are the defaults for the as-of"


def canon(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"))


def digest(v):
    return hashlib.sha256(canon(v).encode()).hexdigest()


def run_at(cut, xv, run_id=None):
    when = parse_ts(cut)
    if when == as_of:
        return compute(pop, when, w_manifest, fd, xv, run_id)
    return compute(pop, when, default_windows(when), fd, xv, run_id, funnel_window=(when - timedelta(days=7), when))


run_ids = {r.analysis_id: r for r in pop.analysis_runs}
cut_list = sorted({manifest["as_of"], *[r["cutoff_at"] for r in rows["analysis_runs"]]})
out = {"generated_by": "web/scripts/make-snapshot-reference.py (domain/productsignal, Python) run once over web/public/data",
       "dataset_hash": manifest["dataset_hash"], "dataset_version": manifest["dataset_version"], "as_of": manifest["as_of"],
       "ingest_counts": ing.counts, "rejected_count": len(ing.rejected), "cutoffs": {}, "runs": {}, "segments": {}}

for cut in cut_list:
    entry = {"windows": "manifest" if parse_ts(cut) == as_of else "default"}
    for xv in sorted(plans):
        c = run_at(cut, xv)
        if "common" not in entry:
            entry["common"] = {k: digest(c.metrics[k]) for k in METRIC_KEYS if k != "experiment"}
            entry["common"]["tracking_quality"] = digest(c.tracking_quality)
            entry["common"]["identity"] = digest(c.identity)
            entry["warning_codes"] = sorted(w["code"] for w in c.warnings if w["code"] not in ("SRM_MISMATCH", "INTERIM_RUN"))
        entry.setdefault("experiment", {})[xv] = digest(c.metrics["experiment"])
    out["cutoffs"][cut] = entry

# the complete figures at the as-of (what the pages show)
out["as_of_metrics"] = {xv: run_at(manifest["as_of"], xv).metrics for xv in sorted(plans)}
c_asof = run_at(manifest["as_of"], "xv-001")
out["as_of_tracking_quality"] = c_asof.tracking_quality
out["as_of_identity"] = c_asof.identity

for aid, r in sorted(run_ids.items()):
    xv = r.experiment_version_id
    c = run_at(r.cutoff_at.strftime("%Y-%m-%dT%H:%M:%SZ"), xv, aid)
    ex = c.metrics["experiment"]
    out["runs"][aid] = {"experiment_version_id": xv, "cutoff_at": r.cutoff_at.strftime("%Y-%m-%dT%H:%M:%SZ"), "experiment": ex,
                        "experiment_digest": digest(ex), "guardrail_review": guardrail_review(ex, plans[xv]),
                        "warning_codes": sorted(w["code"] for w in c.warnings)}
    canon_c = canonicalise(pop, r.cutoff_at)
    for by in ("plan", "segment", "timezone"):
        seg = segment_analysis(pop, r.cutoff_at, plans[xv], by, canon_c)
        out["segments"][f"{aid}/{by}"] = {"digest": digest(seg), "segments_tested": seg["segments_tested"], "bonferroni_threshold": seg["bonferroni_threshold"]}
        if aid in ("an-004", "an-005") and by == "segment":
            out["segments"][f"{aid}/{by}"]["full"] = seg

# the cohort grid by local signup week over every account (the cohorts page): at the as-of and at an interim cutoff
def weekly(cut):
    when = parse_ts(cut)
    canon_c = canonicalise(pop, when)
    ctx = Ctx(pop, when, canon_c, None)
    by = defaultdict(list)
    for a in ctx.signup_at:
        d = ctx.local(a, ctx.signup_at[a])
        by[d - timedelta(days=d.weekday())].append(a)
    cols = [("day1", 1, 1, 1), ("day7", 7, 7, 7), ("day14", 14, 14, 14), ("day28", 28, 28, 28), ("on_or_after_day7", 7, None, 7), ("week4", 28, 34, 34)]
    res = []
    for wk in sorted(by):
        cells = {}
        for name, lo, hi, need in cols:
            mat = [a for a in by[wk] if _matured(ctx, a, need)]
            hit = [a for a in mat if any(lo <= d <= (hi if hi is not None else 10 ** 9) for d in _day_indices(ctx, a))]
            cells[name] = {"mature_accounts": len(mat), "retained": len(hit), "rate": None if not mat else q6(Fraction(len(hit), len(mat)))}
        res.append({"week": wk.isoformat(), "accounts": len(by[wk]), "cells": cells})
    return res


out["weekly_grid"] = {cut: {"digest": digest(weekly(cut)), "weeks": len(weekly(cut))} for cut in (manifest["as_of"], "2026-06-15T00:00:00Z")}
out["weekly_grid"][manifest["as_of"]]["rows"] = weekly(manifest["as_of"])

# the local calendar date of every session in its account's zone (D-02): the browser's Intl conversion must reproduce it
acct = {a.account_id: a for a in pop.accounts}
user = {u.user_id: u for u in pop.users}
loc = [(s.session_id, local_date(s.started_at, acct[user[s.user_id].account_id].timezone).isoformat()) for s in sorted(pop.sessions, key=lambda s: s.session_id)]
out["session_local_dates"] = {"count": len(loc), "digest": digest(loc)}
# probe: the local date of every half hour from 2026-03-01 to 2026-11-12 (both DST transitions of the year) in the three zones
from datetime import datetime, timezone
t0 = int(datetime(2026, 3, 1, tzinfo=timezone.utc).timestamp())
t1 = int(datetime(2026, 11, 12, tzinfo=timezone.utc).timestamp())
probe = {tz: digest([local_date(datetime.fromtimestamp(t, timezone.utc), tz).isoformat() for t in range(t0, t1, 1800)])
         for tz in ("America/New_York", "America/Los_Angeles", "Europe/London")}
out["tz_probe"] = {"from": t0, "to": t1, "step_seconds": 1800, "digests": probe}
out["dataset_hash_check"] = {"sha256_of_entity_files_sorted_by_name": hashlib.sha256("".join(canon(rows[e]) for e in sorted(ENTITIES)).encode()).hexdigest(),
                             "sha256_of_entity_files_contract_order": hashlib.sha256("".join(canon(rows[e]) for e in ENTITIES).encode()).hexdigest(),
                             "manifest": manifest["dataset_hash"]}
Path(__file__).with_name("snapshot-reference.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
print("written", len(json.dumps(out)), "bytes; cutoffs", cut_list)
