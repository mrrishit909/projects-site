# Executive memo: which accounts deserve limited retention attention under uncertain intervention value? (P10-ART-07)

**To:** retention lead, finance partner. **From:** the RetentionLab analysis (synthetic data; roles, not people). **Dataset** `rl-20261026-20261026`, `dataset_hash` `9ebaaadab8a2f70e5f25820616391ee0aec55fbf0b121dee25460de469821b1c`, contract v1, code revision `ce96e65`, as-of 2026-10-05. **Read this memo without installing anything**; every number is reconciled in `sql-analysis.md` (393 reconciliation rows, all equal).

**No retention improvement is claimed, and none can be.** Everything below is a property of a synthetic world. The model's margins over the baselines were reached by construction, and the dollar values are assumptions.

## Decision
Whether to spend a limited contact budget (5, 10 or 20 accounts per cycle) on the accounts the model ranks highest, and how much to trust the ranking and the economics before doing so.

## Evidence (SIMULATED: one draw of a synthetic world; HYPOTHETICAL where marked)
* **The model beats its baselines on the held-out population, by construction.** On 1,513 test rows (442 accounts; 189 churning rows from 95 accounts) the Platt-calibrated logistic regression has average precision 0.238552 and Brier 0.105019, against 0.136653 and 0.109255 for the rule, 0.126793 and 0.326543 for the random baseline and 0.124917 and 0.109664 for the prevalence constant. The generator's engagement signal was strengthened until the declared margins were met (D-G02), so **the margin is a property of the synthetic world, not evidence that such a model beats a simple rule on real accounts**. The Brier margin over the random baseline (0.221524) is uninformative; the margin over the prevalence constant is 0.004645 Brier and 0.113635 AP.
* **The very top of the ranking is weak.** At the three capacities the logistic model's top 5 holds 0 churners, its top 10 holds 2 (precision 0.200000) and its top 20 holds 5 (precision 0.250000, recall 0.026455, risk lift 2.001323, against a 0.124917 base rate). Risk lift is a ranking statistic, not treatment uplift. The rule and the prevalence constant tie across the cut, so their top-K numbers are arbitrary.
* **The probabilities are not calibrated well enough to budget on.** Churn is under-predicted by 2.86 percentage points overall and by 8.07 on the starter plan (a designed, unobserved repricing); apac is at -10.68 (not designed). Six of ten reliability bins hold no rows. Platt scaling made the model slightly worse on test (Brier 0.104515 to 0.105019), because all 289 calibration rows come from one validation cutoff after the purge.
* **Economics are HYPOTHETICAL and depend on the assumption you choose.** With a contact cost of 8.00 and a margin of 200.00: on the **97 scored accounts of the published cohort** the expected value is +21.38 (K = 5, assumed effect 0.3), -6.87 (K = 10, effect 0.2) and -95.46 (K = 20, effect 0.1); on the **1,241 scored accounts of the whole synthetic world** it is +81.13, +71.04 and -29.12. Budgets are 40.00, 80.00 and 160.00. These are different populations. The value is positive only if an intervention removes more than a break-even share of risk: 0.195496, 0.218788 and 0.247894 of the risk of the top 5, 10 and 20 cohort accounts respectively (planning arithmetic from the stored queue). No experiment has measured any such share; the scenario assumptions were changed once after all three showed negative value (D-G02).
* **What the data hides.** 3,594 of 9,039 eligible rows (0.397610) are censored (the mature churn rate is 0.104500); counting them as retained would show churn collapsing to 3.9 % on the last cutoff. Ignoring the arrival instant would change a feature on 11.57 % of the test rows. apac usage drifts from 2026-05-01 (PSI 0.513545 to 0.765053) while the whole population never exceeds 0.043730; the same diagnostic also fires five times before the change, four of them on a floored bin: a diagnostic with false positives.

## Options

| Option | What it is | Evidence for | Evidence against |
|---|---|---|---|
| A. Do nothing | no contact programme | no spend; nothing here proves a benefit | forgoes learning |
| B. Launch at K = 20 now | contact the 20 highest-risk accounts each cycle | lift 2.0 at K = 20 on the test table | top 5 holds 0 churners; hypothetical value negative at K = 20 in both populations; effect unmeasured |
| C. **Randomised trial using the ranking to select the pool** (recommended) | randomise the top-N risk accounts to contact or hold-out and measure churn | the only option that can estimate a treatment effect (P10-DOMAIN-06) | needs a pool larger than the operational capacity; takes at least one 104-day cycle to mature |
| D. Rule-only contact | contact accounts with no usage in 30 days or a high-severity case | simple; precision 0.4 at K = 5 | only two distinct scores, so the top K is a tie broken by account id; AP 0.136653 |

## Uncertainty
* The test rows are correlated across overlapping cutoffs (62 accounts churn in more than one row); with 95 churning accounts no interval is honest, so none is given. A precision of 0.250000 at K = 20 rests on 5 churners.
* The margins, the drift and the calibration gaps are realisations of one seed. The apac gap and the starter gap are single draws.
* The expected values multiply an assumed effect by a margin; neither is estimated. Doubling the assumed effect doubles the gross benefit; halving it can flip the sign.
* The scoring clock is 812 hours old on the cohort (data freshness 1 hour); a refreshed score could differ.

## Limitations
* Synthetic data; four registered features (eight other registered fields are refused); logistic regression only; no hyper-parameter search.
* The world is rebuilt in full by the generator, but only the 200-account cohort and the 1,513-row test table are published at row level.
* Excel and Power BI Desktop were not run for the workbook and the BI package (`workbook.md`, `bi-package.md`).
* The by-construction margin means a held-out win over baselines in this world says nothing about a real customer base.

## Recommendation
1. **Do not claim, plan on or announce a retention improvement** from this evaluation.
2. **Choose option C.** Use the ranking only to select the pool of accounts to randomise; keep every queue a draft until a trial reports.
3. **Before any spend beyond a trial**, recalibrate on more than one validation cutoff and re-evaluate on data the model did not shape; report censored rows as unknown and the apac and starter gaps separately.
4. **Fix the late feeds** (usage 6.8 %, billing 11.7 %, support 9.2 % and subscription 2.6 % of events arrive a day or more late on the whole world) and the logging change in apac before trusting its features.

## The experiment that would be needed (a design, not a result)
* **Question.** Does contacting a high-risk account reduce its 90-day churn, and by how much, compared with not contacting it?
* **Unit and assignment.** The account at one cutoff. Take the accounts the model ranks in the top N at a cutoff; randomise 1:1 to contact or hold-out with a seeded, logged draw; contact only the treatment arm; never re-rank within the pool after assignment.
* **Outcome.** `churned` as defined in D-01: a cancellation in [prediction_at, horizon_end) that arrives before label_end; the result is read only when every row is mature (104 days after the cutoff). Primary analysis: difference in churn proportion with an interval, intention to treat.
* **Size (planning arithmetic, two-sided alpha 0.05, power 0.80, normal approximation).** To detect a 20 % relative reduction in churn from a baseline of 0.25 (the precision of the model's top 20 on the test table) needs about 1,091 accounts per arm; a 30 % reduction needs about 464; from the population base rate 0.124917 a 20 % reduction needs about 2,506 and a 30 % reduction about 1,057 per arm. A capacity of 20 contacts per cycle cannot power this in a cycle: the trial needs a pool far larger than the operational capacity, or many cycles.
* **Guards.** Pre-register the effect size and the analysis; keep the threshold and capacity chosen on validation (P10-TEST-06); keep the experiment identifier on the scenario (`experiment_id` is recorded as a claim only today, `supported_by_randomised_experiment` is always false); use the trial's estimate, never the ranking, as `assumed_effect` in the economics.
* **What would change the decision.** A measured removal share above the break-even (0.195496 to 0.247894 on the cohort's queues) at a contact cost of 8.00 and a margin of 200.00 makes the programme worth running; a measured share below it does not.
