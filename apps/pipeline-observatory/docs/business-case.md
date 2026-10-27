# Pipeline Observatory: business case (P08-ART-01)

Dataset `po-20261026-20261026` (generator `dataset_hash` `0a90687778634365c402c5431661b56625de20785e28d9b2388d36c0cad19aab`), contract v1, code revision `ed7eb5a` (the app content published as `b326690`). **Every stakeholder, scenario and number here is synthetic.** Nothing is a claim about a real organisation, a real data estate, a real person or a measured benefit (P08-GOAL-12, P08-DOMAIN-04). Observed results (what this one generated draw shows), simulated outcomes (what the generator built in: the designed relationships DR-01..DR-05 and twelve injected defects) and hypothetical real-world benefits (not claimed) are kept apart.

**How to read it without installing anything:** this file needs nothing installed. The numbers are quoted from `sql-analysis.md` (observed, investigations 01-10 and the reconciliation of its section 11); `requirements.md` traces each requirement id to code and tests; `executive-memo.md` turns the evidence into a recommendation. Proportions are decimal fractions with six places, minutes have four places, and every rate names its denominator and its scope (complete world, 2,000-row sample, or recorded).

## The business decision
**Is this dataset safe, complete, and fresh enough to publish?** (P08-GOAL-01.) The primary users are a data engineer and a data reliability analyst, with the analytics engineer as the third portfolio role (P08-GOAL-02). Pipeline Observatory changes no source: it fetches, validates, commits, gates and publishes a synthetic dataset, measures each of those steps, and keeps the evidence.

## Business problem
The pipeline dashboard is green and the numbers are wrong. These are the six ways it happens, each with the metric that exposes it and the workflow that handles it:
| What goes wrong | Metric that exposes it | Where it is handled |
|---|---|---|
| A source stops delivering while its jobs keep succeeding | freshness beside ingestion age (P08-MET-01/02) | `freshness_within_target` in the gate (C05); `src-refunds`: 262,378 s against 17,363 s, 72 green runs |
| A batch crashes after writing rows and the replay counts keys twice | received / accepted / duplicate / quarantined (P08-MET-04/05), the key boundary | C03 commit with the checkpoint in one transaction; `accepted_records` primary key; 8 replayed crashes classified once |
| A malformed row vanishes | rejection rate; every received row in exactly one class | C02 validate: quarantine with a reason code; 429 quarantined, 17 schema-quarantined, 123 deleted, nothing dropped |
| A failed run replaces the published table | gate decision and the publication pointer (P08-FLOW-05/06) | C05 gate fails closed; C06 publish only a passed candidate; 25 runs never moved the pointer |
| Events arrive after the watermark and are lost | late events (P08-MET-08) | the watermark is disclosed per publication; late events enter the next one (757 recorded, 0 lost) |
| The published total differs from the source total and nobody can say why | reconciliation residual with its parts (P08-MET-09) | C09 closes an incident only on a verified recovery; 1,318 of 1,318 publications reconcile to 0.00 (recorded), one blocked candidate -141.46 |

## Simulated stakeholders (roles, not people)
| Role | Wants | Uses |
|---|---|---|
| Data engineer | to know the delivery guarantee at the key boundary and to replay safely | commands C01..C10, `docs/api-contract.md`, the crash experiments |
| Data reliability analyst | to see staleness the jobs hide, and to trust the numbers | the freshness view, the gate, the incident timeline, `sql-analysis.md` |
| Analytics engineer | models whose keys and relationships are tested, and a publication with a stated residual | `model_definitions`, `model_outputs`, the quality results |
| Source owner | to be told when a source goes silent or is rate limited | the source contracts, the fetch log |
| Data consumer | a snapshot that is either current or honestly labelled | the publication pointer and its watermark |
| Reviewer | to disprove the claims | the golden fixture, the independent oracle, the injection manifest |

## Scope
In: six synthetic sources (orders, payments, refunds, shipments, inventory, web events) over 56 days of hourly runs: 1,311 batches, 40,191 raw rows (published as a 2,000-row sample plus per-batch counts), 1,343 runs, 5,462 task attempts, 9,296 quality results, 1,318 publications, 25 incidents, 15 backfill requests and 1,361 fetches; ten commands (C01 fetch a page, C02 validate, C03 commit, C04 transform, C05 run the gate, C06 publish, C07 inject a fault, C08 request a backfill, C09 recover an incident, C10 archive evidence); twelve metric families; the static site (ten product screens, P08-UI-01..10, plus the landing and evidence pages) over the published snapshot.
Out: any real source, scheduler, retention job or network fetching; authentication (identity is header-asserted); the full raw-record history in the verified database.

## Current-state and future-state process
**Current (simulated):** the orchestrator is green; a source went quiet three days ago and nobody noticed; a crashed ingest was replayed and a key was counted twice; a row with a negative quantity disappeared; a failed run still swapped the table; the late events were dropped; the published total is off by an amount nobody can explain; the incident closes when the process restarts.
**Future (Pipeline Observatory):**
1. Fetch pages from a cursor; honour `retry_after_seconds`; stop a repeated cursor inside a session (CURSOR_LOOP); record a re-poll in a new session as a refetch.
2. Validate every row against the contract: a key already accepted is a duplicate; else missing field, invalid field, negative quantity, event in the future are quarantined with a reason; a page declaring an unexpected schema is quarantined whole.
3. Commit a batch with its checkpoint in one transaction (at-least-once with idempotent apply, proven at the source-key boundary and never called exactly-once).
4. Transform, then gate fail-closed: seven checks, six critical; a critical failure blocks, opens an incident and leaves the pointer.
5. Publish an immutable snapshot with a disclosed watermark; reconcile source total, published total and signed exclusions to a stated residual.
6. Close an incident only on a verified recovery: a later run that passed its gate and reconciled; measure the time from detection.

## Decision criteria
| Criterion | Rule | At the as-of (observed) |
|---|---|---|
| Safe | the latest gate allowed the run; no failed run moved the pointer; every publication reconciles | `run-1343` allowed; 0 publications of failed runs; residual 0.00 on 1,318 of 1,318 (recorded) |
| Complete | completeness per source against the declared expectation; backfills verified | 0.945541 to 0.995255 per source; 0.000000 on three days of refunds; 11 of 15 partitions (0.733333) |
| Fresh | freshness within the declared target; no silent source | 6 of 6 within target; 1 silent (refunds) |
| Publish | blocked latest gate or a source past its target: no; silent source: with a stated exception | **publish with a stated exception** |

## Decision supported
Publish `pub-1343` with an exception for `src-refunds`; tighten its target; re-request the four unverified partitions (`executive-memo.md`).

## Limits and honesty
* One generated draw: the designed relationships and injected defects are constructed on purpose; the realised values are recorded in the manifest and none was tuned on its value; outcome-informed choices are disclosed there.
* The raw rows are a 2,000-row sample: figures that need them are recorded (labelled) or sample-scoped (labelled); the sample's duplicate rate (0.012247) is not the pipeline's (0.052655).
* The quarantine desk, backfill console and fault injection of the public site simulate their actions in browser memory; the transactional behaviour is verified on hosted runners.
* No benefit to a real organisation is claimed; no number here is a measured effect.
