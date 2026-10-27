# Analyst workbook (P07-ART-05)

`artifacts/trustledger-analyst-workbook.xlsx`, built by `artifacts/build_workbook.py` with openpyxl 3.1.5 and recalculated by LibreOffice headless. **Synthetic data only**: the workbook recomputes the quality ledger of the published snapshot `tl-20261026-20261026` (generator hash `a9f7a3321b102752dd7aa95b76df14c1d9372103e685e10222959fd6438f27ff`, seed 20261026, contract v1, code revision `0b5d686`, as-of 2026-10-05T00:00:00Z): 40 datasets, 60 rules (55 active), 574 issues, 160 lineage edges, 30 published metrics, 400 match candidates. Observed, constructed and hypothetical results are kept apart: everything on `Portfolio` and `Dataset scores` is OBSERVED in one draw of a generated world; the designed relationships (DR-01..DR-06) and the twelve injected defects are constructed; no benefit to a real organisation is claimed.
The decision it supports: **which data issues should be fixed first, and who is accountable?** The workbook shows each dataset's weighted score under **both weight versions** with the **critical override** beside it, the issues by class (**a claim is not a resolution**), mean resolution by team, ownership coverage, lineage, definitions, match precision and timeliness. For `ds-customers` it reads **0.990329 under w1 and 0.990175 under w2 with the override set** (2 failing critical rows, 1 open critical issue).

## How to read it without installing anything
Open the .xlsx in any spreadsheet application, or read this file: it lists every sheet and the checked values. The delivered file already carries the values LibreOffice calculated with the switch at `w2`; **`Checks!B2` (mirrored at `Controls!B15`) is TRUE** when every figure agrees with the Python domain's value and with the golden hand answer.

## Sheets
| Sheet | What it holds |
|---|---|
| `Read me` | What it is, the decision, how to use it, recalculation status, colour code (blue = typed or pasted, black = formula) |
| `Controls` | **The switch:** `Controls!B3` takes `w1` or `w2` (a list); the as-of (`B4`); the weights of the selected version looked up from `Weights` (`B7:B11`, summing to 1 in `B13`); the overall check (`B15`) |
| `Checks` | `B2` = AND of every comparison: all `Portfolio` rows, every dataset row of `Dataset scores` and every `Golden case` row, plus two aggregate checks (`B5`, `B6`) |
| `Portfolio` | 35 live measures (ownership, issue classes, mean resolution overall, by Data Platform and by the other teams, unresolved issues by severity, lineage, definitions, match precision and the review-correct share, timeliness, critical failures and the override): column B a formula over the data sheets, C the domain's value pasted, D the tolerance, E TRUE when they agree |
| `Dataset scores` | One row per dataset (40): dimension scores (mean of the dataset's measured rules), weight sums, weighted score under w1 and under w2 (empty when nothing is measured), the shift, the Selected column (follows `Controls!B3`), critical failures, open critical issues, the override, and a check against the domain; a summary block below (29 scored, 13 differ, 7 moved by at least 0.005, means, the largest move) |
| `Golden case` | The known answer by hand with formulas (100 / 5 / 90 / 95, completeness 0.950000, validity 0.947368 and 0.900000, uniqueness 0.980000, relationship 35 of 37, weighted 0.958116 under w1 and 0.963932 under w2, the override) against `expected.json` |
| `Assumptions` | A-01..A-06 (the contract decisions applied) and W-01..W-05 (the workbook's own limits) |
| `Rule results` | The 55 rules active at the as-of: eligible, populated and failing counts (typed from the independent Python side), the score denominator and the score (formulas) |
| `Issues` | 574 issues: the facts of each issue and of its verifying run (blue), then the owner team, `closed`, `verified`, the class and the hours (formulas) |
| `Owners`, `Datasets` | The register (18) with the accountable-at-as-of formula; the 40 datasets with `owner_covered` and the owner's team |
| `Lineage` | 160 edges with `pair_declared`, `pair_observed` and `counts_as_observed_match` (formulas) |
| `Definitions` | The 30 effective published definitions and the checklist cl-1 as formulas (`LEN(TRIM())`, the source-field list, the owner lookup) |
| `Matching` | 400 candidates with the decision, the reversal flag and the verification layer's truth flag (typed, for the two precision formulas) |
| `Timeliness` | The 15 monitored datasets: occurrence, deadline and last refresh (typed) and the state (formula) |
| `Weights` | The two weight versions (blue) |
| `Domain reference` | PASTED VALUES from the Python domain: each dataset's weighted score under w1 and w2 ("not measured" where the domain measures no dimension), read only by the check columns |
| `SQL results (pasted)` | PASTED VALUES from `data/sql/analysis/run_all.py` (the headline result sets); 175 reconciliation rows, all equal |

## How to use the switch
`Controls!B3` takes **w1** or **w2**. The `Selected` column of `Dataset scores` follows it; both versions are always computed and checked, so `Checks!B2` is TRUE under either. The shift column (w2 minus w1) is independent of the switch.

| Figure (workbook, live) | Value |
|---|---|
| ds-customers weighted score, w1 / w2 | 0.990329 / 0.990175, override set |
| datasets scored / differing between versions / moved by at least 0.005 | 29 / 13 / 7 |
| mean score w1 / w2 | 0.950980 / 0.943118 |
| largest move | -0.167477 (`ds-tickets`) |
| ownership coverage | 0.875000 (35 of 40) |
| issues resolved / claimed / open | 315 / 99 / 160 |
| mean resolution hours: all resolved / Data Platform / all other teams | 68.2716 / 34.4202 / 86.1833 |
| lineage coverage | 0.725000 (58 of 80) |
| definition coverage | 0.766667 (23 of 30) |
| match precision / review-correct share / decision-agreement share | 0.988506 / 0.840909 / 0.931818 |
| timeliness | 0.666667 (10 of 15, none pending) |

## Recalculation status (stated plainly)
openpyxl wrote formulas only; **LibreOffice headless recalculated the delivered file** and it carries the cached values. **Excel itself was NOT run**: nothing here was opened or recalculated by Excel. `fullCalcOnLoad` is set in `workbook.xml` so Excel recalculates when it opens the file. The tests recalculate copies with LibreOffice (as delivered and with the switch at `w1`) and compare them with the Python domain recomputed in the test.

## Rebuild
```
# from apps/trustledger, with openpyxl==3.1.5 (requirements-artifacts.txt) and LibreOffice (soffice) installed
../../.venv/bin/python data/sql/analysis/run_all.py --json artifacts/analysis-results.json --bi-out artifacts/bi
../../.venv/bin/python artifacts/build_workbook.py --recalc
```

## Limits
* **Typed from the independent Python side, not replayed by formulas (W-02):** the per-rule counts (patterns, duplicate keys and parent lookups over 2,554 rows) and the timeliness occurrence and deadline instants (a daily local time in an IANA zone). The formulas turn them into scores, classes, coverage and the weighted score; every result is compared with the domain after recalculation. The workbook is not a rule engine.
* **Edge rows stand for distinct pairs** (80, 70 and 10; asserted by the builder), so the lineage formulas count rows.
* **The decision-agreement share has no domain value** (the contract does not publish it); it is shown with the analysis's own figure (investigation 07) and not checked against the domain.
* **Excel, Power BI and any other spreadsheet engine than LibreOffice were not run**; formulas use legacy function names only (no `_xlfn`).
* **LibreOffice rewrites typed TRUE/FALSE constants as `=TRUE()` / `=FALSE()` when it saves the recalculated file** (owner `active`, dataset `monitored`, the checklist's blank-field flag, the truth flag): the values are unchanged and the tests read both forms.
* No macros, no external links, no credentials.
