# ProductSignal synthetic data generator

`data/generate.py` (stdlib only, specification `docs/data-generator.md`) writes the published synthetic snapshot. A master
`random.Random(seed)` hands one child stream to each purpose (accounts, injections, users, visitors, assign, outcomes, sessions,
events, tracking, subscriptions, exposure, bots). Every probability is parts per million (or per hundred) and every draw is
`randrange`, so no float is used to decide anything; instants are `datetime` arithmetic on fixed UTC offsets; money is integer cents
until it is written as a string; nothing iterates a set of strings. Same seed gives byte-identical entity files and the same
`dataset_hash` (checked under `PYTHONHASHSEED` 0, 1, 2). The generator imports nothing from `domain/`: the activation window,
local-calendar retention, intention to treat, Wilson and Newcombe intervals and the sample-ratio chi-square are restated from
`docs/contracts.md` (D-01..D-06); `tests/test_generator.py` runs the domain over the output and compares.

```sh
python data/generate.py --seed 20261026 --out web/public/data     # about 1 s, 3.92 MB (3,916,027 bytes under web/public/data)
python data/generate.py --profile golden-shape-check              # field names vs tests/fixtures/golden
DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/productsignal python -m pytest tests/test_generator.py   # also seeds Postgres (about 30 s)
```

## Output

| File | Content |
|---|---|
| `web/public/data/<entity>.json` | `{"entity","dataset_version","rows"}` for the 12 entities of the contract: `accounts`, `users`, `identity_links`, `sessions`, `events`, `event_properties`, `subscriptions`, `experiment_versions`, `assignments`, `exposures`, `metric_observations`, `analysis_runs`. Field names equal `tests/fixtures/golden/inputs.json` (including D-05's `accounts.timezone`, `events.anonymous_id`, nullable `events.user_id`, `subscriptions.amount_usd`). Proportions `"0.600000"`, money `"49.00"`, counts integers, instants `...Z` at second precision. |
| `manifest.json` | `dataset_version` `ps-20261026-20261026`, `dataset_hash`, `generated_at` (not hashed), `contract_version` "v1", `as_of`/`cutoff` `2026-10-05T00:00:00Z`, `metric_windows`, `analysis_plan` (v1, the plan of record) and `analysis_plans` (v1, v2), `generator` (name, seed, string parameters, `disclosures`), `row_counts`, `designed_relationships` (DR-01..07, realised numbers), `injection_manifest`, `stats`. |
| `data/injection-manifest.json` (+ copy in `web/public/data/`) | `INJ-01..12` (`test` P06-TEST-01..12) with `entity`, `location`, `record_ids`, `handling_kind`, `expected_handling`, `expected_merges` and `expected_rejections` (both empty: the clean files carry no rejection), `detail`, `expected`, `replay`; and the designed relationships. |
| `data/injection-events.json` | `EV-01, 02, 03, 08, 09, 10, 11`: replay-only command sequences (`steps`, each with `expected_status` / `expected_reason`; a step input may take a value from an earlier response through `bind`: `{"into": "review_id", "from_step": 0, "path": "result.review_id"}` replaces the `$review` placeholder). They run against a seeded database through the API (`tests/test_generator.py::test_replay_events_behave_as_recorded`). |
| `web/public/data/golden/` | the fixture in the same per-entity shape (`golden-v1`), `expected.json`, `manifest.json` (with the plan and windows). |

`dataset_hash` = sha256 over the concatenation, in entity-name order, of `json.dumps(rows, sort_keys=True, separators=(",", ":"))`
per entity file (12 files).

## Loading it

`data/seed.py` loads an inputs object: `{"contract_version", "as_of", "cutoff", "analysis_plan", "metric_windows", <12 entity lists>}`;
build it from the entity files and `manifest.json` (`tests/test_generator.py::make_inputs`). It stores one plan, so v2's plan is added with
`seed.insert_plan`; `seed.py` names the load `ds-<hash12>`, so a `dataset_versions` row named `ps-20261026-20261026` is added for the
replay events (they carry the published name and a stale name is 409).

## The world

* 600 accounts (plans free 45 % / team 40 % / business 15 %, segments smb / mid / enterprise correlated with plan, timezones
  America/New_York, America/Los_Angeles, Europe/London with fixed offsets -4, -7, +1 that no transition touches in the window),
  signing up over 26 weeks 2026-04-06 .. 2026-10-04 (a weekly quota, weekday-heavy, local business hours); 12 internal (2 %).
* 1,824 users: 1,806 real + 18 bots (0.99 %), each account's creator plus invited users; 1,264 identity links (69.7 % of real
  users, rule `v1`; 15 % applied up to 30 minutes after the signup); 4,264 anonymous visitors (1,259 linked real users, 5 bots, 3,000 who
  never sign up). Pre-signup visits belong to the anonymous id; the signup event carries both ids.
* 12,552 events (`visit` 5,503, `signup` 1,845, `onboarding_step_1..3` 1,334 / 729 / 317, `activated` 263, `feature_used` 2,197,
  `product_error` 364), 2,561 properties, 3,420 sessions. `received_at` lags: seconds for most, minutes for 5 %, 237 events (1.9 %) more than
  24 h; 124 re-sent duplicates (1.0 %, 14 of them INJ-05); 30 events of an unknown identity (26 ghost user ids, 4 with no id at all);
  305 bot events and 114 internal-account events are excluded by the domain.
* 207 subscriptions on 198 accounts (33 %, team and business only; trial / active / ended / refunded; 6 % upgrade once).
* One experiment, two versions. v1 (`xv-001`): plan frozen 2026-04-05T12:00Z, 50/50 in permuted blocks of four, 400 assigned accounts
  (signups 2026-04-06 .. 07-25, so every one is mature at planned_end 2026-08-02), exposure 87 %, three interim runs (05-18, 06-15, 07-13)
  and one at planned_end. v2 (`xv-002`): re-planned 2026-08-02T12:00Z after v1's last run, plan 60/40, 154 assigned accounts (signups
  2026-08-05 .. 09-30), planned_end 2026-10-04, one run at planned_end; its randomiser sends 3 of every 5 accounts to treatment.
* Activation within 7 days: probability by plan (free 0.24, team 0.32, business 0.48) plus segment (smb 0, mid 0.03, enterprise 0.06);
  the treatment adds 0.08 (the true effect) to every assigned treatment account; 6 % of the others activate later (after day 7);
  business accounts activate sooner. Retention comes from sessions that depend on plan and on whether the account would have
  activated anyway (organic), never on the arm. Errors are 8 % of sessions. Subscriptions depend on plan and signup date.

## Designed relationships (realised numbers in `manifest.designed_relationships`; every outcome is drawn once)

| | Realised |
|---|---|
| DR-01 treatment lifts activation | v1 mature 200 / 200: control 63 (0.315000), treatment 82 (0.410000): +9.50 pp (true +8.00), relative 0.301587, Newcombe [0.000812, 0.186863]: excludes 0 (barely), final run: conclusive. The same at planned_end and at the as-of. |
| DR-02 no week-4 retention effect | 71 of 200 control (0.355000), 62 of 200 treatment (0.310000): -4.50 pp, Newcombe [-0.136053, 0.047102] includes 0. |
| DR-03 business activates faster | by plan (control and unassigned accounts, mature): business 19 / 36 = 0.527778 (median 9.62 h), team 47 / 131 = 0.358779 (22.12 h), free 26 / 117 = 0.222222 (19.27 h); by segment: enterprise 0.435897, mid 0.385714, smb 0.274286 (the segment medians are noisy: mid 5.53 h, enterprise 11.85 h, smb 22.22 h). |
| DR-04 guardrail equal | units with a `product_error` in the 7-day window: control 31 / 200 (0.155000), treatment 30 / 200 (0.150000): -0.50 pp, Newcombe [-0.076005, 0.066018] includes 0. |
| DR-05 revenue noisy | mean per assigned account USD 97.83 (control) vs 130.95 (treatment); difference +33.12, approx. 95 % [-25.40, 91.64] includes 0. |
| DR-06 sample ratio | v1 200 / 200, chi-square 0.000000, p 1.000000, OK; v2 62 / 92 against expected 92.40 / 61.60, chi-square 25.004329, p 0.000001, MISMATCH. |
| DR-07 exposure | control 175 / 200, treatment 174 / 200: 0.872500. |

## Defects: where each lives

| Defect | Entity files | Events | Domain handling |
|---|---|---|---|
| INJ-01 user-level analysis | | EV-01 | 422 UNIT_MISMATCH |
| INJ-02 treatment-dependent exclusion | | EV-02 | 422 TREATMENT_DEPENDENT_EXCLUSION |
| INJ-03 interim run presented as final (`an-002`) | `analysis_runs` | EV-03 | 409 INTERIM_RUN_CANNOT_SHIP |
| INJ-04 immature cohort (17 signups in the activation window; 10 assigned v2 accounts) | `accounts`, `events` | | excluded and counted, not rejected |
| INJ-05 duplicate activation events (14) | `events` | | dropped as duplicates, no figure moves |
| INJ-06 late event changes a funnel (8 `onboarding_step_1` received days late, 4 with an on-time `activated`) | `events` | | absent from a run at 2026-10-02T12:00Z; present later as a disclosed revision |
| INJ-07 identity link not applied backward (15 visitors, 34 earlier visits, 15 later) | `identity_links`, `events` | | earlier visits stay anonymous, later ones attributed |
| INJ-08 ignored sample ratio mismatch (v2) | `assignments` | EV-08 | MISMATCH; ship and stop 409 SRM_MISMATCH_BLOCKS_DECISION, inconclusive 200 |
| INJ-09 cherry-picked segment | | EV-09 | 422 SEGMENT_NOT_A_DECISION_BASIS; segments labelled exploratory, 3 tested, 0.016667 |
| INJ-10 zero control conversions (instrumentation gap before 2026-04-08, both arms) | `events` (no `activated`) | EV-10 | at 2026-04-15: 0/5 control, relative lift null, absolute 0.00 |
| INJ-11 exposure before assignment | | EV-11 | 422 EXPOSURE_BEFORE_ASSIGNMENT, raw row kept |
| INJ-12 exact day 7 mixed with rolling (10 late returners, 5 timezone-edge accounts; cohort 07-27 .. 08-31) | `sessions` | | two figures; rolling exceeds exact by at least 10 |

The clean files produce no ingest rejection and no merge at all (`expected_rejections` and `expected_merges` are empty everywhere); defects that
cannot sit in a clean file (a user-level request, a treatment-dependent exclusion, an interim run used to ship, a ship under a sample
ratio mismatch, a segment basis, an exposure before its assignment) are replay-only. A second assignment of a unit and a run before the freeze are covered by
`tests/test_adversarial.py` and are not repeated here.

## Outcome-informed choices (disclosed, as ServiceFlow's D-07 did)

No outcome is re-drawn, kept or dropped because of its value. These choices were made after looking at an earlier draft of the same world
(also in `manifest.generator.parameters.disclosures`):

1. **v1 uses permuted blocks of four.** The first draft used an independent fair coin per account and gave 223 control / 177 treatment (p = 0.021, still OK, but unlucky); blocks make "v1 passes the sample-ratio check" a property of the design.
2. **`product_error` is per session (8 %).** The first draft drew errors per account and gave 21.1 % of control and 34.5 % of treatment accounts with an error in the guardrail window (an interval excluding 0 from noise alone) at an unrealistic level; it was rewritten after seeing that.
3. **Counts:** v2 enrolment starts 2026-08-05 (not 08-04: 157 accounts, now 154); bounce visitors 3,000 (first draft 1,600), which puts the signup conversion of the as-of window at 0.331169.
4. **INJ-06 candidates widened** (signups until 2026-10-02T04:00Z) so other seeds also have eight; the picked accounts changed, activation outcomes did not.

The sample sizes are what they are: v1's interval just excludes 0 and v2's lift is not interpretable (sample ratio mismatch). Different seeds give different realised effects.

## Assumptions where the spec or contract was silent (for D-07)

* "The business segment" is the `business` plan (the only "business" in the vocabulary), and the correlated `enterprise` segment; "faster" is both a higher 7-day rate and a shorter median time to activation (9.62 h vs 19-22 h).
* Exposures have `event_id` null: the specification's event names have no `experiment_exposure`; both arms are exposed to the surface `onboarding_checklist` (exposure rate 0.78-0.92, higher for accounts that would activate, so exposed-only differs from ITT).
* v1 enrolment closes a week before planned_end so every assigned account is mature at the final run; v2's closes 2026-10-01 so 10 assigned accounts are immature at the as-of (INJ-04). A re-plan is a new version with its own frozen plan; v1's plan is the plan of record in `inputs.analysis_plan` (the inputs shape carries one).
* The metric windows are the defaults of README assumption 3 (7 days before the cutoff for signup conversion, funnel and adoption; activation 28 days; the retention cohort the seven local dates ending 35 days before the cutoff date).
* Analysis runs are created five minutes after their cutoff; v2 has one run at planned_end. `metric_observations` exist for every assigned account whose window is complete at the as-of (544 of 554).
* Unknown identities (30), bots (18, extra users of team and business accounts, 5 linked to anonymous ids) and internal accounts (12, with events and sessions, never assigned) are generated although the specification gives only the share; the counts are in `stats`.
* Subscriptions: 33 % of accounts, a little under "about 35 %"; amount = unit price (12.00 team, 39.00 business) x seats; the revenue window of a plan is its horizon (v1 2026-04-06 .. 2026-08-02).
* The size cap (5 MB) did not bind: every count of the specification is met at 3.92 MB; the events file is 2.04 MB.
* INJ-10 is an instrumentation gap (no `activated` for signups before 2026-04-08, both arms, 11 accounts) so that a run at 2026-04-15, when only those accounts are mature, has 0 control conversions.

## Domain behaviours noted (not patched)

* **Assignments, exposures and subscriptions are not filtered by the cutoff.** A run at an interim cutoff counts every assignment of the version in the sample ratio, every exposure in the exposure rate and every subscription starting inside the plan's revenue window, including rows dated after the cutoff (at 2026-05-18: `assigned_units` 400 and SRM 200 / 200 although 155 accounts had been assigned; revenue totals include subscriptions that start later). Events, sessions and maturity are cutoff-aware.
* `data/seed.py` stores one plan (the inputs' `analysis_plan`) and names a load `ds-<hash12>`; a multi-version experiment needs `seed.insert_plan` and an extra `dataset_versions` row (done in the test).
