"""Write ``web/public/reference/simulation-runs.json``: the Python simulator's answers for the three published runs
(one replication each, as before) and, since R4-11 / D-09, 50 replications per run on seeds ``seed + r``, the paired
difference baseline (sim-001) against plus-one agent (sim-002) on the same seeds, and the same comparison of sim-001
with sim-003 to show that sim-003 does NOT share the demand path (a different arrival intensity, by design).

    python data/simulation_reference.py            # rewrites the file
    python data/simulation_reference.py --check    # exit 1 when the file differs from what the simulator gives

The browser re-simulates all of it (web/src/views/simulation.tsx) and compares with this file.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "domain"), str(ROOT)]

from serviceflow.simulation import compare_policies, replication_report, simulate  # noqa: E402

REPLICATIONS = 50
TARGET = ROOT / "web" / "public" / "reference" / "simulation-runs.json"
RUNS = ROOT / "web" / "public" / "data" / "simulation_runs.json"


def build() -> dict:
    rows = json.loads(RUNS.read_text())["rows"]
    out_runs, reps = [], {}
    for r in rows:
        res = simulate(r["config"], r["seed"], r["warmup_minutes"], r["horizon_minutes"], r["simulation_id"])
        out_runs.append({"simulation_id": r["simulation_id"], "seed": r["seed"], "golden": res.golden(),
                         "statistics": res.statistics()})
        reps[r["simulation_id"]] = replication_report(r["config"], r["seed"], REPLICATIONS, r["warmup_minutes"],
                                                      r["horizon_minutes"])
    by = {r["simulation_id"]: r for r in rows}
    b, p, h = by["sim-001"], by["sim-002"], by["sim-003"]
    pair = lambda x, y: compare_policies(x["config"], y["config"], b["seed"], REPLICATIONS, b["warmup_minutes"],  # noqa: E731
                                         b["horizon_minutes"])
    return {
        "produced_by": "domain/serviceflow/simulation.py (Python 3.11 random.Random), data/simulation_reference.py; "
                       "the browser re-simulates and compares",
        "runs": out_runs,
        "replications": {"count": REPLICATIONS, "rule": "replication r uses seed + r; 95 % Student-t interval over the "
                        "replication means; an estimate", "runs": reps,
                        "paired": {"baseline_vs_plus_one_agent": {"baseline": "sim-001", "proposal": "sim-002",
                                                                  **pair(b, p)},
                                   "baseline_vs_holdout_intensity": {"baseline": "sim-001", "proposal": "sim-003",
                                                                     "note": "not a policy comparison: sim-003 has "
                                                                             "another arrival intensity, so another "
                                                                             "demand path by design",
                                                                     **pair(b, h)}}},
    }


def main(argv: list[str]) -> int:
    text = json.dumps(build(), indent=1, sort_keys=True) + "\n"
    if "--check" in argv:
        same = TARGET.read_text() == text
        print("simulation-runs.json " + ("matches" if same else "DIFFERS from") + " the Python simulator")
        return 0 if same else 1
    TARGET.write_text(text)
    print(f"wrote {TARGET.relative_to(ROOT)} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
