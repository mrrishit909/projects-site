# TrustLedger: business case (P07-ART-01)

**Every stakeholder, scenario and number here is synthetic.** Nothing is a claim about a real organisation, a real data estate, a real person or a measured benefit (P07-GOAL-12, P07-DOMAIN-06).
Dataset `tl-20261026-20261026` (seed 20261026, generator `dataset_hash` `a9f7a3321b102752dd7aa95b76df14c1d9372103e685e10222959fd6438f27ff`), contract v1, code revision `0b5d686`; the observed figures describe the ledger at the as-of **2026-10-05T00:00:00Z** after 84 daily runs from 2026-07-13: 40 datasets in six source systems, 420 fields, 18 owners (3 inactive), 60 rules (55 active, 5 disabled), 4,609 rule runs, 574 issues, 160 lineage edges, 30 published metrics in 45 versions, 2,000 customer records and 400 match candidates.
Three kinds of statement are kept apart throughout: **observed** (what the synthetic ledger shows, reconciled to `data/sql/reference_metrics.sql` and the Python domain), **constructed** (what the seeded generator built in on purpose: six designed relationships DR-01..DR-06, twelve injected defects INJ-01..INJ-12, and two outcome-informed generator changes it discloses) and **hypothetical** (what a real governance team might gain; none is claimed and no figure below is one).

**How to read it:** this file needs nothing installed. The numbers are quoted from `sql-analysis.md` (observed, investigations 01-10 and the reconciliation of its section 11); `requirements.md` traces each requirement id to code and tests; `executive-memo.md` turns the evidence into a recommendation. Proportions are decimal fractions with six places, hours have four places, and every rate names its denominator.

## The business decision
**Which data issues should be fixed first, and who is accountable?** (P07-GOAL-01.) The primary users are a data governance analyst and a data quality analyst, with the analytics engineer as the third portfolio role (P07-GOAL-02). TrustLedger changes no source data: it measures, records issues and decisions, and a merge needs a person other than its proposer.

## Business problem
A data-quality dashboard reports one green number. Behind it a critical customer key is duplicated on two rows while the dataset scores above 0.99; validity is quoted without saying whether blanks were counted; a rule's weight was changed on 2026-09-01 so the scores of 13 datasets moved without anything in the data changing; issues were closed without anyone checking the rule again; five datasets are owned by people who have left; a lineage diagram mixes declared, observed and guessed edges; definitions were changed to ones that no longer meet their own checklist; and two customers with the same name and address are one click from being merged. Nobody can say which issue to fix first or who owns it.
TrustLedger fixes the measurement first: each dimension on its own denominator, both validity denominators labelled, null foreign keys counted rather than dropped, weights and definitions versioned with reasons, a critical override that no average can hide, resolution that requires a rerun, lineage styled by its evidence, and identity merges that a person approves and can reverse.

What the synthetic ledger shows (OBSERVED, as-of 2026-10-05T00:00:00Z; `sql-analysis.md`):
* **The near-perfect score with a critical failure:** `ds-customers` scores **0.990175** under the weight version in force (w2) and **0.990329** under w1, yet its critical key rule fails on 2 rows and `iss-0461` (critical, investigating for 309.5667 hours) is open: the override is set. It is the only dataset of 40 carrying the override.
* **Nobody is accountable for five datasets:** ownership coverage is **0.875000** (35 of 40); `ds-contacts`, `ds-invoices`, `ds-ledger-entries`, `ds-returns` and `ds-suppliers` belong to three owners who were deactivated (2026-08-18, 2026-09-04, 2026-09-22) and carry **66 unresolved issues**, 48 of them critical or high.
* **The weights alone move the scores:** 13 of the 29 scored datasets get a different score under w2, 7 by at least 0.005, the largest **-0.167477** (`ds-tickets`); the mean falls from 0.950980 to 0.943118; no rule changed version within 14 days of the weight change.
* **A claim is not a resolution:** of 574 issues **315 are resolved** by a passing rerun of the same rule version, **99 are claimed** (28 after a rerun that failed, 71 with none) and **160 are open**; 259 are unresolved. Data Platform resolves in a mean of **34.4202** hours against **86.1833** for all other teams, yet it holds the largest unresolved backlog (90).
* **Lineage and definitions leak:** only **58 of 80** declared edges were ever observed (0.725000), 12 observed edges are undeclared and 10 inferred edges are never counted; **23 of 30** published definitions pass their checklist (0.766667) and five of the seven failures were introduced by an approved version 2.
* **Matching:** of 400 candidates 220 were reviewed (174 approved, 46 rejected); **172 of the 174 approvals are right (precision 0.988506)**, the wider review-correct share is 185 of 220 (0.840909), and 15 approvals were reversed.
* **Timeliness:** 10 of 15 monitored datasets met their daily target (**0.666667**), none pending; two of the five late datasets have no timeliness rule.

## Simulated stakeholders (roles, not people)
| Role (simulated) | Need | Decision criterion | Entities, metrics, commands |
|---|---|---|---|
| Data governance analyst (primary user) | See which dataset has no accountable owner, which definition no longer meets its checklist and what the weight change did | A figure is quoted with its denominator, weight version and as-of; coverage counts only active owners | `owners`, `datasets`, `metric_versions`, `rule_weight_versions`; P07-MET-06, 09, 10; C01 `register-dataset`, C02 `publish-definition` |
| Data quality analyst (primary user) | Know which failures are real, which issues are resolved and which are only claimed | An issue is resolved only after a passing rerun of the same rule version; the override is never averaged away | `quality_rules`, `rule_runs`, `issues`; P07-MET-01..05, 07, 08; C03 `run-rule`, C04 `open-issue`, C05 `triage-issue`, C10 `verify-remediation` |
| Analytics engineer | A reusable metric model and a lineage view that says what it saw | Observed coverage counts declared pairs seen moving; inferred edges are labelled | `lineage_edges`; P07-MET-12; `bi-package.md`, `artifacts/bi/` |
| Steward / admin (decision owner for merges and rules) | Approve or reverse an identity merge, disable a rule, publish a definition | A reviewer is not the proposer; disabling is not repair; a reversal restores both identities | `match_candidates`, `merge_decisions`, `quality_rules`; C06 `suggest-match`, C07 `approve-merge`, C08 `reverse-merge`, C09 `disable-rule` |
| Accountable owner (reader) | See the issues assigned to them, aged, with their class | Open and claimed issues are both unresolved | `issues`, `issue_events`; P07-UI-05 |
| Data platform / source-system team (reader) | See their resolution speed in context | Mean resolution is over resolved issues only | `issues`; P07-MET-08 |
| Auditor (reader) | Reconstruct who changed what and when | Append-only runs, decisions, versions and audits; every refusal is audited | `audit_events`, `command_results`, `rejected_records` |
| Customer-data steward (reader) | See why two records are or are not the same person | Uncertainty is stated; truth lives only in the verification fixture | `customer_records`, `verification_truth`; P07-DOMAIN-02, 03 |

## Scope
In scope: five quality dimensions each on its own denominator (completeness, validity populated-only and all-eligible, uniqueness by group and by row with null keys apart, relationship integrity with null and empty keys counted apart, timeliness with an on-time / pending / late state); a weighted score that names its weight version and leaves unmeasured dimensions out of both sums; critical failures and open critical issues counted apart with the override; versioned weights, rule definitions and metric definitions with reasons; issues resolved only by a successful rerun; ownership coverage by the active owner; definition coverage under a named checklist version; declared, observed and inferred lineage kept apart; identity candidates stored once in canonical order with their uncertainty, approved only by a reviewer other than the proposer and reversible; append-only row corrections and refreshes (C11, C12).
Out of scope: changing any source data, an automated identity merge of an ambiguous pair, ranking owners as people, a chatbot or any paid inference (P07-GOAL-11), live data and any operational write from the public site (P07-GOAL-12).

## Current-state and future-state process
**Current (simulated):** the dashboard shows one score; an owner who left still "owns" five datasets; a rule is switched off to make an alert go away; an issue is closed by clicking; a weight is edited in place; a lineage graph shows guesses as facts; a script merges two same-name customers.
**Future (TrustLedger):**
| Step | Command or read | What it does | Rule | Built |
|---|---|---|---|---|
| 1 | C01 `register-dataset` | a dataset with an active owner, a classification and (if monitored) a schedule | P07-FLOW-01 | yes |
| 2 | C02 `publish-definition` | draft -> reviewed -> published, each step a new version row; the reviewer is not the drafter | P07-FLOW-02, P07-TEST-11 | yes |
| 3 | C03 `run-rule` | measures an active rule with its rule version and weight version; compared only under the same rule version | P07-FLOW-03, P07-TEST-05, 12 | yes |
| 4 | C04 `open-issue` | an owned issue on a failing scheduled run with the rule's severity | P07-FLOW-04 | yes |
| 5 | C05 `triage-issue` | investigate (owner, due date), claim or reopen | P07-FLOW-05, P07-TEST-09 | yes |
| 6 | C06 `suggest-match` | a candidate in canonical order with score, features and uncertainty; never a merge | P07-FLOW-06, P07-TEST-03, 10 | yes |
| 7 | C07 `approve-merge` | a reviewer other than the proposer approves or rejects; the right record maps to the left | P07-FLOW-07 | yes |
| 8 | C08 `reverse-merge` | a reversal with a reason: both identities restored, history kept | P07-FLOW-08, P07-TEST-06 | yes |
| 9 | C09 `disable-rule` | active -> disabled with a reason and date; runs and issues stay; open issues stay open | P07-FLOW-09, P07-TEST-02 | yes |
| 10 | C10 `verify-remediation` | reruns the rule over the issue's records; a passing rerun of the same rule version resolves it | P07-FLOW-10, P07-TEST-09 | yes |
| 11 | C11 `correct-dataset-rows`, C12 `record-refresh` | append-only row versions and refreshes (the only ways to change measured rows or a refresh) | D-10 R7-07 | yes |
| 12 | `GET /metrics` | the twelve metrics for a half-open window, an as-of, a weight version and a grouping | P07-MET-01..12 | yes |
Where it is verified: the commands run against a transient PostgreSQL 16 on GitHub-hosted runners (Mode A); the public site is a static demo over a published snapshot whose issue workbench and duplicate review simulate their actions in browser memory (Mode B, P07-REL-06).

## Decision criteria
1. **Accountability before urgency.** A fix cannot start where nobody is accountable; the 66 unresolved issues on the five datasets with no active owner need an owner first (`ds-ledger-entries` alone has 22).
2. **A critical failure outranks any score.** The override is a count, not an average: `iss-0461` is the first item of the queue although `ds-customers` scores 0.990175.
3. **A claim is unresolved.** Claimed issues (99) are queued with open ones until a passing rerun of the same rule version resolves them.
4. **Severity, then accountability, then age** is the stated ordering rule of investigation 10; it is a judgement of this package, changeable, and its sensitivity (a score-first list changes with the weight version) is in the memo.
5. **Compare like with like.** Runs are compared only under the same rule version (`RULE_VERSION_DIFFERS` for `r-contacts-fk-customer_key`: 65 against 54 eligible); scores only under the same weight version.
6. **Lineage is evidence.** Only observed edges that match a declared edge count towards coverage; an inferred edge is a hypothesis.
7. **A definition is a contract.** A published definition that fails its checklist (7 of 30) is a defect of its version: five were broken by an approved change.
8. **Data-quality caveats travel with the figure.** The synthetic label, the as-of, the weight version, the draw and the two disclosed generator changes appear wherever a number is quoted.

## Decision supported
The memo (`executive-memo.md`) applies these criteria to the synthetic ledger: **fix the critical `ds-customers` key failure first, assign an active owner to the five uncovered datasets, then verify the 99 claimed issues by rerun, then work the open high-severity backlog by age, starting with the teams that hold most of it.** That is a recommendation about a synthetic ledger; the hypothetical real-world benefit is not claimed.

## Limits and honesty
* **The ledger is generated, in one draw.** The designed relationships were chosen, so finding them shows the queries work, not that an organisation has them. Two outcome-informed changes are disclosed in the manifest (a stray draw removed; the rule-change-free window around 2026-09-01 widened from 7 to 14 days); nothing was re-drawn on its value, and precision 0.988506 is reported as drawn.
* **The fix-first order is a judgement** (severity, inactive owner, age); a different rule gives a different list.
* **"One team twice as fast" and "the oldest unresolved issues are all claimed" are properties of the generator** (DR-04, DR-05), not findings about any team.
* **Mode A and Mode B are different evidence.** The transactional behaviour is verified on hosted runners against PostgreSQL; the public site serves a published snapshot and simulates its actions.
* **No Excel, no Power BI.** The workbook (`workbook.md`) was recalculated by LibreOffice only; the BI package (`bi-package.md`) has no `.pbix`; neither is evidence about those products.
* Claims stay consistent with the public case study (`trustledger/project.json` on `unified-portfolio`) and the résumé bullets (`resume-bullets.md`); the one wording to reconcile is listed in `requirements.md` section 5.
