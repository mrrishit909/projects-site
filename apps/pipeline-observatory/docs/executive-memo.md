# Executive memo: is this dataset safe, complete and fresh enough to publish? (P08-ART-07)

**Synthetic data throughout:** one generated platform (seed 20261026, dataset `po-20261026-20261026`, generator hash `0a90687778634365c402c5431661b56625de20785e28d9b2388d36c0cad19aab`, code revision `ed7eb5a`, as-of 2026-10-05T00:00:00Z). Nothing here is a claim about a real platform, a real source or a real person, and no benefit of acting on it is claimed. Three kinds of statement are kept apart: **OBSERVED** (what this one draw shows, reconciled to the independent SQL reference and the Python domain: `sql-analysis.md`), **SIMULATED / constructed** (what the generator built in, and one counterfactual computed here and labelled) and **HYPOTHETICAL** (what a real team might gain: not claimed). Every figure carries its scope: **complete world**, **2,000-row sample** or **recorded** (`sql-analysis.md` section 0).
How to read it without installing anything: the decision first, then the evidence table, the options, the uncertainty, the limits and what the sample cannot show; every figure is a decimal fraction (six places), a minute count (four places) or a count over a named population, each quoted from `sql-analysis.md`.

## Decision
**Publish the current snapshot `pub-1343` with a stated exception for `src-refunds`, and do not call the dataset complete or fresh without it.** This is the rule the site prints: a blocked latest gate or a source past its declared target means do not publish; a silent source means publish with a stated exception. At the as-of the first two conditions are false and the third is true:
1. **Safe: yes.** The latest gate (`run-1343`) allowed the run and moved the pointer to `pub-1343`. All 1,318 publications belong to successful runs with an allowed gate; the 25 runs that failed (10 blocked at the gate, 15 failed in a task before it) published nothing and left the pointer where it was. All 25 incidents closed on a verified recovery (mean 60.6827 minutes). Every publication reconciles to 0.00 (recorded); the one candidate that did not (`run-0731`, -141.46) was blocked.
2. **Fresh: five of six sources, not all.** No source is past its declared freshness target. **`src-refunds` is silent while its jobs are green**: freshness 262,378 s (72 h 52 min) against an ingestion age of 17,363 s (289.3833 min), silent since 2026-10-02T00:00:00Z. All 72 runs since then succeeded and the gate allowed all 72, because the source's declared target is 7 days (604,800 s), looser than the silence. This is the defect the project exists to show (P08-TEST-06), not a surprise: the gate cannot see it.
3. **Complete: 0.945541 for refunds over the window, 0.000000 on its last three days** (recorded); the other five sources are between 0.987485 and 0.995255. The three empty days were expected to hold 192 records (76, 63 and 53). Eleven of the fifteen backfilled partitions were verified (0.733333); four remain unverified.

**The exception to state with the publication:** "Refund events after 2026-10-01T23:07:02Z are not in this snapshot; any figure that nets refunds (net sales, refund rate) is overstated for 2026-10-02 to 2026-10-04."

## Evidence (OBSERVED unless marked)
| Question | Figure | Scope | Where |
|---|---|---|---|
| Rows received, accepted, duplicate, quarantined, deleted | 39,901; 37,248; 2,101; 429; 123 | complete world | sql-analysis 1 |
| Rejection rate, duplicate rate | 0.010752; 0.052655 (the 17 rows of the schema-quarantined batch are listed apart, not in either) | complete world | sql-analysis 1 |
| Crashed ingests replayed without a second copy | 8 of 8 (273 rows written, classified once; version step 1) | complete world | sql-analysis 1 |
| Run funnel | 1,343 runs; 1,328 reached the gate; 1,318 allowed; 10 blocked; 15 failed before it | complete world | sql-analysis 2 |
| Blocked at the gate, by check | freshness 5, relationships 4, residual 1 | complete world | sql-analysis 2 |
| Task success against attempt success | 0.995311 (5,307 of 5,332) against 0.971622 (5,307 of 5,462) | complete world | sql-analysis 3 |
| Freshness against ingestion age, refunds | 262,378 s against 17,363 s; target 604,800 s | freshness recorded; age complete world | sql-analysis 4 |
| Publication pointer | on `pub-1343`; 25 runs left it unmoved; a failure leaves readers on the older snapshot for 6,798 to 7,595 s (mean 120.1453 min, about two run cycles) | complete world | sql-analysis 5 |
| Verified recovery | 25 of 25 incidents; mean 60.6827 min (50.7500 to 72.4000); `inc-022` 67.8833; `inc-015` 63.1000 | complete world | sql-analysis 6 |
| Unexplained residual | `run-0731`, 2026-09-09: 23,694.91 - 22,698.71 - 1,137.66 = -141.46; blocked, no cause recorded | recorded parts, recomputed | sql-analysis 6 |
| Backfill coverage | 11 of 15 partitions = 0.733333; 2 requests for 4 partitions refused for overlap | complete world | sql-analysis 7 |
| Retry-after compliance | 49 of 49 retries honoured the hint (slack 0 to 25 s); 48 refetch rows, 1 loop | complete world | sql-analysis 8 |
| Late events behind the watermark | 757 (707 backfill, 41 corrections, 9 designed), all in the next publication, none lost | **recorded** (the sample recomputes 141) | sql-analysis 10 |
| Golden known answer | 10 / 8 / 1 / 1; 52,200 s against 42,900 s; 8 of 9; 475.0000 min | fixture | sql-analysis 9 |

## Options
| Option | What happens | Cost | Risk |
|---|---|---|---|
| **A. Publish `pub-1343` with the stated exception (recommended)** | consumers get five healthy sources now and are told what refunds lacks | the exception text must travel with the data | a consumer ignores the text and nets refunds anyway |
| B. Hold the publication until refunds resumes | no consumer sees a snapshot with the gap | the five healthy sources wait for a source that may stay silent | holding hides the same staleness longer |
| C. Publish and tighten the refunds target to two cadences (43,200 s) | the silence becomes loud: **SIMULATED**: from 2026-10-02T11:07:02Z the critical freshness check would fail, so 61 of the 72 runs since the silence began would have been blocked and the pointer would have stayed on the last snapshot before then | a blocked pipeline for as long as refunds is silent | blocks the five healthy sources too; the target must be agreed with the source owner |
| D. Publish as the gate says, without an exception | the dashboard is green | none | repeats the defect: a green run on a stale source |
A is the recommendation and C is the follow-up that makes it unnecessary: tighten the target after the exception is published, so the next silence blocks instead of passing.

## What would change the recommendation
* The latest gate blocked (a critical check failed) or any source past its declared target: **do not publish**.
* A second silent source, or `src-refunds` still silent after the exception has been communicated and its target tightened: escalate to the source owner named on the source contract before the next release.
* Evidence that the recorded freshness is wrong. For `src-refunds` the sample corroborates it (the latest accepted refunds event in the sample is the recorded `2026-10-01T23:07:02Z`).

## Uncertainty
* **Recorded, not found.** The latest accepted event of each source, the 757 late events, the reconciliation of each publication and the content hashes need every raw row; the published files hold 2,000 of 40,191. The analysis recomputes the arithmetic around them and labels them. The sample is not a substitute: it overstates accepted records by 53 and its duplicate rate (0.012247) is less than a quarter of the pipeline's (0.052655).
* One draw of a generator whose designed relationships and injected defects were planned before the run; the generator's author also made outcome-informed choices (event rates, targets, backfill dates), disclosed in `manifest.json`; none was tuned on a realised value.
* The completeness warning fails in 1,304 of 1,328 gates (0.981928) and so carries little signal; only the critical checks block.
* The simulated option C assumes the gate would use the same recorded freshness; it counts runs, not consequences.

## Limitations
* Synthetic data; a static snapshot; the quarantine desk, backfill console and fault injection of the site act on browser memory, not on the pipeline. The transactional behaviour is verified on hosted runners against PostgreSQL 16 (`technical-case-study.md`).
* Identity on the verified backend is asserted by headers; there is no authentication (D-09 R8-14). The sandbox for fault injection is off unless `PIPELINE_ENVIRONMENT=sandbox`.
* The verified database holds the published sample rather than the full raw-record history; the recovery and archive commands have no replay event; the SQL reference does not model delete events (the analysis reconciles that gap exactly: `sql-analysis.md` section 11).
* "Safe, complete and fresh enough" is defined here by the site's printed rule and the contract's checks; a real organisation would set its own thresholds.

## What the sample cannot show
Freshness (the latest event of a source); late events (141 over the sample against 757 recorded); the residual of a publication; the content hash of any publication (0 of 1,318 verifiable); the duplicate rate (a key whose first copy is in an unsampled batch looks new); the quarantine reasons of the 399 quarantine rows in unsampled batches; completeness by partition (the check is not discriminating on the sample).

## Recommendation
Publish with the exception, tighten the refunds target, re-request the four unverified partitions (2026-08-13, 2026-08-22, 2026-09-07, 2026-09-17: a settled request no longer blocks a new one), and treat the pipeline's own gate as necessary but not sufficient: it passed 72 runs on a source that had stopped.
