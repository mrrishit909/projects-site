# RetentionLab: business case (P10-ART-01)

**Every account, event, probability and dollar figure here is synthetic.** Nothing is a claim about a real organisation, a real customer base, a real person or a measured benefit (P10-GOAL-12, P10-DOMAIN-05).
Dataset `rl-20261026-20261026` (seed 20261026, generator `dataset_hash` `9ebaaadab8a2f70e5f25820616391ee0aec55fbf0b121dee25460de469821b1c`), contract v1, code revision `ce96e65` (the app content of the lab branch after the review R10 fixes; the published `code_sha` is the lab HEAD at republish time). The observed figures describe the snapshot at the as-of **2026-10-05T00:00:00Z**: a 2,400-account synthetic world evaluated in full by the domain, of which the files publish the complete records of a uniform 200-account cohort plus the 1,513-row held-out test table and the per-cutoff aggregates of the whole world.

Three kinds of statement are kept apart throughout. **Simulated** is what one draw of the synthetic world shows (reconciled to the independent reference SQL, the Python domain and the standard-library reference check). **Constructed** is what the generator built in on purpose: its five designed relationships DR-01..DR-05, twelve injected defects INJ-01..INJ-12, and the outcome-informed choices its author made after seeing earlier draws (manifest disclosures D-G01..D-G09). **Hypothetical** is an assumption-based economic value: it multiplies a model's risk by an assumed share removed and an assumed margin, and no randomised experiment supports the assumed effect. **No retention improvement is claimed**, and the margin of the logistic model over its baselines is met by construction (D-G02), so it is not evidence either.

**How to read it:** this file needs nothing installed. Numbers are quoted from `sql-analysis.md` (ten investigations and a reconciliation of 393 reconciliation rows); `requirements.md` traces each P10 id to code, tests and artifacts; `executive-memo.md` turns the evidence into a recommendation. Proportions and scores are 6-place decimals, percentage points 2 places, money in USD with 2 places, all with their population stated.

## The business decision
**Which accounts deserve limited retention attention under uncertain intervention value?** (P10-GOAL-01.) The primary users are a data scientist, a data analyst and a BI analyst (P10-GOAL-02). RetentionLab sends nothing to anyone: it ranks accounts by predicted 90-day churn risk, shows how trustworthy that ranking is, and prices a contact programme under stated assumptions. The queue it produces is a **draft** (`outreach_events.status = 'draft'` by constraint). High risk is not responsiveness to an offer (P10-FLOW-08, P10-TEST-09): the product refuses `RISK_NOT_RESPONSIVENESS` and never estimates a treatment effect.

## Business problem
A churn model looks excellent and is useless. The cancellation reason sits among its features; an event that happened before the cutoff but arrived after it was used as if known; the same account sits in training and test; label windows straddle the split; the scaler was fitted on everything; the threshold was tuned on the test set; accounts whose outcome is not yet known were labelled as retained; a column of the generator's own truth leaked in; the top of the risk list was read as the list of customers an offer would save; and the capacity exceeded the eligible population. Each of these has an injected defect (INJ-01..INJ-12) and a detect-and-recover test (P10-TEST-01..12).

The decision under uncertainty is narrower than "is the model good". A retention team can contact a handful of accounts per cycle (capacities 5, 10 and 20 in the three scenarios). Contacting an account costs money; the benefit depends on how much of the account's risk a contact removes, which nobody here has measured. So the question is which accounts to prioritise, how far the ranking can be trusted at the very top, and what has to be learned before spending more than a trial.

## Simulated stakeholders (roles, not people)

| Role | What they need from RetentionLab | Decision right | Evidence they use |
|---|---|---|---|
| Retention lead | A short list of accounts per cycle and a plain statement of what is not known | Whether to run a trial contact programme | `executive-memo.md`, capacity planner (`/capacity/`), economics sheet |
| Customer success manager | Why an account is on the list, without a causal story | Whether to act on one account | account explanation (`/account/`), draft queue (`/queue/`) |
| Data scientist | Leak-free evaluation: point-in-time features, purged splits, calibration on the right rows | Whether the model may be scored | investigations 01, 02, 05, 06; `tests/test_adversarial.py` |
| Data analyst | Reconciled numbers with their populations | Which figures may be quoted | `sql-analysis.md`, workbook, `reference_metrics.sql` |
| BI analyst | A reusable metric model that withholds nothing silently | Which measures go on a dashboard | `bi-package.md`, `artifacts/bi/*.csv` |
| Finance partner | Contact budget and a clearly hypothetical value | Whether a budget is released for a trial | investigation 03, `Economics` sheet |
| Data owner for the event feeds | Which feeds arrive late and what that does to features | Whether to fix the feed | investigation 05, monitoring (`/monitoring/`) |

## Scope
In scope: point-in-time features from four event feeds (usage, billing, support, subscription) through the availability instant; labels with a 90-day horizon and a 14-day grace, censored while immature; chronological train / validation / test with a label-window purge and a group purge; preprocessing and Platt calibration fitted only on the rows they may see; a seeded random baseline, a prevalence constant, a business rule and a logistic regression; average precision, Brier score, calibration gaps, precision, recall and risk lift at the capacity actually available; missingness, drift and freshness; a contact budget and a hypothetical expected value; a draft queue.
Out of scope, stated: any real customer data; any message sent; a treatment-effect estimate; a randomised experiment (designed in `executive-memo.md`, never simulated as evidence, P10-DOMAIN-06); more than four registered features (the brief's "about twenty" is not met, D-G07); non-UTC time zones; hyper-parameter search.

## Current-state and future-state process

| Step | Current state (the leaky workflow) | Future state with RetentionLab | Command / id |
|---|---|---|---|
| 1. Features | Features read events by the instant they happened | Only events with `event_at` and `available_at` before the cutoff; late events counted and excluded | C01 `build-point-in-time-features`, P10-FLOW-01 |
| 2. Labels | Accounts with no cancellation yet are "retained" | Mature labels only; immature rows censored (NULL), excluded from every metric | C02 `define-label`, P10-FLOW-02 |
| 3. Split | Random split; label windows cross the boundary | Chronological, label-window purge then group purge, dropped counts published | C03 `split-evaluation`, P10-FLOW-03 |
| 4. Preprocessing | Fitted on all rows | Fitted on retained training rows only, else `LEAKAGE` | C04 `fit-preprocessing`, P10-FLOW-04 |
| 5. Models | One model, no baseline | Random, prevalence constant, rule and logistic regression on one population | C05 `train-baseline`, P10-FLOW-05 |
| 6. Calibration | Judged on its own rows | Fitted on validation, judged on test | C06 `calibrate-model`, P10-FLOW-06 |
| 7. Scoring | A score with no citation | Every prediction cites run, config hash, feature version and label version | C07 `score-accounts`, P10-FLOW-07 |
| 8. Outreach | Top of the list is "who an offer would save" | Capacity-limited draft queue; risk is not responsiveness | C08 `prioritize-outreach`, P10-FLOW-08 |
| 9. Economics | A single optimistic number | Contact budget and a value labelled hypothetical, by population | C09 `simulate-economics`, P10-FLOW-09 |
| 10. Monitoring | A dashboard of today's accuracy | Drift (a diagnostic), missingness, two freshness clocks, performance only on mature rows | C10 `monitor-refresh`, P10-FLOW-10 |

## Decision criteria
A candidate action is acceptable when, on the held-out population: the ranking beats the prevalence constant and the rule on average precision and Brier score (met here, **by construction**); the probabilities are calibrated well enough for a budget (they are not: churn is under-predicted by 2.86 percentage points overall and by 8.07 on the starter plan); the very top of the ranking holds churners (it does not at K = 5: 0 of 5; 2 of 10 at K = 10; 5 of 20 at K = 20); the economics stay positive under the assumed effect (positive at K = 5 in both populations, at K = 10 on the whole world only, and negative at K = 20 in both). Because no criterion about **treatment** can be evaluated without an experiment, the last criterion is the design of one.

## Decision supported
Do not claim, plan on or announce a retention improvement from this evaluation. Use the ranking as a prioritisation aid for a small, randomised trial; keep the draft queue draft; fix the late feeds and the censoring in reporting; recalibrate on more than one validation cutoff before relying on probabilities for a budget. The reasoning and the numbers are in `executive-memo.md`.

## Limits and honesty
* The world is synthetic; every effect is the generator's. The model's margin over the baselines was reached by strengthening the generator's engagement signal (coefficient 1100 to 2200 plus a per-account offset) until the declared margins were met (D-G02, disclosed on every route of the site).
* 3,594 of the 9,039 eligible world rows are censored (their outcome windows are still open) and are excluded from every metric.
* The 1,513 test rows come from 442 accounts (189 churning rows from 95 accounts); the rows are correlated across overlapping cutoffs, so no interval is given.
* The published sample is a 200-account cohort; full-world figures (1,241 scored accounts, per-cutoff counts, the drift series) are published aggregates, not recomputable from the cohort. They were reconciled by re-running the generator in memory (reconciliation group F).
* Economics: +21.38 / -6.87 / -95.46 USD at K = 5 / 10 / 20 on the 97 scored accounts of the cohort and +81.13 / +71.04 / -29.12 on the 1,241 scored accounts of the whole world, all HYPOTHETICAL, different populations, never to be compared with each other as if they were one result.
* This package was built and recalculated in a sandbox with LibreOffice; Excel and Power BI Desktop were not run. See `release-package.md`.
