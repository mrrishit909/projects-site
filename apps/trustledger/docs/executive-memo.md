# Executive memo: which data issues should be fixed first, and who is accountable? (P07-ART-07)

**Synthetic data throughout:** one governance ledger in a generated world (seed 20261026, dataset `tl-20261026-20261026`, generator hash `a9f7a3321b102752dd7aa95b76df14c1d9372103e685e10222959fd6438f27ff`, code revision `0b5d686`, as-of 2026-10-05T00:00:00Z). Nothing here is a claim about a real organisation, a real data estate or a real person, and no benefit of acting on it is claimed. Three kinds of statement are kept apart: **OBSERVED** (what this ledger shows, reconciled to the independent SQL reference and the Python domain: `sql-analysis.md`), **SIMULATED / constructed** (what the generator built in: six designed relationships and twelve injected defects) and **HYPOTHETICAL** (what a real team might gain: not claimed).
How to read it without installing anything: the decision first, then the evidence table, the options, the uncertainty and the limits; every figure is a decimal fraction (six places), an hour count (four places) or a count over a named population, each quoted from `sql-analysis.md`.

## Decision
**Fix in this order, and name the accountable owner before anyone starts:**
1. **`iss-0461` on `ds-customers`: the only unresolved critical issue.** The customer key rule fails on 2 rows, the issue has been investigating for 309.5667 hours (12.9 days), and the dataset scores **0.990175** (w2) and **0.990329** (w1), so a score-ranked list would never show it. Accountable: owner `own-07` (Customer Data, active).
2. **Give the five uncovered datasets an active owner**: `ds-contacts`, `ds-invoices`, `ds-ledger-entries`, `ds-returns`, `ds-suppliers` (coverage 0.875000). They carry **66 unresolved issues**, 48 of them critical or high, assigned to three owners who were deactivated; nobody can verify a fix there until someone is accountable. Assigning an owner is a governance act, not a data fix; the register shows the teams that held them (Finance Systems, Customer Data, Supply Chain).
3. **Re-verify the 99 claimed issues by rerun**, high severity first (65 high). They are closed without a passing rerun of the same rule version, so they count as unresolved: 28 were closed after a rerun that failed, 71 with none. The oldest 64 unresolved issues are all claims (the 65th, `iss-0252`, is the first that is not).
4. **Then work the open high-severity backlog by age** (106 open, 171 high in all), starting where the volume is: Data Platform holds 90 unresolved issues (42 claimed) although it resolves fastest (mean **34.4202** hours against **86.1833** for all other teams), then Finance Systems (50), Supply Chain (41) and Customer Data (39).
5. **Housekeeping that changes what the next report says:** repair the five definitions an approved version 2 made incomplete (`m-csat-score`, `m-customer-lifetime-value`, `m-gross-margin`, `m-net-revenue`, `m-session-conversion-rate`), and reconcile lineage (12 observed edges are undeclared, 22 declared edges were never observed; coverage **0.725000**).
The order is the rule of investigation 10 (severity, then an inactive owner before an active one, then age); it is a judgement, stated so that it can be changed.

## Evidence (OBSERVED)
| Question | Figure | Population and denominator | Where |
|---|---|---|---|
| Does the score hide the critical failure? | w1 0.990329, w2 0.990175, override set; 2 critical failing rows, 1 open critical issue | `ds-customers` (120 eligible rows); 1 of 40 datasets carries the override | investigation 01 |
| Who is accountable? | ownership coverage **0.875000** | 35 of 40 datasets have an active owner | investigation 02 |
| Does the weight version change the picture? | 13 of 29 scored datasets differ, 7 by at least 0.005, largest **-0.167477** (`ds-tickets`); mean 0.950980 to 0.943118 | the 29 datasets with a measured dimension; no rule version changed within 14 days | investigation 03 |
| How many issues are really resolved? | **315 resolved**, **99 claimed**, **160 open** of 574; 259 unresolved | all issues at the as-of | investigation 04 |
| Which team resolves fastest? | Data Platform **34.4202** h (109 issues) against **86.1833** h (206); mean 68.2716 h | resolved issues only; claimed and open excluded | investigation 04 |
| Is lineage trustworthy? | observed coverage **0.725000** (58 of 80); 12 undeclared observed; 10 inferred never counted | distinct (source, target) pairs | investigation 05 |
| Are definitions complete? | **23 of 30** (0.766667); 5 of the 7 failures introduced by version 2 | effective published versions, checklist cl-1 | investigation 06 |
| Can the matches be trusted? | precision **0.988506** (172 of 174); review-correct share **0.840909** (185 of 220); decision agreement 0.931818 (205 of 220); 15 reversals | 220 reviewed candidates of 400 | investigation 07 |
| Are datasets on time? | **0.666667** (10 of 15), none pending; 5 late (2 with no timeliness rule) | monitored datasets evaluated | investigation 08 |
| What does the golden case say? | 95 of 100 complete; validity 90 of 95 (0.947368) and 90 of 100 (0.900000); 0.963932 under w2, 0.958116 under w1, override set | the independent fixture | investigation 09 |

* **The reconciliation is the evidence that the figures are the ledger's, not the query's:** 175 rows, all equal, between the analysis SQL, the independent reference SQL, the Python domain, the manifests and a plain-Python recomputation from the raw JSON (`sql-analysis.md` section 11).
* **Accountability is concentrated.** Of the 259 unresolved issues, 66 (about a quarter) are assigned to inactive owners and are exactly the issues of the five uncovered datasets; they are 48 of the 172 critical or high unresolved issues.
* **A score-first plan would be unstable.** The three lowest-scoring datasets are `ds-payments`, `ds-shipments` and `ds-tickets` under w1 and `ds-tickets`, `ds-payments` and `ds-shipments` under w2 (`ds-tickets` moves from third to first); a plan ranked by score depends on which weight version is in force.

## Options
| Option | What the evidence says | What it needs or risks |
|---|---|---|
| **A. The stated order: severity, inactive owner, age** (recommended) | Puts the one critical issue first and the 66 issues nobody can act on next; 14 of its first 15 issues have an inactive owner | Needs owners assigned first; it is a judgement (the next two options show how much it changes the list) |
| **B. Severity, then age** | Shares only 7 of its first 15 issues with option A; 6 of its first 15 have an inactive owner; it fixes the oldest high claims on teams that are active | Starts work on issues in teams that can act, but leaves the 66 orphaned issues behind and never closes the accountability gap |
| **C. Age alone** | Shares 3 of 15 with option A; starts with a medium claimed issue from July | Ignores severity and the critical issue; the cheapest to explain, the weakest as a priority |
| **D. Rank datasets by quality score and fix the lowest** | The lowest three datasets are the same set under both weights but reordered; `ds-customers` (0.990175) is not on the list at all | The score depends on the weight version and hides the critical failure; it is the picture the override exists to correct |
| **E. Do nothing until the weights and definitions are settled** | 13 of 29 scores move with the weights and 7 of 30 definitions fail their checklist | Delays work on issues whose severity does not depend on either; defensible only for the reporting, not for the fixes |

## Uncertainty
* **One draw.** The ledger was drawn once from the seed; the designed relationships were chosen. That `ds-customers` is near-perfect with a critical failure, that five datasets have no active owner and that one team resolves twice as fast are properties of the generator, so they show that the measurement finds them, not that an organisation has them.
* **Two outcome-informed generator changes are disclosed in the manifest** (a stray draw removed; the rule-change-free window around 2026-09-01 widened from 7 to 14 days). They shape the weight-shift result; nothing was re-drawn on its value, and precision 0.988506 is reported as drawn.
* **The order is a rule, not a measurement.** Whether claimed issues should precede open ones, or datasets with the most serious backlog precede older single issues, is for the accountable people; the overlap figures above show how much the rule matters.
* **Hours are from first detection.** A reopened issue keeps its first `detected_at`; resolved hours end at the verifying rerun; claimed and open issues are not in any mean. A mean over 315 issues says nothing about a single issue.
* **Timeliness at the as-of is one read.** A read taken 10 hours 30 minutes later finds 3 datasets pending and 0.416667 over the 12 evaluated; the loaded history ends at the as-of.
* **Lineage coverage counts pairs, not volumes.** An observed edge says data moved once; an inferred edge says nothing was seen.

## Limitations
* Synthetic owners, datasets, rows and customers: no real data estate, no seasonality, no organisation structure beyond six teams. The relationships were designed, so recovering them shows the pipeline works, not that a real estate has them.
* Match precision uses a synthetic truth that lives only in the verification fixture; a real deployment has no such table.
* The public site is a static demo; its issue workbench and duplicate review simulate their actions in browser memory and nothing is closed or merged from them. The transactional behaviour (C01 to C12) is verified separately on hosted runners against a transient PostgreSQL.
* The review that tested this product (R7) found eight defects, all fixed in the source this package analyses (`0b5d686`), so the figures here are those of the corrected rules; per the public case study the review changed no figure of the published snapshot (`technical-case-study.md`).
* **Excel and Power BI were not run.** The analyst workbook (`workbook.md`) was recalculated by LibreOffice headless only; the BI package (`bi-package.md`) has no `.pbix` and its DAX-like measures were not executed in any engine, only recomputed in Python from the CSV facts. This memo does not support any statement about a realised benefit.

## Recommendation
Start with `iss-0461` (owner `own-07`), in parallel have Data Governance assign active owners to the five uncovered datasets, then verify the 99 claims by rerun and work the open high-severity issues by age. Keep the critical override beside every score, report scores with their weight version, and treat a claim as unresolved until a passing rerun of the same rule version says otherwise. If the people who will do the work prefer to start where they can act today, option B is the defensible alternative; both are consistent with the evidence, and the choice between them is a business decision, not a statistical one. Claims stay consistent with the public case study (`trustledger/project.json`) and the résumé bullets (`resume-bullets.md`).
