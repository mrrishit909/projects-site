# TrustLedger — business contracts, version 1 (2026-10-27; D-10 review fixes 2026-10-27)

Decision owner: coordinator (Fable 5.1). Spec: `projects/07-trustledger.md`, SHA-256 `3a4ec15b…` at pack commit
`fe5f7981` (verified against `docs/program/source-pack.json`). Rules cite the requirement they satisfy; changing one
bumps `CONTRACT_VERSION`, this file, the golden fixture and the tests together.

## Decision the product supports
Which data issues should be fixed first and who is accountable? (P07-GOAL-01). Primary users: a data governance
analyst and a data quality analyst. Non-goals: no automated identity merge of ambiguous pairs (P07-DOMAIN-02); match
truth lives only in verification fixtures, never in the matcher (P07-DOMAIN-03); synthetic personal details only
(P07-DOMAIN-06).

## D-01 Quality dimensions, eligibility and the critical override
* Dimensions are measured and reported separately (P07-DOMAIN-01): completeness = non-missing eligible values ÷
  eligible values, where a value is missing when null or, after trimming, empty (the whitespace policy is declared per
  rule version and defaults to "trimmed empty is missing", P07-MET-01); validity = eligible values passing the domain
  rule ÷ eligible values, and **populated-only validity** = passing ÷ populated, shown with its label beside the
  all-eligible figure (P07-MET-02; validity is format validity, never correctness, P07-DOMAIN-05); uniqueness is
  reported both as duplicate-group share (keys with more than one row ÷ distinct keys) and duplicate-row share
  (rows beyond the first per key ÷ eligible rows) with labels (P07-MET-03); relationship integrity = matched eligible
  foreign keys ÷ eligible foreign keys where a null foreign key is **excluded from the denominator and counted
  separately**, never silently (P07-MET-04, P07-TEST-04); timeliness = datasets refreshed within their target ÷
  monitored datasets, on the dataset's declared schedule and IANA timezone (P07-MET-05).
* Golden (P07-GOLD-01): 100 eligible customer rows, 5 missing required e-mails: completeness 0.950000; of the 95
  populated, 90 pass: populated-only validity 90/95 = 0.947368 and all-eligible validity 90/100 = 0.900000, both
  labelled.
* The weighted quality score = Σ(dimension score × weight) ÷ Σ(active weights) over the dimensions that have a
  measured score, computed with the **rule-weight version** named in the result (P07-MET-06, P07-DOMAIN-04,
  P07-TEST-05). **Critical failures** (open failures of rules with severity `critical`) are counted and shown
  independently and are never hidden by the aggregate: a dataset with any open critical failure carries
  `critical_override: true` beside its score, however high the score (P07-MET-07, P07-TEST-01). Golden: a critical key
  failure stays visible although the weighted aggregate exceeds 0.95.
* A rule run stores the eligible count, the failure count, the rule version and the weight version; two runs are
  comparable only when their eligibility definition (rule version) is the same, and the result says so
  (P07-FLOW-03, P07-TEST-12). Disabling a rule keeps its runs and issues; the rule is `disabled` with a reason and
  date and its history stays readable (P07-FLOW-09, P07-TEST-02).

## D-02 Ownership, definitions and lineage
* A dataset is registered only with an owner and a classification (P07-FLOW-01). Ownership coverage = datasets whose
  accountable owner is **active** ÷ datasets; an inactive owner leaves the dataset uncovered (P07-MET-09,
  P07-TEST-07).
* Metric definitions are versioned: a change creates a new `metric_versions` row with `valid_from` and a
  `definition_changes` row with reason and approver; a published definition is never rewritten in place
  (P07-FLOW-02, P07-TEST-11). Definition coverage = published metrics whose contract checklist (definition, grain,
  source fields, owner, refresh) is complete under the **checklist version** named ÷ published metrics (P07-MET-10).
* Lineage edges carry `evidence_type` ∈ {declared, observed, inferred}; the declared graph and the observed graph
  are kept separate; an inferred edge is never presented as observed (P07-TEST-08). Observed lineage coverage =
  distinct observed edges that match a declared edge ÷ declared edges (P07-MET-12); observed edges with no declared
  counterpart are listed as undeclared.

## D-03 Issues and remediation
* A failure opens an issue linked to the rule run with the rule's severity; triage sets an owner and a due date
  (P07-FLOW-04/05). Resolution time = resolved_at − detected_at in hours (4 dp) over resolved issues; a reopened issue
  keeps its first detected_at and counts its cycles; open issues are aged separately (P07-MET-08).
* An issue is `resolved` only after a **successful rerun** of the same rule version confirms it (the rerun's failure
  count for the issue's records is 0); a close without a rerun is `claimed`, listed separately, and never counts as
  resolved; disabling the rule is not repair (P07-FLOW-10, P07-TEST-09).

## D-04 Identity matching
* Match candidates are proposed from distinct source records with a score in [0,1], the contributing features and an
  explanation; a pair is stored once in a canonical order (left_record_id < right_record_id); the reverse pair is a
  duplicate candidate and is rejected (P07-FLOW-06, P07-TEST-10). Two records sharing a name and an address are a
  candidate with explicit uncertainty, never an automatic merge (P07-DOMAIN-02, P07-TEST-03).
* A merge needs a human decision with reviewer and audit; it maps the right record to the left; a merge is reversible:
  reversal restores both source identities and keeps the mapping history (P07-FLOW-07/08, P07-TEST-06).
* Match precision = reviewed proposed matches confirmed correct ÷ reviewed proposed matches, where "correct" comes
  from the synthetic truth held in the verification fixture, outside the matcher (P07-MET-11, P07-DOMAIN-03).

## D-05 Numbers, time and absence
Proportions are decimal strings with 6 places in [0,1] (the spec's "Output unit: percent", P07-MET-01..05-R03 and P07-MET-09..12-R03, is the same figure
times 100, shown as a percent where a page says percent; P07-MET-06-R03 "score/100" is the weighted score on the same [0,1] scale, P07-MET-07-R03 "failures" a
count and P07-MET-08-R03 "hours" a 4 dp figure; D-10 R7-12); counts nonnegative integers; hours 4 dp; null means unknown or
zero denominator, never 0. Instants are UTC with `Z`; schedules use the dataset's IANA timezone. Windows are half-open
[from, to) on the stated timestamp. Empty population: every count 0, every ratio null, `empty_population` true.

## Mode disclosure
Mode A: Python domain + PostgreSQL + FastAPI verified on hosted runners. Mode B: TypeScript mirror over the published
snapshot; the issue workbench's and duplicate review's actions are browser-memory simulations and say so.

## D-06 Fixture-driven clarifications (2026-10-27, adopted from A-049/A-050; full text D-T7-1..11 in tests/fixtures/golden/CALCULATION.md)
Eligible rows are all rows unless a rule declares a filter; the whitespace policy trims " \t\r\n" and an empty string is
missing. Critical failures = Σ `failure_count` of active critical rules on the current run; open critical issues are
counted separately; `critical_override` is true if either is above 0. Uniqueness key = the rule's field as exact text;
null keys are failures counted separately; the first row is kept; the dimension score is 1 − duplicate-row share.
Timeliness target = the dataset's daily local time in its IANA zone plus a grace in minutes; the window is [occurrence,
deadline), so a refresh at the deadline is late; only monitored datasets count; datasets gain `refresh_local_time`,
`refresh_grace_minutes`, `monitored` and `last_refreshed_at` (added to the data model). Weighted score: unmeasured
dimensions are dropped from both sums, null if none is measured, validity enters as populated-only. Match precision =
approved merge decisions confirmed by the synthetic truth ÷ approved merge decisions (a reversal does not remove the
approval); the wider reviewed share is `reviewed_correct_share`. Checklist cl-1 = definition, grain, source_fields,
owner, refresh (non-blank text, non-empty field list, existing owner); only published metrics count. Resolution time
ends at the verifying rerun's `run_at`; a reopened issue is open and keeps its first `detected_at`. Metric keys:
`metrics.{completeness, validity, uniqueness, relationship_integrity, timeliness, weighted_score, critical_failures,
resolution_time, ownership_coverage, definition_coverage, match_precision, lineage_coverage}`, the first four keyed by
rule id, labelled pairs as {label, value}. Rejection is atomic per record; a child of a rejected parent is
DEPENDENT_REJECTED; a reverse-order twin is DUPLICATE_PAIR; a first-seen pair with left > right is NON_CANONICAL_ORDER;
a dataset without an owner is OWNER_REQUIRED; a merge by its proposer is REVIEWER_IS_PROPOSER. Observed lineage counts
distinct (source, target) pairs; inferred edges never enter the observed numerator. Golden: weighted score 0.963932
under w2 and 0.958116 under w1 with the override true; uniqueness 1/98 groups and 2/100 rows; relationship 36/38 with 2
nulls; timeliness 3/4; ownership 4/5; definitions 3/4; lineage 5/6; precision 2/3; resolution mean 38.4444 h.

## D-07 Backend clarifications (2026-10-27, adopted from A-052; the 23 numbered assumptions are in README.md)
`metrics` is exactly the 12 keys; `rules`, `definitions` and `matching` travel beside it. Facts after `as_of` do not
exist yet (a rule disabled after `as_of` is still active at it; issue lifecycle fields clipped). The half-open window
narrows issues by `detected_at`, observed lineage by `observed_at`, candidates by `proposed_at`, decisions by
`decided_at`; row measurements, timeliness, ownership and definitions are snapshots. Weight version in force = latest
`valid_from` not after `as_of`; C03 refuses weights differing from the named version (422
WEIGHT_CHANGE_REQUIRES_VERSION); weight versions are append-only and sum to 1 over the five dimensions. Several rules
of one dimension on one dataset contribute their mean; an unmonitored dataset's timeliness rule and a validity rule
without a pattern are not measured; a relationship rule whose parent has no rows matches nothing. Cells compare as
exact text; floats and nested values in rows are rejected; rules may declare an eligibility filter {field, equals}.
Timeliness grace is 0..1439 minutes; a monitored dataset declares zone, local time and grace; never refreshed is late;
a repeated local time is the later instant (as PostgreSQL AT TIME ZONE). Issue statuses are open, investigating,
closed; resolved and claimed are derived; `detected_at` = the failing run's `run_at`; a verification must not predate
the latest reopen; an issue whose verification run is not a successful rerun of the same rule and version is rejected
at ingest (VERIFICATION_RUN_INVALID). **Coordinator decision:** C05 gains `action=claim` and `action=reopen` (the
contract had no close/reopen command and P07-TEST-09 needs "closed without rerun = claimed"). C04 opens one issue per
failing scheduled run; owner defaults to the dataset owner and must be active. C10 performs and stores the rerun over
the issue's recorded records; not verified is 200 with status claimed and a reason (RERUN_STILL_FAILING, RULE_DISABLED,
RULE_VERSION_DIFFERS, NO_RECORDS_TO_CHECK). C06: score is a decimal string of at most 6 places; a pair in either
orientation is 409 DUPLICATE_PAIR; a first-seen left > right pair is 422 NON_CANONICAL_ORDER; a shared name and address
gets the uncertainty note and a warning; a candidate never produces a decision. C07/C08: the reviewer is the actor;
reviewer = proposer is 403 REVIEWER_IS_PROPOSER (audited); one decision per candidate also under a race; 409
RECORD_ALREADY_MERGED guards chains; a reversal needs a reason, targets an approval, happens once. C09: disabled stays
disabled; reason required. C02: valid_from and approver server-stamped; statuses draft and published; v2+ needs a
reason; an incomplete checklist is allowed with a warning. C01: registered_at server-stamped; up to 1,000 rows per
load. Precision reads `verification_truth` only when a test or reviewer created it (otherwise null with
MATCH_TRUTH_UNAVAILABLE); any decided record without a truth row gives null, never 0. Extra ingest codes:
MALFORMED_RECORD, DUPLICATE_ID, SCHEDULE_REQUIRED, INVALID_COUNTS, ALREADY_REVIEWED, INVALID_REVERSAL, ALREADY_REVERSED,
VERIFICATION_RUN_INVALID, UNKNOWN_OWNER. group_by returns the 10 scoped metrics per group; definition coverage and
precision are portfolio-wide. `quality_rules` holds one current row per rule; no command creates or versions rules.
Known: SQL uses PostgreSQL regexes and tz data while the domain uses Python `re` and system tzdata (patterns avoid `\s \d \w \b`, which the ingest refuses: D-10 R7-04); reads load the whole population per request.

## D-08 Synthetic world and the observed-edge rule (2026-10-27, adopted from A-055)
Seed 20261026, daily runs 2026-07-13..2026-10-04, `as_of` 2026-10-05T00:00:00Z; 40 datasets across 6 source
systems, 420 fields, 18 owners (3 inactive), 15 monitored datasets, 2,554 rows on 30 datasets; 60 rules (14 at version
2 or more, 5 disabled), 4,609 runs (4,257 scheduled, 352 reruns); 574 issues (315 resolved, 99 claimed, 160 open, 9
reopened); lineage 80 declared, 70 observed (58 on declared edges, 12 undeclared), 10 inferred; 30 metrics with 45
versions and 15 changes; 2,000 customer records, 400 candidates, 220 reviewed (174 approved, 46 rejected), 15
reversals; synthetic match truth only in the manifest. "220 reviewed merges and 15 reversals" = 220 candidates with an
approve or reject decision plus 15 reverse decisions; "70 observed edges" are distinct pairs; "oldest open issues all
claimed" holds by construction before 2026-08-25; "one team twice as fast" is by the owner's team on mean resolution
hours (Data Platform 34.4202 h vs 86.1833 h); "near-perfect" means above 0.95 under both weight versions
(ds-customers 0.990175 under w2 with the override true). Row-level measurement is authoritative at the as-of and the
last scheduled run of every active rule stores the same counts, except the INJ-12 rule whose current version adds a
filter (not comparable). Entity files are wrapped; the config lives in the manifest; the seeder's directory mode
cannot read the wrapped files (tests build the inputs object). Seeded issues carry no `record_ids`, so C10 reruns the
whole rule. Outcome-informed choices, disclosed: a stray draw removed and the rule-version-free window around
2026-09-01 widened from 7 to 14 days before the final run; nothing re-drawn on its value. Precision 172/174 = 0.988506
is reported as drawn. **Observed-edge rule (coordinator fix after the generator's finding):** an edge is accepted only
when (`evidence_type` = observed) ⇔ (`observed_at` is present); otherwise MALFORMED_RECORD, in the domain, the
reference script and the database check `edges_evidence_ck`.

## D-09 Site decisions (adopted from the web hand-back)
1. Small muted text uses `#5a5e57` (AA on `#f4efe4`); the brief's `#6b6f68` stays a token only. Vermilion marks only critical
   severity and the critical override; claimed, inactive and late use hatched or outlined chips. System font stacks, nothing fetched.
2. Rule patterns are JavaScript RegExp in the browser and Python `re` in the reference; both refuse a trailing newline under `$`.
   A pattern using `\s \d \w \b` is refused at ingest and the evidence page says what is and is not assured (D-10 R7-04, R7-13).
3. Time zones use the browser's Intl database (`hourCycle` h23): a local time that occurs twice resolves to the later instant, a
   time that does not exist uses the offset before the change. The golden check probes UTC instants in the seven zones over all of
   2026 and every 30 minutes around both DST transitions against Python digests.
4. JSON cannot distinguish `1.0` from `1`; the published data carries no such float, and the reference rejects one.
5. The manifest carries no `code_sha`; the strip shows "not recorded" until publish stamps it.
6. The manifest's `synthetic_truth` enters only the precision step (verification layer), never the inputs; precision appears on
   `/merges/` and `/evidence/` labelled as such.
7. The simulated rerun on the issue workbench re-measures the whole rule over the published rows (seeded issues carry no record ids);
   not-verified outcomes carry RULE_VERSION_DIFFERS, RULE_NOT_MEASURABLE, NO_RECORDS_TO_CHECK or RERUN_STILL_FAILING; a disabled rule is rerun like an active one
   (D-10 R7-02), and the note says it is disabled.
8. Impact: a metric's source field `orders.amount` reads dataset `ds-orders`; downstream follows declared edges only; the page lists
   what a change reaches and says it does not predict movement. The glossary holds successive versions, not rival concurrent definitions.
9. The weight-shift column and the DR-03 figures use exact fractions (last version minus first). Paging and filters live in the URL.
10. `scripts/review-check.ts` holds hand-worked adversarial worlds (25 checks, 58 after D-10) and runs inside `npm run check`.

## D-10 Review fixes (adopted from review R7)
Adopted 2026-10-27 from the reviewer's reproductions (R7). The domain (`domain/trustledger/`), the SQL reference (`data/sql/reference_metrics.sql`, migration
`0003_review_r7.sql`), the TypeScript mirror (`web/src/domain/`) and the independent `tests/reference_check.py` carry each rule; the golden fixture changed only where
stated. One bullet per item, with the alternative that was rejected where there is one.
* **R7-01 Timeliness at `as_of`.** A dataset is on time at `as_of` when a refresh (not after `as_of`) exists in [latest occurrence <= `as_of`, its deadline). Otherwise,
  if that occurrence's deadline has not passed, it is **pending**: neither on time nor late, outside the timeliness denominator, counted in `pending_count`
  (`evaluated_datasets` is the denominator); once the deadline has passed with no refresh in the window it is late (a refresh at the deadline is late). A pending
  dataset's timeliness rule has eligible 0 and is not scored. Pinned in the golden fixture by `probes.timeliness` / `timeliness_probes` (the reviewer's case: ds-customers
  refreshed 10:10Z, `as_of` 10:30Z, on time; the clocks-back case: a refresh at 05:45Z when the repeated 01:30 in New York resolves to 06:30Z is **late**, a refresh at
  06:45Z on time). *Rejected:* judging only the latest occurrence whose grace has closed (a dataset refreshed 20 minutes into its open window was reported late);
  treating a pending occurrence as late (punishes a window still open) or as on time (credits a refresh that has not happened).
* **R7-02 Disabled critical rules.** A critical rule disabled while its latest run (a rerun counts) fails keeps counting that run's failures in `critical_failures`, and the
  override, until a verified rerun passes; the list is `critical_failures.carried`. Disabling never clears a live failure. C10 therefore reruns a disabled rule's issue
  (it no longer answers RULE_DISABLED without a rerun; a validity rule with no pattern answers RULE_NOT_MEASURABLE) and a passing rerun resolves the issue and clears
  the carried failure. *Rejected:* letting the failure vanish with the rule (the defect), and carrying it for ever (a verified rerun must be able to clear it).
* **R7-03 Identity.** The backend resolves `X-Actor-Id` against `owners` (exact id: 401 UNKNOWN_ACTOR when it is not registered, no case folding or trimming; 403
  ACTOR_INACTIVE when the owner is inactive). The role is the register's: `X-Actor-Role` must be one of analyst/steward/admin (403 ROLE_FORBIDDEN) and equal the
  register's role (403 ROLE_MISMATCH). A proposer cannot approve or reverse their own candidate (409 SELF_REVIEW, audited); the same holds for a definition drafted and
  reviewed by one person (C02). Mode B applies the same rule in its browser simulation (inactive, role, self-review, one decision), with the same codes. The
  domain and database keep REVIEWER_IS_PROPOSER for stored data. *Rejected:* trusting the role header (any caller could claim steward) and a 403 for self-review
  (it is a state conflict with the candidate, so 409).
* **R7-04 Portable patterns.** A pattern is portable only if it avoids `\s \d \w \b` and their negations (an escaped backslash is fine). A rule whose pattern uses them is
  rejected at ingest `PATTERN_NOT_PORTABLE` in Python, TypeScript and the reference, and by a database check; the fixture and generator patterns use explicit classes
  (`[ \t\r\n\f\v]`, `[0-9]`). Five characters the engines disagreed about (U+00A0, U+FEFF, U+0085, U+2028, U+001C) are ordinary characters for the explicit class, and all
  three implementations are shown to agree. *Rejected:* keeping "the common subset" as a promise in documentation and translating the classes per engine.
* **R7-05 Uniqueness.** score = (eligible - null-key rows - duplicate rows) / eligible; null-key rows are counted (`null_key_count`) and listed (`null_key_row_ids`)
  apart. The golden has no null key, so its figure stays 0.980000 by rows; a null-key probe (cust-001's key null: 0.970000) is in the review checks and CALCULATION.md.
  *Rejected:* the old 1 - duplicate-row share (a null key lowered nothing).
* **R7-06 Self-edges.** A lineage edge with source = target is MALFORMED_RECORD in the domain, the TypeScript ingest and the reference (the database check already
  refused it); the seeder never aborts on one.
* **R7-07 Correcting data without SQL.** C11 `correct-dataset-rows` (analyst, steward, admin) is append-only: each correction is a new row version (`row_version`,
  `supersedes_row_id` = `<row_id>@<previous version>`, `reason`, the actor, the server's instant); nothing is edited and every earlier run and earlier `as_of` read stays as
  it was; measurement and C03/C10 use the latest version of each record recorded by their instant. C12 `record-refresh` (all roles) appends a refresh to
  `dataset_refreshes`; a dataset's last refresh at an instant is the latest of the loaded value and the recorded ones not after it. The tests no longer UPDATE `datasets`
  (C12) and resolve a completeness issue through C11 then C10 with no SQL outside the application. *Rejected:* putting the refresh inside C11 (a refresh is not a
  correction of rows) and an UPDATE-in-place of rows (it would rewrite history).
* **R7-11 Empty foreign keys.** An empty-string or whitespace-only foreign key is missing under the `trim_empty_is_missing` policy and is counted with the nulls
  (`null_fk_count`, with `empty_fk_count` for the text ones); the site labels the column "null or empty (whitespace policy)". Pinned in the golden: ord-036's key is
  `""` (relationship 35/37 = 0.945946, ds-orders 0.967568 under w2 and 0.972973 under w1; hand arithmetic in CALCULATION.md).
* **R7-12 Citations, review state, rule versions.** D-05's choice of 6-place proportions cites P07-MET-xx-R03 (the spec's output units; see D-05). Definition versions
  gain the state `reviewed` between `draft` and `published` (P07-FLOW-02-R02): C02 steps draft -> reviewed -> published, each a new version row with the content
  unchanged, the reviewer not the author (409 INVALID_TRANSITION, CONTENT_CHANGED, SELF_REVIEW); only published versions count; the glossary shows the state and the order.
  An append-only `quality_rule_versions` table carries the definition of every rule version (the generator states the earlier ones), so an earlier version's denominator
  is readable (`GET /data/quality_rule_versions?rule_id=`); the rule's own row is its current version. *Rejected:* calling the steward's publication "the review" (the
  contract names three states) and rewriting a rule's definition in place.
* **R7-13 Evidence page.** The limits no longer promise "the common subset": they say patterns are three engines' regular expressions, that non-portable escapes are
  refused, that no assurance is given beyond the patterns in the data, and name the four zones with daylight-saving time (America/New_York, America/Chicago,
  Europe/London, Europe/Berlin) and the three without (UTC, Asia/Kolkata, Asia/Singapore).
* **R7-14 Naive instants on reads.** Reads (`from`, `to`, `as_of`) refuse an instant with no zone, a date included, with 422 TIMESTAMP_INVALID, like commands.
  *Rejected:* reading a naive value as UTC (a silent choice of zone).
* **R7-15 CI skips.** The pytest step runs with `-ra` and a following step fails unless the junit file says `skipped="0"` (and has tests), so a silent skip cannot pass CI.
* **R7-16 Canonical order.** The TypeScript mirror compares strings by code point (`cmp`, with a test on the reviewer's pair rec-U+FF21 / rec-U+1F600), as Python and
  PostgreSQL (`COLLATE "C"`) do; UTF-16 order would reverse that pair and disagree on which orientation is canonical.
* **R7-17 Accessibility.** `/issues/` and `/duplicates/` have `role="status"` live regions that exist before the first action; Escape clears the lineage isolation
  and `aria-pressed`.
* **R7-18 Shift footnote.** The scorecard says the shift column uses the exact fractions, so it can differ from the difference of the rounded scores by 0.000001.
* **R7-20, R7-09, R7-10** are case-study wording the coordinator fixed in `project.json`; nothing here changes it.
