# ProductSignal — UAT evidence for the review corrections (A-051 -> A-053/A-054, T-06-07)

Branch `business-data-lab`, directory `apps/productsignal/`. Decisions are in `docs/contracts.md` D-10; this file is the finding table
with before and after values and the commands that produced them. Nothing here is committed or pushed. "Before" values are the
reviewer's findings as briefed (harness, cases and API scripts in `review06/`; not re-run against the old code here); "After" values come from the commands in the last
section. Golden fixtures (`tests/fixtures/*`) are untouched and every published metric key is unchanged.

Harness: `harness.py case.json` runs hand / Python / SQL (scratch database `review06_a`) / TypeScript on one case; `api1..api4.py`
drive the API (scratch database `review06_b`).

| Finding | Before | After | Tests (Python / SQL / TypeScript / e2e) |
|---|---|---|---|
| R6-01 `conclusive` ignores `plan_frozen` | I_frozen_late: plan frozen after the first run read outcomes, `plan_frozen` false, `conclusive` true (+30.00 pp, 10/100 vs 40/100). L_equal: 0/2 vs 2/2, no logged run, `conclusive` true | `conclusive` = interval excludes 0 AND final AND hash valid AND `plan_frozen` AND SRM OK: false for I and L in Python, SQL, TypeScript and `reference_check.py`; the same data with the plan frozen first is true; no logged run is a preview (false) | `test_R6_01_*` x2, `test_the_sql_reference_equals_the_domain_on_the_review_cases`, review-check "R6-01", e2e verdict text |
| R6-02 SRM df always 1 with three arms | H_three (100/33/67 vs 0.5/0.25/0.25) accepted, p from df 1 (0.000674; df 2 would be 0.003088) | `VARIANTS_NOT_TWO` (422) in `parse_plan` (Python, TypeScript), C06 (api2 12a: 422) and the seed; the harness gives one identical rejection from all four layers | `test_R6_02_*` x3, review-check "R6-02" |
| R6-03 SQL depends on session TimeZone | K_dst_sql and B_maturity: the SQL reference gave different answers under a non-UTC session TimeZone (a `days` interval follows the zone's calendar across a DST change) | hour-based intervals (`hours => 24 * n`); K, B, C and F give 0 disagreements under America/New_York, Europe/London, Pacific/Kiritimati (tzrun.py) and the pytest cases run under all of them | `test_R6_03_*` x2 (SQL) |
| R6-04 cutoff in the future accepted | C07, C08 and GET /metrics at a cutoff after the clock: 200, run `created_at` before `cutoff_at` (api1 2a, 7; api2 13a) | 422 `CUTOFF_IN_FUTURE` on all three (api1 2a, 7; api2 13a), nothing written; the clock's own second is accepted; `created_at >= cutoff_at` for every run | `test_R6_04_*` |
| R6-05 client-controlled fact instants | `assigned_at`, `exposed_at`, `decided_at` taken from the client; event dated in the future accepted; `received_at` before `event_at`; assignment dated before a published run changed it (api2 11a-11e, api3 B/C, api4 F/H) | all three stamped with the API clock; stated instants need admin plus `backfill: true` (403 `BACKFILL_ADMIN_ONLY`, 422 `BACKFILL_FLAG_REQUIRED`, 422 `*_IN_FUTURE`), audited; `EVENT_IN_FUTURE`, `RECEIVED_BEFORE_EVENT`; `ASSIGNMENT_BEFORE_PUBLISHED_RUN` / `EXPOSURE_BEFORE_PUBLISHED_RUN`; `DECIDED_BEFORE_RUN`; a second C08 at the same cutoff returns the same figures (api2 11f) | `test_R6_05_*` x4 |
| R6-06 outcomes readable before the freeze, backdated freeze | `GET /metrics?group_by=variant` returned per-arm activation before any plan (api1 1a: 200); freeze dated 2026-09-01 after that read accepted (api3 A) | 409 `PLAN_NOT_FROZEN` with no per-arm figure (api1 1a, api3 A); plain read: `metrics.experiment` null plus warning `EXPERIMENT_WITHHELD_PLAN_NOT_FROZEN`; `FROZEN_AT_BACKDATED` when `frozen_at` precedes the latest audit instant of the version, `FROZEN_AT_IN_FUTURE` after the clock. A freeze dated in the past is still accepted when nothing was recorded for the version (api3 A: 200, nothing was read) | `test_R6_06_*` x2 |
| R6-07 refusals without audit rows | `record-decision` refusals for a segment basis, review mismatch, second decision and the ship blockers wrote no row | one central `record-decision-refused` row for every `ApiError` of C10 (rule id, role, message): 4 rows for api1 3b..4d, and DECISION_INVALID, BACKFILL_ADMIN_ONLY, ANALYSIS_UNKNOWN, REVIEW_UNKNOWN, DECIDED_BEFORE_RUN, PLAN_NOT_FROZEN too. Refusals before the handler (role, schema, idempotency) keep none | `test_R6_07_*` x2 (counts rows) |
| R6-09 outcome before assignment | J_pre_treatment: 10 accounts activated before assignment, pre-assignment activations counted in the experiment's activation, and the guardrail counted units whose window was still open | experiment activation 0/5 vs 0/5 in all four (the generic activation metric stays 10/10); guardrail eligible 0 (window incomplete); C04 refuses an account that already activated (422 `OUTCOME_BEFORE_ASSIGNMENT`, admin backfill excepted); observations and segments use the same rule. Golden exact; snapshot v1 unchanged; v2 (SRM MISMATCH, lift withheld) loses one pre-assignment activation: treatment 39/87 (was 40/87) | `test_R6_09_*` x4, review-check "R6-09" |
| R6-13 Bonferroni k | k = segments tested in the one split shown (3) | the segments page uses k = 9 across plan, segment and timezone (threshold 0.005556); the API keeps its per-split k; documented in D-10 | `test_R6_13_*`, golden-check "segments_family", e2e |
| R6-14 `conclusive` and SRM | `conclusive` true under an SRM MISMATCH | `conclusive` also requires SRM OK; NOT_CONCLUSIVE warning lists the five reasons; the decision page lists them | `test_R6_14_*` |
| R6-08 INJ-10 gap | disclosed only for the 2026-04-15 read | 11 v1 accounts (control 5, treatment 6) are affected at the as-of; control 63/200 unchanged, treatment 82/200 published vs 86/200 drawn: published +9.50, drawn +11.50, +9.96 without the gap accounts. In `data/README-generator.md` (DR-01, INJ-10), `manifest.json` DR-01 `instrumentation_gap_disclosure`, `injection-manifest.json` INJ-10 `reaches_the_as_of_read`, and the result and case-study pages (`gap-note`) beside "conclusive by a hair". Entity files byte-identical (`python data/generate.py` leaves them unchanged; `dataset_hash` unchanged, `generated_at` moves) | `test_R6_08_*`, review-check "R6-08", e2e |
| R6-10 secondary intervals, linked share | week-4, guardrail and revenue differences were manifest figures only | computed in the browser: week-4 -4.50 pp, Newcombe including 0 (equal to the generator's DR-02, 71/200 vs 62/200); guardrail -0.50 pp including 0; revenue 97.83 vs 130.95 with a Welch interval including 0 (Python restates and the independent snapshot reference agrees); the tracking page shows linked real users of all real users | `test_R6_10_*` x3, golden-check "secondary", review-check, e2e |
| R6-11 / R6-12 wording | "identity links" unqualified; "on-or-after" accounts unlabeled; "p 0.000001" | forward-only identity links, exact day 7 against on-or-after day 7, "p < 0.000001" (exact 5.7e-7) | review-check, e2e (`cs-p`) |

## Reviewer harness after the fixes (hand / Python / SQL / TypeScript)

| Case | Result |
|---|---|
| A, B, C, D, E, F, G, M | 0 disagreements |
| H_three | rejected by all four with `VARIANTS_NOT_TWO` (the text differs only in the language wrapper) |
| I_frozen_late | 0 disagreements; `plan_frozen` false, `conclusive` false |
| J_pre_treatment | 0 disagreements; experiment activation 0/5 vs 0/5, guardrail eligible 0 (hand values) |
| K_dst_sql, B_maturity | 0 disagreements under UTC, America/New_York, Europe/London, Pacific/Kiritimati |
| L_equal | 0 disagreements; `conclusive` false |

## Not changed and why

* A plan frozen in the past is accepted when nothing was recorded for the version (the lower bound is the latest audit instant).
* The API's single-split segment read keeps k = segments tested in that split (R6-13 documented, the site uses the family).
* Refusals before the C10 handler (forbidden role, schema, idempotency conflicts) keep no audit row.
* The DB suite takes about three and a half minutes; the deadlock retry is tested by injection.

## Commands and results (from `apps/productsignal`, 2026-10-27)

| Command | Exit | Result |
|---|---|---|
| `../../.venv/bin/python -I tests/reference_check.py` | 0 | ALL OK (706 checks) |
| `DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/productsignal ../../.venv/bin/python -m pytest -q -p no:cacheprovider` | 0 | 357 passed |
| `harness.py` on cases A..M (scratch database), `tzrun.py` | 0 | see the table above |
| `api1.py` .. `api4.py` (and `api1b.py`, api1 with the clock moved on after section 3) | 0 | new statuses as in the findings table |
| `../../.venv/bin/python data/generate.py` | 0 | entity files byte-identical (git shows no change under `web/public/data/<entity>.json`) |
| `../../.venv/bin/python web/scripts/make-snapshot-reference.py` | 0 | written; v1 digests equal, v2 digests changed (R6-09), segments_family and secondary added |
| `npm run check` (web/) | 0 | typecheck clean; golden ALL OK (2519 checks); review OK (36 checks) |
| `npm run build:pages` (web/) | 0 | built, 12 route copies |
| `npm run e2e` (web/) | 0 | 77 passed |
