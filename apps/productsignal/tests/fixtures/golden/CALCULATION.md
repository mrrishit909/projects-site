# ProductSignal golden calculation (contract v1, decisions D-01..D-04)

Independent of application code. `../../reference_check.py` recomputes every figure below from `inputs.json` and compares it
with `expected.json` leaf by leaf (standard library only, no app imports, no float: `fractions.Fraction` and `decimal.Decimal`,
square roots by integer Newton iteration, error far below the contract's 1e-8). The figures on this page were worked by hand
from the input rows (counts by rule, ratios, Wilson and Newcombe arithmetic, chi-square, t-interval) and cross-checked with a
separate throw-away float script (`math.sqrt`, plain calendar arithmetic, a numeric t-CDF integral); `expected.json` was then
written from the reference's output after those figures agreed. Formats (D-04): proportions 6 dp, percentage points 2 dp,
money 2 dp, counts integers, `null` for a zero denominator. Rounding: ROUND_HALF_UP (DECISIONS D-P6-1).

## The spec sentence [P06-GOLD-01]

> Control: 20 activations among 100 mature assigned accounts; treatment: 30 among 100. Absolute lift = 10 percentage points;
> relative lift = 50%. These counts alone do not guarantee a statistically conclusive result. Retention fixture: 5 of 20 mature
> accounts returning on day 7 gives 25%.

Cutoff `2026-10-26T00:00:00Z`, `as_of` `2026-10-26T00:10:00Z`. One experiment version `xv-001`, unit = account, allocation 50/50,
frozen plan (`frozen_at` 2026-09-30T12:00Z, before every assignment and every outcome), `planned_end` 2026-10-15T00:00Z, before the
cutoff. Five parts share one event log (rows are in `inputs.json`; ids are the keys below).

## Part A: the experiment (accounts `acc-c-001..100`, `acc-t-001..100`)

**Generating rule** (all 200 accounts: plan team, segment smb, timezone UTC, one user `u-<k>`, one `signup` event):

* signup instant: control `2026-10-01T09:00Z + (i-1) minutes`, treatment `2026-10-01T11:00Z + (i-1) minutes` (i = 1..100).
  All 200 are mature: 2026-10-01 + 7 d = 2026-10-08 <= cutoff.
* assignment `as-<k>` at signup + 1 min (variant by prefix); observation `ob-<k>` (`activated_7d`, "1"/"0", window_end = signup + 7 d).
* activation: control i = 1..19 an `activated` event at signup + 2 h; **i = 20 at signup + 6 d 23 h 59 m 59 s** (inside, counts);
  **i = 21 at exactly signup + 7 d** (half-open window, does NOT count). Treatment i = 1..29 at + 2 h; i = 30 at + 6 d 23:59:59
  (counts); i = 31 at exactly + 7 d (does not count).
* exposures: control `acc-c-001..090` exposed (event `experiment_exposure`, one minute after assignment, surface
  `onboarding_checklist`); `acc-c-091..100` unexposed. Treatment `acc-t-011..100` exposed; **`acc-t-001..010` unexposed**.

### Primary outcome (D-02, D-03), intention to treat

| | assigned | mature | activated within [signup, signup + 7 d) | conversion |
|---|---|---|---|---|
| control | 100 | 100 | 20 (i = 1..20; the day-7 event of i = 21 is outside) | 20/100 = **0.200000** |
| treatment | 100 | 100 | 30 (i = 1..30; i = 31 is outside) | 30/100 = **0.300000** |

* Absolute lift = (0.30 - 0.20) x 100 = **10.00** percentage points. Relative lift = 0.10 / 0.20 = **0.500000**.
* Every unexposed account stays in its variant (ITT). Exposed-only (labelled exploratory, never a decision basis): control 20/90 =
  0.222222, treatment 20/90 = 0.222222 (the ten unexposed treatment accounts were all activated), so exposed-only would show lift
  0.00 pp where ITT shows 10.00 pp.
* Exposure rate (D-03, MET-09, over mature assigned accounts): control 90/100 = 0.900000, treatment 90/100 = 0.900000, overall
  180/200 = **0.900000**.

### Wilson intervals (z = 1.959964, z^2 = 3.841458881296)

Wilson: centre = p + z^2/(2n); half = z x sqrt(p(1-p)/n + z^2/(4n^2)); bounds = (centre -/+ half) / (1 + z^2/n).
With n = 100: z^2/n = 0.03841459, denominator 1.03841459, z^2/(4n^2) = 0.0000960365.

| | p | centre | radicand | sqrt | half | low | high |
|---|---|---|---|---|---|---|---|
| control | 0.20 | 0.21920729 | 0.0016 + 0.0000960365 = 0.0016960365 | 0.04118296 | 0.08071713 | (0.21920729 - 0.08071713) / 1.03841459 = **0.133367** | (0.21920729 + 0.08071713) / 1.03841459 = **0.288829** |
| treatment | 0.30 | 0.31920729 | 0.0021 + 0.0000960365 = 0.0021960365 | 0.04686189 | 0.09184761 | **0.218949** | **0.395849** |

### Newcombe hybrid score interval for the difference (treatment - control), 95 %

d = 0.30 - 0.20 = 0.10. With group 1 = treatment (p1 = 0.30, l1 = 0.21894885, u1 = 0.39584855) and group 2 = control
(p2 = 0.20, l2 = 0.13336693, u2 = 0.28882917):

* lower = d - sqrt((p1 - l1)^2 + (u2 - p2)^2) = 0.10 - sqrt(0.08105115^2 + 0.08882917^2) = 0.10 - sqrt(0.0144599093) =
  0.10 - 0.12024936 = **-0.020249** (-2.02 pp)
* upper = d + sqrt((u1 - p1)^2 + (p2 - l2)^2) = 0.10 + sqrt(0.09584855^2 + 0.06663307^2) = 0.10 + sqrt(0.0136269096) =
  0.10 + 0.11673435 = **0.216734** (21.67 pp)

The interval [-0.020249, 0.216734] includes 0, so the result is **not conclusive** although the run is after `planned_end` and the plan
is frozen (D-03: conclusive needs the interval to exclude 0 AND a run at or after `planned_end` of a frozen plan).
Check of the method: the same function reproduces Newcombe (1998) 56/70 vs 48/80 at z = 1.96: (0.0524, 0.3339).

### Sample ratio (MET-10)

Observed assigned 100 / 100; expected 200 x 0.5 = 100.00 each (both >= 5). chi-square = (100-100)^2/100 + (100-100)^2/100 =
**0.000000**, df 1, p = erfc(sqrt(0/2)) = **1.000000** >= 0.001: verdict **OK**.

### Analysis runs (D-03, TEST-03)

`an-001` cutoff 2026-10-10 (before `planned_end`, so **interim**, created 2026-10-10T00:05Z) and `an-002` cutoff 2026-10-26 (this
run, created 2026-10-26T00:05Z, not interim). Prior runs shown with the result: **1**. Both cite `config_hash` =
sha256 of the canonical JSON of the plan (without `config_hash`); it matches. Plan frozen 2026-09-30T12:00Z <= first run.

### Guardrail error rate (MET-11), window [assigned_at, assigned_at + 7 d), per variant, accounts with >= 1 `product_error`

* control: `acc-c-005` (two errors, +1 d and +2 d), `acc-c-050` (+3 d), `acc-c-099` (+1 d; unexposed, still counted by ITT) =
  3 accounts / 100 = **0.030000**.
* treatment: `acc-t-005` (+1 d), `acc-t-040` (+2 d), `acc-t-077` (+3 d), `acc-t-100` (+4 d) = 4 / 100 = **0.040000**.
  `acc-t-060` has an error at +8 d, outside the window: not counted.

### Revenue per assigned account (MET-12), subscriptions with `starts_at` in [2026-10-01, 2026-10-15), status active or ended

| account | starts_at | status | amount | counted |
|---|---|---|---|---|
| acc-c-003 | 10-03 | active | 49.00 | yes |
| acc-c-020 | 10-05 | ended | 99.00 | yes |
| acc-c-060 | 10-06 | trial | 29.00 | no (status) |
| acc-c-070 | 09-20 | active | 79.00 | no (starts before the window) |
| acc-c-080 | 10-15T00:00:00Z | active | 59.00 | no (window is half-open) |
| acc-t-002 | 10-03 | active | 49.00 | yes |
| acc-t-015 | 10-07 | ended | 99.00 | yes |
| acc-t-016 | 10-08 | active | 149.00 | yes |
| acc-t-090 | 10-09 | refunded | 29.00 | no (status) |
| acc-t-095 | 10-16 | active | 19.00 | no (after the window) |

* control: total 148.00 over 100 accounts, mean **1.48**. Account values: 49, 99 and 98 zeros. sum x^2 = 2401 + 9801 = 12202;
  sum (x - mean)^2 = 12202 - 100 x 1.48^2 = 12202 - 219.04 = 11982.96; s^2 = 11982.96 / 99 = 121.04; se = sqrt(121.04 / 100) = 1.100182;
  t(0.975, 99) = 1.984217; half = 2.183; interval **[-0.70, 3.66]**.
* treatment: total 297.00, mean **2.97**. Values 49, 99, 149 and 97 zeros: sum x^2 = 2401 + 9801 + 22201 = 34403; SS = 34403 - 882.09 =
  33520.91; s^2 = 338.595; se = sqrt(3.38595) = 1.840095; half = 3.651; interval **[-0.68, 6.62]**.
* Both intervals contain 0: revenue is noisy and inconclusive, as designed.

## Part B: retention cohort `acc-r-01..20` (D-02, MET-04/05, TEST-12)

Cohort = accounts whose signup day in the account timezone is in [2026-09-14, 2026-09-21). Signup instant 2026-09-14T12:00Z for all
except `acc-r-20` (2026-09-15T03:00Z = 2026-09-14 20:00 Los Angeles, so day 0 is 09-14, not 09-15). Timezones: r-01..10 UTC,
r-11..16 America/New_York (UTC-4 until 2026-11-01), r-17..20 America/Los_Angeles (UTC-7). Day 0 = 2026-09-14 everywhere, so day 7 =
2026-09-21 local, day 8 = 09-22, days 28..34 = 10-12..10-18, day 35 = 10-19. Cutoff 2026-10-26 is past day 35 in every zone, so all 20 are
mature for day 7 (day 8 begun) and for week 4 (day 35 begun). Sessions (UTC instant = local time, day index):

| acc | tz | day 0 | plan | sessions |
|---|---|---|---|---|
| r-01 | UTC | 2026-09-14 | team | 09-15T09:00Z = 09-15 09:00 local, day 1; 09-21T10:00Z = 09-21 10:00 local, day 7; 10-12T12:00Z = 10-12 12:00 local, day 28 |
| r-02 | UTC | 2026-09-14 | team | 09-21T23:59:59Z, day 7; 10-18T23:00Z, day 34 |
| r-03 | UTC | 2026-09-14 | team | 09-20T23:59:59Z, day 6 (one second before day 7) |
| r-04 | UTC | 2026-09-14 | team | 09-17T09:00Z, day 3; **09-22T09:00Z, day 8 (returns only on day 8)**; 10-19T00:00:00Z, day 35 |
| r-05 | UTC | 2026-09-14 | team | 09-17T11:00Z, day 3 |
| r-06 | UTC | 2026-09-14 | team | `u-r-06` 09-21T08:00Z, day 7 and its second user `u-r-06b` 09-21T09:00Z, day 7 (one account, counted once) |
| r-07 | UTC | 2026-09-14 | team | 09-22T00:00:00Z, day 8 (first instant of day 8) |
| r-08, r-09, r-10 | UTC | 2026-09-14 | team | one session each on day 1 |
| r-11 | New York | 2026-09-14 | team | 09-15T14:00Z = 09-15 10:00 local, day 1 |
| r-12 | New York | 2026-09-14 | team | **09-22T02:00Z = 09-21 22:00 local, day 7 only because of the timezone** (UTC date is 09-22); 10-19T02:00Z = 10-18 22:00 local, day 34 |
| r-13 | New York | 2026-09-14 | free | 09-21T02:00Z = 09-20 22:00 local, **day 6** (UTC date 09-21 would say 7) |
| r-14 | New York | 2026-09-14 | free | 09-23T14:00Z = 09-23 10:00 local, day 9 |
| r-15 | New York | 2026-09-14 | free | 09-20T15:00Z, day 6; 09-24T15:00Z, day 10 |
| r-16 | New York | 2026-09-14 | free | 09-15T16:00Z, day 1 |
| r-17 | Los Angeles | 2026-09-14 | free | 10-13T08:00Z = 10-13 01:00 local, day 29 |
| r-18 | Los Angeles | 2026-09-14 | free | **09-22T05:00Z = 09-21 22:00 local, day 7 only because of the timezone** |
| r-19 | Los Angeles | 2026-09-14 | free | 09-22T08:00Z = 09-22 01:00 local, day 8 |
| r-20 | Los Angeles | 2026-09-14 (signup 09-15T03:00Z) | free | 09-22T08:00Z = 09-22 01:00 local, **day 8** (a UTC-day reading would call it day 7); 10-12T05:00Z = 10-11 22:00 local, day 27 |

* **Day-7 retained** (a session on exactly day 7): r-01, r-02, r-06, r-12, r-18 = **5 of 20 = 0.250000**.
* **On or after day 7** (any session on day >= 7, a different figure, never mixed in): the five above plus r-04 (day 8), r-07 (day 8),
  r-14 (day 9), r-15 (day 10), r-17 (day 29), r-19 (day 8), r-20 (day 8) = **12 of 20 = 0.600000**.
* **Week 4** (a session on any of days 28..34): r-01 (day 28), r-02 (day 34), r-12 (day 34), r-17 (day 29) = **4 of 20 = 0.200000**.
  Not counted: r-04 (day 35), r-20 (day 27).
* Excluded: internal account `acc-int-1` (signup 2026-09-15, a day-7 session on 09-22) is inside the signup window; counting it
  would make 21 accounts and 6 day-7 retained. `excluded_internal_accounts` = 1.

## Part C: funnel and signup conversion (window [2026-10-05, 2026-10-12), steps visit -> signup -> onboarding_step_1 -> activated,
maximum gap 48 h between consecutive steps, inclusive; step k must come strictly after step k-1)

Visitor key = the `anonymous_id` (identity links connect the signed-up user's own events to it). Chain anchored on the visitor's
earliest `visit` in the window. Event times are 2026-10-DDThh:mm.

| visitor | visit(s) | signup | step_1 | activated | steps reached | note |
|---|---|---|---|---|---|---|
| a-f01 | 05T09:00 | 05T09:10 | 05T09:30 | 05T10:00 | 4 | |
| a-f02 | 06T09:00 | 06T09:05 | 06T09:30 | 07T09:00 | 4 | step_1 -> activated 23.5 h |
| a-f03 | 06T12:00 | 06T12:10 | 06T12:30 | 08T12:30 | 4 | exactly 48 h, inclusive |
| a-f04 | 06T08:00, 08:30 (anonymous), 10:00 (after the link) | 06T09:00 | 06T09:20 | 06T11:00 | 4 | linked 06T09:01 (below) |
| a-f05 | 07T07:00 | 07T07:10 | 07T07:30 | 07T08:00, **received 09T08:00** | 4 | delayed 48 h, received before the cutoff, so it counts |
| a-f06 | 07T09:00 | 07T09:10 | 07T09:30 | 09T09:00, **received 2026-10-26T00:05Z** | 3 | received after the cutoff: excluded from this run |
| a-f07 | 07T10:00 | 07T10:10 | 07T10:30 | 09T11:30 | 3 | 49 h after step_1: gap exceeded (but within 7 d of signup) |
| a-f08 | 08T09:00 | 08T09:10 | 08T09:30 | none | 3 | |
| a-f09 | 08T10:00 | 08T10:10 | none | none | 2 | |
| a-f10 | 05T14:00 | 08T14:00 | none | none | 1 | signup 72 h after the visit: gap exceeded (still a signup in the window) |
| a-f11 | 09T09:00 | 09T09:10 | **none** | 09T09:40 | 2 | skipped step_1: activated cannot count (strict order) |
| a-v01..v04 | 09T12:00, 09T13:00, 10T09:00, 11T23:59:59 | none | | | 1 | visit only |
| a-v05, a-v06 | 12T00:00:00 and 04T23:59:59 | none | | | not in the funnel | outside the half-open window |

* Funnel units: visit **15** (f01..f11 and v01..v04), signup **10** (f01..f09, f11), onboarding_step_1 **8** (f01..f08), activated
  **5** (f01..f05). Step conversions: 10/15 = 0.666667, 8/10 = 0.800000, 5/8 = 0.625000; overall 5/15 = **0.333333**.
* Signup conversion (MET-01, visitor unit, no gap): 15 visitors with a `visit` in the window; 11 of them (f01..f11) have a `signup`
  with the same `anonymous_id` in the window = 11/15 = **0.733333**. f10 counts here but not in the funnel (the gap).

## Part D: activation within 7 days (MET-02), signups in [2026-10-05, 2026-10-26)

Account signup_at = earliest `signup` of its non-bot users. Population: accounts of f01..f11 (11 signups) plus `acc-m-01`
(2026-10-20T10:00Z) and `acc-m-02` (2026-10-19T00:00:00Z) = 13 signups. `acc-m-01` + 7 d = 2026-10-27 > cutoff: **immature**, excluded
and counted (its activation does not count). `acc-m-02` + 7 d = 2026-10-26T00:00:00Z <= cutoff: **mature on the boundary**.
Mature = 12. Activated within [signup, signup + 7 d): f01, f02, f03, f04, f05, f07 (+2 d, although the funnel gap failed), f11 (no step_1,
but activated), m-02 = **8**; not: f06 (its event arrives after the cutoff), f08, f09, f10. 8/12 = **0.666667**.

## Part E: identity, duplicates, delays, exclusions, tracking quality (D-01)

* Rows: 236 `signup` (one per user) + 63 `activated` (control 21, treatment 31 incl. the two day-7 edge events, f 8, bot 1, m 2) + 180
  `experiment_exposure` + 9 `product_error` + 10 `feature_used` + 22 `visit` (f 13, v 6, bot 1, internal 1, ghost 1) + 9
  `onboarding_step_1` (f 8, bot 1) = **529 rows**.
* Received after the cutoff: 1 (f06's `activated`, ev-f06-act). Received by the cutoff: 528.
* **Duplicate**: `ev-fu-r01-dup` re-sends `ev-fu-r01` (user u-r-01, `feature_used`, 2026-09-21T10:10:00Z, property feature = export) under a new
  event_id, received 7 s later: dropped, counted (1). Not a duplicate: `ev-fu-r02-exp` / `ev-fu-r02-imp` (same user, name and instant,
  properties export vs import) both stay. Canonical = 528 - 1 = **527**.
* **Delayed** (received - event_at > 24 h, among the 527): `ev-f05-act` only (48 h) = 1. f06's event is also late but is outside this run.
* **Unknown identity**: `ev-ghost` (user_id `u-ghost` does not exist, no link) = 1, excluded.
* **Bot**: user `u-bot-1` (account `acc-bot-1`, bot_flag true): 4 events (visit, signup, step_1, activated), excluded. With them out, that account
  has no signup, so it is in no cohort.
* **Internal**: account `acc-int-1`, 3 events (signup 09-15, feature_used 09-22, visit 10-06), excluded.
* Analysed events = 527 - 1 - 4 - 3 = **519**.
* **Identity (time-aware link)**: 19 analysed events have no user_id (the 13 visits of f01..f11, f04 having three, plus the 6 visits of v01..v06) = **19**.
  Links: each of f01..f11 is linked at its signup instant (f04 at 06T09:01, one minute after its signup event). The only anonymous event
  at or after a link is `ev-f04-visit3` (10:00) = **1 attributed by link**; the other **18 stay anonymous** (the 12 visits before a link,
  including f04's two at 08:00 and 08:30, and the 6 events of never-linked visitors v01..v06). Events before `linked_at` are never
  re-attributed backwards.

## Part F: feature adoption of `export` (MET-06), window [2026-09-21, 2026-09-28)

Eligible = non-internal account on plan team or business (decided from the plan, which exists before and independently of any
outcome) with at least one non-bot session started in the window: r-01 (09-21T10:00), r-02, r-04 (09-22), r-06, r-07 (09-22T00:00),
r-12 (09-22T02:00Z) = **6**. Not eligible: r-03 (session before the window), r-05, r-08..r-11 (day 1), free-plan accounts r-13..r-20, and
`acc-int-1` (internal, plan business). Adopters (a non-duplicate `feature_used` with feature = export in the window): r-01, r-02, r-06
(`u-r-06b`), r-12 (09-27T12:00) = **4**. Not: r-04 (event at exactly 09-28T00:00:00Z, half-open), r-02's `import`. Rate 4/6 = **0.666667**.
`use_events` = 4 (the re-sent r-01 event is not counted twice; counting it would give 5).

## Part G: ingest counts

accounts 235 (200 + 20 + 1 internal + 11 f + 1 bot + 2 m), users 236 (the same plus the second user r-06b), identity_links 11, sessions 30
(27 in the Part B table for r-01..r-20 except r-06, plus r-06's two, plus `s-int-1`), events accepted 527 (1 merged as a
duplicate; 1 more received after the cutoff and held out), event_properties 379 (2 x 180 exposures + 9 errors + 10 feature events),
subscriptions 10, experiment_versions 1, assignments 200, exposures 180, metric_observations 200 (each equals the recomputed
activation and window_end), analysis_runs 2. Nothing rejected in the golden case.

## Part H: variant-rejected

Small experiment: `acc-c-001..012` (control), `acc-t-001..008` (treatment); signups from 2026-10-01 as in Part A, all mature; activations:
`acc-t-001..003` only. Plan, cutoff and windows as in the golden case. Rejected:

* `as-c-003-b`: a second assignment of `acc-c-003` (already control since 2026-10-01T09:03Z) to **treatment** at 2026-10-02T09:00Z:
  **ASSIGNMENT_CONFLICT**. The first assignment fixes the variant.
* Dependants of that assignment: exposure `ex-c-003-b` and observation `ob-c-003-b` carry **DEPENDENT_REJECTED**.
* `ex-t-004`: exposure at 2026-10-01T11:02:00Z of an assignment made at 11:04:00Z: **EXPOSURE_BEFORE_ASSIGNMENT**. (The raw
  `experiment_exposure` event stays in the immutable log; it just is not an accepted exposure.)

Why rejection is correct: accepting `as-c-003-b` would put one account in both arms (21 assignments for 20 accounts, observed
12 / 9 and an SRM computed on units that are not distinct), and would let an account that has already been treated as control flip to
treatment, which is contamination of the very comparison. Accepting `ex-t-004` would count as exposed an account that saw the
checklist before it was assigned, so the exposure rate and any exposed-only analysis would credit exposure to the assignment that had
not happened yet.

Figures after rejection (counts: assignments 20 accepted / 1 rejected, exposures 17 / 2, observations 20 / 1):

* SRM: observed 12 / 8 against expected 10 / 10 (both >= 5): chi-square = 2^2/10 + 2^2/10 = **0.800000**, p = erfc(sqrt(0.4)) =
  **0.371093**: OK.
* Conversion: control 0/12 = 0.000000 (Wilson [0.000000, 0.242494]); treatment 3/8 = 0.375000 (Wilson [0.136844, 0.694258]).
  Absolute lift 37.50 pp. **Relative lift null** (control conversion is 0, TEST-10), never infinity or 0.
* Newcombe: d = 0.375; lower = 0.375 - sqrt(0.23815572^2 + 0.24249401^2) = 0.375 - 0.33988452 = **0.035115**; upper =
  0.375 + sqrt(0.31925761^2 + 0^2) = **0.694258**. Excludes 0; the run is after `planned_end` and the plan is frozen, so `conclusive` true.
* Exposure: control 10/12 = 0.833333 (acc-c-001..010), treatment 7/8 = 0.875000 (all but t-004), overall 17/20 = 0.850000.
  Exposed-only (exploratory): control 0/10 = 0.000000, treatment 3/7 = 0.428571.
* Guardrail: no errors, 0/12 = 0.000000 and 0/8 = 0.000000 (a zero rate, not null: the denominators are positive).
* Revenue: one subscription, `acc-t-002` 20.00 in the window. Control mean 0.00, interval [0.00, 0.00] (t(11) = 2.200985, zero variance);
  treatment mean 20/8 = 2.50, s^2 = (400 - 8 x 2.5^2)/7 = 50, se = sqrt(50/8) = 2.5, t(7) = 2.364624, half = 5.911: [-3.41, 8.41].
* Run: `an-001`, cutoff 2026-10-26, prior runs 0, not interim.
* No funnel, retention or adoption population in the window: the unit counts are 0 and the ratios are null.

## Part I: variant-empty

No accounts, users, events, sessions or assignments (the frozen plan and windows are configuration, still present). `empty_population` = true.
Every count is 0; every ratio is `null` (zero denominators): signup, funnel steps, activation, the three retention figures, adoption,
conversion, exposure rate, error rates; absolute and relative lift null, no interval, `conclusive` false. Revenue totals "0.00" with mean and
interval null. **SRM: verdict `INSUFFICIENT` with statistic and p-value null** (no observations; every expected cell is 0 < 5): proposed in
D-P6-24. No analysis run is cited (`analysis_id` null, `plan_frozen` false because there is no run to be frozen before).

## DECISIONS (proposed; the contract is not edited)

* **D-P6-1 Rounding.** ROUND_HALF_UP to the stated places; unrounded values (not previously rounded ones) feed later steps, e.g. the pp
  interval is the exact bound x 100 rounded once; `-0.00` is written `0.00`.
* **D-P6-2 Account timezone.** The contract says "the account's IANA timezone" but `accounts` has none; the fixture adds `accounts.timezone`
  (purpose: day-7 and week-4 calendars). `users.timezone` is carried and equals it. Proposal: add the field to P06-DATA-01.
* **D-P6-3 Event identity fields.** The contract's event fields have no anonymous visitor and D-01 needs one. Added `events.anonymous_id`;
  `events.user_id` is nullable (a visit before sign-in). An event row with both set is a user event.
* **D-P6-4 Subscription amount.** `subscriptions` has no amount, but MET-12 needs USD. Added `subscriptions.amount_usd` (Decimal string, 2 dp):
  the revenue the subscription contributes in its `starts_at` window; no proration; no currency conversion.
* **D-P6-5 Unknown identity.** An event is unknown when `user_id` is not a user, or when `user_id` and `anonymous_id` are both null. An
  anonymous event with an unlinked `anonymous_id` is a valid anonymous event (visitors need them for MET-01).
* **D-P6-6 Order of operations.** (1) keep events with `received_at` <= cutoff; (2) de-duplicate; (3) drop unknown identity; (4) drop events of
  bot users (also those attributed to a bot by a link); (5) drop events of internal accounts. Delayed, duplicate and unknown counts are
  taken at their step; `received_after_cutoff` is reported separately and is not in "delayed".
* **D-P6-7 Duplicate key.** (actor = `user_id` or else `anonymous_id`, `event_name`, `event_at`, the set of (property_key, property_value)). The
  earliest (`received_at`, `event_id`) survives. A repeated `event_id` is also a duplicate. Different properties = not a duplicate.
* **D-P6-8 Delayed.** `received_at - event_at` > 24 h (strictly), over canonical events of the run.
* **D-P6-9 Identity and funnel.** An anonymous event is attributed to a user only when `event_at` >= `linked_at` (the earliest link of that
  `anonymous_id`); never backwards. The funnel's unit is the visitor: the event's `anonymous_id`, else the `anonymous_id` the user was
  linked to, else the user. Time-aware linking therefore changes the identity counts (attributed vs anonymous), not the funnel counts, in
  this fixture; if the owner wants it to change the funnel, say so before implementation. Chain: anchor at the earliest first-step event in
  the window; the next step is the earliest event strictly after the previous step and at most `max_gap_hours` later (gap inclusive); a
  unit that fails a step stops; no re-anchoring on a later visit.
* **D-P6-10 Signup conversion.** Distinct `anonymous_id` with a `visit` in [from, to) (denominator) and a `signup` with the same
  `anonymous_id` in [from, to) (numerator); no gap, so it can exceed the funnel's visit-to-signup conversion.
* **D-P6-11 Activation and maturity.** `activated` in [signup_at, signup_at + 7 d); mature when signup_at + 7 d <= cutoff (inclusive). An
  assigned account without a signup is not mature and is counted in `immature_or_unobserved_excluded`.
* **D-P6-12 Retention.** Day index = local calendar date of the session minus local date of signup_at, in the account timezone. Day-7 and
  "on or after day 7" are separate; sessions count when `started_at` < cutoff; sessions of bot users and internal accounts are ignored;
  user sessions roll up to the account (an account counts once). Maturity: local signup date + 8 (day 7) or + 35 (week 4) <= local cutoff date.
  The cohort is selected by signup date in the account timezone, half-open.
* **D-P6-13 Feature adoption eligibility.** Eligible = plan in `eligible_plans` (pre-existing, outcome-free) and >= 1 non-bot session in the
  window and not internal. Use = a canonical `feature_used` event whose property `feature` equals the feature, in the window. Rate = adopters /
  eligible; `use_events` is reported so double counting would be visible.
* **D-P6-14 Event property shapes.** All values strings (`value_type` "string"), one row per key: `experiment_exposure` {experiment_version_id,
  variant}; `product_error` {error_code}; `feature_used` {feature}; the other events have none.
* **D-P6-15 Metric keys and nesting.** `expected.json` = {contract_version, empty_population, ingest{counts, rejected_records},
  tracking_quality, identity, metrics{signup_conversion, funnel, activation, retention, feature_adoption, experiment}}; experiment =
  {run, srm, primary{variants, absolute_lift_pp, relative_lift, interval, conclusive}, exposure, exploratory_exposed_only, guardrail,
  revenue_per_assigned_account, observations}. Interval bounds appear as proportions (6 dp) and as percentage points (2 dp).
* **D-P6-16 SRM.** Population: every accepted assignment of the version (not only mature ones). Statistic = sum (o - e)^2 / e with
  e = N x allocation, df = (variants - 1), p = P(chi-square_1 > stat) = erfc(sqrt(stat/2)) evaluated with the Maclaurin series of erf in
  Decimal (80 digits; 0 above 100). Verdict order: `INSUFFICIENT` (N = 0 or any expected cell < 5) before `MISMATCH` (p < 0.001) before `OK`.
  Verified against 3.841459 -> 0.050000, 4 -> 0.045500, 10.827566 -> 0.001000.
* **D-P6-17 Newcombe.** Group 1 = treatment, group 2 = control; z = 1.959964 as an exact rational; square roots by integer Newton at 1e-20;
  "includes 0" is the closed interval; `conclusive` = excludes 0 and run not interim (cutoff >= planned_end) and the plan hash valid.
* **D-P6-18 Revenue t-interval.** Per variant over all mature assigned accounts (zeros included): mean +/- t x sqrt(s^2/n), s^2 with n - 1,
  df = n - 1, two-sided 95 %, t found by bisection on the exact t CDF (finite sums of A&S 26.7.3-4; no table), null for n < 2. No
  difference interval is asserted: the contract asks for the interval per variant only.
* **D-P6-19 Exposure.** Exposed = at least one accepted exposure; rate over mature assigned accounts, per variant and overall. Exposed-only
  conversion is shown as `exploratory_exposed_only` with `decision_basis` false.
* **D-P6-20 Guardrail.** Window [assigned_at, assigned_at + `guardrail.window_days`); an account counts once; denominator = mature assigned
  accounts of the variant (the ITT population).
* **D-P6-21 Revenue.** Subscription counts when status in (active, ended) and `starts_at` in the plan's `revenue_window` [from, to);
  account value = sum of its counted amounts; mean = sum / mature assigned accounts.
* **D-P6-22 Plan and runs.** `config_hash` = sha256 of the compact, key-sorted JSON of the plan without `config_hash`; `plan_frozen` =
  `frozen_at` <= the earliest run's `created_at`; the run under test is the `analysis_runs` row whose `cutoff_at` equals the cutoff; `prior_runs`
  = runs of the version created earlier; `interim` = cutoff < `planned_end`. Allocation lives in the plan (the version entity keeps the contract's
  minimum fields).
* **D-P6-23 Rejection codes.** Contract: `ASSIGNMENT_CONFLICT`, `EXPOSURE_BEFORE_ASSIGNMENT`. Added: `DEPENDENT_REJECTED` (an exposure or an
  observation whose assignment is rejected; same code as the other apps) and `UNKNOWN_ASSIGNMENT`. Assignments are processed in (assigned_at,
  assignment_id) order; the first per (version, unit) wins; an identical repeat is idempotent (merged). The event of a rejected exposure
  stays in the log.
* **D-P6-24 Empty population.** `empty_population` = no canonical events and no accepted assignment. SRM then has verdict `INSUFFICIENT`, expected,
  statistic and p-value null (the contract allows "INSUFFICIENT or null"; this proposes INSUFFICIENT with null numbers, which keeps "never 0"
  and shows why nothing can be concluded). Zero-denominator ratios are null; counts are 0; revenue totals "0.00".
* **D-P6-25 Observations.** `metric_observations` rows carry "1"/"0" and `window_end` = signup_at + 7 d; the reference recomputes them from events and
  requires a match; they are never the source of the primary result.

## Contract gaps found (propose; nothing was edited)

1. `accounts.timezone` is missing (D-P6-2). 2. `events.anonymous_id` is missing (D-P6-3). 3. `subscriptions.amount_usd` is missing (D-P6-4).
4. "Unknown identity" is not defined for anonymous events (D-P6-5). 5. The funnel's unit is not pinned (D-P6-9): the contract defines signup
conversion on visitors and later steps on "the same unit". 6. SRM for an empty population, SRM p-value method, t-interval df and rounding mode
are unstated (D-P6-1, D-P6-16, D-P6-18, D-P6-24). 7. No rejection code for a dependent record (D-P6-23). 8. Not exercised, so unpinned: week-4
maturity for DST changes, a session exactly at the cutoff, three or more variants, segment analysis (TEST-09), interim peeking presented as
final (needs a stored decision), a run before the freeze, the Welch difference of revenue means.
