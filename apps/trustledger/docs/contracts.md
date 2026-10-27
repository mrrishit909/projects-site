# TrustLedger — business contracts, version 1 (2026-10-27)

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
Proportions are decimal strings with 6 places in [0,1]; counts nonnegative integers; hours 4 dp; null means unknown or
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
Known: SQL uses PostgreSQL regexes and tz data while the domain uses Python `re` and system tzdata (patterns stay in the
common subset); reads load the whole population per request.
