# TrustLedger synthetic data generator

`data/generate.py` (stdlib only, specification `docs/data-generator.md`) writes the published synthetic snapshot. A master
`random.Random(seed)` hands one child stream to each purpose (owners, datasets, rules, rows, runs, issues, lineage, metrics, customers,
matching, injections). Every probability is parts per million (or per hundred) and every draw is `randrange`; no float decides anything or is
written; instants are `datetime` arithmetic on fixed UTC offsets; nothing iterates a set of strings. The same seed gives byte-identical files and
the same `dataset_hash` (checked under `PYTHONHASHSEED` 0, 1, 2). The generator imports nothing from `domain/`: the five measures, the weighted
score, the timeliness occurrence and the issue classes are restated from `docs/contracts.md` (D-01..D-07); `tests/test_generator.py` runs the
domain over the output and compares.

```sh
python data/generate.py --seed 20261026 --out web/public/data     # about 0.3 s, 2.34 MB in all (entity files 2.15 MB)
python data/generate.py --profile golden-shape-check              # field names against tests/fixtures/golden
python data/generate.py --inputs /tmp/inputs.json                 # one inputs object for data/seed.py (not committed)
DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/trustledger python -m pytest -q -p no:cacheprovider tests/test_generator.py
```

## Output

| File | Content |
|---|---|
| `web/public/data/<entity>.json` | `{"entity","dataset_version","rows"}` for the 12 contract entities (`owners`, `datasets`, `fields`, `quality_rules`, `rule_runs`, `issues`, `lineage_edges`, `metric_versions`, `definition_changes`, `customer_records`, `match_candidates`, `merge_decisions`) and two more: `dataset_rows` (a flat list; each row carries its `dataset_id` beside `row_id` and its cells) and `weight_versions` (w1, w2). `dataset_version` is `tl-20261026-20261026`. |
| `web/public/data/manifest.json` | `dataset_version`, `dataset_hash`, `generated_at` (real UTC, not hashed), `contract_version` "v1", `as_of`, `config` (whitespace policy, weight and checklist versions, probe), `generator` {name, seed, parameters as strings, including the disclosures}, `row_counts`, `designed_relationships` with realised numbers, `stats`, and the `synthetic_truth` block (record id to synthetic entity for the 2,000 records, with the precision it gives). |
| `data/injection-manifest.json` (+ copy in `web/public/data/`) | `INJ-01..12` (`test` P07-TEST-01..12) with `records` (in-file evidence), `expected_handling`, `expected_rejections` (empty everywhere), `events` and machine-checkable `checks` (path into the domain's `golden()` shape and the value or length expected), and `designed_relationships` DR-01..06. |
| `data/injection-events.json` | EV-01..EV-12, one per defect: replay-only command sequences (28 steps). A step is a `command` (headers, the full request envelope, `expected_status`, `expected_reason` = `error.details[0].rule_id`, optional `expected_result` subset of the response and `expected_warning_codes`, `bind` to take a value such as `merge_id` from an earlier step), a `database` insert (`expected_error` names the violated constraint) or a `read` (`path`, `params`, `expect` paths into `data`). |
| `web/public/data/golden/` | the fixture in the same per-entity shape (`golden-v1`), `expected.json`, and `manifest.json` (with the fixture's synthetic truth, as it is the only place the truth may sit). |

`dataset_hash` = sha256 over the concatenation, in entity-name order, of `json.dumps(rows, sort_keys=True, separators=(",", ":"))` for each of
the 14 entity files. The files are not in the shape `data/seed.py` reads from a directory (it expects bare lists and a `dataset_rows` dictionary):
`tests/test_generator.py::make_inputs` builds the inputs object (config from the manifest, `dataset_rows` regrouped by `dataset_id`) and
`seed.seed(conn, inputs, dataset_version="tl-20261026-20261026")` loads it, so that commands carrying the published version are not stale. The
truth is loaded into `verification_truth` by the test only.

## The world

* **Register.** 40 datasets across six source systems (crm 8, billing 7, erp 8, support 6, logistics 6, web 5), 420 fields (10 or 11 each), 18
  owners in six teams (3 inactive: own-09, own-12, own-15), 15 monitored datasets with a zone, a daily local time and a grace. Four datasets are
  registered inside the window (2026-07-20, 08-10, 08-24, 09-14); their rules start with them. 30 datasets carry measured rows (2,554 rows in all).
* **Rules and runs.** 60 rules: completeness 14, validity 12, uniqueness 11, relationship 13, timeliness 10 (five critical: the keys of customers,
  orders, payments and ledger entries, and order lines to orders). 14 rules are at version 2 (one at 3) after an eligibility filter
  (`status = active`) was added; 5 are disabled with a reason and a date. A daily scheduled run from the rule's start (84 days at most) gives 4,257
  scheduled runs and 352 reruns (4,609). Weight version w1 before 2026-09-01, w2 from it.
* **Issues.** 574 issues, each on a failing scheduled run (probability by severity), triaged (investigating with a due date, or open), claimed
  (closed without a rerun, 99) or resolved by a rerun of the same rule version with no failures (315); 9 are reopened. Before 2026-08-25 no
  issue is left open; the fast team (Data Platform) draws delays at about 0.4 of the others'.
* **Lineage.** 80 declared, 70 observed (58 on declared edges, 12 undeclared), 10 inferred (4 on declared edges that were never observed).
* **Definitions.** 30 metrics, 45 versions (15 metrics with a second version and a change record), 7 effective versions with a checklist gap.
* **Customers.** 2,000 records in crm, billing, support (759, 676, 565), invented names and opaque address keys; 400 candidates (342 true
  pairs, 25 households that share a name and an address, 33 near names), 220 reviewed, 15 reversals (235 decisions).
  E-mails in the dataset rows are on example domains.

## Designed relationships (realised numbers in the manifest)

| | Realised |
|---|---|
| DR-01 near-perfect score, open critical key failure | ds-customers 0.990175 (w2), 0.990329 (w1); critical failures 2, one open critical issue; the only dataset with the override |
| DR-02 inactive owners | 5 datasets uncovered, coverage 35/40 = 0.875000 |
| DR-03 weight change without a rule change | 13 of 29 scored datasets differ between w1 and w2 on the same rows (7 by 0.005 or more, largest -0.167477); mean 0.950980 (w1) to 0.943118 (w2); no rule changed version within 14 days of 2026-09-01 |
| DR-04 one team twice as fast | Data Platform 34.4202 h (109 resolved) against 86.1833 h (206): ratio 0.399384 |
| DR-05 oldest unresolved all claimed | the oldest 64 unresolved issues (to 2026-08-25) are all claimed; 259 unresolved in all |
| DR-06 matching | precision 172/174 = 0.988506 (2 wrong approvals, one a household); share of reviewed pairs the truth says are one entity 0.840909 |

## Defects: where each lives

| Defect | In the entity files | Event | Handling |
|---|---|---|---|
| INJ-01 critical failure under a high score | ds-customers, its key rule, one issue | EV-01 | override true beside 0.990175 |
| INJ-02 a disabled rule's history | 5 disabled rules with runs and issues | EV-02 | history retained; a disabled rule is 409 RULE_DISABLED |
| INJ-03 shared name and address | 25 household candidates | EV-03 | uncertainty note, never merged |
| INJ-04 null foreign keys | ds-orders (rule `r-orders-fk-customer_key`) | EV-04 | excluded from the denominator, counted |
| INJ-05 weight change without a version | w1, w2 | EV-05 | 422 WEIGHT_CHANGE_REQUIRES_VERSION |
| INJ-06 irreversible merge / merge by the proposer | 15 reversals | EV-06 | 403 REVIEWER_IS_PROPOSER; reversal restores both identities |
| INJ-07 inactive owner counted as covered | 5 datasets | EV-07 | uncovered; 422 OWNER_INACTIVE |
| INJ-08 inferred lineage as observed | 10 inferred edges | EV-08 | never in the observed numerator; the database refuses observed without `observed_at` |
| INJ-09 closed without a rerun | 99 claimed issues | EV-09 | claimed, not resolved; C10 leaves it claimed |
| INJ-10 duplicate pair both ways | none (cannot sit in a clean file) | EV-10 | 409 DUPLICATE_PAIR; 422 NON_CANONICAL_ORDER |
| INJ-11 definition rewritten in place | 15 metrics with change records | EV-11 | 409 DEFINITION_IMMUTABLE |
| INJ-12 denominator change between compared runs | one rule at version 2 after its last v1 run | EV-12 | RULE_VERSION_DIFFERS, no rates compared |

The clean files produce no ingest rejection (`expected_rejections` is empty everywhere); the defects that cannot sit in a clean file (a merge by its
proposer, a reverse-order pair, a weight change without a version, a rewrite in place, a close without a rerun, an observed edge without an
observation time, an inactive owner on a new dataset) are replay-only.

## Stored counts and row-level truth (D-07 assumption)

The domain re-measures the rows; the stored counts are history. At the as-of the row-level measurement is authoritative, and the generator makes the
last scheduled run of every active rule store the same eligible and failure counts (the test asserts it). Earlier runs follow a trajectory
that ends there (80 % to 100 % of the rows, a drift, noise and occasional spikes); rows are the as-of snapshot, so the domain at an earlier as-of
measures the same rows. The one exception is the INJ-12 rule, whose last run is version 1 (all rows) and whose current version 2 filters the rows.

## Outcome-informed choices (disclosed)

Nothing was re-drawn, kept or dropped because of its value. Parameters of the designed relationships were chosen before the first run and came
out as designed. Two code changes altered the draws before the final run (a stray draw removed; the window kept free of rule-version changes widened from
7 to 14 days around 2026-09-01 after 8 realised changes were seen 8 to 14 days from it); the reported world is the first run of the final code.
The sizes were set to reach "about 4,500" runs and "about 600" issues (4,609 and 574 realised).

## Assumptions where the specification or contract was silent (for D-08)

1. "220 reviewed merges and 15 reversals": 220 candidates carry an approve or reject decision (174 approvals, 46 rejections) and 15 further
   `reverse` decisions reverse approvals (235 `merge_decisions`). Candidates are disjoint pairs of records, so no record is in two merges.
2. "70 observed edges (12 undeclared)": 70 distinct observed pairs, one row each, 58 on declared pairs; coverage 58/80 = 0.725000.
3. "The oldest open issues are all claimed-not-verified": the oldest unresolved issues (open, investigating, reopened or claimed) are all claimed.
4. "Issues owned by one team": by the team of the issue's owner, which is the owner of its dataset; "twice as fast" is the mean of resolution hours
   over resolved issues, the fast team being below half.
5. "Near-perfect weighted score": above 0.95 under both w1 and w2 (0.990175 and 0.990329), exact counts rather than drawn rates.
6. Rule runs are about 4,500 including reruns; rules start at different days, so not every rule has 84 runs.
7. Owners inactive at the as-of keep their datasets (uncovered), and their issues after the deactivation are mostly left open.
8. Rows carry only the columns the rules read plus `status` and a few extras, not all fields of the dataset's register; the 420 fields are the register.
9. Customer records carry no personal details beyond an invented normalized name and an opaque address key (the fixture's fields); e-mails are on
   example.com, example.org and example.net. A pair that shares a normalized name and an address key gets the uncertainty note whether or not the
   truth says it is one person.
10. `config` (whitespace policy, checklist, probe) lives in the manifest; `data/seed.py` has no way to read it from the wrapped entity files.
11. The seeder stores the issues' closed times as given; seeded issues carry no `record_ids`, so C10 reruns the whole rule (replay EV-09 relies on it).

## Domain behaviours noted (not patched)

* `ingest` accepts an `observed` edge without `observed_at` (the database refuses it, `edges_evidence_ck`): the domain would count it as observed.
* The seeder's directory mode cannot read these wrapped files (a limitation of the file format, not of the domain).
