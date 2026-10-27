# TrustLedger: SQL analysis (P07-ART-04)

**Every owner, dataset, row, issue, edge, definition and customer record here is synthetic.** Nothing is a claim about a real organisation, a real data estate or a measured benefit (P07-GOAL-12, P07-DOMAIN-06).
Dataset `tl-20261026-20261026` (seed 20261026, generator `dataset_hash` `a9f7a3321b102752dd7aa95b76df14c1d9372103e685e10222959fd6438f27ff`), contract v1, code revision `0b5d686` (the published source); the figures describe the ledger as it stood at the as-of **2026-10-05T00:00:00Z** after 84 daily runs from 2026-07-13: 40 datasets (30 with rows, 2,554 rows), 60 rules (55 active at the as-of), 4,609 rule runs, 574 issues, 160 lineage edges, 30 published metrics in 45 versions, 2,000 customer records and 400 match candidates.
Three kinds of statement are kept apart throughout: **observed** (what the synthetic ledger shows, reconciled to `data/sql/reference_metrics.sql`, the Python domain and the manifests), **constructed** (what the seeded generator built in on purpose: the six designed relationships DR-01..DR-06 and the twelve injected defects; a designed relationship that the SQL finds is a check on the generator, not a discovery about any organisation) and **hypothetical** (what a real governance team might gain; none is claimed and no figure below is one).
**The organising question** is the product's decision: *which data issues should be fixed first, and who is accountable?* (P07-GOAL-01). Investigation 10 answers it with a stated rule; investigations 01-09 produce the figures that rule leans on.

**How to read it:** this file needs nothing installed. Every table between `<!-- BEGIN:... -->` markers is rendered from `artifacts/analysis-results.json` by `artifacts/render_sql_analysis.py` (no pasted figure in a table is typed by hand) and `tests/test_artifacts.py` fails on drift. The queries are in `data/sql/analysis/`; `run_all.py` runs them and prints the reconciliation of section 11. Proportions are decimal fractions with six places in [0, 1] (D-05), counts are integers, hours have four places, an empty cell is "unknown or zero denominator", never 0.

## Method
* **Scratch databases, never the shared one.** `prepare_snapshot.py` creates and resets databases named `artifacts07_*`, applies `data/migrations/0001_schema.sql`, `0002_constraints.sql` and `0003_review_r7.sql` through `data/migrate.py` and loads `web/public/data` through `data/seed.py` (the domain's `validate_batch`, as `tests/test_generator.py` does): the entity files, the manifest's configuration, both weight versions and the rule-version definitions, dataset version `tl-20261026-20261026` and the generator's hash. The golden fixture loads into its own scratch database. It then creates and loads the verification layer's table `verification_truth` (`data/sql/verification_truth.sql`), which the seeder, the matcher and the API never touch; only investigation 07, the BI candidate fact and the reference SQL read it.
* **`00_measure_rules.sql`** builds temporary tables from facts only: the as-of (the loaded dataset version's), the active rules (a rule disabled after the as-of was still active), the cells of each rule's eligible rows (exact text; missing = null or empty after trimming the whitespace policy's characters), the **row-level measurement of every rule** (completeness, validity populated-only with the all-eligible count beside it, uniqueness with null keys counted apart, relationship integrity with null and empty keys excluded from the denominator and counted apart, timeliness), the dimension scores, the timeliness states at four read instants, and the **issue classes**. It is the analysis's own formulation: it shares no text with `data/sql/reference_metrics.sql`, and `run_all.py` reconciles it with that reference rule by rule (section 11, rows B).
* **The weighted score** is sum(dimension score x weight) / sum(weights of the measured dimensions) under the named weight version; a dimension no rule measures leaves both sums; a dataset that measures nothing has no score (empty, never 0). `critical_failures` are failing rows of active critical rules and `open critical issues` are critical issues not resolved; either sets the override beside the score whatever its value (D-01, D-06).
* **Issue classes (D-03).** An issue is `resolved` only when it is closed and its verification run is a passing rerun, made for that issue, of the same rule at the same rule version, not before the detection or the latest reopen; closed otherwise it is `claimed`; the rest are `open`. Hours: resolved = verifying rerun - first `detected_at`; claimed = close - `detected_at`; open = as-of - `detected_at`.
* **The Python side.** `data/sql/analysis/python_side.py` recomputes every result set of investigations 01-08 and 10 from the published JSON rows with `re`, `zoneinfo`, `Fraction` and `Decimal` (no SQL, no `trustledger` import, no reference SQL); `run_all.py` compares every cell (section 11, rows C).
* **The snapshot carries no row correction and no recorded refresh** (`max(row_version) = 1`, `dataset_refreshes` empty; `run_all.py` asserts it), so "the row" is the row as loaded.
* **Limits that apply to every table:** one draw of one synthetic world; the six designed relationships were chosen, so finding them shows the queries work, not that an organisation has them; two outcome-informed generator changes are disclosed in the manifest (a stray draw removed, the rule-change-free window around 2026-09-01 widened from 7 to 14 days); nothing was re-drawn on its value.

## 1. ds-customers: a near-perfect score with an open critical key failure (`01_ds_customers_override_both_weights.sql`)
*Question: does the weighted score hide the critical key failure of the customer dataset?* Observed on the loaded snapshot; DR-01 / INJ-01 designed it, so this checks the generator and the override rule rather than discovering a fact about an organisation.


*The four active rules of ds-customers and what each measured (120 eligible rows).*

<!-- BEGIN:01_ds_customers_override_both_weights__rules -->
| rule_id | dimension | severity | eligible | populated | failing | score |
|---|---|---|---|---|---|---|
| r-customers-complete-email | completeness | high | 120 | 119 | 1 | 0.991667 |
| r-customers-fresh | timeliness | medium | 1 |  | 0 | 1.000000 |
| r-customers-unique-customer_key | uniqueness | critical | 120 |  | 2 | 0.983333 |
| r-customers-valid-email | validity | medium | 120 | 119 | 2 | 0.991597 |
<!-- END:01_ds_customers_override_both_weights__rules -->


*Dimension scores (a dimension's score is the mean of its measured rules; relationship is not measured on ds-customers).*

<!-- BEGIN:01_ds_customers_override_both_weights__dimensions -->
| dimension | rules | score |
|---|---|---|
| completeness | 1 | 0.991667 |
| validity | 1 | 0.991597 |
| uniqueness | 1 | 0.983333 |
| timeliness | 1 | 1.000000 |
<!-- END:01_ds_customers_override_both_weights__dimensions -->


*The weighted score under both weight versions.*

<!-- BEGIN:01_ds_customers_override_both_weights__weighted -->
| weight_version | valid_from | measured_dimensions | weight_sum | weighted_score | above_0_95 |
|---|---|---|---|---|---|
| w1 | 2026-01-01 | completeness,validity,uniqueness,timeliness | 0.950000 | 0.990329 | true |
| w2 | 2026-09-01 | completeness,validity,uniqueness,timeliness | 0.850000 | 0.990175 | true |
<!-- END:01_ds_customers_override_both_weights__weighted -->


Under **w1** the score is **0.990329** and under **w2** (in force at the as-of, valid from 2026-09-01) **0.990175**: above 0.95 under both, with the relationship weight left out of both sums (weight sums 0.950000 and 0.850000). The critical key rule `r-customers-unique-customer_key` fails on 2 rows and one critical issue is not resolved, so the override is set:


<!-- BEGIN:01_ds_customers_override_both_weights__critical -->
| dataset_id | critical_failures | critical_open_issues | critical_override |
|---|---|---|---|
| ds-customers | 2 | 1 | true |
<!-- END:01_ds_customers_override_both_weights__critical -->


*The three critical issues of ds-customers; the open one is the single unresolved critical issue of the portfolio.*

<!-- BEGIN:01_ds_customers_override_both_weights__critical_issue -->
| issue_id | rule_id | severity | status | class | detected_at | owner_id | age_hours |
|---|---|---|---|---|---|---|---|
| iss-0071 | r-customers-unique-customer_key | critical | closed | resolved | 2026-07-28T02:26:00Z | own-07 | 100.2000 |
| iss-0176 | r-customers-unique-customer_key | critical | closed | resolved | 2026-08-13T02:26:00Z | own-07 | 57.3333 |
| iss-0461 | r-customers-unique-customer_key | critical | investigating | open | 2026-09-22T02:26:00Z | own-07 | 309.5667 |
<!-- END:01_ds_customers_override_both_weights__critical_issue -->


*Datasets carrying the override in the whole portfolio.*

<!-- BEGIN:01_ds_customers_override_both_weights__portfolio_override -->
| datasets_overridden |
|---|
| 1 |
<!-- END:01_ds_customers_override_both_weights__portfolio_override -->


**Reading.** `iss-0461` has been investigating for 309.5667 hours (12.9 days) at the as-of; two earlier critical issues on the same rule were resolved by a passing rerun after 100.2000 and 57.3333 hours. The score cannot be used to rank this dataset low or high: the override, not the average, carries the message. Reconciled to the reference SQL and the domain under both weight versions, and to DR-01 of the manifest (`weighted_score_w1` 0.990329, `weighted_score_w2` 0.990175, 2 critical failures, 1 critical open issue, `iss-0461`).


## 2. Ownership coverage: who is accountable (`02_ownership_coverage.sql`)
*Question: which datasets have no accountable owner?* Ownership coverage = datasets whose owner is **active** at the as-of / datasets registered by it (P07-MET-09, D-02). Observed; DR-02 / INJ-07 designed three inactive owners.


<!-- BEGIN:02_ownership_coverage__summary -->
| datasets | covered | uncovered | coverage |
|---|---|---|---|
| 40 | 35 | 5 | 0.875000 |
<!-- END:02_ownership_coverage__summary -->


*The five datasets with no accountable owner and what they still carry.*

<!-- BEGIN:02_ownership_coverage__uncovered -->
| dataset_id | dataset_name | classification | monitored | owner_id | owner_team | owner_deactivated_at | unresolved_issues | active_rules |
|---|---|---|---|---|---|---|---|---|
| ds-contacts | Contacts | confidential | true | own-12 | Finance Systems | 2026-09-04T09:00:00Z | 8 | 2 |
| ds-invoices | Invoices | confidential | true | own-09 | Customer Data | 2026-08-18T09:00:00Z | 14 | 3 |
| ds-ledger-entries | Ledger entries | restricted | false | own-12 | Finance Systems | 2026-09-04T09:00:00Z | 22 | 3 |
| ds-returns | Returns | internal | false | own-09 | Customer Data | 2026-08-18T09:00:00Z | 10 | 1 |
| ds-suppliers | Suppliers | confidential | false | own-15 | Supply Chain | 2026-09-22T09:00:00Z | 12 | 3 |
<!-- END:02_ownership_coverage__uncovered -->


<!-- BEGIN:02_ownership_coverage__by_team -->
| team | datasets | covered | uncovered | coverage |
|---|---|---|---|---|
| Customer Data | 7 | 5 | 2 | 0.714286 |
| Data Governance | 5 | 5 | 0 | 1.000000 |
| Data Platform | 9 | 9 | 0 | 1.000000 |
| Finance Systems | 5 | 3 | 2 | 0.600000 |
| Supply Chain | 9 | 8 | 1 | 0.888889 |
| Support Operations | 5 | 5 | 0 | 1.000000 |
<!-- END:02_ownership_coverage__by_team -->


*The three inactive owners and the unresolved issues still assigned to them.*

<!-- BEGIN:02_ownership_coverage__inactive_owners -->
| owner_id | owner_name | team | deactivated_at | datasets_owned | unresolved_issues_assigned |
|---|---|---|---|---|---|
| own-09 | Ione Kestrel | Customer Data | 2026-08-18T09:00:00Z | 2 | 24 |
| own-12 | Linden Thorpe | Finance Systems | 2026-09-04T09:00:00Z | 2 | 30 |
| own-15 | Odessa Quillfeather | Supply Chain | 2026-09-22T09:00:00Z | 1 | 12 |
<!-- END:02_ownership_coverage__inactive_owners -->


**Reading.** 35 of 40 datasets are covered (**0.875000**); the five uncovered datasets are owned by `own-09` (Customer Data), `own-12` (Finance Systems) and `own-15` (Supply Chain), deactivated on 2026-08-18, 2026-09-04 and 2026-09-22. They carry **66 unresolved issues** between them (investigation 10 shows 48 of them are critical or high). An inactive owner leaves the dataset uncovered; the register does not say who took over. Reconciled to the reference SQL, the domain, DR-02 and INJ-07.


## 3. The weight change that moves scores with no rule change (`03_weight_shift_dr03.sql`)
*Question: how much of a score movement is the weights alone?* The same rows and rules are scored under w1 and w2 (the weight change is dated 2026-09-01). The shift is the exact difference w2 - w1 of the unrounded scores, shown to six places (it can differ by 0.000001 from the difference of two rounded scores, D-10 R7-18). Observed; DR-03 / INJ-05 designed it.


<!-- BEGIN:03_weight_shift_dr03__weights -->
| weight_version | valid_from | completeness | validity | uniqueness | relationship | timeliness |
|---|---|---|---|---|---|---|
| w1 | 2026-01-01 | 0.400000 | 0.300000 | 0.200000 | 0.050000 | 0.050000 |
| w2 | 2026-09-01 | 0.250000 | 0.250000 | 0.250000 | 0.150000 | 0.100000 |
<!-- END:03_weight_shift_dr03__weights -->


*Over the 29 datasets that measure at least one dimension.*

<!-- BEGIN:03_weight_shift_dr03__summary -->
| datasets_scored | datasets_with_different_score | datasets_moved_at_least_0_005 | mean_score_w1 | mean_score_w2 | largest_move | largest_move_dataset |
|---|---|---|---|---|---|---|
| 29 | 13 | 7 | 0.950980 | 0.943118 | -0.167477 | ds-tickets |
<!-- END:03_weight_shift_dr03__summary -->


*The stored runs name the weight version in force: the change is a new version, not an edit.*

<!-- BEGIN:03_weight_shift_dr03__runs_by_weight_version -->
| weight_version | runs | first_run | last_run |
|---|---|---|---|
| w1 | 2568 | 2026-07-13T02:01:00Z | 2026-08-31T23:50:00Z |
| w2 | 2041 | 2026-09-01T02:00:00Z | 2026-10-04T23:50:00Z |
<!-- END:03_weight_shift_dr03__runs_by_weight_version -->


*No rule version took effect within 14 days of the weight change (the nearest is 15 days away), so the movement is the weights alone; two rules were disabled inside that window.*

<!-- BEGIN:03_weight_shift_dr03__rule_changes_near_the_weight_change -->
| rule_versions_after_the_first | within_14_days_of_the_weight_change | nearest_days | rules_disabled_within_14_days |
|---|---|---|---|
| 15 | 0 | 15 | 2 |
<!-- END:03_weight_shift_dr03__rule_changes_near_the_weight_change -->


*A score-first priority list changes with the weights.*

<!-- BEGIN:03_weight_shift_dr03__lowest_scores -->
| dataset_id | score_w1 | rank_w1 | score_w2 | rank_w2 |
|---|---|---|---|---|
| ds-tickets | 0.852608 | 3 | 0.685131 | 1 |
| ds-payments | 0.831301 | 1 | 0.796341 | 2 |
| ds-shipments | 0.848394 | 2 | 0.850297 | 3 |
| ds-opportunities | 0.886076 | 4 | 0.886076 | 4 |
| ds-orders | 0.936207 | 9 | 0.891379 | 5 |
| ds-returns | 0.930000 | 6 | 0.930000 | 6 |
| ds-consent-records | 0.916340 | 5 | 0.932773 | 7 |
| ds-warehouses | 0.933333 | 7 | 0.933333 | 8 |
<!-- END:03_weight_shift_dr03__lowest_scores -->


*All 29 scored datasets.*

<!-- BEGIN:03_weight_shift_dr03__shift_by_dataset -->
| dataset_id | score_w1 | score_w2 | shift | differs | moved_at_least_0_005 |
|---|---|---|---|---|---|
| ds-accounts | 0.990000 | 0.981250 | -0.008750 | true | true |
| ds-carriers | 0.966387 | 0.966387 | 0.000000 | false | false |
| ds-consent-records | 0.916340 | 0.932773 | 0.016433 | true | true |
| ds-contacts | 0.984127 | 0.988839 | 0.004712 | true | false |
| ds-cost-centres | 0.974359 | 0.974359 | 0.000000 | false | false |
| ds-csat-surveys | 0.935484 | 0.935484 | 0.000000 | false | false |
| ds-customers | 0.990329 | 0.990175 | -0.000153 | true | false |
| ds-delivery-events | 0.955882 | 0.955882 | 0.000000 | false | false |
| ds-employees | 1.000000 | 1.000000 | 0.000000 | false | false |
| ds-inventory | 1.000000 | 1.000000 | 0.000000 | false | false |
| ds-invoices | 0.987767 | 0.986495 | -0.001272 | true | false |
| ds-kb-articles | 0.984848 | 0.984848 | 0.000000 | false | false |
| ds-ledger-entries | 0.942387 | 0.950617 | 0.008230 | true | true |
| ds-opportunities | 0.886076 | 0.886076 | 0.000000 | false | false |
| ds-order-lines | 0.966981 | 0.966981 | 0.000000 | false | false |
| ds-orders | 0.936207 | 0.891379 | -0.044828 | true | true |
| ds-payments | 0.831301 | 0.796341 | -0.034959 | true | true |
| ds-products | 0.982759 | 0.982759 | 0.000000 | false | false |
| ds-purchase-orders | 0.977778 | 0.977778 | 0.000000 | false | false |
| ds-refunds | 0.938776 | 0.938776 | 0.000000 | false | false |
| ds-returns | 0.930000 | 0.930000 | 0.000000 | false | false |
| ds-shipments | 0.848394 | 0.850297 | 0.001903 | true | false |
| ds-subscriptions | 0.961988 | 0.955044 | -0.006944 | true | true |
| ds-suppliers | 0.961149 | 0.964894 | 0.003745 | true | false |
| ds-ticket-events | 0.971429 | 0.971429 | 0.000000 | false | false |
| ds-tickets | 0.852608 | 0.685131 | -0.167477 | true | true |
| ds-warehouses | 0.933333 | 0.933333 | 0.000000 | false | false |
| ds-web-sessions | 0.985714 | 0.985714 | 0.000000 | false | false |
| ds-web-users | 0.986014 | 0.987374 | 0.001360 | true | false |
<!-- END:03_weight_shift_dr03__shift_by_dataset -->


**Reading.** **13 of 29** scored datasets get a different score from the weights alone, **7** by at least 0.005, the largest **-0.167477** (`ds-tickets`, from 0.852608 to 0.685131); the mean falls from **0.950980** to **0.943118**. `ds-tickets` is third-lowest under w1 and lowest under w2. The 11 datasets with no rows or no measurable rule have no score under either version. Reconciled to the reference SQL (`by_weight_version`) and to every figure of DR-03 (29, 13, 7, both means, the largest move, 2,568 and 2,041 runs, no rule change within 14 days).


## 4. Issue classes, the claimed-versus-resolved split and resolution by team (`04_issue_classes_and_resolution.sql`)
*Questions: how many issues are really resolved, how many were only claimed, and which team resolves fastest?* A claim is not a resolution (P07-FLOW-10, P07-TEST-09). The team of an issue is its owner's team. Observed; DR-04, DR-05 and INJ-09 designed it.


<!-- BEGIN:04_issue_classes_and_resolution__classes -->
| class | issues | share_of_issues | reopened |
|---|---|---|---|
| resolved | 315 | 0.548780 | 1 |
| claimed | 99 | 0.172474 | 0 |
| open | 160 | 0.278746 | 8 |
<!-- END:04_issue_classes_and_resolution__classes -->


<!-- BEGIN:04_issue_classes_and_resolution__class_by_severity -->
| severity | resolved | claimed | open | issues | unresolved |
|---|---|---|---|---|---|
| critical | 6 | 0 | 1 | 7 | 1 |
| high | 197 | 65 | 106 | 368 | 171 |
| medium | 96 | 27 | 43 | 166 | 70 |
| low | 16 | 7 | 10 | 33 | 17 |
<!-- END:04_issue_classes_and_resolution__class_by_severity -->


*Of the 99 claimed issues, 28 were closed after a rerun that failed and 71 with no rerun at all.*

<!-- BEGIN:04_issue_classes_and_resolution__claimed_split -->
| claimed | claimed_with_a_failed_rerun | claimed_without_a_rerun | unresolved | oldest_unresolved_detected_at | oldest_unresolved_issue | claimed_among_the_oldest_25_unresolved | leading_claimed_run | first_not_claimed |
|---|---|---|---|---|---|---|---|---|
| 99 | 28 | 71 | 259 | 2026-07-14T02:13:00Z | iss-0004 | 25 | 64 | iss-0252 |
<!-- END:04_issue_classes_and_resolution__claimed_split -->


*Resolved issues only: claimed and open issues are not in any mean.*

<!-- BEGIN:04_issue_classes_and_resolution__resolution_by_team -->
| team | resolved | mean_hours |
|---|---|---|
| Customer Data | 28 | 77.5452 |
| Data Governance | 9 | 83.4130 |
| Data Platform | 109 | 34.4202 |
| Finance Systems | 68 | 91.9537 |
| Supply Chain | 55 | 82.8748 |
| Support Operations | 46 | 87.4087 |
<!-- END:04_issue_classes_and_resolution__resolution_by_team -->


<!-- BEGIN:04_issue_classes_and_resolution__fast_team_vs_others -->
| group_name | resolved | mean_hours |
|---|---|---|
| Data Platform | 109 | 34.4202 |
| all other teams | 206 | 86.1833 |
<!-- END:04_issue_classes_and_resolution__fast_team_vs_others -->


<!-- BEGIN:04_issue_classes_and_resolution__resolution_overall -->
| resolved | mean_hours | fast_team_ratio | open_count | reopened_issues | reopen_cycles |
|---|---|---|---|---|---|
| 315 | 68.2716 | 0.399384 | 160 | 9 | 9 |
<!-- END:04_issue_classes_and_resolution__resolution_overall -->


*Disabling a rule is not repair: the five disabled rules keep their 329 runs and 52 issues, and 19 of those issues are still unresolved.*

<!-- BEGIN:04_issue_classes_and_resolution__disabled_rules -->
| rule_id | dataset_id | disabled_at | disabled_reason | runs_retained | issues_retained | issues_still_unresolved |
|---|---|---|---|---|---|---|
| r-cost-centres-complete-owner_ref | ds-cost-centres | 2026-09-29T16:55:00Z | Superseded by the upstream contract check | 90 | 18 | 7 |
| r-leads-valid-email | ds-leads | 2026-09-20T01:05:00Z | Superseded by the upstream contract check | 77 | 17 | 6 |
| r-purchase-orders-fresh | ds-purchase-orders | 2026-08-20T05:35:00Z | Superseded by the upstream contract check | 40 | 3 | 1 |
| r-shipments-fresh | ds-shipments | 2026-08-30T07:47:00Z | Threshold review: check moved to the vendor | 48 | 0 | 0 |
| r-tickets-fk-customer_key | ds-tickets | 2026-09-16T04:07:00Z | Threshold review: check moved to the vendor | 74 | 14 | 5 |
<!-- END:04_issue_classes_and_resolution__disabled_rules -->


**Reading.** **315 of 574** issues are resolved by a verifying rerun, **99** were closed without one and are listed as claimed, **160** are open (9 reopen cycles in total). The mean resolution over the resolved is **68.2716** hours; **Data Platform** resolves in a mean of **34.4202** hours (109 issues) against **86.1833** (206 issues) for all other teams, a ratio of **0.399384**. The oldest unresolved issue is `iss-0004` (2026-07-14); **all of the oldest 64 unresolved issues are claimed** (the 65th, `iss-0252` detected 2026-08-25, is the first that is not), which is a property of how the generator drew the first weeks (before 2026-08-25 every unresolved issue is a claim), not a finding about any team. Unresolved issues: 259 (open + claimed), of which 172 are critical or high. The five rules disabled with a reason and a date keep their 329 runs and 52 issues readable, and 19 of those issues remain unresolved: disabling is not repair (INJ-02). Reconciled to the reference SQL, the domain, DR-04 (fast mean, others' mean, 109 and 206, ratio), DR-05 (64 leading claims, the first issue that is not claimed) and INJ-09 (99 claimed, `iss-0004` claimed) and the manifest statistic `claimed_with_failed_rerun` 28.


## 5. Lineage coverage and the three evidence kinds (`05_lineage_coverage_evidence.sql`)
*Question: how much of the declared lineage has been seen moving, and what is only guessed?* Observed lineage coverage = distinct observed (source, target) pairs that match a declared pair / declared pairs (P07-MET-12); observed pairs with no declared counterpart are listed; **inferred edges never enter the numerator** and are never presented as observed (P07-TEST-08). Observed; INJ-08 designed it.


<!-- BEGIN:05_lineage_coverage_evidence__evidence_kinds -->
| evidence_type | edge_rows | distinct_pairs | rows_with_observed_at |
|---|---|---|---|
| declared | 80 | 80 | 0 |
| observed | 70 | 70 | 70 |
| inferred | 10 | 10 | 0 |
<!-- END:05_lineage_coverage_evidence__evidence_kinds -->


<!-- BEGIN:05_lineage_coverage_evidence__coverage -->
| declared_pairs | observed_pairs | observed_matching_declared | coverage | undeclared_observed | declared_not_observed | inferred_pairs | inferred_on_declared_unobserved | inferred_also_observed |
|---|---|---|---|---|---|---|---|---|
| 80 | 70 | 58 | 0.725000 | 12 | 22 | 10 | 4 | 0 |
<!-- END:05_lineage_coverage_evidence__coverage -->


*Observed but never declared: data moves along these paths and nobody documented them.*

<!-- BEGIN:05_lineage_coverage_evidence__undeclared_observed -->
| source_dataset_id | target_dataset_id |
|---|---|
| ds-csat-surveys | ds-cost-centres |
| ds-employees | ds-ledger-entries |
| ds-invoices | ds-web-sessions |
| ds-kb-articles | ds-shipments |
| ds-leads | ds-csat-surveys |
| ds-ledger-entries | ds-web-users |
| ds-price-books | ds-inventory |
| ds-price-books | ds-warehouses |
| ds-refunds | ds-support-agents |
| ds-sla-policies | ds-employees |
| ds-tickets | ds-order-lines |
| ds-web-sessions | ds-accounts |
<!-- END:05_lineage_coverage_evidence__undeclared_observed -->


*Declared but never seen moving; four are covered by an inferred edge, which is not evidence of movement.*

<!-- BEGIN:05_lineage_coverage_evidence__declared_not_observed -->
| source_dataset_id | target_dataset_id | an_inferred_edge_covers_it |
|---|---|---|
| ds-accounts | ds-carriers | false |
| ds-billing-accounts | ds-page-events | false |
| ds-billing-accounts | ds-warehouses | false |
| ds-contacts | ds-page-events | false |
| ds-cost-centres | ds-consent-records | false |
| ds-cost-centres | ds-warehouses | false |
| ds-credit-notes | ds-consent-records | true |
| ds-credit-notes | ds-csat-surveys | true |
| ds-customers | ds-sla-policies | false |
| ds-leads | ds-carriers | false |
| ds-leads | ds-cost-centres | false |
| ds-leads | ds-suppliers | false |
| ds-payments | ds-refunds | true |
| ds-price-books | ds-cost-centres | false |
| ds-products | ds-web-sessions | false |
| ds-shipments | ds-carriers | true |
| ds-sla-policies | ds-shipments | false |
| ds-subscriptions | ds-products | false |
| ds-subscriptions | ds-purchase-orders | false |
| ds-ticket-events | ds-support-agents | false |
| ds-tickets | ds-warehouses | false |
| ds-warehouses | ds-delivery-events | false |
<!-- END:05_lineage_coverage_evidence__declared_not_observed -->


<!-- BEGIN:05_lineage_coverage_evidence__inferred -->
| source_dataset_id | target_dataset_id | declared | observed |
|---|---|---|---|
| ds-accounts | ds-invoices | false | false |
| ds-credit-notes | ds-consent-records | true | false |
| ds-credit-notes | ds-csat-surveys | true | false |
| ds-crm-activities | ds-segments | false | false |
| ds-csat-surveys | ds-shipments | false | false |
| ds-payments | ds-order-lines | false | false |
| ds-payments | ds-refunds | true | false |
| ds-purchase-orders | ds-experiments | false | false |
| ds-shipments | ds-carriers | true | false |
| ds-ticket-events | ds-payments | false | false |
<!-- END:05_lineage_coverage_evidence__inferred -->


**Reading.** Of 80 declared edges **58** were observed (**0.725000**); **12** observed edges are undeclared and **22** declared edges were never observed; 10 inferred edges exist, 4 of them on declared but unobserved pairs, and none is counted as observed. An observed edge has an observation instant and a declared one does not (the database check `edges_evidence_ck`). Reconciled to the reference SQL, the domain, INJ-08 and the manifest statistics (declared 80, observed 70, undeclared 12, inferred 10, inferred on declared unobserved 4).


## 6. Definition coverage under checklist cl-1 (`06_definition_coverage.sql`)
*Question: which published metrics fail their contract?* Definition coverage = published metrics whose checklist (definition, grain, source_fields, owner, refresh) is complete / published metrics, counting each metric's effective published version at the as-of (P07-MET-10). Observed; the incomplete definitions are part of the generated world (manifest `stats.definitions_incomplete`).


<!-- BEGIN:06_definition_coverage__summary -->
| checklist_version | published_metrics | complete_metrics | incomplete_metrics | coverage |
|---|---|---|---|---|
| cl-1 | 30 | 23 | 7 | 0.766667 |
<!-- END:06_definition_coverage__summary -->


*The seven incomplete published metrics, the item missing from each, and whether a version change broke them.*

<!-- BEGIN:06_definition_coverage__incomplete -->
| metric_id | metric_name | version_number | missing_items | owner_id | history |
|---|---|---|---|---|---|
| m-average-order-value | Average order value | 1 | grain | own-16 | single version |
| m-csat-score | CSAT score | 2 | source_fields | own-03 | broken by version 2 |
| m-customer-lifetime-value | Customer lifetime value | 2 | definition | own-06 | broken by version 2 |
| m-gross-margin | Gross margin | 2 | refresh | own-18 | broken by version 2 |
| m-net-revenue | Net revenue | 2 | grain | own-02 | broken by version 2 |
| m-session-conversion-rate | Session conversion rate | 2 | owner | (none) | broken by version 2 |
| m-ticket-resolution-time | Ticket resolution time | 1 | refresh | own-12 | single version |
<!-- END:06_definition_coverage__incomplete -->


*Five of the seven were complete in version 1 and made incomplete by an approved version 2.*

<!-- BEGIN:06_definition_coverage__regressions -->
| change_id | metric_id | version_number | missing_after | approved_by | changed_at |
|---|---|---|---|---|---|
| dc-csat-score-2 | m-csat-score | 2 | source_fields | own-06 | 2026-08-19T09:00:00Z |
| dc-customer-lifetime-value-2 | m-customer-lifetime-value | 2 | definition | own-18 | 2026-08-18T09:00:00Z |
| dc-gross-margin-2 | m-gross-margin | 2 | refresh | own-04 | 2026-09-24T09:00:00Z |
| dc-net-revenue-2 | m-net-revenue | 2 | grain | own-02 | 2026-07-17T09:00:00Z |
| dc-session-conversion-rate-2 | m-session-conversion-rate | 2 | owner | own-16 | 2026-08-13T09:00:00Z |
<!-- END:06_definition_coverage__regressions -->


<!-- BEGIN:06_definition_coverage__versions -->
| metrics | versions | metrics_with_more_than_one_version | change_records | versions_without_change_record | published_versions | superseded_versions |
|---|---|---|---|---|---|---|
| 30 | 45 | 15 | 15 | 0 | 30 | 15 |
<!-- END:06_definition_coverage__versions -->


**Reading.** **23 of 30** published metrics pass the checklist (**0.766667**). Five of the seven failures were **introduced by a change** that an approver signed (`dc-csat-score-2`, `dc-customer-lifetime-value-2`, `dc-gross-margin-2`, `dc-net-revenue-2`, `dc-session-conversion-rate-2`): version 1 was complete, version 2 lost a source-field list, a definition, a refresh, a grain or an owner. The other two (`m-average-order-value`, `m-ticket-resolution-time`) never had the item. Fifteen metrics have a second version and every one has a change record (no version without a reason and an approver). Reconciled to the reference SQL, the domain, the manifest's `definitions_incomplete` and INJ-11 (15 change records, none missing).


## 7. Match precision over approvals and the review-correct share (`07_match_precision.sql`)
*Question: how good were the proposed matches and the human reviews?* **Match precision** = approved merge decisions confirmed correct by the synthetic truth / approved merge decisions; a reversal does not remove the approval (D-06). The contract's **review-correct share** (`reviewed_correct_share`) = reviewed candidates whose two records are the same true entity / reviewed candidates. This analysis adds the **decision-agreement share** (reviews that agree with the truth: an approval of a true match or a rejection of a non-match) because it answers a different question; the two are never mixed. The truth is the verification layer's table, outside the matcher (P07-DOMAIN-03). Synthetic personal details only. Observed; DR-06 designed it.


<!-- BEGIN:07_match_precision__precision -->
| approved | approved_correct | precision | reviewed | rejected | reviewed_correct | reviewed_correct_share | decisions_agreeing_with_truth | decision_agreement_share |
|---|---|---|---|---|---|---|---|---|
| 174 | 172 | 0.988506 | 220 | 46 | 185 | 0.840909 | 205 | 0.931818 |
<!-- END:07_match_precision__precision -->


<!-- BEGIN:07_match_precision__review_matrix -->
| decision | truth | decisions | verdict |
|---|---|---|---|
| approve | same entity | 172 | agrees with the truth |
| approve | different entities | 2 | disagrees |
| reject | same entity | 13 | disagrees |
| reject | different entities | 33 | agrees with the truth |
<!-- END:07_match_precision__review_matrix -->


<!-- BEGIN:07_match_precision__candidates -->
| candidates | canonical_distinct_pairs | reviewed | unreviewed | reversals | candidates_flagged_shared_name_and_address | reviews_by_the_proposer |
|---|---|---|---|---|---|---|
| 400 | 400 | 220 | 180 | 15 | 207 | 0 |
<!-- END:07_match_precision__candidates -->


*The two approvals the truth says were wrong; both were reversed afterwards.*

<!-- BEGIN:07_match_precision__wrong_approvals -->
| candidate_id | left_record_id | right_record_id | score | flagged_possible_household | reviewer_id | reversed_afterwards |
|---|---|---|---|---|---|---|
| cand-0161 | rec-0010 | rec-1165 | 0.560000 | false | own-16 | true |
| cand-0273 | rec-0381 | rec-1116 | 0.950000 | true | own-06 | true |
<!-- END:07_match_precision__wrong_approvals -->


<!-- BEGIN:07_match_precision__reversals -->
| reversals | approvals_reversed | reversals_of_wrong_approvals | reversals_without_a_reason |
|---|---|---|---|
| 15 | 15 | 2 | 0 |
<!-- END:07_match_precision__reversals -->


**Reading.** Of 400 candidates 220 were reviewed by a person (174 approved, 46 rejected) and 180 await review. **172 of the 174 approvals are right: precision 0.988506**, reported as drawn. The wider **review-correct share is 185 of 220 = 0.840909** (172 approved true matches plus 13 true matches that were rejected). The reviews that **agree with the truth number 205 of 220 (0.931818)**: 172 approvals of true matches plus 33 rejections of non-matches. 15 approvals were reversed, each with a reason; 2 of them were the 2 wrong approvals (one was a flagged possible household). No review was made by the candidate's proposer. 207 candidates carry the uncertainty "Shared name and address; possible household" and none was merged automatically. Reconciled to the reference SQL, the domain, DR-06 and the manifest's `synthetic_truth.precision` block.
**Wording note (reported to the coordinator):** the public case study's "205 of the 220 reviews, approvals and rejections together, agree with the truth" is the decision-agreement count reproduced here; it is **not** the contract's `reviewed_correct_share` (185 of 220, 0.840909, which the manifest and the reference SQL publish). Both are correct statements; a reader comparing the case study with the manifest could take them for a mismatch, so the case study should name which one it quotes.


## 8. Timeliness: on time, pending and late (`08_timeliness_states.sql`)
*Question: which monitored datasets met their daily target?* Timeliness = monitored datasets refreshed within their target / monitored datasets **evaluated**. The target is the dataset's daily local time in its IANA zone plus a grace; the window is half-open [occurrence, occurrence + grace), so a refresh at the deadline is late; while the latest occurrence's window is still open and no refresh has arrived the dataset is **pending**, neither on time nor late and outside the denominator (D-10 R7-01). Observed at the as-of; the other read instants are the same loaded refresh history read later (a sensitivity: the loaded history ends at the as-of, so only the first row is an observed read).


<!-- BEGIN:08_timeliness_states__summary -->
| monitored_datasets | on_time | pending | late | evaluated | timeliness |
|---|---|---|---|---|---|
| 15 | 10 | 0 | 5 | 15 | 0.666667 |
<!-- END:08_timeliness_states__summary -->


*Pending appears only while a window is open: 3 datasets are pending at as-of + 10h30m.*

<!-- BEGIN:08_timeliness_states__by_read_instant -->
| read_no | label | read_at | monitored_datasets | on_time | pending | late | evaluated | timeliness |
|---|---|---|---|---|---|---|---|---|
| 0 | as-of | 2026-10-05T00:00:00Z | 15 | 10 | 0 | 5 | 15 | 0.666667 |
| 1 | as-of + 10h30m | 2026-10-05T10:30:00Z | 15 | 5 | 3 | 7 | 12 | 0.416667 |
| 2 | as-of + 13h | 2026-10-05T13:00:00Z | 15 | 5 | 0 | 10 | 15 | 0.333333 |
| 3 | as-of + 25h | 2026-10-06T01:00:00Z | 15 | 0 | 0 | 15 | 15 | 0.000000 |
<!-- END:08_timeliness_states__by_read_instant -->


<!-- BEGIN:08_timeliness_states__at_the_as_of -->
| dataset_id | timezone | scheduled_local | grace_minutes | evaluated_occurrence_utc | deadline_utc | last_refreshed_at | state | owner_team | owner_active |
|---|---|---|---|---|---|---|---|---|---|
| ds-campaigns | Asia/Singapore | 01:00 | 60 | 2026-10-04T17:00:00Z | 2026-10-04T18:00:00Z | 2026-10-04T20:03:25Z | late | Customer Data | true |
| ds-consent-records | America/Chicago | 15:00 | 60 | 2026-10-04T20:00:00Z | 2026-10-04T21:00:00Z | 2026-10-04T20:05:40Z | on_time | Supply Chain | true |
| ds-contacts | America/New_York | 11:30 | 30 | 2026-10-04T15:30:00Z | 2026-10-04T16:00:00Z | 2026-10-04T15:43:25Z | on_time | Finance Systems | false |
| ds-customers | America/New_York | 06:00 | 60 | 2026-10-04T10:00:00Z | 2026-10-04T11:00:00Z | 2026-10-04T10:58:22Z | on_time | Customer Data | true |
| ds-inventory | Asia/Kolkata | 18:45 | 30 | 2026-10-04T13:15:00Z | 2026-10-04T13:45:00Z | 2026-10-04T13:18:39Z | on_time | Data Platform | true |
| ds-invoices | Asia/Singapore | 12:45 | 60 | 2026-10-04T04:45:00Z | 2026-10-04T05:45:00Z | 2026-10-04T05:05:44Z | on_time | Customer Data | false |
| ds-orders | Europe/London | 15:45 | 30 | 2026-10-04T14:45:00Z | 2026-10-04T15:15:00Z | 2026-10-04T17:00:02Z | late | Data Platform | true |
| ds-payments | UTC | 06:00 | 120 | 2026-10-04T06:00:00Z | 2026-10-04T08:00:00Z | 2026-10-04T11:54:24Z | late | Data Platform | true |
| ds-price-books | Europe/Berlin | 19:15 | 120 | 2026-10-04T17:15:00Z | 2026-10-04T19:15:00Z | 2026-10-04T17:28:12Z | on_time | Supply Chain | true |
| ds-purchase-orders | America/New_York | 18:30 | 30 | 2026-10-04T22:30:00Z | 2026-10-04T23:00:00Z | 2026-10-04T22:37:46Z | on_time | Data Platform | true |
| ds-shipments | America/New_York | 03:45 | 30 | 2026-10-04T07:45:00Z | 2026-10-04T08:15:00Z | 2026-10-04T08:14:21Z | on_time | Supply Chain | true |
| ds-sla-policies | Asia/Kolkata | 14:30 | 120 | 2026-10-04T09:00:00Z | 2026-10-04T11:00:00Z | 2026-10-04T10:11:35Z | on_time | Finance Systems | true |
| ds-subscriptions | Europe/London | 16:30 | 60 | 2026-10-04T15:30:00Z | 2026-10-04T16:30:00Z | 2026-10-04T17:23:38Z | late | Data Platform | true |
| ds-tickets | America/Chicago | 05:45 | 120 | 2026-10-04T10:45:00Z | 2026-10-04T12:45:00Z | 2026-10-04T15:17:33Z | late | Data Platform | true |
| ds-web-users | Europe/Berlin | 12:30 | 30 | 2026-10-04T10:30:00Z | 2026-10-04T11:00:00Z | 2026-10-04T10:49:04Z | on_time | Data Platform | true |
<!-- END:08_timeliness_states__at_the_as_of -->


*Two of the five late datasets have no timeliness rule at all.*

<!-- BEGIN:08_timeliness_states__late_with_rules -->
| dataset_id | deadline_utc | last_refreshed_at | minutes_after_deadline | timeliness_rule |
|---|---|---|---|---|
| ds-campaigns | 2026-10-04T18:00:00Z | 2026-10-04T20:03:25Z | 123 | none |
| ds-orders | 2026-10-04T15:15:00Z | 2026-10-04T17:00:02Z | 105 | r-orders-fresh (active) |
| ds-payments | 2026-10-04T08:00:00Z | 2026-10-04T11:54:24Z | 234 | r-payments-fresh (active) |
| ds-subscriptions | 2026-10-04T16:30:00Z | 2026-10-04T17:23:38Z | 54 | none |
| ds-tickets | 2026-10-04T12:45:00Z | 2026-10-04T15:17:33Z | 153 | r-tickets-fresh (active) |
<!-- END:08_timeliness_states__late_with_rules -->


**Reading.** Of 15 monitored datasets **10 are on time and 5 late (0.666667)**, none pending. Three of the late datasets (`ds-orders`, `ds-payments`, `ds-tickets`) have an active timeliness rule; `ds-campaigns` and `ds-subscriptions` are monitored with no timeliness rule, so no issue can open for them. Read 10 hours 30 minutes after the as-of (2026-10-05T10:30Z) three datasets are pending and the rate over the 12 evaluated is 0.416667 (a different question, not a different answer). Reconciled to the reference SQL and the domain at the as-of and at each probe, and to the manifest statistics (15 monitored, 10 on time).


## 9. The golden known answer (`09_golden_known_answer.sql`, golden database)
`09_golden_known_answer.sql` recomputes the known answer from the raw tables of the golden database (P07-GOLD-01): 100 eligible customer rows, 5 missing e-mails, 90 of the 95 populated passing the format rule, 2 duplicated keys, a critical key rule failing on 2 rows.


*Completeness 95 of 100 = 0.950000; validity 90 of 95 = 0.947368 populated-only and 90 of 100 = 0.900000 over all eligible rows, both labelled.*

<!-- BEGIN:09_golden_known_answer__completeness_validity -->
| completeness_rule | eligible | missing | populated | completeness | validity_rule | validity_populated | passing | validity_all_eligible | validity_populated_only |
|---|---|---|---|---|---|---|---|---|---|
| r-cust-complete-email | 100 | 5 | 95 | 0.950000 | r-cust-valid-email | 95 | 90 | 0.900000 | 0.947368 |
<!-- END:09_golden_known_answer__completeness_validity -->


*Uniqueness 1 of 98 keys (0.010204) and 2 of 100 rows (0.020000); relationship 35 of 37 (0.945946) with 3 null or empty keys counted apart (D-10 R7-11).*

<!-- BEGIN:09_golden_known_answer__uniqueness_relationship -->
| uniqueness_eligible | distinct_keys | duplicate_groups | duplicate_rows | group_share | row_share | fk_total | fk_null_or_empty | fk_eligible | fk_matched | relationship |
|---|---|---|---|---|---|---|---|---|---|---|
| 100 | 98 | 1 | 2 | 0.010204 | 0.020000 | 40 | 3 | 37 | 35 | 0.945946 |
<!-- END:09_golden_known_answer__uniqueness_relationship -->


*The score is above 0.95 under both versions and the critical override is set beside it.*

<!-- BEGIN:09_golden_known_answer__weighted_scores -->
| weight_version | measured_dimensions | weight_sum | weighted_score | critical_failures | critical_open_issues | critical_override |
|---|---|---|---|---|---|---|
| w1 | completeness,validity,uniqueness,timeliness | 0.950000 | 0.958116 | 2 | 1 | true |
| w2 | completeness,validity,uniqueness,timeliness | 0.850000 | 0.963932 | 2 | 1 | true |
<!-- END:09_golden_known_answer__weighted_scores -->


*Timeliness 3 of 4, ownership 4 of 5, definitions 3 of 4, lineage 5 of 6, issues 3 resolved, 1 claimed, 2 open with a mean of 38.4444 hours, precision 2 of 3.*

<!-- BEGIN:09_golden_known_answer__portfolio -->
| timeliness_monitored | timeliness_on_time | datasets | ownership_covered | published_metrics | definitions_complete | lineage_declared | lineage_observed_matching | issues_resolved | issues_claimed | issues_open | resolution_mean_hours | approved_correct | approved |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 4 | 3 | 5 | 4 | 4 | 3 | 6 | 5 | 3 | 1 | 2 | 38.4444 | 2 | 3 |
<!-- END:09_golden_known_answer__portfolio -->


`data/sql/reference_metrics.sql` on the same database equals `expected.json` key by key, and so does the domain (rows A of the reconciliation); `tests/reference_check.py` (standard library only) reproduces the same figures from the records.


## 10. Which issues first, and who is accountable (`10_fix_first_queue.sql`)
*Question: in what order should the unresolved issues be fixed, and who is accountable for each?* The queue is every unresolved issue (open, investigating, reopened or **claimed**) ordered by a stated rule: **(1) severity** (critical, high, medium, low); **(2) an issue whose accountable owner is no longer active before one with an active owner** (nobody can act on it); **(3) the older detection first**; **(4) the issue id**. The rule is a recommendation of this analysis, not a contract metric; the counts it ranks are the contract's. Observed, then judged.


<!-- BEGIN:10_fix_first_queue__unresolved_by_severity_and_class -->
| severity | open | claimed | unresolved |
|---|---|---|---|
| critical | 1 | 0 | 1 |
| high | 106 | 65 | 171 |
| medium | 43 | 27 | 70 |
| low | 10 | 7 | 17 |
<!-- END:10_fix_first_queue__unresolved_by_severity_and_class -->


*Who can act: 66 unresolved issues, all of them on the five datasets whose owner is inactive.*

<!-- BEGIN:10_fix_first_queue__accountability -->
| unresolved | issue_owner_inactive | dataset_owner_inactive | either_owner_inactive | critical_or_high | critical_or_high_with_an_inactive_owner |
|---|---|---|---|---|---|
| 259 | 66 | 66 | 66 | 172 | 48 |
<!-- END:10_fix_first_queue__accountability -->


*The accountable team of an unresolved issue is its owner's team.*

<!-- BEGIN:10_fix_first_queue__by_team -->
| team | unresolved | claimed | critical_or_high | owner_inactive | oldest_detected_at |
|---|---|---|---|---|---|
| Data Platform | 90 | 42 | 65 | 0 | 2026-07-15T03:57:00Z |
| Finance Systems | 50 | 17 | 37 | 30 | 2026-07-22T02:52:00Z |
| Supply Chain | 41 | 14 | 29 | 12 | 2026-07-29T04:30:00Z |
| Customer Data | 39 | 9 | 19 | 24 | 2026-07-14T02:13:00Z |
| Support Operations | 25 | 12 | 16 | 0 | 2026-07-17T03:44:00Z |
| Data Governance | 14 | 5 | 6 | 0 | 2026-07-19T05:28:00Z |
<!-- END:10_fix_first_queue__by_team -->


*The first fifteen of the queue.*

<!-- BEGIN:10_fix_first_queue__queue_top -->
| rank | issue_id | dataset_id | rule_id | severity | class | status | age_days | owner_id | owner_team | owner_active | dataset_owner_active |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | iss-0461 | ds-customers | r-customers-unique-customer_key | critical | open | investigating | 12.9 | own-07 | Customer Data | true | true |
| 2 | iss-0031 | ds-invoices | r-invoices-valid-currency | high | claimed | closed | 1.5 | own-09 | Customer Data | false | false |
| 3 | iss-0046 | ds-contacts | r-contacts-complete-email | high | claimed | closed | 1.8 | own-12 | Finance Systems | false | false |
| 4 | iss-0055 | ds-invoices | r-invoices-valid-currency | high | claimed | closed | 0.7 | own-09 | Customer Data | false | false |
| 5 | iss-0082 | ds-suppliers | r-suppliers-unique-supplier_key | high | claimed | closed | 1.3 | own-15 | Supply Chain | false | false |
| 6 | iss-0091 | ds-ledger-entries | r-ledger-entries-valid-currency | high | claimed | closed | 0.6 | own-12 | Finance Systems | false | false |
| 7 | iss-0099 | ds-ledger-entries | r-ledger-entries-valid-currency | high | claimed | closed | 3.2 | own-12 | Finance Systems | false | false |
| 8 | iss-0110 | ds-ledger-entries | r-ledger-entries-valid-currency | high | claimed | closed | 1.9 | own-12 | Finance Systems | false | false |
| 9 | iss-0119 | ds-ledger-entries | r-ledger-entries-valid-currency | high | claimed | closed | 2.9 | own-12 | Finance Systems | false | false |
| 10 | iss-0144 | ds-invoices | r-invoices-valid-currency | high | claimed | closed | 2.1 | own-09 | Customer Data | false | false |
| 11 | iss-0193 | ds-contacts | r-contacts-complete-email | high | claimed | closed | 2.3 | own-12 | Finance Systems | false | false |
| 12 | iss-0217 | ds-invoices | r-invoices-valid-currency | high | claimed | closed | 2.1 | own-09 | Customer Data | false | false |
| 13 | iss-0221 | ds-suppliers | r-suppliers-unique-supplier_key | high | claimed | closed | 2.7 | own-15 | Supply Chain | false | false |
| 14 | iss-0222 | ds-ledger-entries | r-ledger-entries-valid-currency | high | claimed | closed | 0.6 | own-12 | Finance Systems | false | false |
| 15 | iss-0252 | ds-invoices | r-invoices-valid-currency | high | open | investigating | 40.9 | own-09 | Customer Data | false | false |
<!-- END:10_fix_first_queue__queue_top -->


<!-- BEGIN:10_fix_first_queue__datasets_with_the_most_unresolved_serious_issues -->
| dataset_id | unresolved_critical_or_high | claimed | dataset_owner_team | dataset_owner_active |
|---|---|---|---|---|
| ds-ledger-entries | 22 | 5 | Finance Systems | false |
| ds-web-users | 19 | 7 | Data Platform | true |
| ds-subscriptions | 18 | 9 | Data Platform | true |
| ds-opportunities | 13 | 9 | Data Platform | true |
| ds-consent-records | 11 | 3 | Supply Chain | true |
| ds-invoices | 10 | 4 | Customer Data | false |
| ds-customers | 9 | 2 | Customer Data | true |
| ds-contacts | 8 | 2 | Finance Systems | false |
| ds-orders | 8 | 4 | Data Platform | true |
| ds-suppliers | 8 | 4 | Supply Chain | false |
<!-- END:10_fix_first_queue__datasets_with_the_most_unresolved_serious_issues -->


*The stated order against two simpler orders, first 15 each.*

<!-- BEGIN:10_fix_first_queue__ordering_sensitivity -->
| first_n | overlap_with_severity_then_age | overlap_with_age_only | stated_with_an_inactive_owner | severity_then_age_with_an_inactive_owner | age_only_with_an_inactive_owner |
|---|---|---|---|---|---|
| 15 | 7 | 3 | 14 | 6 | 3 |
<!-- END:10_fix_first_queue__ordering_sensitivity -->


**Reading.** 259 issues are unresolved: **1 critical** (`iss-0461`, `ds-customers`, owner `own-07`, active), **171 high** (65 claimed), 70 medium and 17 low. **66 of the 259 are assigned to the three inactive owners** (48 of them critical or high), so they are queued first within their severity: ranks 2 to 14 are high-severity *claimed* issues on `ds-invoices`, `ds-contacts`, `ds-suppliers` and `ds-ledger-entries`. The team with the most unresolved issues is Data Platform (90, none with an inactive owner) although it resolves fastest, which says the backlog is a matter of volume, not speed. Ordering by severity then age alone shares only **7 of the first 15** issues with the stated order, and ordering by age alone **3 of 15**; 14 of the stated first 15 have an inactive owner against 6 and 3. A dataset-score order also differs (investigation 03 shows the score-first list moves with the weights); the memo (`executive-memo.md`) states the rule and its sensitivity. Reconciled to the plain-Python side (rows C) and to the contract counts of investigation 04 (259 = 99 + 160).


## 11. Reconciliation
`run_all.py` prints one row per check and exits 0 only when every row is equal. Rows **A**: the golden fixture (the reference SQL, the Python domain and `expected.json` agree on every metric key and on the whole expected shape, and investigation 09 equals the hand answer); rows **B**: the snapshot headline figures against the reference SQL and the domain at the as-of, at two earlier instants, under both weight versions and at the timeliness probes, rule by rule and issue by issue; rows **C**: every result set cell by cell against `python_side.py`; rows **D**: the designed relationships DR-01..DR-06, the injection manifest and the manifest statistics; rows **E**: the BI measures recomputed from the CSV facts. The mutation checks below show the rows can fail.


<!-- BEGIN:reconciliation -->
| check | analysis_sql | second_source | third_source | fourth_source | equal |
|---|---|---|---|---|---|
| A golden metric completeness: reference SQL = Python domain = expected.json (digest) | ff3dea65587bcbc3 | ff3dea65587bcbc3 | ff3dea65587bcbc3 |  | true |
| A golden metric validity: reference SQL = Python domain = expected.json (digest) | c4bb5bd20d5428e8 | c4bb5bd20d5428e8 | c4bb5bd20d5428e8 |  | true |
| A golden metric uniqueness: reference SQL = Python domain = expected.json (digest) | 89557f868996c08b | 89557f868996c08b | 89557f868996c08b |  | true |
| A golden metric relationship_integrity: reference SQL = Python domain = expected.json (digest) | f2d094cab3824625 | f2d094cab3824625 | f2d094cab3824625 |  | true |
| A golden metric timeliness: reference SQL = Python domain = expected.json (digest) | b94c195bd9ae62e9 | b94c195bd9ae62e9 | b94c195bd9ae62e9 |  | true |
| A golden metric weighted_score: reference SQL = Python domain = expected.json (digest) | 927ae20c7cb18abb | 927ae20c7cb18abb | 927ae20c7cb18abb |  | true |
| A golden metric critical_failures: reference SQL = Python domain = expected.json (digest) | aeeddc213d634391 | aeeddc213d634391 | aeeddc213d634391 |  | true |
| A golden metric resolution_time: reference SQL = Python domain = expected.json (digest) | 36d88ab8c7ed5ec3 | 36d88ab8c7ed5ec3 | 36d88ab8c7ed5ec3 |  | true |
| A golden metric ownership_coverage: reference SQL = Python domain = expected.json (digest) | f1b7a3c37b430701 | f1b7a3c37b430701 | f1b7a3c37b430701 |  | true |
| A golden metric definition_coverage: reference SQL = Python domain = expected.json (digest) | 87e67c9e8daccdf1 | 87e67c9e8daccdf1 | 87e67c9e8daccdf1 |  | true |
| A golden metric match_precision: reference SQL = Python domain = expected.json (digest) | 33737d523d7b82a4 | 33737d523d7b82a4 | 33737d523d7b82a4 |  | true |
| A golden metric lineage_coverage: reference SQL = Python domain = expected.json (digest) | 314dda349f639817 | 314dda349f639817 | 314dda349f639817 |  | true |
| A golden empty_population (reference SQL vs expected.json vs domain) | false | false | false |  | true |
| A golden whole shape of expected.json (domain result.golden() vs the file, digest) | 6c7094178d722e04 | 6c7094178d722e04 |  |  | true |
| A golden timeliness probes (domain vs expected.json, digest) | 8950aeba3f05c659 | 8950aeba3f05c659 |  |  | true |
| A golden weighted_score under w1 (reference SQL vs domain, digest) | 8d090dabc185e6e4 | 8d090dabc185e6e4 |  |  | true |
| A golden weighted_score under w2 (reference SQL vs domain, digest) | 927ae20c7cb18abb | 927ae20c7cb18abb |  |  | true |
| A golden completeness: eligible / missing / populated / value (09 vs expected.json vs the spec's hand answer 100 / 5 / 95 / 0.950000) | 100/5/95/0.950000 | 100/5/95/0.950000 | 100/5/95/0.950000 |  | true |
| A golden validity: populated / passing / populated-only / all-eligible (09 vs expected.json vs the hand answer 95 / 90 / 0.947368 / 0.900000) | 95/90/0.947368/0.900000 | 95/90/0.947368/0.900000 | 95/90/0.947368/0.900000 |  | true |
| A golden uniqueness: eligible / distinct keys / groups / duplicate rows / group share / row share (09 vs expected.json) | 100/98/1/2/0.010204/0.020000 | 100/98/1/2/0.010204/0.020000 |  |  | true |
| A golden relationship: total / null or empty / eligible / matched / value (09 vs expected.json; ds-orders 35 of 37, D-10 R7-11) | 40/3/37/35/0.945946 | 40/3/37/35/0.945946 |  |  | true |
| A golden ds-customers under w1: score / weight sum / critical failures / open critical / override (09 vs domain vs hand answer 0.958116) | 0.958116/0.950000/2/1/true | 0.958116/0.950000/2/1/true | 0.958116/0.950000/2/1/true |  | true |
| A golden ds-customers under w2: score / weight sum / critical failures / open critical / override (09 vs domain vs hand answer 0.963932) | 0.963932/0.850000/2/1/true | 0.963932/0.850000/2/1/true | 0.963932/0.850000/2/1/true |  | true |
| A golden timeliness: monitored / on time (09 vs expected.json) | 4/3 | 4/3 |  |  | true |
| A golden ownership: datasets / covered (09 vs expected.json) | 5/4 | 5/4 |  |  | true |
| A golden definitions: published / complete (09 vs expected.json) | 4/3 | 4/3 |  |  | true |
| A golden lineage: declared / observed matching declared (09 vs expected.json) | 6/5 | 6/5 |  |  | true |
| A golden issues: resolved / claimed / open / mean hours (09 vs expected.json) | 3/1/2/38.4444 | 3/1/2/38.4444 |  |  | true |
| A golden match precision: approved / approved correct (09 vs expected.json) | 3/2 | 3/2 |  |  | true |
| B loaded row counts equal the manifest row_counts (every entity) | c430b581c1f29ec3 | c430b581c1f29ec3 |  |  | true |
| B verification_truth rows equal the manifest's synthetic truth entries (records) | 2000 | 2000 |  |  | true |
| B reference SQL equals the Python domain on completeness at 2026-10-05T00:00:00Z (digest) | 0f93e608f13d6b0e | 0f93e608f13d6b0e |  |  | true |
| B reference SQL equals the Python domain on validity at 2026-10-05T00:00:00Z (digest) | 53bf1e76c8a0565f | 53bf1e76c8a0565f |  |  | true |
| B reference SQL equals the Python domain on uniqueness at 2026-10-05T00:00:00Z (digest) | 4b8255d0beca4441 | 4b8255d0beca4441 |  |  | true |
| B reference SQL equals the Python domain on relationship_integrity at 2026-10-05T00:00:00Z (digest) | 93f906c9b3d1f0e0 | 93f906c9b3d1f0e0 |  |  | true |
| B reference SQL equals the Python domain on timeliness at 2026-10-05T00:00:00Z (digest) | f29619331a5775ed | f29619331a5775ed |  |  | true |
| B reference SQL equals the Python domain on weighted_score at 2026-10-05T00:00:00Z (digest) | 24133000d3998fda | 24133000d3998fda |  |  | true |
| B reference SQL equals the Python domain on critical_failures at 2026-10-05T00:00:00Z (digest) | aeeddc213d634391 | aeeddc213d634391 |  |  | true |
| B reference SQL equals the Python domain on resolution_time at 2026-10-05T00:00:00Z (digest) | 16969145064f7f56 | 16969145064f7f56 |  |  | true |
| B reference SQL equals the Python domain on ownership_coverage at 2026-10-05T00:00:00Z (digest) | c15d2c8b1254d09d | c15d2c8b1254d09d |  |  | true |
| B reference SQL equals the Python domain on definition_coverage at 2026-10-05T00:00:00Z (digest) | a1fe5673758d2c56 | a1fe5673758d2c56 |  |  | true |
| B reference SQL equals the Python domain on match_precision at 2026-10-05T00:00:00Z (digest) | c8ae1b2c24b6e51c | c8ae1b2c24b6e51c |  |  | true |
| B reference SQL equals the Python domain on lineage_coverage at 2026-10-05T00:00:00Z (digest) | 98a7e0f50e6d041a | 98a7e0f50e6d041a |  |  | true |
| B reference SQL equals the Python domain on completeness at 2026-09-14T00:00:00Z (digest) | 3413e092b370052a | 3413e092b370052a |  |  | true |
| B reference SQL equals the Python domain on validity at 2026-09-14T00:00:00Z (digest) | ffe179558525f189 | ffe179558525f189 |  |  | true |
| B reference SQL equals the Python domain on uniqueness at 2026-09-14T00:00:00Z (digest) | 99c533d373ba4f5a | 99c533d373ba4f5a |  |  | true |
| B reference SQL equals the Python domain on relationship_integrity at 2026-09-14T00:00:00Z (digest) | 84d453050421fe3e | 84d453050421fe3e |  |  | true |
| B reference SQL equals the Python domain on timeliness at 2026-09-14T00:00:00Z (digest) | 03831b69d000ffbc | 03831b69d000ffbc |  |  | true |
| B reference SQL equals the Python domain on weighted_score at 2026-09-14T00:00:00Z (digest) | c8318d2e569f20ad | c8318d2e569f20ad |  |  | true |
| B reference SQL equals the Python domain on critical_failures at 2026-09-14T00:00:00Z (digest) | 0a4ea1e5f89fbdf8 | 0a4ea1e5f89fbdf8 |  |  | true |
| B reference SQL equals the Python domain on resolution_time at 2026-09-14T00:00:00Z (digest) | 30bc3c22861943ac | 30bc3c22861943ac |  |  | true |
| B reference SQL equals the Python domain on ownership_coverage at 2026-09-14T00:00:00Z (digest) | 85eee8746642237b | 85eee8746642237b |  |  | true |
| B reference SQL equals the Python domain on definition_coverage at 2026-09-14T00:00:00Z (digest) | 2aa51868bf6079bb | 2aa51868bf6079bb |  |  | true |
| B reference SQL equals the Python domain on match_precision at 2026-09-14T00:00:00Z (digest) | 6fa6dfffd56fe574 | 6fa6dfffd56fe574 |  |  | true |
| B reference SQL equals the Python domain on lineage_coverage at 2026-09-14T00:00:00Z (digest) | 0c80f910a7ebedcd | 0c80f910a7ebedcd |  |  | true |
| B reference SQL equals the Python domain on completeness at 2026-08-17T00:00:00Z (digest) | 38b9b8c9a6633c9e | 38b9b8c9a6633c9e |  |  | true |
| B reference SQL equals the Python domain on validity at 2026-08-17T00:00:00Z (digest) | ffe179558525f189 | ffe179558525f189 |  |  | true |
| B reference SQL equals the Python domain on uniqueness at 2026-08-17T00:00:00Z (digest) | 99c533d373ba4f5a | 99c533d373ba4f5a |  |  | true |
| B reference SQL equals the Python domain on relationship_integrity at 2026-08-17T00:00:00Z (digest) | 84d453050421fe3e | 84d453050421fe3e |  |  | true |
| B reference SQL equals the Python domain on timeliness at 2026-08-17T00:00:00Z (digest) | dccc163ba705c0de | dccc163ba705c0de |  |  | true |
| B reference SQL equals the Python domain on weighted_score at 2026-08-17T00:00:00Z (digest) | 105219c714c6c883 | 105219c714c6c883 |  |  | true |
| B reference SQL equals the Python domain on critical_failures at 2026-08-17T00:00:00Z (digest) | 0a4ea1e5f89fbdf8 | 0a4ea1e5f89fbdf8 |  |  | true |
| B reference SQL equals the Python domain on resolution_time at 2026-08-17T00:00:00Z (digest) | c9bbf9720e697e9c | c9bbf9720e697e9c |  |  | true |
| B reference SQL equals the Python domain on ownership_coverage at 2026-08-17T00:00:00Z (digest) | e6fed48ff0605b8c | e6fed48ff0605b8c |  |  | true |
| B reference SQL equals the Python domain on definition_coverage at 2026-08-17T00:00:00Z (digest) | 5ceecc4c6aa199e7 | 5ceecc4c6aa199e7 |  |  | true |
| B reference SQL equals the Python domain on match_precision at 2026-08-17T00:00:00Z (digest) | dd6d3b10cd3b8966 | dd6d3b10cd3b8966 |  |  | true |
| B reference SQL equals the Python domain on lineage_coverage at 2026-08-17T00:00:00Z (digest) | 07d9331901782508 | 07d9331901782508 |  |  | true |
| B reference SQL equals the Python domain on weighted_score and critical_failures under w1 at the as-of (digest) | 78b2981635c8c030 | 78b2981635c8c030 |  |  | true |
| B reference SQL equals the Python domain on weighted_score and critical_failures under w2 at the as-of (digest) | 87d18417a58713eb | 87d18417a58713eb |  |  | true |
| B timeliness at the probe 2026-10-05T10:30:00Z: reference SQL = Python domain (digest) | d56bedec8bab31ac | d56bedec8bab31ac |  |  | true |
| B timeliness at the probe 2026-10-05T10:30:00Z: on time / pending / late / evaluated / value (08 vs reference SQL vs domain) | 5/3/7/12/0.416667 | 5/3/7/12/0.416667 | 5/3/7/12/0.416667 |  | true |
| B timeliness at the probe 2026-10-05T13:00:00Z: reference SQL = Python domain (digest) | 4ced953706b5e616 | 4ced953706b5e616 |  |  | true |
| B timeliness at the probe 2026-10-05T13:00:00Z: on time / pending / late / evaluated / value (08 vs reference SQL vs domain) | 5/0/10/15/0.333333 | 5/0/10/15/0.333333 | 5/0/10/15/0.333333 |  | true |
| B timeliness at the probe 2026-10-06T01:00:00Z: reference SQL = Python domain (digest) | 434fc499915be1b5 | 434fc499915be1b5 |  |  | true |
| B timeliness at the probe 2026-10-06T01:00:00Z: on time / pending / late / evaluated / value (08 vs reference SQL vs domain) | 0/0/15/15/0.000000 | 0/0/15/15/0.000000 | 0/0/15/15/0.000000 |  | true |
| B per-rule measurement of the 47 row-based rules: eligible / failing / score (analysis temp table vs reference SQL, digest) | 219cf6335ead5ad7 | 219cf6335ead5ad7 |  |  | true |
| B per-rule measurement of the 47 row-based rules: eligible / failing / score (analysis temp table vs Python domain, digest) | 219cf6335ead5ad7 | 219cf6335ead5ad7 |  |  | true |
| B timeliness state of each of the 15 monitored datasets at the as-of (analysis tl_tstate vs reference SQL vs domain, digest) | 9a53c0e0ae633e76 | 9a53c0e0ae633e76 | 9a53c0e0ae633e76 |  | true |
| B class and hours of every one of the 574 issues (analysis tl_issue vs reference SQL, digest) | 27e840141a3dd6c4 | 27e840141a3dd6c4 |  |  | true |
| B class of every issue (analysis vs Python domain, digest) | ffe95e62b96b2b51 | ffe95e62b96b2b51 |  |  | true |
| B ds-customers weighted score under the version in force (w2): the analysis vs reference SQL vs domain | 0.990175 | 0.990175 | 0.990175 |  | true |
| B ds-customers weighted score under w1: the analysis vs reference SQL (by_weight_version) vs domain under w1 | 0.990329 | 0.990329 | 0.990329 |  | true |
| B ds-customers critical failures / open critical issues / override (01 vs reference SQL vs domain) | 2/1/true | 2/1/true | 2/1/true |  | true |
| B ds-customers dimension scores (01 vs reference SQL vs domain) | 924137132e0feb11 | 924137132e0feb11 | 924137132e0feb11 |  | true |
| B all 29 scored datasets under w1 and w2 (03 vs reference SQL by_weight_version, digest) | 591c89a32155f29d | 591c89a32155f29d |  |  | true |
| B ownership coverage: datasets / covered / value / uncovered list (02 vs reference SQL vs domain) | 40/35/0.875000/ds-contacts,ds-invoices,ds-ledger-entries,ds-returns,ds-suppliers | 40/35/0.875000/ds-contacts,ds-invoices,ds-ledger-entries,ds-returns,ds-suppliers | 40/35/0.875000/ds-contacts,ds-invoices,ds-ledger-entries,ds-returns,ds-suppliers |  | true |
| B issues: resolved / claimed / open / reopened / cycles / mean hours (04 vs reference SQL vs domain) | 315/99/160/9/9/68.2716 | 315/99/160/9/9/68.2716 | 315/99/160/9/9/68.2716 |  | true |
| B lineage: declared / observed / matching / coverage / undeclared / inferred (05 vs reference SQL vs domain) | 80/70/58/0.725000/12/10 | 80/70/58/0.725000/12/10 | 80/70/58/0.725000/12/10 |  | true |
| B lineage undeclared and declared-not-observed pair lists (05 vs reference SQL, digest) | cfcaee432d315795 | cfcaee432d315795 |  |  | true |
| B definitions: published / complete / value / incomplete metrics and their missing items (06 vs reference SQL vs domain) | 30/23/0.766667/f7264522390c8d72 | 30/23/0.766667/f7264522390c8d72 | 30/23/0.766667/f7264522390c8d72 |  | true |
| B match precision: approved / correct / precision / reviewed / reviewed correct / share (07 vs reference SQL vs domain) | 174/172/0.988506/220/185/0.840909 | 174/172/0.988506/220/185/0.840909 | 174/172/0.988506/220/185/0.840909 |  | true |
| B timeliness at the as-of: monitored / evaluated / on time / pending / value (08 vs reference SQL vs domain) | 15/15/10/0/0.666667 | 15/15/10/0/0.666667 | 15/15/10/0/0.666667 |  | true |
| B critical failures: failures / open critical issues / datasets overridden / carried (analysis 01 and portfolio vs reference SQL vs domain) | 2/1/1/0 | 2/1/1/0 | 2/1/1/0 |  | true |
| B unresolved issues (10 vs reference SQL vs domain): open + claimed | 259 | 259 | 259 |  | true |
| C 01_ds_customers_override_both_weights__rules: 4 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 7966afb5db276365 | 7966afb5db276365 |  |  | true |
| C 01_ds_customers_override_both_weights__dimensions: 4 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 9d0d09f1840880e0 | 9d0d09f1840880e0 |  |  | true |
| C 01_ds_customers_override_both_weights__weighted: 2 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 195bbd6ec3326041 | 195bbd6ec3326041 |  |  | true |
| C 01_ds_customers_override_both_weights__critical: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 87f457af38dec1ef | 87f457af38dec1ef |  |  | true |
| C 01_ds_customers_override_both_weights__critical_issue: 3 row(s), every cell (SQL result set vs plain Python from the raw JSON) | e4067026818e028d | e4067026818e028d |  |  | true |
| C 01_ds_customers_override_both_weights__portfolio_override: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | ed5c6f9c0a5aeb48 | ed5c6f9c0a5aeb48 |  |  | true |
| C 02_ownership_coverage__summary: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 72734eaf4246268d | 72734eaf4246268d |  |  | true |
| C 02_ownership_coverage__uncovered: 5 row(s), every cell (SQL result set vs plain Python from the raw JSON) | d93247ef789a130e | d93247ef789a130e |  |  | true |
| C 02_ownership_coverage__by_team: 6 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 7f0ff310febf6cc5 | 7f0ff310febf6cc5 |  |  | true |
| C 02_ownership_coverage__inactive_owners: 3 row(s), every cell (SQL result set vs plain Python from the raw JSON) | e617f4b8c50507e9 | e617f4b8c50507e9 |  |  | true |
| C 03_weight_shift_dr03__weights: 2 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 0beb84846d4b0187 | 0beb84846d4b0187 |  |  | true |
| C 03_weight_shift_dr03__shift_by_dataset: 29 row(s), every cell (SQL result set vs plain Python from the raw JSON) | b39584c9083f40ca | b39584c9083f40ca |  |  | true |
| C 03_weight_shift_dr03__summary: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | e01fe7c1686c7493 | e01fe7c1686c7493 |  |  | true |
| C 03_weight_shift_dr03__runs_by_weight_version: 2 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 2e80c8513f772fb4 | 2e80c8513f772fb4 |  |  | true |
| C 03_weight_shift_dr03__rule_changes_near_the_weight_change: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 7e03de73b23b70ed | 7e03de73b23b70ed |  |  | true |
| C 03_weight_shift_dr03__lowest_scores: 8 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 8fc823427fa2675a | 8fc823427fa2675a |  |  | true |
| C 04_issue_classes_and_resolution__classes: 3 row(s), every cell (SQL result set vs plain Python from the raw JSON) | cadc1c0151781b36 | cadc1c0151781b36 |  |  | true |
| C 04_issue_classes_and_resolution__class_by_severity: 4 row(s), every cell (SQL result set vs plain Python from the raw JSON) | dbb27b8923e846a7 | dbb27b8923e846a7 |  |  | true |
| C 04_issue_classes_and_resolution__claimed_split: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 877b41f3d5e02c83 | 877b41f3d5e02c83 |  |  | true |
| C 04_issue_classes_and_resolution__resolution_by_team: 6 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 0765a881e2d7beba | 0765a881e2d7beba |  |  | true |
| C 04_issue_classes_and_resolution__fast_team_vs_others: 2 row(s), every cell (SQL result set vs plain Python from the raw JSON) | be27ae19cb17264a | be27ae19cb17264a |  |  | true |
| C 04_issue_classes_and_resolution__resolution_overall: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 931425ed9875d4d6 | 931425ed9875d4d6 |  |  | true |
| C 04_issue_classes_and_resolution__disabled_rules: 5 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 586cb8e93c1b4810 | 586cb8e93c1b4810 |  |  | true |
| C 05_lineage_coverage_evidence__evidence_kinds: 3 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 708ef4991a168966 | 708ef4991a168966 |  |  | true |
| C 05_lineage_coverage_evidence__coverage: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | ab7cd2643829aeaf | ab7cd2643829aeaf |  |  | true |
| C 05_lineage_coverage_evidence__undeclared_observed: 12 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 8f363b59e8613cf6 | 8f363b59e8613cf6 |  |  | true |
| C 05_lineage_coverage_evidence__declared_not_observed: 22 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 3fce95ddfc3ef455 | 3fce95ddfc3ef455 |  |  | true |
| C 05_lineage_coverage_evidence__inferred: 10 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 6f9833ec85996e21 | 6f9833ec85996e21 |  |  | true |
| C 06_definition_coverage__summary: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 67bcaebfdd4d12a8 | 67bcaebfdd4d12a8 |  |  | true |
| C 06_definition_coverage__incomplete: 7 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 690b6ec20fbfaa70 | 690b6ec20fbfaa70 |  |  | true |
| C 06_definition_coverage__versions: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 55833efd032b9ac2 | 55833efd032b9ac2 |  |  | true |
| C 06_definition_coverage__regressions: 5 row(s), every cell (SQL result set vs plain Python from the raw JSON) | e3039b0bb0be287a | e3039b0bb0be287a |  |  | true |
| C 07_match_precision__precision: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 5f4414410b8dbc7e | 5f4414410b8dbc7e |  |  | true |
| C 07_match_precision__review_matrix: 4 row(s), every cell (SQL result set vs plain Python from the raw JSON) | c17fc64d5a9ae2db | c17fc64d5a9ae2db |  |  | true |
| C 07_match_precision__candidates: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 418e45e8fee1d0b3 | 418e45e8fee1d0b3 |  |  | true |
| C 07_match_precision__wrong_approvals: 2 row(s), every cell (SQL result set vs plain Python from the raw JSON) | fb5d233ad1bddfbd | fb5d233ad1bddfbd |  |  | true |
| C 07_match_precision__reversals: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | c9040ec30c11e64c | c9040ec30c11e64c |  |  | true |
| C 08_timeliness_states__at_the_as_of: 15 row(s), every cell (SQL result set vs plain Python from the raw JSON) | a1541ac937ef3646 | a1541ac937ef3646 |  |  | true |
| C 08_timeliness_states__summary: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 1610771f874e24d6 | 1610771f874e24d6 |  |  | true |
| C 08_timeliness_states__by_read_instant: 4 row(s), every cell (SQL result set vs plain Python from the raw JSON) | abcd7e40ab7e72fd | abcd7e40ab7e72fd |  |  | true |
| C 08_timeliness_states__late_with_rules: 5 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 506be82351085ddc | 506be82351085ddc |  |  | true |
| C 10_fix_first_queue__unresolved_by_severity_and_class: 4 row(s), every cell (SQL result set vs plain Python from the raw JSON) | c0d4cc50e0ded49f | c0d4cc50e0ded49f |  |  | true |
| C 10_fix_first_queue__accountability: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | afa1ef014307db43 | afa1ef014307db43 |  |  | true |
| C 10_fix_first_queue__by_team: 6 row(s), every cell (SQL result set vs plain Python from the raw JSON) | d546a7250e6ba816 | d546a7250e6ba816 |  |  | true |
| C 10_fix_first_queue__queue_top: 15 row(s), every cell (SQL result set vs plain Python from the raw JSON) | d395e0b729438dfe | d395e0b729438dfe |  |  | true |
| C 10_fix_first_queue__ordering_sensitivity: 1 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 8956726e7964c6c7 | 8956726e7964c6c7 |  |  | true |
| C 10_fix_first_queue__datasets_with_the_most_unresolved_serious_issues: 10 row(s), every cell (SQL result set vs plain Python from the raw JSON) | 1833e95dabdbe8e9 | 1833e95dabdbe8e9 |  |  | true |
| D injection manifest and manifest carry the dataset hash and version of this package | a9f7a3321b102752dd7aa95b76df14c1d9372103e685e10222959fd6438f27ff/tl-20261026-20261026 | a9f7a3321b102752dd7aa95b76df14c1d9372103e685e10222959fd6438f27ff/tl-20261026-20261026 | a9f7a3321b102752dd7aa95b76df14c1d9372103e685e10222959fd6438f27ff/tl-20261026-20261026 |  | true |
| D DR-01 near-perfect score with an open critical key failure: w1 / w2 / critical failures / open critical issues / override / datasets overridden / issue / rule (01 vs the manifest) | 0.990329/0.990175/2/1/true/1/iss-0461/r-customers-unique-customer_key | 0.990329/0.990175/2/1/true/1/iss-0461/r-customers-unique-customer_key |  |  | true |
| D DR-02 inactive owners leave five datasets uncovered: covered / value / uncovered list / inactive owners (02 vs the manifest) | 35/0.875000/ds-contacts,ds-invoices,ds-ledger-entries,ds-returns,ds-suppliers/own-09,own-12,own-15 | 35/0.875000/ds-contacts,ds-invoices,ds-ledger-entries,ds-returns,ds-suppliers/own-09,own-12,own-15 |  |  | true |
| D DR-03 the weight change moves scores: scored / different / moved >= 0.005 / mean w1 / mean w2 / largest move / runs w1 / runs w2 / rule changes within 14 days (03 vs the manifest) | 29/13/7/0.950980/0.943118/-0.167477/2568/2041/0 | 29/13/7/0.950980/0.943118/-0.167477/2568/2041/0 |  |  | true |
| D DR-04 one team resolves twice as fast: fast resolved / fast mean / other resolved / other mean / ratio (04 vs the manifest) | 109/34.4202/206/86.1833/0.399384 | 109/34.4202/206/86.1833/0.399384 |  |  | true |
| D DR-05 the oldest unresolved issues are all claimed: unresolved / oldest issue / oldest detected / claimed among the oldest 25 of 25 (04 vs the manifest) | 259/iss-0004/2026-07-14T02:13:00Z/25 | 259/iss-0004/2026-07-14T02:13:00Z/25 |  |  | true |
| D DR-05 the leading run of claimed issues among the unresolved, oldest first: length / first issue that is not claimed (04 vs the manifest) | 64/iss-0252 | 64/iss-0252 |  |  | true |
| D DR-06 precision: candidates / reviewed / approved / rejected / correct / precision / reviewed share / reversals / reversed wrong approvals (07 vs the manifest) | 400/220/174/46/172/0.988506/0.840909/15/2 | 400/220/174/46/172/0.988506/0.840909/15/2 |  |  | true |
| D DR-06 households: candidates flagged as a possible household / wrongly approved households (07 vs the manifest) | 207/1 | 207/1 |  |  | true |
| D synthetic_truth precision block in the manifest (07 vs the manifest) | 174/172/0.988506/220/0.840909 | 174/172/0.988506/220/0.840909 |  |  | true |
| D manifest stats.issues: resolved / claimed / open / claimed with a failed rerun / reopened issues (04 vs the manifest) | 315/99/160/28/9 | 315/99/160/28/9 |  |  | true |
| D manifest stats.lineage: declared / observed / undeclared observed / inferred / inferred on declared unobserved (05 vs the manifest) | 80/70/12/10/4 | 80/70/12/10/4 |  |  | true |
| D manifest stats.datasets and timeliness: monitored / on time (08 vs the manifest) | 15/10 | 15/10 |  |  | true |
| D manifest stats.definitions_incomplete: the seven incomplete metrics and the item missing from each (06 vs the manifest) | ecc9d3a4b494bb35 | ecc9d3a4b494bb35 |  |  | true |
| D INJ-11 definitions: change records / versions without a change record / metrics with a second version (06 vs the injection manifest) | 15/0/15 | 15/0/15 |  |  | true |
| D INJ-07 ownership and INJ-08 lineage checks (02 and 05 vs the injection manifest): uncovered list / value / lineage value / observed / matching / undeclared / inferred | ds-contacts,ds-invoices,ds-ledger-entries,ds-returns,ds-suppliers/0.875000/0.725000/70/58/12/10 | ds-contacts,ds-invoices,ds-ledger-entries,ds-returns,ds-suppliers/0.875000/0.725000/70/58/12/10 |  |  | true |
| D INJ-09 issues closed without a verifying rerun: claimed / iss-0004 is claimed (04 and 01 vs the injection manifest) | 99/iss-0004 | 99/iss-0004 |  |  | true |
| D INJ-04 null foreign keys counted apart on r-orders-fk-customer_key: null / eligible / unmatched (reference SQL vs the injection manifest) | 5/61/0 | 5/61/0 |  |  | true |
| D INJ-02 the five disabled rules keep their runs and issues: runs retained / issues retained for each rule (04 vs the injection manifest) | r-cost-centres-complete-owner_ref:90:18/r-leads-valid-email:77:17/r-purchase-orders-fresh:40:3/r-shipments-fresh:48:0/r-tickets-fk-customer_key:74:14 | r-cost-centres-complete-owner_ref:90:18/r-leads-valid-email:77:17/r-purchase-orders-fresh:40:3/r-shipments-fresh:48:0/r-tickets-fk-customer_key:74:14 |  |  | true |
| D INJ-05 identical rows score differently under w1 and w2: ds-orders (03 vs the injection manifest) | 0.936207/0.891379 | 0.936207/0.891379 |  |  | true |
| D INJ-06 15 approved merges are reversed and both identities restored: reversals / identity map of rec-1275 and rec-0102 (07 and the domain vs the injection manifest) | 15/rec-1275/rec-0102 | 15/rec-1275/rec-0102 |  |  | true |
| D INJ-03 and INJ-10 400 distinct canonical candidates, none merged automatically: candidates / distinct canonical pairs / reviews by the proposer (07 vs the injection manifest) | 400/400/0 | 400/400/0 |  |  | true |
| D INJ-12 a changed denominator is not comparable: comparable / reason / previous eligible / current eligible (domain vs the injection manifest) | false/RULE_VERSION_DIFFERS/65/54 | false/RULE_VERSION_DIFFERS/65/54 |  |  | true |
| D the stored last scheduled run of each active row-based rule equals the row-level measurement except the INJ-12 rule (rules compared / rules that differ: analysis tl_rule_measure vs the stored runs) | 47/r-contacts-fk-customer_key | 47/r-contacts-fk-customer_key |  |  | true |
| E BI row counts: dim_owner / dim_dataset / dim_rule / dim_metric / fact_rule_measure / fact_dataset_score / fact_issue / fact_lineage_edge / fact_candidate / fact_timeliness | 18/40/60/30/55/80/574/160/400/15 | 18/40/60/30/55/80/574/160/400/15 |  |  | true |
| E BI ownership coverage / definition coverage / lineage coverage (CSV facts vs reference SQL vs domain) | 0.875000/0.766667/0.725000 | 0.875000/0.766667/0.725000 | 0.875000/0.766667/0.725000 |  | true |
| E BI issue classes / mean resolution hours / Data Platform mean (CSV facts vs reference SQL vs domain) | 315/99/160/68.2716/34.4202 | 315/99/160/68.2716/34.4202 | 315/99/160/68.2716/34.4202 |  | true |
| E BI timeliness / pending / late (CSV facts vs reference SQL vs domain) | 0.666667/0/5 | 0.666667/0/5 | 0.666667/0/5 |  | true |
| E BI match precision / reviewed correct share (CSV facts vs reference SQL vs domain) | 0.988506/0.840909 | 0.988506/0.840909 | 0.988506/0.840909 |  | true |
| E BI weighted score of every dataset under w1 and w2: the 80 rows recomputed from the exact rule fractions vs the SQL fact vs reference SQL (digest; unmeasured datasets stay empty) | b35a6ef2530f4072 | b35a6ef2530f4072 | b35a6ef2530f4072 |  | true |
| E BI weighted score mean under w1 / w2 / datasets that differ / moved / largest move (CSV facts vs 03 vs the manifest DR-03) | 0.950980/0.943118/13/7/-0.167477 | 0.950980/0.943118/13/7/-0.167477 | 0.950980/0.943118/13/7/-0.167477 |  | true |
| E BI critical failures / datasets with the override / open critical issues (CSV facts vs reference SQL vs domain) | 2/1/1 | 2/1/1 | 2/1/1 |  | true |
| E BI unresolved issues / with an inactive owner (CSV facts vs 10) | 259/66 | 259/66 |  |  | true |
| E BI nothing withheld silently: every dataset x weight version has a measure row and each empty value carries a status (rows / empty values / empty values with a non-value status) | 80/22/22 | 80/22/22 |  |  | true |
<!-- END:reconciliation -->


**Mutation check (run once by the author of this package, not part of the suite).** Changing the `>= 0.005` threshold of investigation 03 to `>= 0.0089` made rows C (the per-dataset flags and the summary count), D (the DR-03 figure) and E (the BI count) fail; the original text was restored and all 175 rows are equal again.

## 12. What this analysis does not claim
* **No finding about any real organisation, data estate, team or person.** The designed relationships (DR-01..DR-06) and the twelve injected defects are constructed; finding them shows the queries and rules work. "One team resolves twice as fast" is a property of the generator's draw.
* **The fix-first order is a judgement.** Its inputs are contract counts; the rule (severity, then inactive owner, then age) is stated and changeable. Whether claimed issues should come before open ones, or datasets with the most serious backlog before older single issues, is a decision for the accountable people; the memo gives the sensitivity.
* **The generator made two outcome-informed changes after seeing earlier draws** (a stray draw removed and the rule-change-free window around 2026-09-01 widened from 7 to 14 days), disclosed in the manifest; nothing was re-drawn on its value. Precision 0.988506 is reported as drawn.
* **Row-level measurement is authoritative at the as-of.** The stored last scheduled run of each active row-based rule equals it for 46 of 47 rules; the exception is `r-contacts-fk-customer_key` (INJ-12: its current version adds a filter, so its stored runs are not comparable, and the comparison says so).
* **Patterns are three engines' regular expressions.** Non-portable escapes are refused, so the SQL and the Python side agree on the patterns in this data; no assurance is given beyond them (D-10 R7-13).
* **Timeliness probes after the as-of read the same loaded history**; they illustrate the pending state, they are not observations.
* **All twelve injected defects appear in the reconciliation (rows D), through what they leave in the data:** INJ-01 (the override beside 0.990175), INJ-02 (the five disabled rules keep their runs and issues), INJ-03 and INJ-10 (400 distinct canonical candidates, 207 flagged as a possible household, none merged by its proposer), INJ-04 (null foreign keys counted apart, via the reference SQL), INJ-05 (scores differ between w1 and w2 on identical rows), INJ-06 (15 reversals restore both identities), INJ-07 (five uncovered datasets), INJ-08 (lineage 0.725000), INJ-09 (99 claimed), INJ-11 (15 change records, none missing) and INJ-12 (the stored run and the measurement differ for exactly one rule, whose comparison is `RULE_VERSION_DIFFERS`). The refusals themselves (409 `DUPLICATE_PAIR`, 422 `WEIGHT_CHANGE_REQUIRES_VERSION`, 409 `SELF_REVIEW`) are API behaviour that leaves no row in a snapshot; the adversarial and generator tests carry them.
* **Excel and Power BI were not run**, and no `.pbix` exists; the workbook was recalculated by LibreOffice only (`workbook.md`, `bi-package.md`).
