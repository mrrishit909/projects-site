# TrustLedger golden calculation (contract v1, decisions D-01..D-05; revised for review R7, D-10)

Independent of application code. `../../reference_check.py` recomputes every figure below from `inputs.json` and compares it
with `expected.json` leaf by leaf (standard library only, no app imports, `fractions.Fraction` for every ratio, no float).
`expected.json` states the figures worked by hand on this page. Proportions: decimal strings, 6 places. Hours: 4 places.
Rounding: ROUND_HALF_UP. Null = unknown or zero denominator, never 0 (D-05). `as_of` = 2026-10-05T00:00:00Z. Weight version in
force: **w2** (from 2026-09-01). Checklist version in force: **cl-1**. Whitespace policy: `trim_empty_is_missing`
(trim " \t\r\n"; a trimmed-empty string is missing).

## The spec sentence [P07-GOLD-01]

> 100 eligible customer rows with 5 missing required emails gives completeness = 95%. Of 95 populated emails, 90 pass the
> validity rule gives populated-only validity = 90/95, not 90/100; show both with labels. A critical key failure must remain
> visible even if a weighted aggregate exceeds 95.

## Part (a): the golden case

Five datasets, five owners (own-05 inactive since 2026-09-15). Row-level data exists for ds-customers (100 rows) and
ds-orders (40 rows); the other datasets are measured on timeliness only. The matcher input (10 synthetic customer records,
5 candidates) is separate; the **synthetic truth** is its own top-level block `synthetic_truth`, read only by the
precision step, never by the matcher and never carried on a record.

### Eligibility (the documented rule)

Eligible rows of ds-customers = all rows cust-001..cust-100 (100). Nothing is excluded, so eligible = 100 for the email
rules and for the key rule. For the relationship rule the eligible population is the non-null foreign keys (below).

### Completeness [P07-MET-01, D-01] rule r-cust-complete-email (v1)

Missing email rows: cust-011 (null), cust-029 (null), cust-047 (empty string), cust-063 ("   "), cust-088 ("\t \t").
Two are whitespace-only (cust-063, cust-088): under the policy they are missing, not populated. Missing = 5,
populated = 100 - 5 = 95. **Completeness = 95/100 = 0.950000.** (Without the policy it would be 97/100: pinned by the two
whitespace-only rows.) Run: eligible 100, failures 5.

### Validity [P07-MET-02, D-01] rule r-cust-valid-email (v2), pattern `^[^@ \t\r\n\f\v]+@[^@ \t\r\n\f\v]+\.[A-Za-z]{2,}$`

The pattern uses explicit classes only. `\s`, `\d`, `\w` and `\b` (and their negations) are refused at ingest as PATTERN_NOT_PORTABLE (D-10 R7-04): Python
`re`, JavaScript and PostgreSQL disagree on which characters they match (Unicode or ASCII classes) and on what `\b` means. With the class
`[ \t\r\n\f\v]` the five failures below are the same in all three engines, and a no-break space, a byte-order mark, U+0085, U+2028 or U+001C inside
an address is an ordinary character (it passes), so replacing the no-`@` value of cust-005 by `a<that character>b@x.io` gives 91 passing of 95 populated =
0.957895 everywhere (`reference_check.py`, `review-check.ts`, `tests/test_review_r7.py` and the SQL reference all state this).

Populated = 95. Populated rows failing the format: cust-005 (no @), cust-019 (no dot after @), cust-033 (two @),
cust-052 (space in local part), cust-077 (one-letter top-level label) = 5. Passing = 95 - 5 = 90.
* **Populated-only validity = 90/95 = 0.947368** (label `validity_populated_only`).
* **All-eligible validity = 90/100 = 0.900000** (label `validity_all_eligible`).
Missing values fail the all-eligible form only, so the two differ. Validity is format validity, never correctness.
Run: eligible 100, failures 10 (5 missing + 5 malformed), populated 95.

### Uniqueness [P07-MET-03, D-01] rule r-cust-key-unique (v1, severity critical)

customer_key CK-0060 appears on cust-060, cust-061, cust-062 (three rows); every other key once; no null keys.
Distinct keys = 100 - 2 = 98. Keys with more than one row = 1. Rows beyond the first per key = 2.
* **Duplicate-group share = 1/98 = 0.010204** (label `duplicate_group_share`).
* **Duplicate-row share = 2/100 = 0.020000** (label `duplicate_row_share`).
They differ (group share is per key, row share per eligible row). Run: eligible 100, failures = 0 null + 2 = 2.
Dimension score used in the weighted score = (eligible - null-key rows - duplicate rows) / eligible = (100 - 0 - 2) / 100 = 0.980000 (DECISIONS, D-T7-3,
D-10 R7-05). The golden has no null key, so the figure by rows is unchanged and `null_key_row_ids` is empty.

Null-key probe (not in the fixture; `reference_check.py`, `review-check.ts`, `tests/test_review_r7.py`): customer_key of cust-001 set to null. Eligible 100;
null-key rows 1 (cust-001, listed apart); the 99 other keys hold CK-0060 three times, so distinct keys = 96 + 1 = 97, groups 1, rows beyond the first 2. Group share
1/97 = 0.010309; row share 2/100 = 0.020000; run failures 1 + 2 = 3; score (100 - 1 - 2) / 100 = **0.970000** (the null key lowers the score exactly as a duplicate
does). ds-customers under w2: numerator 0.25 x 0.95 + 0.25 x 90/95 + 0.25 x 0.97 + 0.10 x 1 = 0.2375 + 0.236842 + 0.2425 + 0.1 = 0.816842; / 0.85 = **0.960991**.

### Relationship integrity [P07-MET-04, D-01, P07-TEST-04] rule r-ord-cust-fk (v1)

ds-orders has 40 foreign keys (customer_key). Missing under the whitespace policy: ord-017 and ord-033 are null and ord-036 is the **empty string**
(an empty or whitespace-only key is missing, like a null, D-10 R7-11) = 3, **excluded from the denominator and counted separately** (`null_fk_count` 3, of
which `empty_fk_count` 1 is text; the site labels the column "null or empty (whitespace policy)"). Eligible = 40 - 3 = 37. Unmatched against
ds-customers.customer_key: ord-008 (CK-0999), ord-025 (CK-0777) = 2. Matched = 37 - 2 = 35. **Relationship integrity = 35/37 = 0.945946**.
(Silently counting the missing keys would give 35/40 = 0.875000, or 37/40 = 0.925000 if they were counted as matched: both wrong. Before the empty string was
pinned the figures were 36/38 = 0.947368 with 2 nulls; ord-036 was CK-0036 and matched.) Run: eligible 37, failures 2.

### Timeliness [P07-MET-05, D-01, D-10 R7-01] over the 4 monitored datasets (ds-products is not monitored and not counted)

Target = the dataset's declared daily local time in its IANA zone plus its grace. A dataset is **on time at `as_of`** when a refresh (not after `as_of`) exists in
[latest occurrence <= as_of, its deadline) (half-open, D-05). If there is no such refresh the dataset is **pending** while that occurrence's deadline is still in the
future (neither on time nor late, **excluded from the denominator** and counted in `pending_count`), and **late** once the deadline has passed. A repeated local time is the
LATER instant; a local time that does not exist uses the offset before the change (D-07). On 2026-10-04/05 New York is EDT (UTC-4) and London is BST (UTC+1); DST in both
zones ends later in October and November, so the offsets are the summer ones. At 2026-10-05T00:00Z no occurrence is open (the next local occurrences are after `as_of`), so
the latest started occurrence is the one of 2026-10-04 and its window has closed:

| Dataset | Zone, local time, grace | Occurrence (UTC) | Deadline (UTC) | Last refresh (UTC) | State |
|---|---|---|---|---|---|
| ds-customers | America/New_York 06:00, 60 min | 2026-10-04 06:00 EDT = 10:00Z | 11:00Z | 10:20Z | on time (10:00 <= 10:20 < 11:00) |
| ds-orders | Europe/London 07:00, 30 min | 2026-10-04 07:00 BST = 06:00Z (Oct 5 07:00 BST = 06:00Z Oct 5 is after as_of) | 06:30Z | 06:10Z | on time |
| ds-payments | America/New_York 02:00, 120 min | 2026-10-04 02:00 EDT = 06:00Z | 08:00Z | 07:59Z | on time (one minute inside) |
| ds-shipments | Europe/London 05:00, 60 min | 2026-10-04 05:00 BST = 04:00Z | 05:00Z | 05:00Z | **late** (05:00 is not < 05:00) |

3 on time of 4 evaluated (monitored 4, pending 0): **timeliness = 3/4 = 0.750000.** Read as UTC clock times without the zone, ds-customers (06:00Z)
and ds-payments (02:00Z) would be judged against the wrong instants: the zones matter.

**Stated cases (`probes.timeliness` in `inputs.json`, `timeliness_probes` in `expected.json`).** One schedule, ds-customers' (New York 06:00, grace 60), and the
New York clock change; each probe states its own refresh and `as_of`:

| Probe | as_of | Last refresh | Occurrence judged | Window | State | Why |
|---|---|---|---|---|---|---|
| open-window-refreshed | 2026-10-05T10:30Z | 10-05T10:10Z | 06:00 EDT = 10:00Z | [10:00Z, 11:00Z) | **on_time** | the reviewer's case: the occurrence started at 10:00Z, the window is open at 10:30Z and 10:10Z is inside it (the old rule judged only closed windows and called this late) |
| open-window-not-yet-refreshed | 2026-10-05T10:30Z | 10-04T10:20Z | 10:00Z | [10:00Z, 11:00Z) | **pending** | yesterday's refresh is not in today's window and the deadline (11:00Z) is after `as_of`: neither on time nor late, outside the denominator |
| deadline-equals-as-of-no-refresh | 2026-10-05T11:00Z | 10-04T10:20Z | 10:00Z | [10:00Z, 11:00Z) | **late** | the deadline 11:00Z is not after `as_of`: the window has closed with no refresh in it |
| refresh-at-the-deadline | 2026-10-05T12:00Z | 10-05T11:00Z | 10:00Z | [10:00Z, 11:00Z) | **late** | 11:00Z is not < 11:00Z |
| refresh-after-as-of | 2026-10-05T10:30Z | 10-05T10:45Z | 10:00Z | [10:00Z, 11:00Z) | **pending** | a refresh after `as_of` has not happened yet: no refresh is known and the window is open |
| clocks-back-refresh-in-the-first-0130 | 2026-11-01T12:00Z | 11-01T05:45Z | 01:30 = 06:30Z | [06:30Z, 07:30Z) | **late** | on 2026-11-01 New York goes from EDT to EST at 02:00 EDT, so 01:30 happens at 01:30 EDT = 05:30Z and again at 01:30 EST = 06:30Z; the contract takes the later instant (D-07), so the refresh at 05:45Z (01:45 EDT, in the first 01:30 hour) is 45 minutes BEFORE the occurrence and is not in its window; the deadline 07:30Z has passed |
| clocks-back-refresh-in-the-second-0130 | 2026-11-01T12:00Z | 11-01T06:45Z | 06:30Z | [06:30Z, 07:30Z) | **on_time** | 06:30Z <= 06:45Z < 07:30Z |

The clocks-back result is what the rule gives, not a judgement that the first refresh was bad: a dataset whose source clock repeats an hour is judged against the later
01:30. Both results are the same in the Python domain, the SQL reference, the TypeScript mirror and `reference_check.py`.

### Weighted quality score and the critical override [P07-MET-06/07, D-01]

Score = sum(dimension score x weight) / sum(weights of the measured dimensions) (unmeasured dimensions are left out of both
sums, DECISIONS D-T7-5). ds-customers measures completeness 0.950000, validity (populated-only) 0.947368, uniqueness
0.980000, timeliness 1.000000; relationship is not measured on it.

Weights **w2** (completeness 0.25, validity 0.25, uniqueness 0.25, relationship 0.15, timeliness 0.10):
numerator = 0.25 x 0.95 + 0.25 x 90/95 + 0.25 x 0.98 + 0.10 x 1 = 0.2375 + 0.236842 + 0.245 + 0.1 = 0.819342;
denominator = 0.25 + 0.25 + 0.25 + 0.10 = 0.85; **score = 0.819342 / 0.85 = 0.963932.**

Weights **w1** (0.40, 0.30, 0.20, 0.05, 0.05): numerator = 0.38 + 0.284211 + 0.196 + 0.05 = 0.910211; denominator =
0.40 + 0.30 + 0.20 + 0.05 = 0.95; **score = 0.958116.** Same data, different weight version, different score; the result names
the version.

Both exceed 0.95. **Critical failures:** r-cust-key-unique has severity critical and 2 failures on the current run, and
issue iss-006 (critical, status investigating) is open. So ds-customers: critical_failures = 2, critical_open_issues = 1,
**critical_override = true**, shown beside 0.963932. Across the portfolio: failures 2, open critical issues 1,
datasets overridden 1, carried 0 (`carried` is the list of live failures of disabled critical rules, empty here: the only disabled rule, r-ord-amount-range, is not critical).

Disabled-critical probe (not in the fixture; `reference_check.py`, `review-check.ts`, `tests/test_review_r7.py`, the API sequence run-rule then disable-rule): disable
r-cust-key-unique at 2026-10-04T00:00Z with its latest run rr-003 failing (2 rows). It is no longer measured, but disabling is not repair: its latest run's 2 failures are
**carried**, so critical_failures stays 2 (`carried` = [rr-003: 2]) and the override stays true even with no issue open; ds-customers' score then has no uniqueness
dimension. A later successful rerun of the same rule (failure_count 0, run_at after rr-003) is the latest run and clears it: critical_failures 0, `carried` empty (the
open critical issue iss-006 still holds the override). A rule disabled after `as_of` was still active at it and is measured, not carried (D-10 R7-02).

Other datasets (w2 / w1): ds-orders measures relationship 0.945946 (35/37) and timeliness 1: w2 = (0.15 x 35/37 + 0.10) / 0.25 =
0.241892 / 0.25 = 0.967568; w1 = (0.05 x 35/37 + 0.05) / 0.10 = 0.097297 / 0.10 = 0.972973. ds-payments timeliness 1 only:
1.000000 both. ds-shipments timeliness 0 only: 0.000000 both. ds-products measures nothing: score null (weight sum 0).

### Rule runs and comparability [P07-FLOW-03, P07-TEST-12]

The as_of run of each active rule stores eligible count, failure count, rule version and weight version w2 (8 active rules:
the 3 customer rules + r-ord-cust-fk + 4 timeliness rules; timeliness eligible 1 per dataset). Comparison is against the latest
earlier scheduled run of the same rule:
* r-cust-complete-email: previous rr-001 (v1, 8/100 = 0.080000) vs now v1 5/100 = 0.050000: comparable.
* r-cust-key-unique: rr-003 (v1) 2/100 = 0.020000 vs now 0.020000: comparable.
* r-ord-cust-fk: rr-006 (v1) 3/36 = 0.083333 vs now 2/37 = 0.054054: comparable (same rule version, and the missing FKs are
  excluded in both, so the eligibility definition is the same).
* r-cust-valid-email: previous rr-002 was **rule v1** (eligible 92) and now is **v2** (eligible 100): **not comparable**,
  reason RULE_VERSION_DIFFERS, no rates are compared.

### Disabled rule [P07-FLOW-09, P07-TEST-02]

r-ord-amount-range is disabled (2026-09-20, with a reason). Its 2 runs (rr-004, rr-005) and its issue (iss-004) are retained
and readable; it is not among the 8 active rules and has no current run.

### Ownership coverage [P07-MET-09, D-02]

5 datasets. ds-shipments is owned by own-05, inactive since 2026-09-15, so it is uncovered. Covered = 4.
**Ownership coverage = 4/5 = 0.800000**, uncovered [ds-shipments].

### Definitions [P07-MET-10, P07-TEST-11, D-02]

Metric versions as of `as_of`: m-revenue v2 (published; v1 superseded), m-churn v1, m-aov v1, m-ltv v1 (all published), m-nps v1
(draft, not counted). **Published metrics = 4.** Checklist cl-1 = definition, grain, source fields, owner, refresh.
m-revenue, m-churn, m-aov complete; m-ltv has an empty grain and a null refresh: incomplete (grain, refresh).
**Definition coverage = 3/4 = 0.750000.** m-revenue has a second version created by change dc-001 (valid_from 2026-08-15T09:00Z =
changed_at, reason and approver recorded); v1 is not rewritten. Effective definition at the probe 2026-08-01T00:00Z:
m-revenue -> mv-rev-1; at as_of: mv-rev-2.

### Lineage [P07-MET-12, P07-TEST-08, D-02]

Declared (6): customers->orders, products->orders, orders->payments, orders->shipments, customers->payments,
products->shipments. Observed rows = 7 (customers->orders was observed twice: eo-1 on 10-03 and eo-6 on 10-04): distinct observed
pairs = 6. Observed matching a declared edge = 5 (all but products->shipments, which was not observed). Observed with no
declared counterpart = 1: payments->shipments (listed as undeclared). Inferred = 1: products->shipments, kept in its own
list; it does **not** make products->shipments observed. **Lineage coverage = 5/6 = 0.833333.**

### Issues [P07-MET-08, D-03, P07-TEST-09]

Resolved only by a successful rerun of the same rule version for that issue (rerun failure count 0, at or after detection);
resolution time = rerun time - first detected_at.
* iss-001: detected 09-20 08:00, rerun rr-007 (same rule r-ord-cust-fk v1, 0 failures) 09-21 14:30: 30h 30m = **30.5000 h**.
* iss-002: 09-22 09:15 -> rr-009 09-22 21:45: **12.5000 h**.
* iss-003: 09-25 10:00 -> rr-011 09-28 10:20 (the close was 09-27 16:00, before the rerun; the rerun time governs):
  3 d 0 h 20 m = 72 + 1/3 = **72.3333 h**.
* iss-004: closed 08-28 12:00 with no rerun and its rule disabled: **claimed**, not resolved (claimed age 81.0000 h, listed
  separately).
* iss-005: detected 09-10 06:00, rerun rr-013 verified it on 09-11 08:00, **reopened** 09-20 05:00 (1 cycle), status open: keeps its
  first detected_at, not resolved; open age = 09-10 06:00 -> 10-05 00:00 = 24 d 18 h = **594.0000 h**.
* iss-006: critical, investigating, detected 09-30 02:00: open age 4 d 22 h = **118.0000 h**.
Resolved 3, claimed 1, open 2 (one of them reopened). **Mean resolution time = (30.5 + 12.5 + 72.3333...) / 3 = 115.3333 / 3 =
38.4444 h.**

### Match candidates, merges and precision [P07-MET-11, D-04, P07-TEST-03/06/10]

Five candidates, each stored once with left_record_id < right_record_id, score, features and explanation:
cand-001 (rec-001, rec-002; 0.97), cand-002 (rec-003, rec-004; 0.91), cand-003 (rec-005, rec-006; 0.88), cand-004 (rec-007, rec-008;
0.62), cand-005 (rec-009, rec-010; 0.95). Name-and-address pairs carry the explicit uncertainty "possible household"; none is
merged automatically. Reviewed = 4 (cand-005 is unreviewed): approved 3 (md-1 cand-001, md-2 cand-002, md-3 cand-003), rejected 1
(md-4 cand-004). All reviewers differ from the proposer (own-01) and are stewards or admins.

Synthetic truth (`synthetic_truth.true_entity`): rec-001=rec-002 (E1), rec-003=rec-004 (E2), **rec-005 (E3) != rec-006 (E4)**,
rec-007 (E5) != rec-008 (E6), rec-009=rec-010 (E7). So approvals md-1, md-2 are correct and **md-3 is wrong** (two different
people sharing a household); the rejection of cand-004 is correct.

**Precision definition (D-04, DECISIONS D-T7-6): approved (confirmed-as-match) decisions that the truth shows are the same
entity / approved decisions = 2/3 = 0.666667.** A reversal does not remove the earlier approval from this ratio.
The alternative reading "reviewed pairs the truth says are the same entity / all reviewed" is stored beside it and labelled
`reviewed_correct_share` = 2/4 = 0.500000. The contract text supports either; the proposal below picks the first.

Merge md-5 (own-03) reverses md-3 on 2026-10-01 09:00 with a reason. The merge maps the right record to the left; reversal
restores both identities and keeps the history: md-1 active (rec-002 -> rec-001), md-2 active (rec-004 -> rec-003), md-3 reversed
by md-5 (rec-006 -> rec-005 restored: rec-005 and rec-006 map to themselves). Merges 3, reversed 1, active 2.

### Counts at ingest

Every record is accepted (the explicit-class pattern, the empty-string key and the timeliness probes change no count): owners 5, datasets 5, fields 7, quality_rules 9, rule_runs 13, issues 6, lineage_edges 14, metric_versions 6,
definition_changes 1, customer_records 10, match_candidates 5, merge_decisions 5, dataset rows 140 (100 + 40). Rejected 0.

## Part (b): variant-rejected

Inputs: 2 owners (own-01 analyst, own-02 steward), ds-customers (4 rows, one missing email) and the offending records:
1. **Dataset without an owner.** ds-orphan has `owner_id: null`. A dataset is registered only with an owner and a
   classification (D-02, P07-FLOW-01), so it is rejected: OWNER_REQUIRED. If it were accepted it would sit in the denominator of
   ownership coverage with nobody accountable. Its field fld-009, rule r-orphan-complete, run rr-001 and its 3 rows
   (feed-001..003) are DEPENDENT_REJECTED (never silently dropped); they would otherwise measure a dataset that does not exist
   in the register.
2. **Reverse-order pair.** cand-002 stores rec-002, rec-001, the reverse of cand-001 (rec-001, rec-002). A pair is stored once
   in canonical order (D-04, P07-FLOW-06, P07-TEST-10), so cand-002 is rejected: DUPLICATE_PAIR. Accepting it would let one
   pair be reviewed twice and count twice in precision. Its decision md-2 is DEPENDENT_REJECTED.
3. **Merge decided by the proposer.** cand-003 was proposed by own-02 and md-3 is an approval by own-02: reviewer = proposer is
   refused (D-04, P07-FLOW-07/C07): REVIEWER_IS_PROPOSER. A merge needs an independent human decision; md-4, a reversal of the
   never-accepted md-3, is DEPENDENT_REJECTED.
Result: datasets 1 accepted / 1 rejected; candidates 2 / 1; decisions 1 / 3; dataset rows 4 accepted / 3 rejected (dependent).
Measured on what remains: ds-customers completeness 3/4 = 0.750000, weighted score (w2, completeness only) =
0.25 x 0.75 / 0.25 = 0.750000, no critical failure, override false; ownership coverage 1/1 = 1.000000 (ds-orphan is not in the
denominator); matching: 2 candidates, 1 reviewed (approved md-1 only), 1 unreviewed, no reversal. The rejected records are
listed with reason codes and raw rows (sorted by entity, id).

## Part (c): variant-empty

No owners, datasets, rows, rules, runs, issues, edges, metrics, records, candidates or decisions. Every count is 0, every ratio
is null (completeness/validity/uniqueness/relationship keyed objects are empty because there is no rule; timeliness 0/0 null,
ownership 0/0 null, definition coverage 0/0 null, lineage 0/0 null, match precision 0/0 null, mean resolution hours null;
the weighted score has no dataset), and `empty_population` is **true**. Nothing reads 0.000000 where it means unknown.

Note (D-10): `variant-rejected/expected.json` and `variant-empty/expected.json` gained three keys and no figure moved: `metrics.timeliness.evaluated_datasets` (0),
`metrics.timeliness.pending_count` (0) and `metrics.critical_failures.carried` ([]).

## DECISIONS (proposed; the contract is not edited, see "Contract gaps" for what needs the owner)

* **D-T7-1 Eligibility and the whitespace policy.** Eligible rows = all rows of the dataset in the golden case (documented here;
  cust-001..100). The whitespace policy is the contract default, trim " \t\r\n", declared in `inputs.json` as
  `whitespace_policy`. The empty string counts as missing, and `whitespace_only_count` (non-empty strings that trim to empty) is
  reported beside it.
* **D-T7-2 Critical-failure count.** `critical_failures` = sum of `failure_count` over the dataset's active rules with
  severity `critical` on the current run at `as_of` (here the 2 duplicate rows), plus the `failure_count` of the latest run of every critical rule that is
  disabled at `as_of` while that run fails (`carried`, D-10 R7-02; a passing rerun is the latest run and clears it). `critical_open_issues` = issues of critical
  rules whose class is not resolved (open, reopened or claimed). `critical_override` = either is above 0. Both numbers are always
  shown and the override is never recomputed from the score.
* **D-T7-3 Uniqueness key and score.** Key = the rule's named field, compared as exact text after the missing-value policy;
  null keys are failures and are counted separately (`null_key_count`) and not grouped. The first row in row order is kept, the
  rows after it fail. Group share = groups with more than one row / distinct non-null keys; row share = rows beyond the first /
  eligible rows. The dimension score fed to the weighted score is (eligible - null-key rows - duplicate rows) / eligible (D-10 R7-05); the null-key rows are listed
  apart in `null_key_row_ids`. With no null key it equals 1 - row share, as in the golden.
* **D-T7-4 Timeliness target.** Target = the dataset's declared daily local time in its IANA zone plus `refresh_grace_minutes`.
  The occurrence evaluated at `as_of` is the latest that has STARTED (D-10 R7-01); a refresh not after `as_of` is on time in [occurrence, deadline),
  half-open (D-05), so a refresh exactly at the deadline is late. With no such refresh the dataset is pending while the deadline is in the future (outside
  the denominator, counted in `pending_count`) and late once it has passed. Only datasets with `monitored: true` count; a never-refreshed dataset is pending
  until its deadline and late after. The timeliness rule's run is one eligible dataset (1) with 0 or 1 failure, or eligible 0 while pending.
* **D-T7-5 Weighted score and unmeasured dimensions.** Dimensions with no measured score (no active rule, or zero
  denominator) are omitted from both numerator and denominator (contract: "over the dimensions that have a measured score");
  the measured dimensions and the weight sum are returned with the score; a dataset with none has a null score. Validity enters
  the score as populated-only validity (completeness already carries the missing share, so missing values are not penalised
  twice). The weight version is named in the result and chosen by the caller (`weight_version`, default the one in force);
  rule runs store the version they were scored under.
* **D-T7-6 Match precision.** Precision = approved merge decisions whose pair the synthetic truth shows to be one entity /
  approved merge decisions (2/3). Reversed approvals stay in the ratio; rejected and unreviewed pairs are outside it. The wider
  `reviewed_correct_share` (2/4) is reported separately and labelled so nobody reads it as precision.
* **D-T7-7 Checklist items.** cl-1 = {definition, grain, source_fields, owner, refresh}. An item is complete when the text
  is non-empty after trim; `source_fields` when the list is non-empty with no blank member; `owner` when it references an owner
  in the register. The count of published metrics is at the effective version as of `as_of` (status published); drafts and
  superseded versions are not counted.
* **D-T7-8 Resolution time.** resolved_at = run_at of the verifying rerun (not the human close time); an issue reopened after a
  verified rerun is open, keeps its first detected_at and counts its cycles; open ages run to `as_of`; claimed issues show their
  claimed age. Rerun must be of the same rule and rule version, for that issue, with 0 failures.
* **D-T7-9 Metric key names and nesting.** Under `metrics`: `completeness`, `validity`, `uniqueness`, `relationship_integrity`
  (each keyed by rule id), `timeliness`, `weighted_score` (`datasets`, `by_weight_version`), `critical_failures`,
  `resolution_time`, `ownership_coverage`, `definition_coverage`, `match_precision`, `lineage_coverage`; labelled paired
  figures are objects `{label, value}`.
* **D-T7-10 Rejection.** Rejection is atomic per record with a reason code; a record whose parent was rejected is
  DEPENDENT_REJECTED. Codes used: OWNER_REQUIRED, DUPLICATE_PAIR, REVIEWER_IS_PROPOSER, DEPENDENT_REJECTED (and, in the checker,
  UNKNOWN_*, OWNER_INACTIVE, CLASSIFICATION_REQUIRED, NON_CANONICAL_ORDER, SAME_RECORD, INVALID_CANDIDATE, ROLE_NOT_PERMITTED).
  A reverse-order pair whose twin already exists is DUPLICATE_PAIR; a first-seen pair with left > right is
  NON_CANONICAL_ORDER.
* **D-T7-11 Observed lineage.** Distinct (source, target) pairs; repeat observations do not raise coverage. Inferred edges
  are never part of the observed numerator. An edge whose source and target are the same dataset is MALFORMED_RECORD (D-10 R7-06).
* **D-T7-12 Portable patterns, empty keys, stated timeliness cases (D-10).** A validity pattern that uses `\s`, `\d`, `\w` or `\b` is PATTERN_NOT_PORTABLE; the fixture
  pattern uses `[ \t\r\n\f\v]`. An empty or whitespace-only foreign key is missing under the whitespace policy and counted with the nulls (`empty_fk_count` reports the
  text ones). `probes.timeliness` states cases for the timeliness rule alone and `timeliness_probes` is their expected state.

## Contract gaps found (propose; nothing was edited)

1. D-04 "reviewed proposed matches confirmed correct / reviewed proposed matches" admits two denominators (approved 3, or
   reviewed 4). Proposed text: "Match precision = approved merge decisions confirmed as one entity by the synthetic truth /
   approved merge decisions." (D-T7-6).
2. D-01 says critical failures are "open failures of rules with severity critical" without saying whether a failure is a row
   or an issue. Proposed: both are reported (D-T7-2); the override uses either.
3. D-01 does not say what a dimension score is for uniqueness or for validity inside the weighted score. Proposed: 1 - row
   share, and populated-only validity (D-T7-3, D-T7-5).
4. D-01 does not define the target for timeliness beyond "declared schedule and IANA timezone": proposed daily local time plus
   a grace in minutes, half-open (D-T7-4); the data model has no field for grace, so the fixture adds
   `refresh_local_time` and `refresh_grace_minutes` to datasets.
5. D-02 leaves "resolved_at" implicit: proposed to be the verifying rerun's run_at (D-T7-8).
6. Nothing in the contract made the golden answer impossible.
