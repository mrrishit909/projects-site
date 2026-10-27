"""Build artifacts/productsignal-analyst-workbook.xlsx with openpyxl (P06-ART-05).

Usage:  ../../.venv/bin/python artifacts/build_workbook.py [--recalc]

Inputs: the published snapshot ``web/public/data`` (typed into the data sheets: accounts, assignments with their signup, activation, error and exposure
instants, subscriptions, runs and plans), the Python domain (``domain_reference``: the figures it publishes for each of the five logged runs, pasted for the check column
only), tests/fixtures/golden/expected.json, artifacts/analysis-results.json (data/sql/analysis/run_all.py) and web/public/data/manifest.json. openpyxl cannot calculate,
so the file it writes holds formulas only. With --recalc, LibreOffice (soffice) opens it headless and saves a recalculated copy over the same path, which then also carries
cached values. Everything on ``Metrics`` is a live formula over the data sheets and the ``Cutoff`` switch (Cutoff!B3 = an-001 .. an-005, the five logged runs): the assignments
that existed by the cutoff (D-08), maturity (signup + 7 x 24 h <= cutoff), activation (at or after max(signup, assigned_at), inside the window, event received by the cutoff),
the conversions, the absolute and relative lift, the Wilson and Newcombe intervals, the chi-square sample-ratio statistic with its p-value and verdict, exposure, the guardrail,
revenue per assigned account with its t and Welch intervals and the conclusive rule. When the sample ratio is a MISMATCH every outcome row shows the word ``withheld`` (as the site
does). What the spreadsheet does not do: canonicalise the event log (duplicates, identity, bots) or recompute the plan hash; those are typed from the domain (limits W-02, W-03).
Excel is never run.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "domain"), str(ROOT), str(ROOT / "data" / "sql" / "analysis")]

import python_side as ps  # noqa: E402
from productsignal import run_pipeline  # noqa: E402
from productsignal.metrics import Ctx, guardrail_review, revenue_difference  # noqa: E402
from productsignal.timeutil import parse_ts  # noqa: E402

OUT = ROOT / "artifacts" / "productsignal-analyst-workbook.xlsx"
RESULTS_PATH = ROOT / "artifacts" / "analysis-results.json"
MANIFEST = json.loads((ROOT / "web/public/data/manifest.json").read_text())
EXPECTED = json.loads((ROOT / "tests/fixtures/golden/expected.json").read_text())
CODE_REVISION = "fdf911a"
DATASET_HASH = "12672f9c39402517083bbbbe9164cbefe3435361dff086eb0d9e16e60f9b66f8"
NEVER = 1e15            # "no such instant", so a numeric comparison with a cutoff is always false
RUN_IDS = ("an-001", "an-002", "an-003", "an-004", "an-005")
RUN_VERSION = {"an-001": ps.V1, "an-002": ps.V1, "an-003": ps.V1, "an-004": ps.V1, "an-005": ps.V2}
SCOPES = ("control", "treatment", "combined")
HDR = PatternFill("solid", fgColor="23303A")
BLUE = Font(color="0000FF")
BOLD = Font(bold=True)
WHITE = Font(bold=True, color="FFFFFF")
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
DAY = 86400


def epoch(dt: datetime | None) -> int | None:
    return None if dt is None else int((dt - EPOCH).total_seconds())


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


# ---- the metric list (id, label, unit, tolerance kind, which scopes have a figure, outcome row, definition) --------------------------------------------------------------
METRICS = [
    ("assigned_accounts", "assigned accounts", "accounts", "count", "ct+", False, "Assignments of the selected version with assigned_at <= the cutoff (D-08): the first assignment of each account is its assignment."),
    ("mature_accounts", "mature assigned accounts", "accounts", "count", "ct+", False, "Assigned accounts whose signup (the earliest signup event received by the cutoff) + 7 x 24 h <= the cutoff."),
    ("immature_or_unobserved", "assigned, not yet mature", "accounts", "count", "ct+", False, "Assigned minus mature: counted apart and in no rate."),
    ("srm_expected", "expected assignments under the allocation", "accounts", "stat", "ct", False, "Total assigned x the plan's allocation of the arm."),
    ("srm_statistic", "sample-ratio chi-square statistic", "chi-square, df 1", "stat", "+", False, "Sum of (observed - expected)^2 / expected over the two arms."),
    ("srm_p_value", "sample-ratio p-value", "probability", "stat", "+", False, "CHIDIST(statistic, 1); the domain publishes it to six decimals."),
    ("srm_verdict", "sample-ratio verdict", "text", "text", "+", False, "INSUFFICIENT when an expected cell is below the plan's minimum, MISMATCH when p is below the plan's threshold, else OK."),
    ("exposure_rate", "exposure rate", "share", "stat", "ct", False, "Mature assigned accounts with an exposure by the cutoff / mature assigned accounts (reported beside intention to treat, never a denominator)."),
    ("activated_accounts", "activated within 7 days", "accounts", "count", "ct", True, "Mature accounts with an activation at or after max(signup, assigned_at) and before signup + 7 x 24 h, received by the cutoff (D-10)."),
    ("conversion_rate", "activation conversion (intention to treat)", "share", "stat", "ct", True, "Activated / mature assigned accounts, six decimals in the domain."),
    ("wilson_low", "Wilson 95% low", "share", "stat", "ct", True, "Wilson score interval of the arm's conversion at the plan's z."),
    ("wilson_high", "Wilson 95% high", "share", "stat", "ct", True, "As above."),
    ("absolute_lift_pp", "absolute lift (treatment - control)", "percentage points", "pp", "+", True, "(treatment conversion - control conversion) x 100."),
    ("relative_lift", "relative lift", "ratio", "stat", "+", True, "Absolute lift / control conversion; blank when the control conversion is 0."),
    ("newcombe_low", "Newcombe 95% low (difference)", "share difference", "stat", "+", True, "Newcombe hybrid score interval of treatment minus control from the two Wilson intervals."),
    ("newcombe_high", "Newcombe 95% high (difference)", "share difference", "stat", "+", True, "As above."),
    ("interval_includes_zero", "interval includes 0", "TRUE/FALSE", "text", "+", True, "low <= 0 <= high."),
    ("interim", "interim run (cutoff before planned_end)", "TRUE/FALSE", "text", "+", False, "The cutoff is before the plan's planned_end; an interim run cannot support a ship decision."),
    ("plan_frozen", "plan frozen before the first run", "TRUE/FALSE", "text", "+", False, "The plan's frozen_at is at or before the creation of the version's first logged run (typed from the plan and the run log)."),
    ("plan_hash_valid", "plan hash valid", "TRUE/FALSE", "text", "+", False, "config_hash is the sha256 of the key-sorted compact plan (typed: a spreadsheet cannot take a sha256; the domain and SQL do)."),
    ("conclusive", "conclusive (D-10)", "TRUE/FALSE", "text", "+", True, "The interval excludes 0 AND a final run AND a valid plan hash AND a plan frozen before the first run AND a sample-ratio verdict of OK."),
    ("guardrail_eligible", "guardrail: eligible accounts", "accounts", "count", "ct", True, "Mature accounts whose 7 x 24 h guardrail window is complete at the cutoff (D-10)."),
    ("guardrail_errors", "guardrail: accounts with a product_error", "accounts", "count", "ct", True, "An analysed product_error in [assigned_at, assigned_at + 7 x 24 h), received by the cutoff."),
    ("guardrail_error_rate", "guardrail: error rate", "share", "stat", "ct", True, "Errors / eligible."),
    ("guardrail_wilson_low", "guardrail: Wilson 95% low", "share", "stat", "ct", True, "Wilson interval of the error rate (intermediate for the Newcombe interval)."),
    ("guardrail_wilson_high", "guardrail: Wilson 95% high", "share", "stat", "ct", True, "As above."),
    ("guardrail_difference_pp", "guardrail: error-rate difference (treatment - control)", "percentage points", "pp", "+", True, "(treatment rate - control rate) x 100."),
    ("guardrail_newcombe_low", "guardrail: Newcombe 95% low", "share difference", "stat", "+", True, "Newcombe interval of the error-rate difference."),
    ("guardrail_newcombe_high", "guardrail: Newcombe 95% high", "share difference", "stat", "+", True, "As above."),
    ("guardrail_verdict", "guardrail verdict (C09)", "text", "text", "+", True, "HARMFUL when the whole interval is above 0, INSUFFICIENT when an arm has no eligible account, else OK."),
    ("revenue_total", "revenue (USD)", "USD", "money", "ct", True, "Subscriptions active or ended, starts_at inside the plan's revenue window and <= the cutoff, of the mature assigned accounts."),
    ("revenue_per_assigned_account", "revenue per assigned account (USD)", "USD per account", "money", "ct", True, "Revenue / mature assigned accounts, zeros included."),
    ("revenue_variance", "revenue: sample variance", "USD squared", "money", "ct", True, "Sum of squared deviations of the account-level revenue / (n - 1)."),
    ("revenue_t_low", "revenue: t interval low", "USD", "money", "ct", True, "mean - t(0.975, n - 1) x sqrt(variance / n)."),
    ("revenue_t_high", "revenue: t interval high", "USD", "money", "ct", True, "mean + t(0.975, n - 1) x sqrt(variance / n)."),
    ("revenue_difference", "revenue difference of means (treatment - control)", "USD", "money", "+", True, "Treatment mean - control mean."),
    ("welch_df", "Welch degrees of freedom (rounded down)", "df", "count", "+", True, "Welch-Satterthwaite, rounded down so the interval is never narrower than the exact t."),
    ("welch_low", "revenue difference: Welch 95% low", "USD", "money", "+", True, "difference - t(0.975, df) x sqrt(se^2)."),
    ("welch_high", "revenue difference: Welch 95% high", "USD", "money", "+", True, "As above."),
]
TOL = {"count": 0, "stat": 0.0000005, "pp": 0.005, "money": 0.005, "text": 0}
LETTER = {"control": "D", "treatment": "E", "combined": "F"}


# ---- the data sheets -----------------------------------------------------------------------------------------------------------------------------------------------------
def put(ws, rows: list[list], first_row: int = 2, blue: bool = True):
    for r, row in enumerate(rows, start=first_row):
        for c, v in enumerate(row, start=1):
            cell = ws.cell(row=r, column=c, value=v)
            if blue and v is not None and not (isinstance(v, str) and v.startswith("=")):
                cell.font = BLUE


class Data:
    """The typed inputs derived once from the snapshot (events through the independent Python side; no domain code)."""

    def __init__(self, ctx: ps.Ctx) -> None:
        self.ctx = ctx
        log = ctx.log["as-of"]
        first_act: dict[str, tuple] = {}
        acts: dict[str, list] = {}
        errs: dict[str, list] = {}
        for e in log:
            if e.cls != "analysed" or e.acct is None:
                continue
            if e.name == "activated":
                acts.setdefault(e.acct, []).append((e.at, e.recv))
            elif e.name == "product_error":
                errs.setdefault(e.acct, []).append((e.at, e.recv))
        self.acts, self.errs = acts, errs
        assert all(len(v) == 1 for v in acts.values()), "an account with several canonical activations: the workbook's single activation column would be wrong"
        sg_recv: dict[str, datetime] = {}
        for e in log:
            if e.cls == "analysed" and e.name == "signup" and e.acct is not None and e.at == ctx.signup["as-of"].get(e.acct):
                sg_recv[e.acct] = min(e.recv, sg_recv.get(e.acct, e.recv))
        self.sg_recv = sg_recv
        self.exposure = {x["assignment_id"]: ps.ts(x["exposed_at"]) for x in ctx.rows["exposures"]}

    def accounts(self):
        out = []
        for a in self.ctx.rows["accounts"]:
            aid = a["account_id"]
            s = self.ctx.signup["as-of"].get(aid)
            act = self.acts.get(aid)
            out.append([aid, a["plan"], a["segment"], a["timezone"], 1 if a["internal"] else 0, NEVER if s is None else epoch(s), NEVER if act is None else epoch(act[0][0])])
        return out

    def assignments(self):
        out = []
        for xv in (ps.V1, ps.V2):
            for a in self.ctx.asg[xv]:
                aid, unit = a["assignment_id"], a["unit_id"]
                at = ps.ts(a["assigned_at"])
                s = self.ctx.signup["as-of"].get(unit)
                act = self.acts.get(unit)
                win = [(t, r) for t, r in self.errs.get(unit, ()) if at <= t < at + 7 * ps.timedelta(days=1)]
                ex = self.exposure.get(aid)
                out.append([aid, xv, unit, a["variant"], epoch(at), NEVER if s is None else epoch(s), NEVER if s is None else epoch(self.sg_recv[unit]),
                            NEVER if act is None else epoch(act[0][0]), NEVER if act is None else epoch(act[0][1]), NEVER if ex is None else epoch(ex),
                            NEVER if not win else epoch(min(r for _, r in win))])
        return out


ASG_COLS = ["assignment_id", "version", "unit_id", "variant", "assigned_epoch", "signup_epoch", "signup_received_epoch", "activation_epoch", "activation_received_epoch",
            "exposed_epoch", "first_error_received_epoch (inside the 7-day guardrail window)", "in_read", "signup_known", "mature", "activated", "exposed", "guardrail_eligible", "errored", "revenue_usd"]
A = {n: get_column_letter(i + 1) for i, n in enumerate(["id", "version", "unit", "variant", "assigned", "signup", "signup_recv", "act", "act_recv", "exposed_at", "err_recv",
                                                          "in_read", "known", "mature", "activated", "exposed", "g_elig", "errored", "revenue"])}
N_ASG = 554
LAST = N_ASG + 1
SUBS_LAST = 208


def arng(name: str) -> str:
    return f"Assignments!${A[name]}$2:${A[name]}${LAST}"


def build_assignments(wb, data: Data):
    ws = wb.create_sheet("Assignments")
    title(ws, "Assignments (554 rows, typed inputs in blue, formulas in black)",
          "One row per assignment of either version. The blue instants are epoch seconds (UTC) from the published snapshot; NEVER (1E15) means no such event. The black columns are the cutoff-dependent flags of the selected run (Cutoff!B3).")
    # header goes on row 1 for compact ranges: move the title to a comment cell far right
    ws["A1"] = None
    ws["A1"].font = Font()
    header(ws, 1, ASG_COLS)
    rows = data.assignments()
    assert len(rows) == N_ASG
    put(ws, rows)
    for r in range(2, LAST + 1):
        k = {n: f"{A[n]}{r}" for n in A}
        ws[k["in_read"]] = f"=IF(AND({k['version']}=Cutoff!$B$12,{k['assigned']}<=Cutoff!$B$10),1,0)"
        ws[k["known"]] = f"=IF(AND({k['in_read']}=1,{k['signup']}<1E+15,{k['signup_recv']}<=Cutoff!$B$10),1,0)"
        ws[k["mature"]] = f"=IF(AND({k['known']}=1,{k['signup']}+Cutoff!$B$16<=Cutoff!$B$10),1,0)"
        ws[k["activated"]] = (f"=IF({k['mature']}=1,IF(AND({k['act']}<1E+15,{k['act']}>=MAX({k['signup']},{k['assigned']}),{k['act']}<{k['signup']}+Cutoff!$B$16,"
                              f"{k['act_recv']}<=Cutoff!$B$10),1,0),0)")
        ws[k["exposed"]] = f"=IF(AND({k['in_read']}=1,{k['exposed_at']}<=Cutoff!$B$10),1,0)"
        ws[k["g_elig"]] = f"=IF(AND({k['mature']}=1,{k['assigned']}+Cutoff!$B$17<=Cutoff!$B$10),1,0)"
        ws[k["errored"]] = f"=IF({k['g_elig']}=1,IF({k['err_recv']}<=Cutoff!$B$10,1,0),0)"
        ws[k["revenue"]] = (f"=IF({k['mature']}=1,SUMIFS(Subscriptions!$D$2:$D${SUBS_LAST},Subscriptions!$A$2:$A${SUBS_LAST},{k['unit']},Subscriptions!$E$2:$E${SUBS_LAST},1,"
                            f"Subscriptions!$B$2:$B${SUBS_LAST},\">=\"&Cutoff!$B$24,Subscriptions!$B$2:$B${SUBS_LAST},\"<\"&Cutoff!$B$25,Subscriptions!$B$2:$B${SUBS_LAST},\"<=\"&Cutoff!$B$10),0)")
    widths(ws, {"A": 14, "B": 10, "C": 11, "D": 11, "E": 14, "F": 14, "G": 14, "H": 14, "I": 14, "J": 14, "K": 22})
    ws.freeze_panes = "E2"


def build_subscriptions(wb, ctx: ps.Ctx):
    ws = wb.create_sheet("Subscriptions")
    header(ws, 1, ["account_id", "starts_epoch", "status", "amount_usd", "carries_revenue (active or ended = 1)", "subscription_id"])
    rows = [[s["account_id"], epoch(ps.ts(s["starts_at"])), s["status"], float(s["amount_usd"]), None, s["subscription_id"]] for s in ctx.rows["subscriptions"]]
    assert len(rows) == SUBS_LAST - 1
    put(ws, rows)
    for r in range(2, SUBS_LAST + 1):
        ws[f"E{r}"] = f'=IF(OR(C{r}="active",C{r}="ended"),1,0)'
    widths(ws, {"A": 12, "B": 14, "C": 10, "D": 12, "E": 20, "F": 16})


def build_accounts(wb, data: Data):
    ws = wb.create_sheet("Accounts")
    header(ws, 1, ["account_id", "plan", "segment", "timezone", "is_internal", "signup_epoch (as-of)", "activation_epoch (as-of)", "mature_7d at the as-of", "activated_7d at the as-of"])
    rows = data.accounts()
    put(ws, rows)
    for r in range(2, len(rows) + 2):
        ws[f"H{r}"] = f"=IF(AND(E{r}=0,F{r}<1E+15,F{r}+Cutoff!$B$16<=Cutoff!$D$13),1,0)"
        ws[f"I{r}"] = f"=IF(AND(H{r}=1,G{r}<1E+15,G{r}>=F{r},G{r}<F{r}+Cutoff!$B$16),1,0)"
    widths(ws, {"A": 12, "B": 10, "C": 12, "D": 20, "E": 10, "F": 18, "G": 18, "H": 14, "I": 14})
    return len(rows) + 1


def build_runs_and_plans(wb, ctx: ps.Ctx):
    ws = wb.create_sheet("Runs")
    title(ws, "The five logged analysis runs (typed from analysis_runs.json)")
    header(ws, 4, ["run id", "experiment version", "cutoff (UTC)", "cutoff epoch", "created_at epoch", "created_at (UTC)"])
    for r, row in enumerate(sorted(ctx.rows["analysis_runs"], key=lambda x: x["cutoff_at"]), start=5):
        for c, v in enumerate([row["analysis_id"], row["experiment_version_id"], row["cutoff_at"], epoch(ps.ts(row["cutoff_at"])), epoch(ps.ts(row["created_at"])), row["created_at"]], start=1):
            ws.cell(row=r, column=c, value=v).font = BLUE
    widths(ws, {"A": 10, "B": 18, "C": 24, "D": 14, "E": 16, "F": 24})
    wp = wb.create_sheet("Plans")
    title(wp, "The two frozen analysis plans (typed from manifest.json analysis_plans)")
    header(wp, 4, ["experiment version", "planned_end epoch", "frozen_at epoch", "first logged run created epoch", "allocation control", "allocation treatment", "z", "confidence",
                   "SRM p threshold", "SRM min expected cell", "activation window (days)", "guardrail window (days)", "revenue from epoch", "revenue to epoch", "config_hash", "plan hash valid"])
    runs = ctx.rows["analysis_runs"]
    for r, xv in enumerate((ps.V1, ps.V2), start=5):
        p = ctx.plans[xv]
        pf = ps.plan_facts(ctx, xv)
        first = min(epoch(ps.ts(x["created_at"])) for x in runs if x["experiment_version_id"] == xv)
        vals = [xv, epoch(pf["planned_end"]), epoch(pf["frozen_at"]), first, float(p["allocation"]["control"]), float(p["allocation"]["treatment"]), float(p["z"]), float(p["confidence"]),
                float(p["srm"]["p_threshold"]), float(p["srm"]["min_expected_cell"]), p["activation_window_days"], p["guardrail"]["window_days"], epoch(pf["rev_from"]), epoch(pf["rev_to"]),
                p["config_hash"], pf["hash_ok"]]
        for c, v in enumerate(vals, start=1):
            wp.cell(row=r, column=c, value=v).font = BLUE
    wp["A8"] = "Plan hash valid is typed: the sha256 of the key-sorted compact plan was recomputed by data/sql/analysis/python_side.py, the Python domain and the SQL reference; a spreadsheet has no sha256 (limit W-03)."
    widths(wp, {"A": 18, "B": 16, "C": 16, "D": 20, "O": 66})


def build_readme(wb):
    ws = wb.active
    ws.title = "Read me"
    title(ws, "ProductSignal analyst workbook (P06-ART-05)",
          "SYNTHETIC DATA: every account, user and event is generated (seed 20261026); nothing describes a real product, customer or measurement.")
    rows = [
        ("What it is", "A formula-driven workbook over the published synthetic snapshot of ProductSignal (600 accounts, 554 experiment assignments in two versions of one onboarding experiment). It recomputes the experiment read of any of the five logged analysis runs with live formulas: conversions, absolute and relative lift, Wilson and Newcombe intervals, the chi-square sample-ratio statistic, exposure, the guardrail, revenue per assigned account and the conclusive rule."),
        ("The decision it supports", "Should an onboarding change ship, stop, or receive more investigation? Metrics shows, for the selected run, what the evidence was at that cutoff, and the check column compares every figure with the Python domain's value for the same run."),
        ("How to read it without installing anything", "Open the .xlsx in any spreadsheet application, or read docs/workbook.md (it lists every sheet and the checked values). The delivered file already carries values calculated by LibreOffice for run an-004 (the final run of v1)."),
        ("How to use the switch", "Cutoff!B3 takes an-001, an-002, an-003, an-004 or an-005 (a list): the four v1 runs (an-001, an-002, an-003 are interim, an-004 is the final run at planned_end) and v2's one run (an-005). Every figure on Metrics follows it, including which assignments existed (the cutoff rule D-08)."),
        ("The sample ratio comes first", "When the sample-ratio verdict is MISMATCH (v2, an-005) every outcome row of Metrics shows the word withheld, as the site does: no lift of v2 is shown or decided on. The domain's figures are not pasted for those rows."),
        ("Observed, constructed, hypothetical", "Everything here is OBSERVED in one draw of a synthetic world. The generator built the treatment effect (a designed +8.00 percentage points), a designed sample-ratio mismatch in v2 and an injected instrumentation gap (INJ-10) that reaches the published v1 lift: published +9.50, drawn +11.50, +9.96 excluding the 11 gap accounts. Four generator choices were made after looking at earlier drafts (docs/executive-memo.md). Nothing is a benefit to a real product. The v1 result is conclusive by a hair: the lower bound of the Newcombe interval is +0.000812."),
        ("Inputs (blue) and formulas (black)", "Blue cells are typed inputs: the accounts, the assignments with their signup, activation, error and exposure instants (epoch seconds), the subscriptions, the runs and the plans. Black cells are formulas."),
        ("What the formulas do NOT do", "They do not canonicalise the event log (received by the cutoff, deduplicated, identity forward only, bots and internal accounts excluded) or take the plan's sha256: the instants of the first signup, the activation and the first error inside the guardrail window are typed from the independent Python side. A signup whose earliest event arrives late while a later one arrives earlier would be read differently; none exists in this snapshot at the five runs (limit W-02, checked at build time)."),
        ("Provenance", f"Dataset hash {DATASET_HASH} (generator, seed 20261026, dataset ps-20261026-20261026), contract v1, code revision {CODE_REVISION}. Built by artifacts/build_workbook.py with openpyxl 3.1.5."),
        ("Recalculation status", "openpyxl wrote formulas only; LibreOffice (headless) recalculated the delivered file. Microsoft Excel was NOT run: nothing here was opened or recalculated by Excel (docs/workbook.md)."),
    ]
    for i, (k, v) in enumerate(rows, start=4):
        ws.cell(row=i, column=1, value=k).font = BOLD
        c = ws.cell(row=i, column=2, value=v)
        c.alignment = Alignment(wrap_text=True, vertical="top")
    widths(ws, {"A": 38, "B": 150})


def build_cutoff(wb, ctx: ps.Ctx):
    ws = wb.create_sheet("Cutoff")
    title(ws, "The cutoff switch", "Type an-001 .. an-005 in B3 (a list). Every figure on Metrics and every flag column of Assignments follows it.")
    ws["A3"], ws["B3"] = "selected run", "an-004"
    ws["B3"].font = BLUE
    dv = DataValidation(type="list", formula1='"an-001,an-002,an-003,an-004,an-005"', allow_blank=False)
    ws.add_data_validation(dv)
    dv.add("B3")
    lab = {"A10": "selected cutoff (epoch seconds, UTC)", "A11": "selected position in Runs", "A12": "selected experiment version", "A13": "selected planned_end (epoch)",
           "A14": "selected run is interim (cutoff before planned_end)", "A16": "activation window (seconds)", "A17": "guardrail window (seconds)", "A18": "z of the plan", "A19": "alpha (1 - confidence)",
           "A20": "allocation control", "A21": "allocation treatment", "A22": "SRM p threshold", "A23": "SRM minimum expected cell", "A24": "revenue window from (epoch)", "A25": "revenue window to (epoch)",
           "A26": "plan frozen before the first logged run", "A27": "plan hash valid (typed)", "C13": "as-of epoch (2026-10-05T00:00:00Z), used by Accounts", "D13": epoch(ps.ts(ps.ASOF))}
    for k, v in lab.items():
        ws[k] = v
    ws["D13"].font = BLUE
    ws["B11"] = "=MATCH($B$3,Runs!$A$5:$A$9,0)"
    ws["B10"] = "=INDEX(Runs!$D$5:$D$9,B11)"
    ws["B12"] = "=INDEX(Runs!$B$5:$B$9,B11)"
    pl = lambda col: f"INDEX(Plans!${col}$5:${col}$6,MATCH($B$12,Plans!$A$5:$A$6,0))"      # noqa: E731
    ws["B13"] = "=" + pl("B")
    ws["B14"] = "=B10<B13"
    ws["B16"] = f"={pl('K')}*86400"
    ws["B17"] = f"={pl('L')}*86400"
    ws["B18"] = "=" + pl("G")
    ws["B19"] = f"=1-{pl('H')}"
    ws["B20"], ws["B21"], ws["B22"], ws["B23"] = "=" + pl("E"), "=" + pl("F"), "=" + pl("I"), "=" + pl("J")
    ws["B24"], ws["B25"] = "=" + pl("M"), "=" + pl("N")
    ws["B26"] = f"={pl('C')}<={pl('D')}"
    ws["B27"] = "=" + pl("P")
    widths(ws, {"A": 52, "B": 24, "C": 46, "D": 16})


def f_wilson(x: str, n: str, sign: int) -> str:
    z = "Cutoff!$B$18"
    p = f"({x}/{n})"
    return f"=IF({n}=0,\"\",({p}+{z}^2/(2*{n}){'-' if sign < 0 else '+'}{z}*SQRT({p}*(1-{p})/{n}+{z}^2/(4*{n}^2)))/(1+{z}^2/{n}))"


def build_metrics(wb, dref_rows, n_ref_cols):
    ws = wb.create_sheet("Metrics", 1)
    title(ws, "Experiment read for the selected run (live formulas)",
          "Run: Cutoff!B3. Control, treatment and a combined/difference column. 'check' is TRUE when every figure of the row equals the Python domain's value for the same run within the tolerance (pasted on 'Domain reference'; for a sample-ratio MISMATCH the reference is the word withheld).")
    ws["A3"], ws["B3"] = "selected run", "=Cutoff!B3"
    ws["D3"], ws["E3"] = "all checks TRUE", None
    ws["A4"], ws["B4"] = "outcomes withheld (sample ratio is a MISMATCH)", None
    header(ws, 5, ["metric id", "metric", "unit", "control", "treatment", "combined / difference", "definition", "tolerance", "check"])
    rows = {mid: 6 + i for i, (mid, *_r) in enumerate(METRICS)}
    last_row = 5 + len(METRICS)
    W = "$B$4"

    def ref(mid: str, scope: str) -> str:
        return f"${LETTER[scope]}${rows[mid]}"

    def cnt(arm: str, flag: str) -> str:
        return f"COUNTIFS({arng('variant')},\"{arm}\",{arng(flag)},1)"

    def formula(mid: str, scope: str) -> str | None:
        arm = scope if scope in ("control", "treatment") else None
        c, t = (lambda m: ref(m, "control")), (lambda m: ref(m, "treatment"))
        X = lambda body: f'=IF({W},"withheld",{body})'      # noqa: E731
        if mid == "assigned_accounts":
            return f"=SUMIFS({arng('in_read')},{arng('variant')},\"{arm}\")" if arm else f"={c(mid)}+{t(mid)}"
        if mid == "mature_accounts":
            return "=" + cnt(arm, "mature") if arm else f"={c(mid)}+{t(mid)}"
        if mid == "immature_or_unobserved":
            return f"={ref('assigned_accounts', scope)}-{ref('mature_accounts', scope)}"
        if mid == "srm_expected":
            return f"={ref('assigned_accounts', 'combined')}*Cutoff!$B${20 if arm == 'control' else 21}"
        if mid == "srm_statistic":
            return (f"=IF({ref('assigned_accounts', 'combined')}=0,\"\",({c('assigned_accounts')}-{c('srm_expected')})^2/{c('srm_expected')}+"
                    f"({t('assigned_accounts')}-{t('srm_expected')})^2/{t('srm_expected')})")
        if mid == "srm_p_value":
            return f"=IF({ref('srm_statistic', 'combined')}=\"\",\"\",CHIDIST({ref('srm_statistic', 'combined')},1))"
        if mid == "srm_verdict":
            return (f"=IF({ref('assigned_accounts', 'combined')}=0,\"INSUFFICIENT\",IF(MIN({c('srm_expected')},{t('srm_expected')})<Cutoff!$B$23,\"INSUFFICIENT\","
                    f"IF({ref('srm_p_value', 'combined')}<Cutoff!$B$22,\"MISMATCH\",\"OK\")))")
        if mid == "exposure_rate":
            return f"=IF({ref('mature_accounts', scope)}=0,\"\",COUNTIFS({arng('variant')},\"{arm}\",{arng('mature')},1,{arng('exposed')},1)/{ref('mature_accounts', scope)})"
        if mid == "activated_accounts":
            return X(cnt(arm, "activated"))
        if mid == "conversion_rate":
            return X(f"IF({ref('mature_accounts', scope)}=0,\"\",{ref('activated_accounts', scope)}/{ref('mature_accounts', scope)})")
        if mid in ("wilson_low", "wilson_high"):
            return X(f_wilson(ref("activated_accounts", scope), ref("mature_accounts", scope), -1 if mid == "wilson_low" else 1)[1:])
        both = f"OR({c('mature_accounts')}=0,{t('mature_accounts')}=0)"
        if mid == "absolute_lift_pp":
            return X(f"IF({both},\"\",({t('conversion_rate')}-{c('conversion_rate')})*100)")
        if mid == "relative_lift":
            return X(f"IF({both},\"\",IF({c('conversion_rate')}=0,\"\",({t('conversion_rate')}-{c('conversion_rate')})/{c('conversion_rate')}))")
        if mid == "newcombe_low":
            return X(f"IF({both},\"\",({t('conversion_rate')}-{c('conversion_rate')})-SQRT(({t('conversion_rate')}-{t('wilson_low')})^2+({c('wilson_high')}-{c('conversion_rate')})^2))")
        if mid == "newcombe_high":
            return X(f"IF({both},\"\",({t('conversion_rate')}-{c('conversion_rate')})+SQRT(({t('wilson_high')}-{t('conversion_rate')})^2+({c('conversion_rate')}-{c('wilson_low')})^2))")
        if mid == "interval_includes_zero":
            return X(f"IF({ref('newcombe_low', 'combined')}=\"\",TRUE,AND({ref('newcombe_low', 'combined')}<=0,{ref('newcombe_high', 'combined')}>=0))")
        if mid == "interim":
            return "=Cutoff!$B$14"
        if mid == "plan_frozen":
            return "=Cutoff!$B$26"
        if mid == "plan_hash_valid":
            return "=Cutoff!$B$27"
        if mid == "conclusive":
            return X(f"AND(NOT({ref('interval_includes_zero', 'combined')}),NOT({ref('interim', 'combined')}),{ref('plan_hash_valid', 'combined')},{ref('plan_frozen', 'combined')},{ref('srm_verdict', 'combined')}=\"OK\")")
        if mid == "guardrail_eligible":
            return X(cnt(arm, "g_elig"))
        if mid == "guardrail_errors":
            return X(cnt(arm, "errored"))
        if mid == "guardrail_error_rate":
            return X(f"IF({ref('guardrail_eligible', scope)}=0,\"\",{ref('guardrail_errors', scope)}/{ref('guardrail_eligible', scope)})")
        if mid in ("guardrail_wilson_low", "guardrail_wilson_high"):
            return X(f_wilson(ref("guardrail_errors", scope), ref("guardrail_eligible", scope), -1 if mid.endswith("low") else 1)[1:])
        gb = f"OR({c('guardrail_eligible')}=0,{t('guardrail_eligible')}=0)"
        if mid == "guardrail_difference_pp":
            return X(f"IF({gb},\"\",({t('guardrail_error_rate')}-{c('guardrail_error_rate')})*100)")
        if mid == "guardrail_newcombe_low":
            return X(f"IF({gb},\"\",({t('guardrail_error_rate')}-{c('guardrail_error_rate')})-SQRT(({t('guardrail_error_rate')}-{t('guardrail_wilson_low')})^2+({c('guardrail_wilson_high')}-{c('guardrail_error_rate')})^2))")
        if mid == "guardrail_newcombe_high":
            return X(f"IF({gb},\"\",({t('guardrail_error_rate')}-{c('guardrail_error_rate')})+SQRT(({t('guardrail_wilson_high')}-{t('guardrail_error_rate')})^2+({c('guardrail_error_rate')}-{c('guardrail_wilson_low')})^2))")
        if mid == "guardrail_verdict":
            return X(f"IF({gb},\"INSUFFICIENT\",IF({ref('guardrail_newcombe_low', 'combined')}>0,\"HARMFUL\",\"OK\"))")
        if mid == "revenue_total":
            return X(f"SUMIFS({arng('revenue')},{arng('variant')},\"{arm}\")")
        if mid == "revenue_per_assigned_account":
            return X(f"IF({ref('mature_accounts', scope)}=0,\"\",{ref('revenue_total', scope)}/{ref('mature_accounts', scope)})")
        if mid == "revenue_variance":
            return X(f"IF({ref('mature_accounts', scope)}<2,\"\",SUMPRODUCT(({arng('variant')}=\"{arm}\")*({arng('mature')}=1)*({arng('revenue')}-{ref('revenue_per_assigned_account', scope)})^2)/({ref('mature_accounts', scope)}-1))")
        if mid in ("revenue_t_low", "revenue_t_high"):
            sgn = "-" if mid.endswith("low") else "+"
            return X(f"IF({ref('mature_accounts', scope)}<2,\"\",{ref('revenue_per_assigned_account', scope)}{sgn}TINV(Cutoff!$B$19,{ref('mature_accounts', scope)}-1)*SQRT({ref('revenue_variance', scope)}/{ref('mature_accounts', scope)}))")
        rb = f"OR({c('mature_accounts')}<2,{t('mature_accounts')}<2)"
        se2 = f"({t('revenue_variance')}/{t('mature_accounts')}+{c('revenue_variance')}/{c('mature_accounts')})"
        if mid == "revenue_difference":
            return X(f"IF({rb},\"\",{t('revenue_per_assigned_account')}-{c('revenue_per_assigned_account')})")
        if mid == "welch_df":
            return X(f"IF({rb},\"\",INT({se2}^2/(({t('revenue_variance')}/{t('mature_accounts')})^2/({t('mature_accounts')}-1)+({c('revenue_variance')}/{c('mature_accounts')})^2/({c('mature_accounts')}-1))))")
        if mid in ("welch_low", "welch_high"):
            sgn = "-" if mid.endswith("low") else "+"
            return X(f"IF({rb},\"\",{ref('revenue_difference', 'combined')}{sgn}TINV(Cutoff!$B$19,{ref('welch_df', 'combined')})*SQRT({se2}))")
        raise KeyError(mid)

    ref_z = get_column_letter(1 + n_ref_cols)
    fmts = {"count": "0", "stat": "0.000000", "pp": "0.00", "money": "#,##0.00", "text": "General"}
    for mid, label, unit, kind, scopes, outcome, definition in METRICS:
        r = rows[mid]
        ws.cell(row=r, column=1, value=mid)
        ws.cell(row=r, column=2, value=label)
        ws.cell(row=r, column=3, value=unit)
        ws.cell(row=r, column=7, value=definition).alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(row=r, column=8, value=TOL[kind]).font = BLUE
        checks = []
        for scope in SCOPES:
            if not (scope == "control" and "c" in scopes) and not (scope == "treatment" and "t" in scopes) and not (scope == "combined" and "+" in scopes):
                continue
            cell = f"{LETTER[scope]}{r}"
            ws[cell] = formula(mid, scope)
            ws[cell].number_format = fmts[kind]
            col = f"MATCH(Cutoff!$B$3&\"|{scope}\",'Domain reference'!$B$4:${ref_z}$4,0)"
            rf = f"INDEX('Domain reference'!$B${dref_rows[mid]}:${ref_z}${dref_rows[mid]},{col})"
            checks.append(f"IF(ISNUMBER({rf}),IF(ISNUMBER({cell}),ABS({cell}-{rf})<=$H{r}+0.0000000001,FALSE),IF(ISBLANK({rf}),{cell}=\"\",{cell}={rf}))")
        ws.cell(row=r, column=9, value="=AND(" + ",".join(checks) + ")")
    ws["B4"] = f"=F{rows['srm_verdict']}=\"MISMATCH\""
    ws["E3"] = f"=AND(I6:I{last_row})"
    ws["E3"].font = BOLD
    widths(ws, {"A": 30, "B": 48, "C": 18, "D": 16, "E": 16, "F": 22, "G": 80, "H": 10, "I": 8})
    ws.freeze_panes = "D6"
    return rows


# ---- the domain's figures for each run (pasted; read only by the check column and the tests) ------------------------------------------------------------------------
def fnum(s):
    return None if s is None else float(s)


def domain_reference(ctx: ps.Ctx) -> dict[tuple[str, str], dict[str, object]]:
    """For each (run id, scope) the figure of every metric id as the Python domain publishes it ('withheld' for the outcome rows of a sample-ratio MISMATCH); the derived intermediates
    the domain does not publish (the guardrail's Wilson intervals, the revenue variance) come from the independent python_side code."""
    inputs = {"contract_version": 1, "as_of": MANIFEST["as_of"], "cutoff": MANIFEST["cutoff"], "analysis_plan": MANIFEST["analysis_plans"][ps.V1],
              "metric_windows": MANIFEST["metric_windows"], **ctx.rows}
    out: dict[tuple[str, str], dict[str, object]] = {}
    for run in RUN_IDS:
        xv = RUN_VERSION[run]
        res = run_pipeline({**inputs, "analysis_plan": MANIFEST["analysis_plans"][xv]}, cutoff=ps.RUNS[run], experiment_version_id=xv, run_id=run)
        ex = res.metrics["experiment"]
        plan = res.population.plans[xv]
        cx = Ctx(res.population, parse_ts(ps.RUNS[run]), res.computation.canon)
        gr = guardrail_review(ex, plan)
        rd = revenue_difference(cx, plan)
        zc = ps.Decimal(plan.z)
        withheld = ex["srm"]["verdict"] == "MISMATCH"
        W = lambda v: "withheld" if withheld else v      # noqa: E731
        d = {s: {} for s in SCOPES}
        for arm in ("control", "treatment"):
            v = ex["primary"]["variants"][arm]
            g = ex["guardrail"]["by_variant"][arm]
            rv = ex["revenue_per_assigned_account"]["by_variant"][arm]
            n = v["mature_units"]
            d[arm].update({"assigned_accounts": v["assigned"], "mature_accounts": n, "immature_or_unobserved": v["assigned"] - n,
                           "srm_expected": fnum(ex["srm"]["expected"][arm]), "exposure_rate": fnum(ex["exposure"]["by_variant"][arm]["rate"]),
                           "activated_accounts": W(v["activated"]), "conversion_rate": W(fnum(v["conversion"])),
                           "wilson_low": W(fnum(v["wilson_95"]["low"]) if v["wilson_95"] else None), "wilson_high": W(fnum(v["wilson_95"]["high"]) if v["wilson_95"] else None),
                           "guardrail_eligible": W(g["eligible_units"]), "guardrail_errors": W(g["units_with_error"]), "guardrail_error_rate": W(fnum(g["error_rate"])),
                           "revenue_total": W(fnum(rv["total"])), "revenue_per_assigned_account": W(fnum(rv["mean"])),
                           "revenue_t_low": W(fnum(rv["interval"]["low"]) if rv["interval"] else None), "revenue_t_high": W(fnum(rv["interval"]["high"]) if rv["interval"] else None)})
            if g["eligible_units"]:
                _, wl, wh = ps.wilson(g["units_with_error"], g["eligible_units"], zc)
                d[arm].update({"guardrail_wilson_low": W(float(ps.rnd(wl, 6))), "guardrail_wilson_high": W(float(ps.rnd(wh, 6)))})
            else:
                d[arm].update({"guardrail_wilson_low": W(None), "guardrail_wilson_high": W(None)})
            rows_rev = ps._revenue(ctx, run)[arm]
            d[arm]["revenue_variance"] = W(float(ps.rnd(ps._stats(rows_rev)[2], 2)) if len(rows_rev) > 1 else None)
        p = ex["primary"]
        d["combined"].update({"assigned_accounts": ex["assigned_units"], "mature_accounts": ex["mature_units"], "immature_or_unobserved": ex["immature_or_unobserved_excluded"],
                              "srm_statistic": fnum(ex["srm"]["statistic"]), "srm_p_value": fnum(ex["srm"]["p_value"]), "srm_verdict": ex["srm"]["verdict"],
                              "absolute_lift_pp": W(fnum(p["absolute_lift_pp"])), "relative_lift": W(fnum(p["relative_lift"])),
                              "newcombe_low": W(fnum(p["interval"]["low"]) if p["interval"] else None), "newcombe_high": W(fnum(p["interval"]["high"]) if p["interval"] else None),
                              "interval_includes_zero": W(p["interval"]["includes_zero"] if p["interval"] else True), "interim": ex["run"]["interim"],
                              "plan_frozen": ex["run"]["plan_frozen"], "plan_hash_valid": plan.hash_valid, "conclusive": W(p["conclusive"]),
                              "guardrail_difference_pp": W(fnum(gr["difference_pp"])), "guardrail_newcombe_low": W(fnum(gr["interval"]["low"]) if gr["interval"] else None),
                              "guardrail_newcombe_high": W(fnum(gr["interval"]["high"]) if gr["interval"] else None), "guardrail_verdict": W(gr["verdict"]),
                              "revenue_difference": W(fnum(rd["difference"])), "welch_df": W(rd["interval"]["df"] if rd["interval"] else None),
                              "welch_low": W(fnum(rd["interval"]["low"]) if rd["interval"] else None), "welch_high": W(fnum(rd["interval"]["high"]) if rd["interval"] else None)})
        for s in SCOPES:
            out[(run, s)] = d[s]
    return out


def build_domain_reference(wb, ref):
    ws = wb.create_sheet("Domain reference")
    title(ws, "PASTED VALUES from the Python domain (run_pipeline, guardrail_review, revenue_difference), not formulas",
          "One column per run and scope: the domain's figure over web/public/data, exact decimals as numbers. Metrics reads these only for its check column. Blank = the domain publishes no such figure; the word withheld = an outcome of a run whose sample ratio is a MISMATCH.")
    labels = [f"{run}|{s}" for run in RUN_IDS for s in SCOPES]
    header(ws, 4, ["metric"] + labels)
    rows = {}
    for r, (mid, *_rest) in enumerate(METRICS, start=5):
        rows[mid] = r
        ws.cell(row=r, column=1, value=mid)
        for c, run in enumerate(RUN_IDS):
            for s, scope in enumerate(SCOPES):
                v = ref[(run, scope)].get(mid)
                if v is not None:
                    ws.cell(row=r, column=2 + c * 3 + s, value=v)
    widths(ws, {"A": 30})
    return rows, len(labels)


def build_golden(wb):
    ws = wb.create_sheet("Golden case")
    title(ws, "The known answer, with formulas (P06-GOLD-01)",
          "20 of 100 control and 30 of 100 treatment mature assigned accounts activate: 0.200000 and 0.300000, +10.00 pp, relative lift 0.500000, Newcombe [-0.020249, 0.216734] includes 0, not conclusive; "
          "the sample ratio 100/100 against 0.50/0.50 gives chi-square 0. Blue = typed inputs, black = formulas, column C = tests/fixtures/golden/expected.json.")
    header(ws, 3, ["input", "value"])
    for i, (k, v) in enumerate([("control mature assigned accounts", 100), ("control activated", 20), ("treatment mature assigned accounts", 100), ("treatment activated", 30),
                                ("z", 1.959964), ("allocation control", 0.5), ("allocation treatment", 0.5), ("control assigned", 100), ("treatment assigned", 100)], start=4):
        ws.cell(row=i, column=1, value=k)
        ws.cell(row=i, column=2, value=v).font = BLUE
    # B4 nc, B5 xc, B6 nt, B7 xt, B8 z, B9 ac, B10 at, B11 asg c, B12 asg t
    ex = EXPECTED["metrics"]["experiment"]
    pv = ex["primary"]["variants"]
    wil = lambda x, n, sign: f"=({x}/{n}+$B$8^2/(2*{n}){'-' if sign < 0 else '+'}$B$8*SQRT(({x}/{n})*(1-{x}/{n})/{n}+$B$8^2/(4*{n}^2)))/(1+$B$8^2/{n})"      # noqa: E731
    header(ws, 15, ["figure", "formula", "expected.json", "check"])
    rows = [
        ("control conversion", "=B5/B4", float(pv["control"]["conversion"])),
        ("treatment conversion", "=B7/B6", float(pv["treatment"]["conversion"])),
        ("control Wilson low", wil("B5", "B4", -1), float(pv["control"]["wilson_95"]["low"])),
        ("control Wilson high", wil("B5", "B4", 1), float(pv["control"]["wilson_95"]["high"])),
        ("treatment Wilson low", wil("B7", "B6", -1), float(pv["treatment"]["wilson_95"]["low"])),
        ("treatment Wilson high", wil("B7", "B6", 1), float(pv["treatment"]["wilson_95"]["high"])),
        ("absolute lift (percentage points)", "=(B17-B16)*100", float(ex["primary"]["absolute_lift_pp"])),
        ("relative lift", "=(B17-B16)/B16", float(ex["primary"]["relative_lift"])),
        ("Newcombe low", "=(B17-B16)-SQRT((B17-B20)^2+(B19-B16)^2)", float(ex["primary"]["interval"]["low"])),
        ("Newcombe high", "=(B17-B16)+SQRT((B21-B17)^2+(B16-B18)^2)", float(ex["primary"]["interval"]["high"])),
        ("interval includes 0", "=AND(B24<=0,B25>=0)", ex["primary"]["interval"]["includes_zero"]),
        ("sample-ratio chi-square", "=(B11-(B11+B12)*B9)^2/((B11+B12)*B9)+(B12-(B11+B12)*B10)^2/((B11+B12)*B10)", float(ex["srm"]["statistic"])),
        ("sample-ratio p-value", "=CHIDIST(B27,1)", float(ex["srm"]["p_value"])),
    ]
    for i, (label, f, want) in enumerate(rows, start=16):
        ws.cell(row=i, column=1, value=label)
        ws.cell(row=i, column=2, value=f)
        ws.cell(row=i, column=3, value=want).font = BLUE
        ws.cell(row=i, column=4, value=f"=IF(ISNUMBER(B{i}),ABS(B{i}-C{i})<=0.0000005+0.0000000001,B{i}=C{i})" if not isinstance(want, bool) else f"=B{i}=C{i}")
    last = 16 + len(rows)
    ws[f"A{last + 1}"] = "all golden checks TRUE"
    ws[f"B{last + 1}"] = f"=AND(D16:D{last - 1})"
    ws[f"B{last + 1}"].font = BOLD
    widths(ws, {"A": 46, "B": 20, "C": 16, "D": 10})
    return last + 1


def build_plan_segment(wb, last_account_row):
    ws = wb.create_sheet("Plan x segment")
    title(ws, "Seven-day activation by plan and segment at the as-of (live formulas over Accounts)",
          "Internal accounts excluded. Mature = signup + 7 x 24 h <= 2026-10-05T00:00:00Z; the rate has the mature accounts as denominator. Equals investigation 01 (docs/sql-analysis.md); observed, not experimental.")
    header(ws, 4, ["plan", "segment", "accounts", "signed up", "mature", "activated", "activation rate", "immature (signed up, not mature)"])
    rng = lambda col: f"Accounts!${col}$2:${col}${last_account_row}"      # noqa: E731
    r = 5
    plans, segs = ("business", "free", "team"), ("enterprise", "mid", "smb")
    for p in plans + ("ALL",):
        for s in segs + ("ALL",):
            ws.cell(row=r, column=1, value=p)
            ws.cell(row=r, column=2, value=s)
            crit = f'{rng("E")},0' + (f',{rng("B")},A{r}' if p != "ALL" else "") + (f',{rng("C")},B{r}' if s != "ALL" else "")
            ws.cell(row=r, column=3, value=f"=COUNTIFS({crit})")
            ws.cell(row=r, column=4, value=f'=COUNTIFS({crit},{rng("F")},"<1E+15")')
            ws.cell(row=r, column=5, value=f'=COUNTIFS({crit},{rng("H")},1)')
            ws.cell(row=r, column=6, value=f'=COUNTIFS({crit},{rng("I")},1)')
            ws.cell(row=r, column=7, value=f'=IF(E{r}=0,"",F{r}/E{r})').number_format = "0.000000"
            ws.cell(row=r, column=8, value=f"=D{r}-E{r}")
            r += 1
    widths(ws, {"A": 12, "B": 12, "C": 12, "D": 12, "E": 10, "F": 12, "G": 16, "H": 30})


ASSUMPTIONS = [
    ("D-01", "Canonical events are received by the cutoff and deduplicated (the earliest received wins); an identity link attributes anonymous events forward only; bots, internal accounts and unknown identities are excluded and counted."),
    ("D-02", "The unit is the account. Signup = the earliest signup event of its non-bot users. Activation within [signup, signup + 7 x 24 h); a signup is mature when signup + 7 x 24 h <= the cutoff; immature signups are counted apart."),
    ("D-03", "Intention to treat on mature assigned accounts; the exposure rate is reported beside it. Sample ratio: chi-square against the plan's allocation (df 1); MISMATCH when p < 0.001, INSUFFICIENT when an expected cell < 5. Wilson per arm, Newcombe for treatment minus control (z = 1.959964); relative lift is blank when the control conversion is 0."),
    ("D-05", "Rounding half up once on unrounded values (the domain); this workbook keeps double precision and is compared within 5E-7 for six-decimal figures."),
    ("D-07", "Synthetic world, seed 20261026, 26 weeks, as-of 2026-10-05T00:00:00Z; v1 (400 assigned, permuted blocks of four) and v2 (154 assigned, 3 of 5 to treatment against a 0.40 plan). Four generator choices were made after seeing earlier draws; the realised results are one draw."),
    ("D-08", "A run at cutoff C sees only the facts that existed by C: assignments with assigned_at <= C, exposures with exposed_at <= C, subscriptions with starts_at <= C, events received by C."),
    ("D-10", "conclusive = the interval excludes 0, a final run, a valid plan hash, a plan frozen before the first logged run and an OK sample ratio. An activation counts only at or after the assignment; the guardrail counts only accounts whose 7-day window is complete. The INJ-10 instrumentation gap sits inside the published v1 lift (published +9.50, drawn +11.50, +9.96 excluding the gap accounts)."),
    ("W-01", "The sample ratio comes first: when it is a MISMATCH the outcome rows show the word withheld; no lift of v2 is shown."),
    ("W-02", "The first signup instant (and its received instant), the activation and the first error received inside the guardrail window are TYPED from the independent Python side: the event canonicalisation (duplicates, identity, bots) is not replayed by formulas. An account whose earliest signup event arrives late while a later one arrives earlier would be read differently; build_workbook.py asserts that no such case exists at the five runs, and every run is compared with the domain after recalculation."),
    ("W-03", "The plan hash is typed (a spreadsheet has no sha256). Recalculation: openpyxl writes formulas only; the delivered file was recalculated by LibreOffice headless and carries its cached values; Excel was NOT run. fullCalcOnLoad is set so Excel recalculates on open. Functions used: SUMIFS, COUNTIFS, SUMPRODUCT, INDEX, MATCH, IF, ABS, SQRT, INT, CHIDIST and TINV (the legacy forms, no _xlfn prefix, in Excel and LibreOffice)."),
    ("W-04", "Floating point: formulas use double precision. The domain publishes six decimals (two for money); the check column allows 5E-7 on six-decimal figures and 0.005 on money and percentage points."),
    ("W-05", "The revenue t interval and the Welch interval use TINV(0.05, df): LibreOffice's quantile agrees with the domain's fixed-point quantile to the printed two decimals (the test compares all five runs)."),
]


def build_assumptions(wb):
    ws = wb.create_sheet("Assumptions")
    title(ws, "Decisions applied (docs/contracts.md) and the workbook's own limits")
    header(ws, 3, ["id", "statement"])
    for i, (k, v) in enumerate(ASSUMPTIONS, start=4):
        ws.cell(row=i, column=1, value=k).font = BOLD
        ws.cell(row=i, column=2, value=v).alignment = Alignment(wrap_text=True, vertical="top")
    widths(ws, {"A": 8, "B": 150})


def build_sql_results(wb):
    ws = wb.create_sheet("SQL results (pasted)")
    ws["A1"] = "PASTED VALUES, not formulas, from data/sql/analysis/run_all.py"
    ws["A1"].font = Font(bold=True, size=14)
    if not RESULTS_PATH.exists():
        ws["A2"] = "artifacts/analysis-results.json was not found: run data/sql/analysis/run_all.py --json artifacts/analysis-results.json first"
        return
    res = json.loads(RESULTS_PATH.read_text())
    meta = res["meta"][0]
    ws["A2"] = f"dataset hash {meta['dataset_hash']} | code revision {meta['code_revision']} | contract v{meta['contract_version']} | goes stale if the data or the queries change"
    ws["A3"], ws["B3"], ws["C3"] = "reconciliation rows | equal", meta["reconciliation_rows"], meta["reconciliation_equal"]
    r = 5
    text_cols = {"run", "arm", "plan", "segment", "week_start", "cutoff_at", "read", "reading", "pattern", "step", "event_name", "timezone", "signup_month", "experiment_version", "verdict",
                 "srm_verdict", "day7_status", "week4_status", "interim", "interval_includes_zero", "plan_hash_valid", "plan_frozen", "conclusive"}
    for key in ("05_experiment_v1_at_each_run_cutoff__lift_by_cutoff", "06_experiment_v2_sample_ratio__srm_by_read", "07_guardrail_and_revenue_per_arm__guardrail_by_cutoff",
                "07_guardrail_and_revenue_per_arm__revenue_difference", "05_experiment_v1_at_each_run_cutoff__gap_lift", "01_activation_by_plan_and_segment__plan_segment",
                "02_weekly_cohort_grid__cohort_grid", "04_tracking_quality_by_week__by_week"):
        rows = res[key]
        ws.cell(row=r, column=1, value=key).font = BOLD
        header(ws, r + 1, list(rows[0]))
        for i, row in enumerate(rows, start=r + 2):
            for j, (k, v) in enumerate(row.items(), start=1):
                if k not in text_cols and v != "":
                    try:
                        v = float(v)
                    except ValueError:
                        pass
                ws.cell(row=i, column=j, value=v)
        r += len(rows) + 4
    widths(ws, {"A": 56})


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


SHEET_ORDER = ["Read me", "Cutoff", "Metrics", "Domain reference", "Golden case", "Plan x segment", "Assumptions", "Assignments", "Subscriptions", "Accounts", "Runs", "Plans",
               "SQL results (pasted)"]


def check_signup_reading(data: Data) -> None:
    """The single typed signup of an assignment (earliest event, with its received instant) must give the SQL/domain signup at every run: the build refuses otherwise."""
    ctx = data.ctx
    for run in RUN_IDS:
        c = ctx.cuts[run]
        for a in ctx.asg[RUN_VERSION[run]]:
            if ps.ts(a["assigned_at"]) > c:
                continue
            want = ctx.signup[run].get(a["unit_id"])
            s = ctx.signup["as-of"].get(a["unit_id"])
            got = s if (s is not None and data.sg_recv[a["unit_id"]] <= c) else None
            assert got == want, (run, a["unit_id"], got, want)


def build(path: Path) -> None:
    ctx = ps.load()
    data = Data(ctx)
    check_signup_reading(data)
    ref = domain_reference(ctx)
    wb = Workbook()
    build_readme(wb)
    build_cutoff(wb, ctx)
    build_runs_and_plans(wb, ctx)
    build_assignments(wb, data)
    build_subscriptions(wb, ctx)
    last_acc = build_accounts(wb, data)
    dref_rows, n_ref = build_domain_reference(wb, ref)
    build_metrics(wb, dref_rows, n_ref)
    build_golden(wb)
    build_plan_segment(wb, last_acc)
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
