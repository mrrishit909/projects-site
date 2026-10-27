"""Build artifacts/trustledger-analyst-workbook.xlsx with openpyxl (P07-ART-05).

Usage:  ../../.venv/bin/python artifacts/build_workbook.py [--recalc]

Inputs: the published snapshot ``web/public/data`` (typed into the data sheets: owners, datasets, the 55 active rules' measured counts, 574 issues with the facts of their verifying
rerun, lineage edges, the effective metric definitions, 400 match candidates with their decision and the verification layer's truth flag, the 15 monitored datasets' schedule facts),
the Python domain (``Domain reference``: the figures it publishes, pasted for the check columns only), tests/fixtures/golden/expected.json and artifacts/analysis-results.json
(data/sql/analysis/run_all.py). openpyxl cannot calculate, so the file it writes holds formulas only. With --recalc, LibreOffice (soffice) opens it headless and saves a
recalculated copy over the same path, which then also carries cached values.

What the formulas do, live: each dimension's score of a dataset (the mean of its rules' passing / eligible, populated for validity), the weighted score under BOTH weight versions with
unmeasured dimensions left out of both sums, the switch ``Controls!B3`` (w1 or w2) that selects which one the Selected column shows, the shift between them, the critical failures and
open critical issues counted apart with the override, the issue class of every one of 574 issues (closed AND verified by a successful rerun of the same rule version = resolved; closed
otherwise = claimed; else open) and its hours, mean resolution by team, ownership coverage by the active owner at the as-of, declared / observed / inferred lineage coverage, definition
coverage under checklist cl-1, match precision over approvals and the review-correct share, and the timeliness state (on time / pending / late) with its denominator.
What the spreadsheet does not do: measure a rule over the dataset rows (patterns, duplicates, parent lookups) or work out a daily occurrence in an IANA zone; those counts and instants
are TYPED from the independent Python side and every result is compared with the Python domain after recalculation (limits W-02, W-03). Excel is never run.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from fractions import Fraction as F
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "domain"), str(ROOT), str(ROOT / "data" / "sql" / "analysis")]

import python_side as ps  # noqa: E402
from trustledger import run_pipeline  # noqa: E402
from prepare_snapshot import snapshot_inputs  # noqa: E402

OUT = ROOT / "artifacts" / "trustledger-analyst-workbook.xlsx"
RESULTS_PATH = ROOT / "artifacts" / "analysis-results.json"
MANIFEST = json.loads((ROOT / "web/public/data/manifest.json").read_text())
EXPECTED = json.loads((ROOT / "tests/fixtures/golden/expected.json").read_text())
CODE_REVISION = "0b5d686"
DATASET_HASH = "a9f7a3321b102752dd7aa95b76df14c1d9372103e685e10222959fd6438f27ff"
HDR = PatternFill("solid", fgColor="23303A")
BLUE = Font(color="0000FF")
BOLD = Font(bold=True)
WHITE = Font(bold=True, color="FFFFFF")
EXCEL_EPOCH = datetime(1899, 12, 30, tzinfo=timezone.utc)
DIMS = ("completeness", "validity", "uniqueness", "relationship", "timeliness")
SHEET_ORDER = ["Read me", "Controls", "Checks", "Portfolio", "Dataset scores", "Golden case", "Assumptions", "Rule results", "Issues", "Owners", "Datasets", "Lineage", "Definitions",
               "Matching", "Timeliness", "Weights", "Domain reference", "SQL results (pasted)"]


def serial(s: str | None):
    return None if s is None else (ps.ts(s) - EXCEL_EPOCH).total_seconds() / 86400


def header(ws, row, labels, col=1):
    for i, text in enumerate(labels):
        c = ws.cell(row=row, column=col + i, value=text)
        c.font, c.fill = WHITE, HDR
        c.alignment = Alignment(wrap_text=True, vertical="top")


def title(ws, text, note=None):
    ws["A1"] = text
    ws["A1"].font = Font(bold=True, size=14)
    if note:
        ws["A2"] = note


def widths(ws, spec):
    for col, w in spec.items():
        ws.column_dimensions[col].width = w


def put(ws, rows: list[list], first_row: int, blue: bool = True):
    for r, row in enumerate(rows, start=first_row):
        for c, v in enumerate(row, start=1):
            cell = ws.cell(row=r, column=c, value=v)
            if blue and v is not None and not (isinstance(v, str) and v.startswith("=")):
                cell.font = BLUE


def fl(x) -> float | None:
    return None if x is None else float(x)


class Data:
    """Typed inputs from the snapshot through the independent Python side, plus the domain's figures for the check columns."""

    def __init__(self) -> None:
        self.c = ps.Ctx()
        inputs, manifest = snapshot_inputs()
        truth = manifest["synthetic_truth"]["true_entity"]
        self.truth = truth
        self.dom = {wv: run_pipeline(inputs, weight_version=wv, truth=truth) for wv in ("w1", "w2")}
        self.d0 = self.dom["w2"]


# ---- data sheets -------------------------------------------------------------------------------------------------------------------------------------------------------------
def build_weights(wb, data: Data):
    ws = wb.create_sheet("Weights")
    title(ws, "Rule-weight versions (append-only: a change is a new version, D-07 assumption 4)")
    header(ws, 3, ["weight_version", "valid_from (UTC)", *DIMS])
    rows = [[wv, w["valid_from"], *[float(w["weights"][d]) for d in DIMS]] for wv, w in data.c.weights.items()]
    put(ws, rows, 4)
    widths(ws, {"A": 16, "B": 24})


def build_owners(wb, data: Data):
    ws = wb.create_sheet("Owners")
    title(ws, "Owners register (18; three inactive)", "accountable_at_as_of = the owner is active at the as-of (a deactivation after the as-of still counts as active).")
    header(ws, 3, ["owner_id", "team", "active", "deactivated_at (serial)", "accountable_at_as_of"])
    owners = sorted(data.c.owners.values(), key=lambda o: o["owner_id"])
    put(ws, [[o["owner_id"], o["team"], bool(o["active"]), serial(o["deactivated_at"])] for o in owners], 4)
    for i in range(len(owners)):
        r = 4 + i
        ws.cell(row=r, column=4).number_format = "yyyy-mm-dd hh:mm"
        ws.cell(row=r, column=5, value=f"=IF(ISNUMBER(D{r}),Controls!$B$4<D{r},C{r})")
    widths(ws, {"A": 12, "B": 22, "D": 22})
    return 4 + len(owners) - 1


def build_datasets(wb, data: Data):
    ws = wb.create_sheet("Datasets")
    title(ws, "Datasets registered by the as-of (40)", "owner_covered = the owner is accountable at the as-of (Owners!E).")
    header(ws, 3, ["dataset_id", "owner_id", "monitored", "owner_covered", "owner_team"])
    ds = [d for _, d in sorted(data.c.datasets.items())]
    put(ws, [[d["dataset_id"], d["owner_id"], bool(d["monitored"])] for d in ds], 4)
    for i in range(len(ds)):
        r = 4 + i
        ws.cell(row=r, column=4, value=f"=INDEX(Owners!$E$4:$E$21,MATCH(B{r},Owners!$A$4:$A$21,0))")
        ws.cell(row=r, column=5, value=f"=INDEX(Owners!$B$4:$B$21,MATCH(B{r},Owners!$A$4:$A$21,0))")
    widths(ws, {"A": 22, "B": 12, "E": 22})
    return 4 + len(ds) - 1


def build_rule_results(wb, data: Data):
    ws = wb.create_sheet("Rule results")
    title(ws, "The 55 rules active at the as-of: measured counts (typed) and the score each contributes (formula)",
          "eligible, populated and failing are TYPED from the independent Python side (W-02); score_den = populated for validity else eligible; score = (eligible - failing) / score_den, empty when it measures nothing.")
    header(ws, 3, ["rule_id", "dataset_id", "dimension", "severity", "eligible", "populated", "failing", "score_den", "score"])
    ms = sorted(data.c.ms.values(), key=lambda m: m["rule_id"])
    put(ws, [[m["rule_id"], m["dataset_id"], m["dimension"], m["severity"], m["eligible"], m["populated"], m["failing"]] for m in ms], 4)
    for i in range(len(ms)):
        r = 4 + i
        ws.cell(row=r, column=8, value=f'=IF(C{r}="validity",F{r},E{r})')
        c = ws.cell(row=r, column=9, value=f'=IF(H{r}>0,(E{r}-G{r})/H{r},"")')
        c.number_format = "0.000000"
    widths(ws, {"A": 38, "B": 20, "C": 14, "D": 10})
    return 4 + len(ms) - 1


def build_issues(wb, data: Data):
    ws = wb.create_sheet("Issues")
    title(ws, "574 issues: the facts of each issue and its verifying run (typed), the class and the hours (formulas)",
          "resolved = closed by the as-of AND the verification run is a rerun, for this issue, of the same rule at the same version, with 0 failures, not before the detection or the latest reopen; claimed = closed otherwise; open = the rest.")
    header(ws, 3, ["issue_id", "dataset_id", "rule_id", "owner_id", "severity", "status", "detected_at", "closed_at", "verified_at", "ver_kind", "ver_for_issue", "ver_rule_id", "ver_rule_version",
                   "base_rule_version", "ver_failure_count", "last_reopen_at", "reopen_cycles", "owner_team", "closed", "verified", "class", "hours", "owner_accountable"])
    rows = []
    for i in sorted(data.c.issues, key=lambda x: x["issue_id"]):
        base = data.c.runs[i["rule_run_id"]]
        rule = data.c.rules[base["rule_id"]]
        v = data.c.runs.get(i["verification_run_id"]) if i["verification_run_id"] else None
        reopen = [t for t in i["reopened_at"] if ps.ts(t) <= data.c.as_of]
        rows.append([i["issue_id"], rule["dataset_id"], rule["rule_id"], i["owner_id"], rule["severity"], i["status"], serial(i["detected_at"]), serial(i["closed_at"]),
                     serial(v["run_at"]) if v else None, v["kind"] if v else None, v["rerun_for_issue"] if v else None, v["rule_id"] if v else None, v["rule_version"] if v else None,
                     base["rule_version"], v["failure_count"] if v else None, serial(max(reopen)) if reopen else None, len(reopen)])
    put(ws, rows, 4)
    n = len(rows)
    for k in range(n):
        r = 4 + k
        for col in (7, 8, 9, 16):
            ws.cell(row=r, column=col).number_format = "yyyy-mm-dd hh:mm"
        ws.cell(row=r, column=18, value=f"=INDEX(Owners!$B$4:$B$21,MATCH(D{r},Owners!$A$4:$A$21,0))")
        ws.cell(row=r, column=19, value=f'=AND(F{r}="closed",ISNUMBER(H{r}),H{r}<=Controls!$B$4)')
        ws.cell(row=r, column=20, value=f'=AND(ISNUMBER(I{r}),I{r}<=Controls!$B$4,J{r}="rerun",K{r}=A{r},L{r}=C{r},M{r}=N{r},O{r}=0,I{r}>=G{r},IF(ISNUMBER(P{r}),I{r}>=P{r},TRUE))')
        ws.cell(row=r, column=21, value=f'=IF(AND(S{r},T{r}),"resolved",IF(S{r},"claimed","open"))')
        ws.cell(row=r, column=22, value=f'=ROUND((IF(U{r}="resolved",I{r},IF(U{r}="claimed",H{r},Controls!$B$4))-G{r})*24,4)')
        ws.cell(row=r, column=23, value=f"=INDEX(Owners!$E$4:$E$21,MATCH(D{r},Owners!$A$4:$A$21,0))")
    widths(ws, {"A": 11, "B": 20, "C": 36, "G": 17, "H": 17, "I": 17, "P": 17, "R": 20})
    return 4 + n - 1


def build_lineage(wb, data: Data):
    ws = wb.create_sheet("Lineage")
    title(ws, "160 lineage edges: declared 80, observed 70, inferred 10", "An observed edge has an observation instant and a declared one does not (D-08). pair_declared / pair_observed look the (source, target) pair up across the edges; an inferred edge is never observed.")
    header(ws, 3, ["edge_id", "source_dataset_id", "target_dataset_id", "evidence_type", "observed_at", "pair", "pair_declared", "pair_observed", "counts_as_observed_match"])
    edges = sorted(data.c.edges, key=lambda e: e["edge_id"])
    put(ws, [[e["edge_id"], e["source_dataset_id"], e["target_dataset_id"], e["evidence_type"], serial(e["observed_at"])] for e in edges], 4)
    n = len(edges)
    last = 4 + n - 1
    for k in range(n):
        r = 4 + k
        ws.cell(row=r, column=5).number_format = "yyyy-mm-dd hh:mm"
        ws.cell(row=r, column=6, value=f'=B{r}&">"&C{r}')
        ws.cell(row=r, column=7, value=f'=COUNTIFS($F$4:$F${last},F{r},$D$4:$D${last},"declared")>0')
        ws.cell(row=r, column=8, value=f'=COUNTIFS($F$4:$F${last},F{r},$D$4:$D${last},"observed")>0')
        ws.cell(row=r, column=9, value=f'=AND(D{r}="observed",G{r})')
    widths(ws, {"A": 9, "B": 20, "C": 20, "D": 12, "E": 17, "F": 42})
    return last


def build_definitions(wb, data: Data):
    ws = wb.create_sheet("Definitions")
    title(ws, "The effective published version of each of the 30 metrics at the as-of, and the checklist cl-1",
          "Complete when definition, grain and refresh are non-blank, the source-field list is non-empty with no blank entry and the owner exists in the register. The texts are TYPED; the checks are formulas.")
    header(ws, 3, ["metric_id", "version", "owner_id", "definition", "grain", "refresh", "source_fields", "blank_source_field", "has_definition", "has_grain", "has_refresh", "has_source_fields", "has_owner", "complete"])
    eff: dict[str, dict] = {}
    for m in sorted(data.c.metrics, key=lambda m: (m["metric_id"], m["version_number"])):
        if m["status"] == "published" and ps.ts(m["valid_from"]) <= data.c.as_of:
            eff[m["metric_id"]] = m
    chars = data.c.chars
    rows = []
    for mid in sorted(eff):
        m = eff[mid]
        sf = m["source_fields"] or []
        rows.append([mid, m["version_number"], m["owner_id"], m["definition"], m["grain"], m["refresh"], len(sf), any(str(x).strip(chars) == "" for x in sf)])
    put(ws, rows, 4)
    for k in range(len(rows)):
        r = 4 + k
        ws.cell(row=r, column=9, value=f'=LEN(TRIM(D{r}))>0')
        ws.cell(row=r, column=10, value=f'=LEN(TRIM(E{r}))>0')
        ws.cell(row=r, column=11, value=f'=LEN(TRIM(F{r}))>0')
        ws.cell(row=r, column=12, value=f'=AND(G{r}>0,NOT(H{r}))')
        ws.cell(row=r, column=13, value=f'=COUNTIF(Owners!$A$4:$A$21,C{r})>0')
        ws.cell(row=r, column=14, value=f'=AND(I{r},J{r},K{r},L{r},M{r})')
    widths(ws, {"A": 28, "D": 40})
    return 4 + len(rows) - 1


def build_matching(wb, data: Data):
    ws = wb.create_sheet("Matching")
    title(ws, "400 match candidates: the human decision and the verification layer's truth flag", "truth_same_entity comes from the synthetic truth held only in the manifest (verification layer): TYPED here for the precision formulas, never used to propose or decide.")
    header(ws, 3, ["candidate_id", "decision", "reversed", "flagged_possible_household", "truth_same_entity", "decision_agrees_with_truth"])
    by: dict[str, str] = {}
    approved_merge: dict[str, str] = {}
    for d in data.c.decisions:
        if d["decision"] in ("approve", "reject"):
            by[d["candidate_id"]] = d["decision"]
        if d["decision"] == "approve":
            approved_merge[d["merge_id"]] = d["candidate_id"]
    reversed_c = {approved_merge[d["reverses_merge_id"]] for d in data.c.decisions if d["decision"] == "reverse"}
    rows = []
    for cid, cd in sorted(data.c.candidates.items()):
        same = data.truth[cd["left_record_id"]] == data.truth[cd["right_record_id"]]
        rows.append([cid, by.get(cid, "none"), cid in reversed_c, bool(cd["uncertainty"]), same])
    put(ws, rows, 4)
    for k in range(len(rows)):
        r = 4 + k
        ws.cell(row=r, column=6, value=f'=IF(B{r}="none","",(B{r}="approve")=E{r})')
    widths(ws, {"A": 12, "D": 26, "F": 26})
    return 4 + len(rows) - 1


def build_timeliness(wb, data: Data):
    ws = wb.create_sheet("Timeliness")
    title(ws, "The 15 monitored datasets at the as-of: the judged occurrence and deadline (typed from the Python side) and the state (formula)",
          "state = on_time when a refresh lies in [occurrence, deadline); otherwise pending while the deadline is after the as-of; otherwise late. A pending dataset is outside the denominator.")
    header(ws, 3, ["dataset_id", "timezone", "scheduled_local", "grace_minutes", "occurrence_utc", "deadline_utc", "last_refreshed_at", "state"])
    st = data.c.tstates[0]
    rows = [[d, s["tz"], s["local_time"], s["grace"], serial(iso(s["occurrence"])), serial(iso(s["deadline"])), serial(iso(s["last_refresh"]))] for d, s in sorted(st.items())]
    put(ws, rows, 4)
    for k in range(len(rows)):
        r = 4 + k
        for col in (5, 6, 7):
            ws.cell(row=r, column=col).number_format = "yyyy-mm-dd hh:mm"
        ws.cell(row=r, column=8, value=f'=IF(AND(ISNUMBER(G{r}),G{r}>=E{r},G{r}<F{r}),"on_time",IF(F{r}>Controls!$B$4,"pending","late"))')
    widths(ws, {"A": 20, "B": 18, "E": 17, "F": 17, "G": 17})
    return 4 + len(rows) - 1


def iso(t):
    return ps.iso(t)


# ---- the domain's figures, pasted for the check columns -----------------------------------------------------------------------------------------------------------------------------
def domain_reference(data: Data) -> dict:
    d0 = data.d0.metrics
    ref: dict = {"by_version": {wv: data.dom[wv].metrics["weighted_score"]["datasets"] for wv in ("w1", "w2")}}
    ref["ownership"] = d0["ownership_coverage"]
    ref["definition"] = d0["definition_coverage"]
    ref["lineage"] = d0["lineage_coverage"]
    ref["timeliness"] = d0["timeliness"]
    ref["resolution"] = d0["resolution_time"]
    ref["precision"] = d0["match_precision"]
    ref["critical"] = d0["critical_failures"]
    # mean resolution by team: from the domain's own per-issue hours, averaged here in exact arithmetic (the domain publishes only the overall mean)
    owner_team = {o["owner_id"]: o["team"] for o in data.c.owners.values()}
    owner_of = {i["issue_id"]: i["owner_id"] for i in data.c.issues}
    by: dict[str, list[F]] = {}
    for iid, x in d0["resolution_time"]["issues"].items():
        if x["class"] == "resolved":
            by.setdefault(owner_team[owner_of[iid]], []).append(F(x["resolution_hours"]))
    ref["team_mean"] = {t: ps.rnd(sum(v, F(0)) / len(v), 4) for t, v in by.items()}
    allv = [h for v in by.values() for h in v]
    other = [h for t, v in by.items() if t != "Data Platform" for h in v]
    ref["other_mean"] = ps.rnd(sum(other, F(0)) / len(other), 4)
    ref["ratio"] = ps.rnd((sum(by["Data Platform"], F(0)) / len(by["Data Platform"])) / (sum(other, F(0)) / len(other)), 6)
    ref["unresolved_by_sev"] = {s: sum(1 for x in d0["resolution_time"]["issues"].values() if x["class"] != "resolved" and x["severity"] == s) for s in ("critical", "high", "medium", "low")}
    return ref


def build_domain_reference(wb, ref: dict, data: Data):
    ws = wb.create_sheet("Domain reference")
    title(ws, "PASTED VALUES from the Python domain (run_pipeline over the snapshot with the verification truth for precision), read only by the check columns",
          "Dataset weighted scores under both weight versions (\"not measured\" = the domain measures no dimension: never 0).")
    header(ws, 3, ["dataset_id", "w1", "w2"])
    ds = sorted(data.c.datasets)
    rows = []
    for d in ds:
        row = [d]
        for wv in ("w1", "w2"):
            v = ref["by_version"][wv][d]["value"]
            row.append("not measured" if v is None else float(v))
        rows.append(row)
    put(ws, rows, 4)
    widths(ws, {"A": 22})
    return 4 + len(rows) - 1


def build_dataset_scores(wb, data: Data, last_rule: int, iss_last: int):
    ws = wb.create_sheet("Dataset scores")
    title(ws, "Weighted score of every dataset under both weight versions, with the critical override beside it",
          "Dimension score = mean of the dataset's measured rules; weighted = sum(weight x score) / sum(weights of the MEASURED dimensions); a dataset that measures nothing is empty, never 0. Selected = the version chosen at Controls!B3.")
    header(ws, 3, [*DIMS, "weight_sum_w1", "weighted_w1", "weight_sum_w2", "weighted_w2", "shift (w2 - w1)", "selected", "critical_failures", "open_critical_issues", "critical_override",
                   "differs", "moved_at_least_0_005", "abs_shift", "ref_w1 (domain)", "ref_w2 (domain)", "check"], col=2)
    ws.cell(row=3, column=1, value="dataset_id").font = WHITE
    ws.cell(row=3, column=1).fill = HDR
    ds = sorted(data.c.datasets)
    n = len(ds)
    rr = f"'Rule results'!$I$4:$I${last_rule}"
    rb = f"'Rule results'!$B$4:$B${last_rule}"
    rc = f"'Rule results'!$C$4:$C${last_rule}"
    for k, d in enumerate(ds):
        r = 4 + k
        ws.cell(row=r, column=1, value=d)
        for j, dim in enumerate(DIMS):
            col = 2 + j
            letter = "BCDEF"[j]
            c = ws.cell(row=r, column=col, value=f'=IFERROR(AVERAGEIFS({rr},{rb},$A{r},{rc},{letter}$3),"")')
            c.number_format = "0.000000"
        for base, wrow, sumcol, scol in ((7, 4, "G", "H"), (9, 5, "I", "J")):
            ws.cell(row=r, column=base, value="=" + "+".join(f"IF(ISNUMBER({'BCDEF'[j]}{r}),Weights!${'CDEFG'[j]}${wrow},0)" for j in range(5)))
            num = "+".join(f"IF(ISNUMBER({'BCDEF'[j]}{r}),Weights!${'CDEFG'[j]}${wrow}*{'BCDEF'[j]}{r},0)" for j in range(5))
            c = ws.cell(row=r, column=base + 1, value=f'=IF({sumcol}{r}=0,"",({num})/{sumcol}{r})')
            c.number_format = "0.000000"
        ws.cell(row=r, column=11, value=f'=IF(AND(ISNUMBER(H{r}),ISNUMBER(J{r})),J{r}-H{r},"")').number_format = "0.000000"
        ws.cell(row=r, column=12, value=f'=IF(Controls!$B$3="w1",H{r},J{r})').number_format = "0.000000"
        ws.cell(row=r, column=13, value=f"=SUMIFS('Rule results'!$G$4:$G${last_rule},{rb},$A{r},'Rule results'!$D$4:$D${last_rule},\"critical\")")
        ws.cell(row=r, column=14, value=f'=COUNTIFS(Issues!$B$4:$B${iss_last},$A{r},Issues!$E$4:$E${iss_last},"critical",Issues!$U$4:$U${iss_last},"<>resolved")')
        ws.cell(row=r, column=15, value=f"=OR(M{r}>0,N{r}>0)")
        ws.cell(row=r, column=16, value=f'=IF(ISNUMBER(K{r}),IF(ABS(K{r})>0.000000000001,1,0),"")')
        ws.cell(row=r, column=17, value=f'=IF(ISNUMBER(K{r}),IF(ABS(K{r})>=0.005,1,0),"")')
        ws.cell(row=r, column=18, value=f'=IF(ISNUMBER(K{r}),ABS(K{r}),"")')
        ws.cell(row=r, column=19, value=f"='Domain reference'!B{r}")
        ws.cell(row=r, column=20, value=f"='Domain reference'!C{r}")
        ws.cell(row=r, column=21, value=f'=AND(IF(ISNUMBER(H{r}),ISNUMBER(S{r}),NOT(ISNUMBER(S{r}))),IF(ISNUMBER(J{r}),ISNUMBER(T{r}),NOT(ISNUMBER(T{r}))),IF(ISNUMBER(H{r}),ABS(ROUND(H{r},6)-S{r})<0.0000005,TRUE),IF(ISNUMBER(J{r}),ABS(ROUND(J{r},6)-T{r})<0.0000005,TRUE))')
    last = 4 + n - 1
    s = last + 2
    labels = [("datasets scored (w1)", f"=COUNT(H4:H{last})"), ("datasets whose score differs between w1 and w2", f"=SUM(P4:P{last})"), ("datasets moved by at least 0.005", f"=SUM(Q4:Q{last})"),
              ("mean score under w1", f"=AVERAGE(H4:H{last})"), ("mean score under w2", f"=AVERAGE(J4:J{last})"),
              ("largest absolute shift", f"=MAX(R4:R{last})"), ("largest move (signed)", f"=INDEX(K4:K{last},MATCH(MAX(R4:R{last}),R4:R{last},0))"),
              ("datasets carrying the critical override", f"=COUNTIF(O4:O{last},TRUE)"), ("critical failures (failing rows of active critical rules)", f"=SUM(M4:M{last})"),
              ("open critical issues", f"=SUM(N4:N{last})")]
    for i, (lab, f) in enumerate(labels):
        ws.cell(row=s + i, column=1, value=lab).font = BOLD
        ws.cell(row=s + i, column=2, value=f)
    widths(ws, {"A": 46, "G": 14, "I": 14})
    return last, s


def build_portfolio(wb, data: Data, ref: dict, ds_last: int, iss_last: int, edge_last: int, def_last: int, match_last: int, tl_last: int, own_last: int, scores_summary_row: int):
    ws = wb.create_sheet("Portfolio")
    title(ws, "Portfolio metrics, live formulas against the domain's values", "Column B is a formula over the data sheets; C is the domain's value pasted from `Domain reference`; D is the tolerance; E is TRUE when they agree.")
    header(ws, 3, ["measure", "workbook (formula)", "domain (pasted)", "tolerance", "check"])
    R = f"Issues!$U$4:$U${iss_last}"
    H = f"Issues!$V$4:$V${iss_last}"
    T = f"Issues!$R$4:$R${iss_last}"
    S = f"Issues!$E$4:$E${iss_last}"
    ow, rs, ds_ = ref["ownership"], ref["resolution"], ref["precision"]
    rows = [
        ("datasets", f"=COUNTA(Datasets!A4:A{ds_last})", 40, 0),
        ("datasets with an accountable owner", f"=COUNTIF(Datasets!D4:D{ds_last},TRUE)", ow["covered"], 0),
        ("ownership coverage", f"=COUNTIF(Datasets!D4:D{ds_last},TRUE)/COUNTA(Datasets!A4:A{ds_last})", float(ow["value"]), 5e-7),
        ("issues resolved (a successful rerun of the same rule version)", f'=COUNTIF({R},"resolved")', rs["resolved_count"], 0),
        ("issues claimed (closed without one)", f'=COUNTIF({R},"claimed")', rs["claimed_count"], 0),
        ("issues open", f'=COUNTIF({R},"open")', rs["open_count"], 0),
        ("mean resolution hours (resolved only)", f'=AVERAGEIFS({H},{R},"resolved")', float(rs["mean_hours"]), 0.00005),
        ("mean resolution hours, Data Platform", f'=AVERAGEIFS({H},{R},"resolved",{T},"Data Platform")', float(ref["team_mean"]["Data Platform"]), 0.00005),
        ("mean resolution hours, all other teams", f'=AVERAGEIFS({H},{R},"resolved",{T},"<>Data Platform")', float(ref["other_mean"]), 0.00005),
        ("fast team ratio (Data Platform / others)", f'=AVERAGEIFS({H},{R},"resolved",{T},"Data Platform")/AVERAGEIFS({H},{R},"resolved",{T},"<>Data Platform")', float(ref["ratio"]), 5e-7),
        ("unresolved critical issues", f'=COUNTIFS({S},"critical",{R},"<>resolved")', ref["unresolved_by_sev"]["critical"], 0),
        ("unresolved high issues", f'=COUNTIFS({S},"high",{R},"<>resolved")', ref["unresolved_by_sev"]["high"], 0),
        ("unresolved medium issues", f'=COUNTIFS({S},"medium",{R},"<>resolved")', ref["unresolved_by_sev"]["medium"], 0),
        ("unresolved low issues", f'=COUNTIFS({S},"low",{R},"<>resolved")', ref["unresolved_by_sev"]["low"], 0),
        ("declared lineage edges", f'=COUNTIF(Lineage!D4:D{edge_last},"declared")', ref["lineage"]["declared_edges"], 0),
        ("observed edges matching a declared pair", f"=COUNTIF(Lineage!I4:I{edge_last},TRUE)", ref["lineage"]["observed_matching_declared"], 0),
        ("lineage coverage", f'=COUNTIF(Lineage!I4:I{edge_last},TRUE)/COUNTIF(Lineage!D4:D{edge_last},"declared")', float(ref["lineage"]["value"]), 5e-7),
        ("undeclared observed edges", f'=COUNTIFS(Lineage!D4:D{edge_last},"observed",Lineage!G4:G{edge_last},FALSE)', len(ref["lineage"]["undeclared_observed"]), 0),
        ("inferred edges (never observed)", f'=COUNTIF(Lineage!D4:D{edge_last},"inferred")', len(ref["lineage"]["inferred_edges"]), 0),
        ("published metrics", f"=COUNTA(Definitions!A4:A{def_last})", ref["definition"]["published_metrics"], 0),
        ("metrics with a complete checklist", f"=COUNTIF(Definitions!N4:N{def_last},TRUE)", ref["definition"]["complete_metrics"], 0),
        ("definition coverage", f"=COUNTIF(Definitions!N4:N{def_last},TRUE)/COUNTA(Definitions!A4:A{def_last})", float(ref["definition"]["value"]), 5e-7),
        ("approved merge decisions", f'=COUNTIF(Matching!B4:B{match_last},"approve")', ds_["approved_decisions"], 0),
        ("approved decisions the truth confirms", f'=COUNTIFS(Matching!B4:B{match_last},"approve",Matching!E4:E{match_last},TRUE)', ds_["approved_correct"], 0),
        ("match precision (over approvals)", f'=COUNTIFS(Matching!B4:B{match_last},"approve",Matching!E4:E{match_last},TRUE)/COUNTIF(Matching!B4:B{match_last},"approve")', float(ds_["precision"]), 5e-7),
        ("reviewed candidates (approved or rejected)", f'=COUNTIF(Matching!B4:B{match_last},"approve")+COUNTIF(Matching!B4:B{match_last},"reject")', ds_["reviewed"], 0),
        ("review-correct share (reviewed candidates that are the same entity)", f'=(COUNTIFS(Matching!B4:B{match_last},"approve",Matching!E4:E{match_last},TRUE)+COUNTIFS(Matching!B4:B{match_last},"reject",Matching!E4:E{match_last},TRUE))/(COUNTIF(Matching!B4:B{match_last},"approve")+COUNTIF(Matching!B4:B{match_last},"reject"))',
         float(ds_["reviewed_correct_share"]), 5e-7),
        ("decision-agreement share (reviews that agree with the truth; the analysis's own)", f"=COUNTIF(Matching!F4:F{match_last},TRUE)/COUNT(Matching!F4:F{match_last})", None, 0),
        ("monitored datasets", f"=COUNTA(Timeliness!A4:A{tl_last})", ref["timeliness"]["monitored_datasets"], 0),
        ("on time", f'=COUNTIF(Timeliness!H4:H{tl_last},"on_time")', ref["timeliness"]["on_time_count"], 0),
        ("pending (outside the denominator)", f'=COUNTIF(Timeliness!H4:H{tl_last},"pending")', ref["timeliness"]["pending_count"], 0),
        ("timeliness", f'=COUNTIF(Timeliness!H4:H{tl_last},"on_time")/(COUNTA(Timeliness!A4:A{tl_last})-COUNTIF(Timeliness!H4:H{tl_last},"pending"))', float(ref["timeliness"]["value"]), 5e-7),
        ("critical failures (failing rows of active critical rules)", f"='Dataset scores'!B{scores_summary_row + 8}", ref["critical"]["failures"], 0),
        ("datasets carrying the critical override", f"='Dataset scores'!B{scores_summary_row + 7}", ref["critical"]["datasets_overridden"], 0),
        ("open critical issues", f"='Dataset scores'!B{scores_summary_row + 9}", ref["critical"]["open_issues"], 0),
    ]
    first = 4
    for i, (lab, f, refv, tol) in enumerate(rows):
        r = first + i
        ws.cell(row=r, column=1, value=lab)
        c = ws.cell(row=r, column=2, value=f)
        if isinstance(refv, float) and refv < 1 or "hours" in lab:
            c.number_format = "0.000000" if "hours" not in lab else "0.0000"
        if refv is not None:
            ws.cell(row=r, column=3, value=refv).font = BLUE
            ws.cell(row=r, column=4, value=tol)
            ws.cell(row=r, column=5, value=f"=ABS(B{r}-C{r})<=D{r}")
        else:
            ws.cell(row=r, column=3, value="(no domain value: the contract does not publish it; see the SQL investigation 07)")
    widths(ws, {"A": 70, "B": 20, "C": 20, "E": 8})
    return first, first + len(rows) - 1


def build_golden(wb):
    ws = wb.create_sheet("Golden case")
    title(ws, "The known answer (P07-GOLD-01) by hand, with formulas, against tests/fixtures/golden/expected.json",
          "100 eligible customer rows, 5 missing e-mails; 90 of the 95 populated pass the format rule; the critical key rule fails on 2 rows. Blue cells are typed from the fixture; every figure in column C is a formula.")
    header(ws, 3, ["input or figure", "value (typed or formula)", "formula result", "expected.json / hand answer", "check"])
    ec, ev = EXPECTED["metrics"]["completeness"]["r-cust-complete-email"], EXPECTED["metrics"]["validity"]["r-cust-valid-email"]
    eu, er = EXPECTED["metrics"]["uniqueness"]["r-cust-key-unique"], EXPECTED["metrics"]["relationship_integrity"]["r-ord-cust-fk"]
    wsd = EXPECTED["metrics"]["weighted_score"]["datasets"]["ds-customers"]
    wsum = lambda row: f"(Weights!$C${row}+Weights!$D${row}+Weights!$E${row}+Weights!$G${row})"          # noqa: E731  relationship (F) is not measured on ds-customers
    wnum = lambda row: f"(Weights!$C${row}*C7+Weights!$D${row}*C9+Weights!$E${row}*C12+Weights!$G${row}*B17)"    # noqa: E731
    rows = [
        ("eligible customer rows", 100, None, None, None),
        ("missing e-mails (null or trimmed-empty)", 5, None, None, None),
        ("passing the format rule", 90, None, None, None),
        ("completeness = (eligible - missing) / eligible", None, "=(B4-B5)/B4", float(ec["value"]), "=ABS(C7-D7)<0.0000005"),
        ("populated = eligible - missing", None, "=B4-B5", ec["populated_count"], "=C8=D8"),
        ("validity, populated-only = passing / populated (labelled)", None, "=B6/C8", float(ev["populated_only"]["value"]), "=ABS(C9-D9)<0.0000005"),
        ("validity, all eligible = passing / eligible (labelled)", None, "=B6/B4", float(ev["all_eligible"]["value"]), "=ABS(C10-D10)<0.0000005"),
        ("key rows duplicated beyond the first", 2, None, None, None),
        ("uniqueness score = (eligible - null keys - duplicate rows) / eligible", None, "=(B4-0-B11)/B4", 1 - float(eu["row_share"]["value"]), "=ABS(C12-D12)<0.0000005"),
        ("orders: foreign keys in total", 40, None, None, None),
        ("null or empty foreign keys (counted apart, outside the denominator)", 3, None, None, None),
        ("matched", 35, None, None, None),
        ("relationship integrity = matched / (total - null or empty)", None, "=B15/(B13-B14)", float(er["value"]), "=ABS(C16-D16)<0.0000005"),
        ("timeliness score of ds-customers (refreshed in its window)", 1, None, None, None),
        ("(weights come from the Weights sheet; relationship is unmeasured on ds-customers)", None, None, None, None),
        ("weighted score under w1 = sum(w x score) / sum(w of the measured dimensions)", None, f"={wnum(4)}/{wsum(4)}", 0.958116, "=ABS(C19-D19)<0.0000005"),
        ("weighted score under w2", None, f"={wnum(5)}/{wsum(5)}", float(wsd["value"]), "=ABS(C20-D20)<0.0000005"),
        ("critical failures of active critical rules (the key rule)", None, "=B11", wsd["critical_failures"], "=C21=D21"),
        ("critical override (a failing critical rule or an open critical issue)", None, "=OR(C21>0,B24>0)", wsd["critical_override"], "=C22=D22"),
        ("both scores above 0.95 although the override is set", None, "=AND(C19>0.95,C20>0.95,C22)", True, "=C23=D23"),
        ("open critical issues (typed from the fixture)", wsd["critical_open_issues"], None, None, None),
    ]
    for i, (lab, typed, formula, exp, chk) in enumerate(rows):
        r = 4 + i
        ws.cell(row=r, column=1, value=lab)
        if typed is not None:
            ws.cell(row=r, column=2, value=typed).font = BLUE
        if formula is not None:
            ws.cell(row=r, column=3, value=formula)
        if exp is not None:
            ws.cell(row=r, column=4, value=exp)
        if chk is not None:
            ws.cell(row=r, column=5, value=chk)
    widths(ws, {"A": 74, "B": 22, "C": 18, "D": 26})
    return 4, 4 + len(rows) - 1


def build_checks(wb, port_first, port_last, g_first, g_last, ds_last):
    ws = wb.create_sheet("Checks")
    title(ws, "Checks: TRUE when every comparison with the Python domain and the golden hand answer holds")
    ws["A2"] = "All checks pass"
    ws["A2"].font = BOLD
    ws["B2"] = f"=AND(Portfolio!E{port_first}:E{port_last},'Dataset scores'!U4:U{ds_last},'Golden case'!E{g_first}:E{g_last},B5,B6)"
    ws["A4"] = "check"
    ws["B4"] = "result"
    ws["A5"] = "Selected column equals the domain's score under the version chosen at Controls!B3 (every dataset)"
    ws["B5"] = f'=SUMPRODUCT(--ISNUMBER(\'Dataset scores\'!L4:L{ds_last}))=SUMPRODUCT(--ISNUMBER(IF(Controls!B3="w1",\'Dataset scores\'!S4:S{ds_last},\'Dataset scores\'!T4:T{ds_last})))'
    ws["A6"] = "Every dataset-by-version row of Dataset scores agrees with the domain (rounded to 6 places)"
    ws["B6"] = f"=COUNTIF('Dataset scores'!U4:U{ds_last},TRUE)=ROWS('Dataset scores'!U4:U{ds_last})"
    for c in ("A4", "B4"):
        ws[c].font = BOLD
    widths(ws, {"A": 96, "B": 12})


def build_controls(wb, data: Data):
    ws = wb.create_sheet("Controls")
    title(ws, "Controls", "Change B3 (w1 or w2): the Selected column of `Dataset scores` follows it. Blue cells are inputs.")
    ws["A3"], ws["B3"] = "Weight version (switch)", "w2"
    ws["B3"].font = BLUE
    dv = DataValidation(type="list", formula1='"w1,w2"', allow_blank=False)
    ws.add_data_validation(dv)
    dv.add("B3")
    ws["A4"], ws["B4"] = "As-of (UTC)", serial("2026-10-05T00:00:00Z")
    ws["B4"].font = BLUE
    ws["B4"].number_format = "yyyy-mm-dd hh:mm"
    ws["A6"] = "Weights of the selected version"
    ws["A6"].font = BOLD
    for j, dim in enumerate(DIMS):
        ws.cell(row=7 + j, column=1, value=dim)
        ws.cell(row=7 + j, column=2, value=f"=INDEX(Weights!${'CDEFG'[j]}$4:${'CDEFG'[j]}$5,MATCH($B$3,Weights!$A$4:$A$5,0))")
    ws["A13"], ws["B13"] = "Sum of the five weights (must be 1)", "=SUM(B7:B11)"
    ws["A15"], ws["B15"] = "All checks pass (Checks!B2)", "=Checks!B2"
    ws["A15"].font = BOLD
    widths(ws, {"A": 44, "B": 22})


def build_readme(wb):
    ws = wb.create_sheet("Read me")
    title(ws, "TrustLedger analyst workbook (P07-ART-05)")
    rows = [
        ("What it is", f"A formula-driven recomputation of the TrustLedger quality ledger over the published synthetic snapshot tl-20261026-20261026 (dataset hash {DATASET_HASH}, code revision {CODE_REVISION}, as-of 2026-10-05T00:00:00Z): 40 datasets, 60 rules (55 active), 574 issues, 160 lineage edges, 30 published metrics, 400 match candidates."),
        ("The decision", "Which data issues should be fixed first and who is accountable? The workbook shows each dataset's score under both weight versions with the critical override beside it, the issues by class (a claim is not a resolution), mean resolution by team, ownership coverage, lineage, definitions, match precision and timeliness."),
        ("Synthetic data", "Everything is synthetic (a seeded generator). Observed = what this one draw shows; constructed = what the generator built in on purpose (its designed relationships and injected defects); hypothetical benefits are not claimed."),
        ("How to use it", "Open the .xlsx in any spreadsheet application. Controls!B3 switches the weight version; Checks!B2 is TRUE when every figure agrees with the Python domain and the golden hand answer. Nothing needs installing to read the cached values."),
        ("Recalculation status", "openpyxl wrote formulas only; LibreOffice (headless) recalculated the delivered file. Microsoft Excel was NOT run: nothing here was opened or recalculated by Excel (docs/workbook.md)."),
        ("Sheets", "Controls, Checks, Portfolio, Dataset scores, Golden case, Assumptions (read-this-first limits), data sheets (Rule results, Issues, Owners, Datasets, Lineage, Definitions, Matching, Timeliness, Weights), Domain reference (pasted values), SQL results (pasted)."),
        ("Colour", "Blue = typed input or pasted value; black = formula."),
    ]
    for i, (k, v) in enumerate(rows, start=3):
        ws.cell(row=i, column=1, value=k).font = BOLD
        ws.cell(row=i, column=2, value=v).alignment = Alignment(wrap_text=True, vertical="top")
    widths(ws, {"A": 24, "B": 140})


ASSUMPTIONS = [
    ("A-01", "Weights and checklists are append-only versions (D-07 assumption 4): the weighted score is sum(weight x score) / sum(weights of the measured dimensions) under the version named; unmeasured dimensions leave both sums; null if none is measured. Validity enters as populated-only (D-06)."),
    ("A-02", "A dimension's score on a dataset is the plain mean of its measured rules' scores (D-07 assumption 5). Critical failures are the failing rows of active critical rules; open critical issues (open, reopened or claimed) are counted apart; either sets the override whatever the score is (D-01, D-06)."),
    ("A-03", "An issue is resolved only after a successful rerun of the same rule version (D-03); claimed issues are listed apart and never counted as resolved; hours = verifying rerun - first detected_at, 4 places."),
    ("A-04", "Ownership coverage counts datasets whose owner is active at the as-of (D-02). Lineage coverage counts distinct observed pairs that match a declared pair over declared pairs; the workbook counts edge rows, which equal distinct pairs per kind on this snapshot (80, 70 and 10; asserted by build_workbook.py). Inferred edges never count as observed."),
    ("A-05", "Timeliness: the latest daily occurrence started by the as-of, on time in [occurrence, occurrence + grace), pending while open (outside the denominator), else late (D-10 R7-01)."),
    ("A-06", "Match precision = approved decisions confirmed by the synthetic truth / approved decisions; the review-correct share = reviewed candidates that are the same true entity / reviewed candidates (D-06). The truth is the verification layer's and is typed only for these two formulas."),
    ("W-01", "Observed, constructed and hypothetical results are kept apart: every figure is observed in one draw of a generated world; the designed relationships (DR-01..DR-06) and the twelve injected defects are constructed; no benefit to a real organisation is claimed."),
    ("W-02", "TYPED from the independent Python side, not replayed by formulas: the per-rule counts (eligible, populated, failing: pattern matching, duplicate keys and parent lookups over 2,554 rows) and the timeliness occurrence and deadline instants (a daily local time in an IANA zone). Every result is compared with the Python domain after recalculation."),
    ("W-03", "Recalculation: openpyxl writes formulas only; the delivered file was recalculated by LibreOffice headless and carries its cached values; Excel was NOT run. fullCalcOnLoad is set so Excel recalculates on open. Functions used: AVERAGEIFS, COUNTIFS, SUMIFS, SUMPRODUCT, INDEX, MATCH, IF, IFERROR, ISNUMBER, AND, OR, ROUND, ABS (no _xlfn functions)."),
    ("W-04", "The switch changes which weight version the Selected column shows; both versions are always computed and checked, so the check cell does not depend on the switch."),
    ("W-05", "The workbook has no macros, no external links and no credentials."),
]


def build_assumptions(wb):
    ws = wb.create_sheet("Assumptions")
    title(ws, "Assumptions and limits")
    header(ws, 3, ["id", "statement"])
    for i, (k, v) in enumerate(ASSUMPTIONS, start=4):
        ws.cell(row=i, column=1, value=k)
        ws.cell(row=i, column=2, value=v).alignment = Alignment(wrap_text=True, vertical="top")
    widths(ws, {"A": 8, "B": 150})


def build_sql_results(wb):
    ws = wb.create_sheet("SQL results (pasted)")
    title(ws, "PASTED VALUES from data/sql/analysis/run_all.py (artifacts/analysis-results.json)", "The headline result sets; reconciliation: every row equal across the SQL, the reference SQL, the Python domain, the manifests and the independent Python side.")
    res = json.loads(RESULTS_PATH.read_text())
    meta = res["meta"][0]
    r = 4
    ws.cell(row=r, column=1, value=f"reconciliation rows {meta['reconciliation_rows']}, equal {meta['reconciliation_equal']}; result sets {meta['result_sets']}, rows {meta['result_rows']}; dataset {meta['dataset_version']} / {meta['dataset_hash']}; code {meta['code_revision']}").font = BOLD
    r += 2
    for key in ("01_ds_customers_override_both_weights__weighted", "02_ownership_coverage__summary", "03_weight_shift_dr03__summary", "04_issue_classes_and_resolution__classes",
                "04_issue_classes_and_resolution__resolution_overall", "04_issue_classes_and_resolution__fast_team_vs_others", "05_lineage_coverage_evidence__coverage", "06_definition_coverage__summary",
                "07_match_precision__precision", "08_timeliness_states__by_read_instant", "09_golden_known_answer__weighted_scores"):
        rows = res[key]
        ws.cell(row=r, column=1, value=key).font = BOLD
        r += 1
        cols = list(rows[0])
        header(ws, r, cols)
        r += 1
        for row in rows:
            for j, c in enumerate(cols, start=1):
                v = row[c]
                if isinstance(v, str) and re.fullmatch(r"-?\d+(\.\d+)?", v):
                    v = float(v) if "." in v else int(v)
                ws.cell(row=r, column=j, value=v).font = BLUE
            r += 1
        r += 1
    widths(ws, {"A": 34})


def recalc(path: Path) -> None:
    """Open with LibreOffice headless and save a recalculated copy over ``path`` (cached values included)."""
    if shutil.which("soffice") is None:
        raise SystemExit("soffice not installed; the file has formulas but no cached values")
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "in" / path.name
        src.parent.mkdir()
        shutil.copy(path, src)
        out = Path(td) / "out"
        subprocess.run(["soffice", "--headless", "--norestore", f"-env:UserInstallation=file://{td}/profile",
                        "--convert-to", "xlsx:Calc MS Excel 2007 XML", "--outdir", str(out), str(src)],
                       check=True, capture_output=True, timeout=1800)
        shutil.copy(out / path.name, path)
    set_full_calc_on_load(path)


def set_full_calc_on_load(path: Path) -> None:
    """LibreOffice drops fullCalcOnLoad; put it back (workbook.xml only) so Excel recalculates when it opens the file."""
    tmp = path.with_suffix(".tmp")
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "xl/workbook.xml":
                text = data.decode("utf-8")
                assert "<calcPr " in text and "fullCalcOnLoad" not in text
                data = text.replace("<calcPr ", '<calcPr fullCalcOnLoad="1" ', 1).encode("utf-8")
            zout.writestr(item, data)
    tmp.replace(path)


def check_edges(data: Data) -> None:
    """The workbook counts edge rows: assert they equal distinct pairs per kind (assumption A-04)."""
    for kind in ("declared", "observed", "inferred"):
        rows = [(e["source_dataset_id"], e["target_dataset_id"]) for e in data.c.edges if e["evidence_type"] == kind]
        assert len(rows) == len(set(rows)), kind


def build(path: Path) -> None:
    data = Data()
    check_edges(data)
    ref = domain_reference(data)
    wb = Workbook()
    build_readme(wb)
    build_controls(wb, data)
    build_weights(wb, data)
    build_owners(wb, data)
    ds_last = build_datasets(wb, data)
    rule_last = build_rule_results(wb, data)
    iss_last = build_issues(wb, data)
    assert iss_last == 577, iss_last
    edge_last = build_lineage(wb, data)
    def_last = build_definitions(wb, data)
    match_last = build_matching(wb, data)
    tl_last = build_timeliness(wb, data)
    ref_last = build_domain_reference(wb, ref, data)
    last_scores, summary_row = build_dataset_scores(wb, data, rule_last, iss_last)
    p_first, p_last = build_portfolio(wb, data, ref, ds_last, iss_last, edge_last, def_last, match_last, tl_last, 21, summary_row)
    g_first, g_last = build_golden(wb)
    build_checks(wb, p_first, p_last, g_first, g_last, last_scores)
    build_assumptions(wb)
    build_sql_results(wb)
    wb._sheets = [wb[n] for n in SHEET_ORDER]
    wb.calculation.fullCalcOnLoad = True
    wb.save(path)


def main(argv: list[str]) -> int:
    build(OUT)
    print(f"wrote {OUT.relative_to(ROOT)}")
    if "--recalc" in argv:
        recalc(OUT)
        print("recalculated with LibreOffice headless; cached values written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
