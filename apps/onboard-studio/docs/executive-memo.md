# Executive memo: adopt workflow v2, and how to handle exceptions? (P02-ART-07)

To: head of onboarding and compliance lead of "Harbor Financial Services" (simulated, `business-case.md`). From: Onboard Studio analyst workbench. Contract v1, snapshot `os-20261026-20261026`.
**Every person, company and figure here is synthetic.** The numbers come from `data/sql/analysis/` run on a generated dataset (`sql-analysis.md`, `artifacts/analysis-results.json`) and were reconciled to the Python domain and `data/sql/reference_metrics.sql`; none is a real saving, delay or forecast.

## Decision
Which onboarding workflow should be adopted, and how should exceptions be handled? (P02-GOAL-01). The business case's rule: adopt the version with lower active elapsed time and fewer handoffs on the same calendar and population, provided its first-pass approval and document completeness are not worse.

## Answer the data supports
**On this synthetic data v2 meets the adoption rule: lower active time, fewer handoffs, first pass not worse. The size of the active-time gain depends on how customer waiting is classified, and rework is higher. Exceptions are rare, owned and already separable by rule.**

Comparison on the **overlapping window** only (cases opened 2025-10-01 to 2026-09-30, when both versions ran; v2 was published 2025-10-01; query `02_version_comparison_comparable_window`):

| Rule input (completed cases) | v1 (`wfv-001`) | v2 (`wfv-002`) | Reading |
|---|---|---|---|
| Cases | 178 completed, 10 open | 282 completed, 8 open | v1 is a smaller, later cohort here |
| Active elapsed hours (mean) | 9.2503 | 5.8690 | 3.3813 h (36.6 %) lower for v2; rough 95 % interval 3.0864 to 3.6762 h |
| Handoffs per completed case | 1.2135 | 0.8865 | 26.9 % fewer (20.1 % fewer against v1's all-window mean 1.1093) |
| SLA attainment (480 business minutes) | 0.258427 | 0.950355 | open cases reported beside, not inside |
| First-pass approval | 0.933036 | 0.941718 | not worse |
| Document completeness (completed cases) | 1 | 1 | every completed case has all required documents (checked); cannot separate the versions |
| Rework rate | 0.160428 | 0.193772 | v2 3.3 percentage points higher |

Where the gain comes from (same query): v2 has fewer **business** hours per case (16.8776 against 18.7568, 1.8792 h or 10.0 % lower) and more business hours deducted as customer waiting (11.0086 against 9.5066 h, 1.5020 h more). The deduction is 44 % of the active-time gap.
If no waiting reason were pause-eligible, active time would equal business time and SLA attainment would be 0.290780 (v2) against 0.056180 (v1): v2 is ahead in both states, but the "36.6 %" is specific to the pause policy `customer_info_requested` and `external_verification`.

Other evidence for how to run the process:

| Finding | Evidence (query) | What it suggests |
|---|---|---|
| Wall-clock time overstates work | calendar 79.9529 h against business 18.5028 h per completed case, a factor of 4.32 (`01_cycle_time_by_opening_month`) | judge SLA on the working calendar, not calendar days |
| The slowest step is `approve_account`, and it is one reviewer | step waiting 1.0491 business hours, next 0.5163; `rev-004` 1.7855 h against 0.5398 and 0.5451 for `rev-005`, `rev-006` (3.3 times); by assignee 0.9711 to 1.1281 only (`04_step_waiting_by_step_assignee`) | look at decision ownership and queue routing for approvals; an assignment-only view would miss it |
| Customer waiting is regional | `reg-north` 59.0534 paused hours per case against 26.2899 to 30.5270 elsewhere; 84.6 % of its cases wait against 68.0 % to 70.3 % (`06_paused_time_by_reason_region`) | keep customer waiting visible and separate from processing; target reminders by region |
| Rework is an enterprise identity-proof problem | enterprise rework 0.290123 against 0.142384 (smb) and 0.172285 (mid_market); `identity_proof` first pass 0.759259 for enterprise (`05_rework_first_pass_by_segment`) | a clearer identity-document checklist for enterprise is the first thing to try |
| Backlog stepped up in 2026-03 | open cases 8 at 2026-02 month-end, 17 at 2026-03, 21 at the end (`07_backlog_month_ends`) | watch the stock; the data do not say why |
| Exceptions are few and classified | 269 rejected rows = 7 cases (2 missing document, 3 wrong pause reason, 2 self-approval) with their rows, plus 2 conflicting decisions; 3 pauses outside working time flagged at 0 business hours (`08_flags_and_rejections_by_reason`) | below |

Reconciliation holds: the golden case's business hours are 2.0000 from the analysis SQL, from `reference_metrics.sql` and from the Python domain; the snapshot's population means equal the reference to 4 decimals, and all 712 completed cases equal the domain one by one (37 reconciliation rows, all equal; `sql-analysis.md`).

## Options
1. **Adopt v2 for all new cases.** Supported by the rule above. Cost: v2's rework is higher and the headline gain rests on the pause policy.
2. **Adopt v2 for new cases and keep v1 for open ones.** The contract already binds a case to its version for life (D-02), so there is no forced migration; the migration command (C10) is not implemented in the slice.
3. **Run both and decide later.** Cheap, but the 13 open cases still on v1 and the 3.3 point rework difference stay unresolved.
4. **Fix approvals first.** Rebalance `approve_account` away from the one slow reviewer; query 04 says this is the largest step delay. It is independent of the version choice.

Exception handling the data supports (all of it is existing rules, not new ones). Refuse at ingest and keep the raw row for any case that completes with a missing required document (owner named in the business case: the case owner), that waits for a reason outside the pause policy, or that was approved by its own assignee
(the business case names no owner for these two; the compliance lead is the natural one for self-approval, which is a suggestion). Accept a pause outside working time but count it as 0 business hours and flag it (owner: the team lead). On two decisions for one step version keep the first and reject the second (owner: the compliance lead).
7 of 740 generated cases (0.9 %) fell into the three case-level rules.

## Uncertainty
* **Sampling.** One synthetic dataset, one seed; the interval above treats cases as independent and covers sampling variation only. No other interval is computed here.
* **Pause policy.** The v2 advantage is 36.6 % with both waiting reasons pause-eligible and 10.0 % (business hours) with none; which is right is a policy decision, versioned in `sla_rules.pause_policy`, not a data question.
* **Version mix.** The snapshot documents v2 as taking 60 % of cases from its publication; the segment and region mix of the two cohorts is similar (enterprise 18.4 % against 20.2 %, `reg-north` 21.6 % against 22.5 %), but a real rollout would not be assigned this evenly.
* **Rework.** The 3.3 point difference is one overlap-window comparison of 460 completed cases; v2 requires an extra document type (`address_proof`), which can explain more rejections, but this analysis did not test that.

## Limitations
* **Synthetic and designed-in.** The generator planted four relationships (v2 faster, enterprise rework about 2x, `reg-north` waiting, a `rev-004` bottleneck; `data/injection-manifest.json`). Finding them shows the analysis can detect such effects; it does not show they exist in any business.
* **Open defects in the product** (independent review, `docs/program/verification-ledger.json` entry of 2026-10-26T13:25:24Z, status failed, fix task T-02-07 pending): completion accepted before recorded work (Q-01), a lock-order deadlock (Q-02), the reference SQL's per-case truncation and wait double counting (Q-03, no effect on these figures, `sql-analysis.md`), and four suspected issues (Q-04..Q-07). The case study text must be re-checked against the computed figures after the fixes.
* **Not analysed:** exceptions by version, the simulated capacity gain (a modelled direction, P02-MET-12, never a saving), reassignment and migration (C07, C10 return 501), the web app's browser simulation.
* No real stakeholders, interviews or measured adoption (P02-DOMAIN-06).

## Recommendation
On what this synthetic data supports: **adopt v2 for new cases**, keep v1 cases on v1 until they complete, and handle exceptions by the rules above. Before treating the 36.6 % as a finding about any real process, confirm the pause policy with customer success, look at the 3.3 point rework increase (start with the `address_proof` step), and fix the `approve_account` queue for `rev-004`. These are directions for review, **not real savings**: no time, cost or capacity gain is claimed, and a real decision would need real case data.
