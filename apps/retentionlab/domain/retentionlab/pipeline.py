"""The whole domain over one import: validation, point-in-time rebuild, consistency of the stored derived rows, the fixture's command
requests, the split, every metric. ``evaluate(inputs)`` equals ``expected.json`` leaf for leaf on the golden fixture and both variants."""
from __future__ import annotations

from typing import Any

from . import errors as E
from .contract import CONTRACT_VERSION, ENTITIES
from .ingest import Ingest, validate
from .metrics import freshness, publications, rank_key, set_metrics
from .numbers import canon, config_hash
from .rules import check_calibration_rows, check_capacity, check_feature_request, check_fit_rows, check_threshold
from .split import retained, split_run
from .timeutil import days, iso_z, parse_ts
from .world import World
from fractions import Fraction


def consistency(world: World, ingest: Ingest, splits: dict[str, Any], pubs: list[dict[str, Any]], queues: dict[str, list[int]]) -> dict[str, list[str]]:
    """The stored derived rows that differ from the rebuilt ones (D-P10-19). Empty lists mean the stored rows are what the application
    would have produced."""
    acc = ingest.accepted
    out: dict[str, list[str]] = {"cutoff_windows_mismatched": [], "feature_rows_mismatched": [], "labels_mismatched": [],
                                 "split_assignments_mismatched": [], "scoring_publications_mismatched": [], "config_hash_mismatched": [],
                                 "outreach_queue_mismatched": [], "predictions_citation_mismatched": []}
    for c in acc["prediction_cutoffs"]:
        pa = parse_ts(c["prediction_at"])
        if parse_ts(c["horizon_end"]) != pa + days(world.horizon) or parse_ts(c["observation_start"]) != pa - days(world.obs_days):
            out["cutoff_windows_mismatched"].append(c["cutoff_id"])
    for fr in acc["feature_rows"]:
        a = world.analyse(fr["cutoff_id"])
        if not (a["eligible"] and fr["features_json"] == a["features"] and fr["max_available_at"] == a["max_available_at"]
                and fr["feature_version"] == world.feature_version
                and (fr["max_available_at"] is None or parse_ts(fr["max_available_at"]) < parse_ts(a["prediction_at"]))):
            out["feature_rows_mismatched"].append(fr["feature_row_id"])
    for lb in acc["labels"]:
        a = world.analyse(lb["cutoff_id"])
        if not (a["eligible"] and lb["churned"] == a["churned"] and lb["mature"] == a["mature"] and lb["label_end"] == a["label_end"]):
            out["labels_mismatched"].append(lb["label_id"])
    for r in acc["training_runs"]:
        if config_hash(r["config"]) != r["config_hash"]:
            out["config_hash_mismatched"].append(r["training_run_id"])
    for p in acc["predictions"]:
        run = world.runs[p["training_run_id"]]
        if (p["config_hash"], p["feature_version"], p["label_version"]) != (run["config_hash"], run["config"]["feature_version"], run["config"]["label_version"]):
            out["predictions_citation_mismatched"].append(p["prediction_id"])
    for sa in acc["split_assignments"]:
        d = {r["cutoff_id"]: r for r in splits[sa["training_run_id"]][0]}[sa["cutoff_id"]]
        if (sa["split"], sa["status"], sa["drop_reason"]) != (d["split"], d["status"], d["drop_reason"]):
            out["split_assignments_mismatched"].append(sa["assignment_id"])
    stored_status = {sp["publication_id"]: sp["status"] for sp in acc["scoring_publications"]}
    for p in pubs:
        if stored_status[p["publication_id"]] != p["status"]:
            out["scoring_publications_mismatched"].append(p["publication_id"])
    for scenario_id, rebuilt in queues.items():
        stored = sorted(o["account_id"] for o in acc["outreach_events"] if o["scenario_id"] == scenario_id)
        if stored != sorted(rebuilt):
            out["outreach_queue_mismatched"].append(scenario_id)
    return out


def run_request(world: World, rq: dict[str, Any], splits: dict[str, Any]) -> dict[str, Any]:
    """One fixture request through the same refusal rules the API uses."""
    res: dict[str, Any] = {"request_id": rq["request_id"], "command": rq["command"], "status": "accepted", "reason_code": None, "offending": [], "result": None}
    try:
        cmd = rq["command"]
        if cmd == "build-point-in-time-features":
            res["result"] = {"fields": check_feature_request(world.registry, rq["fields"])}
            return res
        run = world.runs.get(rq.get("training_run_id"))
        if run is None:
            raise E.DomainError(E.UNKNOWN_TRAINING_RUN, "unknown training run", None,
                                {"offending": [{"item": rq.get("training_run_id"), "code": E.UNKNOWN_TRAINING_RUN}]})
        rows = splits[run["training_run_id"]][0]
        if cmd == "fit-preprocessing":
            check_fit_rows(rq["fit_rows"], retained(rows, "train"))
            res["result"] = {"fit_rows": len(rq["fit_rows"])}
        elif cmd == "calibrate-model":
            check_calibration_rows(rq["fit_rows"], rq["evaluation_rows"], retained(rows, "validation"))
            res["result"] = {"fit_rows": len(rq["fit_rows"]), "evaluation_rows": len(rq["evaluation_rows"])}
        elif cmd == "select-threshold":
            check_threshold(rq["parameter"], rq["selected_on"])
            res["result"] = {"parameter": rq["parameter"], "selected_on": "validation"}
        elif cmd == "prioritize-outreach":
            scenario = world.scenarios.get(rq["scenario_id"])
            if scenario is None:
                raise E.DomainError(E.UNKNOWN_SCENARIO, "unknown scenario", None, {"offending": [{"item": rq["scenario_id"], "code": E.UNKNOWN_SCENARIO}]})
            pool = sorted(({"p": Fraction(world.preds[(run["training_run_id"], r["cutoff_id"])]["probability"]), "account_id": r["account_id"]}
                           for r in world.set_rows(rq["prediction_at"]) if r["eligible"] and (run["training_run_id"], r["cutoff_id"]) in world.preds),
                          key=rank_key)
            check_capacity(scenario["scenario_id"], scenario["capacity"], len(pool))
            res["result"] = {"capacity": scenario["capacity"], "population": len(pool), "status": "draft",
                             "queue_account_ids": [q["account_id"] for q in pool[:scenario["capacity"]]]}
    except E.DomainError as err:
        res.update(status="refused", reason_code=err.code, offending=err.details.get("offending", []), result=None)
    return res


def evaluate(data: dict[str, Any]) -> dict[str, Any]:
    ingest = validate(data)
    world = World(data, ingest.accepted)
    splits = {rid: split_run(world, run) for rid, run in world.runs.items()}
    pubs = publications(world)
    scope = data["scope"]
    sets: dict[str, Any] = {}
    point_in_time: list[dict[str, Any]] = []
    queues: dict[str, list[int]] = {}
    for sc in scope["sets"]:
        m = set_metrics(world, scope["training_run_id"], sc["prediction_at"], sc.get("scenario_id"), scope.get("drift"))
        sets[sc["prediction_at"]] = m
        point_in_time.extend(world.set_rows(sc["prediction_at"]))
        if sc.get("scenario_id") and m["outreach_queue"] is not None:
            queues[sc["scenario_id"]] = m["outreach_queue"]["account_ids"]
    drift = scope.get("drift")
    if drift:
        have = {r["cutoff_id"] for r in point_in_time}
        point_in_time.extend(r for r in world.set_rows(drift["reference_prediction_at"]) if r["cutoff_id"] not in have)
    return {
        "contract_version": data["contract_version"], "as_of": data["as_of"],
        "ingest": {"counts": ingest.counts(), "rejected_records": ingest.rejected},
        "consistency": consistency(world, ingest, splits, pubs, queues),
        "commands": [run_request(world, rq, splits) for rq in data.get("requests", [])],
        "split": {rid: {"train_end": world.runs[rid]["train_end"], "validation_end": world.runs[rid]["validation_end"],
                        "test_end": world.runs[rid]["test_end"], "embargo_days": world.horizon + world.grace, "counts": counts,
                        "assignments": [{"cutoff_id": r["cutoff_id"], "split": r["split"], "status": r["status"], "drop_reason": r["drop_reason"]} for r in rs]}
                  for rid, (rs, counts) in splits.items()},
        "point_in_time": {"rows": point_in_time},
        "scoring_publications": pubs,
        "freshness": freshness(world, pubs),
        "cutoff_sets": sets,
        "empty_population": all(s["empty_population"] for s in sets.values()) if sets else True}


__all__ = ["evaluate", "ENTITIES", "CONTRACT_VERSION", "canon", "iso_z"]
