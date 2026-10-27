# InvoiceBridge: requirements and traceability (P05-ART-02)

Dataset `ib-20261026-20261026` (generator hash `1f001a43a7031d4260f5abb3b9f7a83f6e1b48397e85cf8b04e0b4d9e052162e`), contract v1, code revision `2dcc460`. **Synthetic data only.**
Organising question: **which invoices may advance and which require exception review?** (P05-GOAL-01). Observed, simulated and hypothetical results are kept apart in every row below: nothing is a realised benefit, and the only simulation is the seeded generator that produced the history.

Status values: `verified` (a command was run and its result is recorded here, in `uat-evidence.md` or in `release-package.md`) | `partial` (built in part, the gap named) | `deferred` (not built, stated openly) | `501` (the endpoint exists and answers 501 `NOT_IMPLEMENTED`) | `not_checked` (no check was run). The machine-readable ledger of the program is `docs/program/verification-ledger.json` (outside this directory). "Local" means run in the Linux container on PostgreSQL 16; "hosted" means a GitHub Actions run on a hosted runner. Hosted runs cited here are those of the ledger: Mode A at `a381e53` (run `40395845883`) and at the generator commit `ba922a1` (run `40402231716`), Mode A and Mode B at the site commit `be20031` (run `40405870287`) and the live check of that release (run `40406631388`).
**The reviewer fixes at `2dcc460` (release `188e409`) have local evidence only until their own hosted CI and live-check runs are recorded** (`release-package.md`).
How to read this without installing anything: sections 1-3 are the requirements, section 4 the traceability matrix, section 5 what is deferred.

## 1. User stories and acceptance criteria
1. **As an AP automation analyst** I open the landing page and see, for the as-of 2026-10-01T02:00:00Z, which invoices matched, which are obligations, what is blocked and why, what was exported and what is payable, each with its definition beside it and money per currency.
   *Accept:* the eleven metric keys equal the independent reference on the snapshot (`data/sql/reference_metrics.sql` against the Python domain; 227 TypeScript golden checks; the reconciliation of `sql-analysis.md` section 10).
2. **As an analyst** I see the known answer reproduced before any volume: a purchase order for 10 at 20.00, a receipt of 6, an invoice for 6 gives 120.00 before tax, 12.00 tax, 132.00 and one obligation; a second invoice for 4 is `QUANTITY_BLOCKED`; the first invoice imported again leaves one obligation.
   *Accept:* equal in the Python domain, the SQL reference, the TypeScript domain, the standard-library oracle `tests/reference_check.py` (ALL OK, 412 checks), `expected.json` and the workbook's `Golden case` sheet.
3. **As a clerk** I import the same bytes under another file name, or a re-scanned copy with another number format, and the desk keeps one obligation, with both imports in the lineage.
   *Accept:* `DUPLICATE_SOURCE_BYTES` and `DUPLICATE_IDENTITY` merge into the earliest import; a byte-twin with other extracted fields is held (`needs_review`); the same number from another vendor is not a duplicate.
4. **As a reviewer** I cannot approve what I imported, cannot approve above the limit of the policy in force at my decision, and when two reviewers race for one invoice exactly one approval stands.
   *Accept:* 403 `SELF_APPROVAL` and `SELF_DECISION`, `ROLE_OR_LIMIT`, 409 on the loser; the refusal is audited; the decision instant is stamped by the server.
5. **As a controller** I export what is approved, once, and a retry after a timeout returns the prior batch; I see the payable net of credits per currency and the exclusions that explain any difference.
   *Accept:* an idempotent batch (7 of 59 snapshot requests are retries), `UNIQUE (invoice_id)` on export rows, `export.by_currency` differences explained by explicit exclusions; credits apply once and move no cash.
6. **As a supervisor** every exception has an owner or is counted as unowned, and the backlog as of a cutoff is reconstructed from the append-only assignments.
   *Accept:* 232 open at the as-of, 29 unowned; the March and June month-end backlogs reconstructed (`sql-analysis.md` query 05).
7. **As a BI analyst** I can rebuild the headline measures from CSV exports and compare them with the independent recomputation.
   *Accept:* the measures recomputed from `artifacts/bi/*.csv` equal `reference_metrics.sql` and the domain (`bi-package.md`).
8. **As a reader of the evidence** I see what is built, what returns 501 (C06) and which screens do not act.
   *Accept:* the case-study route and this file say so (section 5).

## 2. Functional requirements
| ID | Requirement | Entities, metrics, commands |
|---|---|---|
| FR-01 | Import an invoice with its source hash and idempotency key; the same bytes under another name is one obligation; the extracted source is immutable | `invoices`, `import_lineage`; C01 |
| FR-02 | Validate decimal totals, required fields and a known active vendor; a rounding gap is an exception, not a validation failure | `invoices.validity`; C02 |
| FR-03 | Find duplicates by identity (vendor, normalised number, date, computed total) and merge later copies into the earliest; hold a byte-twin with other fields for review | `invoices.merged_into`; C03; P05-MET-09 |
| FR-04 | Match three ways per line, cumulatively against net receipts, with the reasons NO_PO_LINE, CURRENCY_MISMATCH, QUANTITY_BLOCKED, PRICE_VARIANCE; committed invoices keep their quantity | `match_results`, `receipts`, `po_lines`; C04; P05-MET-03..05 |
| FR-05 | Assign an exception to an owner with an append-only history; reconstruct the backlog as of a cutoff | `exceptions`, `exception_assignments`; C05; P05-MET-12 |
| FR-06 | Correct an extraction as a versioned row that never overwrites the original | C06 (501) |
| FR-07 | Approve under separation of duties and the policy version in force; reject with a reason | `approvals`, `approval_policies`; C07, C08; P05-MET-08 |
| FR-08 | Export approved invoices as an idempotent batch with a content hash; reconcile accepted export against eligible approved per currency with explicit exclusions | `export_batches`, `export_rows`, `export_requests`; C09; P05-MET-11 |
| FR-09 | Apply a credit note once, reducing the approved payable, moving no cash | `credit_notes`; C10; P05-MET-10 |
| FR-10 | Compute the eleven contract metrics for any half-open window, cutoff and grouping (none, vendor, currency) with disclosures beside them; money per currency | `GET /metrics`; P05-MET-01..12 |
| FR-11 | Read every entity with stable code-point ordering, paging and a half-open time filter | `GET /data/{entity}` |
| FR-12 | Serve the published snapshot as a static interactive site that reproduces the golden case and the derived views in the browser, with no write | Mode B: `web/` |
| FR-13 | Provide an independent SQL recomputation of every metric and reconcile every artifact number to it | `data/sql/reference_metrics.sql`, `data/sql/analysis/` |

## 3. Non-functional requirements
| ID | Requirement | How it is met |
|---|---|---|
| NFR-01 | Deterministic synthetic data: the same seed gives the same bytes; size under 5 MB | `data/generate.py` seed 20261026, byte-identical under three `PYTHONHASHSEED` values; 3.7 MB |
| NFR-02 | Exact arithmetic: Decimal and Fraction in Python, integer arithmetic in TypeScript, exact numerics in SQL; no float in a published figure | `domain/invoicebridge/money.py`; `test_domain_source_has_no_float`; `test_the_published_manifest_carries_no_float` |
| NFR-03 | Idempotent commands bound to actor, role, payload and dataset version; 409 for a reused key, a stale dataset version or a deadlock after three attempts; 422 with a rule id; never a stack trace | `api/commands.py`, `api/errors.py` (D-06, D-09.13) |
| NFR-04 | Atomic audit: the effect, the audit row and the stored result are one transaction; a failed command leaves no trace | `test_a_command_and_its_audit_row_are_atomic`, `test_every_successful_command_writes_its_audit_rows` |
| NFR-05 | Concurrency: lock order idempotency key, invoice rows, PO line rows; two approvals race: exactly one wins | `test_two_concurrent_approvals_leave_exactly_one_approval`, `test_concurrent_matches_on_one_po_line_never_double_consume` |
| NFR-06 | Authorization on the verified backend: 401 without an identity, 403 for a forbidden role; the public site claims no access control | `test_commands_need_an_actor_and_a_known_role`, `test_the_role_decides_who_may_run_a_command` |
| NFR-07 | Accessibility and responsiveness: four widths (360, 768, 1280, 1920) and 200 % zoom, no horizontal overflow, labelled tables | `web/e2e/screens.spec.ts` (60 screenshots in `web/evidence/`) |
| NFR-08 | No credentials, real personal records or secrets in any artifact; synthetic label visible | the artifact documents hold placeholders only (the local development login of the CI workflow is never written into them); `tests/test_artifacts.py::test_no_credentials...` |
| NFR-09 | Hosted compute and durable evidence: backend on a `postgres:16` service, static build on a hosted runner, evidence archived with checksums | `.github/workflows/invoicebridge-ci.yml`, `artifacts/CHECKSUMS.txt` |
| NFR-10 | Reproducible artifacts: every artifact number is reproducible by a named command and reconciled to an independent source | `data/sql/analysis/run_all.py` (the reconciliation rows), `tests/test_artifacts.py` |
| NFR-11 | Money is per currency: no figure adds one currency to another | `by_currency` in the metrics, `sql-analysis.md`, `workbook.md`, `bi-package.md` |

## 4. Traceability matrix
Code paths are under `apps/invoicebridge/`. A test name is a function of the named file.

| Requirement | Built in | Test | Evidence | Status |
|---|---|---|---|---|
| P05-GOAL-01, 02 (decision, roles) | `docs/business-case.md`, `docs/executive-memo.md` | `tests/test_artifacts.py` (documents quote the stored results) | `business-case.md` | verified (local) |
| P05-GOAL-03, 04, 06 (visual direction, slug and routes, static default) | `web/src`, `web/public/data/manifest.json` | `web/e2e/journey.spec.ts` (11 routes reachable by direct entry and reload) | CI `40405870287` (Mode B, `be20031`); local `npm run e2e` 71 passed at `2dcc460` | verified (hosted on `be20031`, local on `2dcc460`) |
| P05-GOAL-05, REL-05 (hosted backend suite with a transient PostgreSQL) | `.github/workflows/invoicebridge-ci.yml` | the whole `pytest` suite | CI `40405870287` Mode A (`be20031`); local 402 passed at `2dcc460` | verified (hosted on `be20031`); hosted run of `2dcc460` pending |
| P05-GOAL-09 (entry milestone: one source-to-decision journey and a working export) | `web/src/views/*`, `api/` | `web/e2e/journey.spec.ts`; `test_the_spec_sentence_through_the_api` | `uat-evidence.md` (entry journey) | verified: the journey runs end to end in the browser (browser-memory simulation) and the export is real in the API (C09) |
| P05-GOAL-10 (exceptions, robustness, versioning, recovery) | `api/`, `domain/` | `tests/test_adversarial.py`, `tests/test_api_commands.py`, `tests/test_review_findings.py` | `uat-evidence.md` (R5-01..R5-22) | verified (local); **versioning (C06) is 501** |
| P05-GOAL-12 (no live data, payment, operational write in the demo) | `web/` (in-memory adapter) | `web/e2e/journey.spec.ts` (honesty labels) | the landing and case study state it | verified |
| P05-DOMAIN-01 no payments | no `paid` status, no payment column | `test_a_paid_flag_attempt_is_refused_and_no_command_can_mark_an_invoice_paid` | `sql-analysis.md` 08 (INJ-12 replay-only) | verified (local) |
| P05-DOMAIN-03 decimal never float | `domain/invoicebridge/money.py` | `test_domain_source_has_no_float`, `test_floats_and_excess_precision_are_refused_not_rounded`, `test_money_and_quantities_are_exact_numeric_never_float` | local | verified (local) |
| P05-DOMAIN-04 matching does not confer approval | `book.py` | `test_matching_never_approves`, `test_a_matched_invoice_is_not_approved_until_someone_else_decides` | 114 matched invoices unapproved at the as-of | verified (local) |
| P05-DOMAIN-05 creator/reviewer distinction | `api/commands.py` C07, C08 | `test_self_approval_is_refused_403_and_the_refusal_is_audited`, `test_the_creator_cannot_reject_their_own_invoice_and_the_refusal_is_audited` | `sql-analysis.md` 04 (0 self-approvals in the snapshot) | verified (local) |
| P05-DOMAIN-06 source hash and correction lineage | `0001`, `0002` (`invoices_source_fixed`, `import_lineage`) | `test_import_creates_one_received_invoice_with_computed_amounts_lineage_and_audit`, `test_the_database_refuses` | `data-dictionary.md` | verified (local); corrections: C06 501 |
| P05-GOLD-01..07 (known answer, hash, tolerance) | `tests/fixtures/golden/`, `tests/reference_check.py` | `tests/reference_check.py` (ALL OK, 412 checks), `tests/test_golden_domain.py` (10), `tests/test_sql_reference.py` | `sql-analysis.md` 09 and section 10: the 11 metric keys equal in three sources | verified (local); ledger entry `dc96dbe` |
| P05-GOLD-08, 09 (rejected and empty variants) | `tests/fixtures/golden/variant-rejected`, `variant-empty` | `tests/test_variants.py` (6) | local | verified (local) |
| P05-DATA-01..12 (entities and field contracts) | `data/migrations/0001_schema.sql`, `0002_constraints.sql`, `0003_review_status.sql`, `domain/invoicebridge/models.py` | `tests/test_migrations.py` (10) | `data-dictionary.md`, `erd.md` | verified (local) |
| P05-MET-01, 02 (invoice subtotal, total) | `domain/invoicebridge/amounts.py`, `reference_metrics.sql` | `test_tax_is_computed_once_per_invoice_on_the_unrounded_subtotal`, `test_total_follows_the_declared_order_subtotal_tax_freight_discount` | matched by currency USD 1,608,460.47, EUR 531,691.91, GBP 347,369.86 in three sources | verified (local) |
| P05-MET-03 (uninvoiced received quantity) | `match.py` `quantities` | `test_quantity_is_consumed_cumulatively_and_a_blocked_invoice_consumes_nothing` | received not invoiced 15,318.7500 units at the as-of (query 02); three cutoffs reconciled | verified (local) |
| P05-MET-04, 05 (price and quantity variance) | `match.py` | `test_price_variance_within_and_beyond_tolerance`, `test_partial_receipts_and_cumulative_consumption_block_the_second_invoice` | query 01: 193 quantity-blocked and 32 price-variance open | verified (local) |
| P05-MET-06, 07 (straight-through and exception rate) | `metrics.py` | `test_rates_have_distinct_validated_invoices_as_denominator`, `test_straight_through_rate_keeps_its_published_meaning_not_blocked_at_the_cutoff` | 0.912287 / 0.087713 and never-excepted 0.772401 in three sources | verified (local) |
| P05-MET-08 (processing time) | `metrics.py` | `test_processing_time_is_exact_minutes_and_rounds_half_up_at_the_end`, `test_processing_minutes_are_never_negative_whatever_the_decision_instants` | 5,466.7066 minutes, 346 pending (query 04, 06) | verified (local) |
| P05-MET-09 (potential duplicate count) | `duplicates.py` | `test_same_source_bytes_are_one_obligation_under_another_filename`, `test_a_window_before_the_resent_pdf_does_not_count_the_merge` | 98 merged: 95 identity, 3 bytes (query 03) | verified (local) |
| P05-MET-10 (approved payable) | `book.py` | `test_a_credit_adjusts_the_payable_once_per_credit_id_and_moves_no_cash` | USD 1,416,036.99, EUR 450,586.03, GBP 281,108.17 (query 07) | verified (local) |
| P05-MET-11 (export reconciliation) | `book.py`, `metrics.py` | `test_only_approved_invoices_export_and_the_others_are_listed_as_exclusions`, `test_the_export_is_reconciled_against_the_stored_rows_too` | 0.00 per currency **by construction**; 346 exclusions explained (query 06) | verified (local) |
| P05-MET-12 (review backlog) | `book.py` exceptions, `exception_assignments` | `test_exception_records_get_stable_ids_and_the_owner_as_of_the_cutoff` | open at the three cutoffs: 129 / 201 / 232 derived from facts and 128 / 201 / 232 in the stored nightly history, 29 unowned at the as-of (query 05) | verified (local) |
| P05-FLOW-01 (C01 import) | `api/commands.py`, `domain/invoicebridge/ingest.py` | `test_import_creates_one_received_invoice_with_computed_amounts_lineage_and_audit`, `test_the_same_key_and_payload_replays_the_stored_response`, `test_same_bytes_under_another_invoice_id_is_one_obligation` | `uat-evidence.md` | verified (local) |
| P05-FLOW-02 (C02 validate) | `api/commands.py` | `test_validate_moves_received_to_valid_and_only_from_received`, `test_an_inactive_vendor_is_invalid` | local | verified (local) |
| P05-FLOW-03 (C03 find duplicates) | `api/commands.py`, `duplicates.py` | `test_find_duplicates_explains_the_matching_fields_and_merges_into_the_earliest`, `test_same_bytes_with_other_extracted_fields_are_held_for_review` | local | verified (local); the held invoice has no resolving command |
| P05-FLOW-04 (C04 match) | `api/commands.py`, `match.py` | `test_match_persists_line_results_exceptions_and_the_rule_version`, `test_a_late_receipt_resolves_the_exception_on_the_next_match` | local | verified (local) |
| P05-FLOW-05 (C05 assign) | `api/commands.py` | `test_assigning_keeps_the_history_and_a_resolved_exception_cannot_be_assigned` | local | verified (local) |
| **P05-FLOW-06 (C06 correct extraction)** | `api/app.py` routes it | `test_c06_correct_extraction_is_routed_and_answers_501` | the route answers 501 `NOT_IMPLEMENTED` | **501** (deferred) |
| P05-FLOW-07 (C07 approve) | `api/commands.py` | `test_approval_records_the_actor_role_and_policy_version_and_moves_the_state`, `test_the_policy_in_force_at_decision_time_decides_role_and_limit` | local | verified (local) |
| P05-FLOW-08 (C08 reject) | `api/commands.py` | `test_rejection_needs_a_reason_and_releases_the_received_quantity`, `test_an_approved_invoice_cannot_be_rejected` | 57 valid rejections (query 08) | verified (local) |
| P05-FLOW-09 (C09 export) | `api/commands.py` | `test_export_writes_a_batch_with_a_content_hash_and_moves_approved_to_exported`, `test_a_batch_id_names_one_set_of_invoices_and_an_invoice_exports_once` | 52 batches, 7 retries (query 06) | verified (local) |
| P05-FLOW-10 (C10 credit) | `api/commands.py` | `test_a_credit_adjusts_the_approved_payable_once_and_moves_no_cash`, `test_credits_accumulate_up_to_the_invoice_total` | 117 notes on 112 invoices (query 07) | verified (local) |
| P05-UI-01 Intake desk | `web/src/views/intake.tsx` | `journey.spec.ts` (intake: the import replays in order, duplicates merged) | `intake-*.png` | verified (hosted on `be20031`, local on `2dcc460`); browser-memory simulation, acts on nothing |
| P05-UI-02 Invoice detail | `web/src/views/invoices.tsx`, `desk.tsx` | `journey.spec.ts` (the golden pair; the snapshot desk) | `invoices-*.png`, `invoices-golden-*.png` | verified |
| P05-UI-03 Matching panel | `web/src/views/matching.tsx` | `journey.spec.ts` (matching: filters, ven-02x and ven-007) | `matching-*.png` | verified |
| P05-UI-04 Duplicate review | `web/src/views/duplicates.tsx` | `journey.spec.ts` (read-only views) | `duplicates-*.png` | verified (read-only) |
| P05-UI-05 Exception queue | `web/src/views/exceptions.tsx` | `journey.spec.ts` (the open queue by reason and owner) | `exceptions-*.png` | verified (read-only: assignment does not act) |
| P05-UI-06 Approval desk | `web/src/views/approvals.tsx` | `journey.spec.ts` (read-only views) | `approvals-*.png` | verified (read-only: nothing is approved from the site) |
| P05-UI-07 Vendor view, P05-UI-08 Export review, P05-UI-09 Audit timeline | `vendors.tsx`, `exports.tsx`, `audit.tsx` | `journey.spec.ts` | `vendors-*.png`, `exports-*.png`, `audit-*.png` | verified (read-only; the audit timeline is derived from facts, no stored event log) |
| P05-UI-10 Case study | `web/src/views/case-study.tsx` | `journey.spec.ts` (what is built, what is not, C06) | `case-study-*.png` | verified |
| P05-TEST-01 same bytes under two names | `ingest.py`, `duplicates.py` | `test_same_bytes_under_two_filenames_leave_one_obligation`, `test_the_same_invoice_bytes_imported_concurrently_under_different_keys_make_one_invoice` | `sql-analysis.md` 08 (INJ-01: 3 groups, all merged) | verified (local) |
| P05-TEST-02 number reused by another vendor | `duplicates.py` | `test_a_reused_invoice_number_across_vendors_is_not_a_duplicate` | query 03, 08 (INJ-02: 4 pairs, none merged) | verified (local) |
| P05-TEST-03 partial receipts | `match.py` | `test_partial_receipts_and_cumulative_consumption_block_the_second_invoice` | query 08 (INJ-03: 5 injected inside 30 candidates) | verified (local) |
| P05-TEST-04 previous invoices consume the receipt | `match.py` | `test_quantity_is_consumed_cumulatively_and_a_blocked_invoice_consumes_nothing` | query 02, 08 (INJ-04: 3 injected inside 19 candidates) | verified (local) |
| P05-TEST-05 rounding over tolerance | `amounts.py`, `match.py` | `test_a_rounding_gap_over_tolerance_is_a_rounding_exception_and_within_tolerance_is_disclosed` | query 08 (INJ-05: 4) | verified (local) |
| P05-TEST-06 creator approves own invoice | `api/commands.py` | `test_self_approval_is_refused_and_leaves_the_invoice_matched` | query 04 (0 in the snapshot); INJ-06 is replay-only | verified (local) |
| P05-TEST-07 two approvals race | row locks, optimistic `version` | `test_two_concurrent_approvals_leave_exactly_one_approval`, `test_many_concurrent_approvals_from_many_threads_still_leave_one` | INJ-07 replay-only (query 08: 0 rows) | verified (local) |
| P05-TEST-08 credit applied twice | `credit_notes` key | `test_a_credit_note_applies_once_even_when_sent_again_under_new_keys`, `test_concurrent_credit_notes_for_one_credit_id_apply_once` | INJ-08 replay-only | verified (local) |
| P05-TEST-09 currency without a rate | `match.py` | `test_a_foreign_currency_invoice_without_a_rate_is_a_currency_mismatch` | query 08 (INJ-09: 3; 3 open `CURRENCY_MISMATCH`) | verified (local) |
| P05-TEST-10 correction erases the original | trigger `invoices_source_fixed` | `test_a_correction_never_overwrites_the_original_extraction`, `test_the_database_refuses` | INJ-10 replay-only | verified (local); versioned corrections: C06 501 |
| P05-TEST-11 export repeated after a timeout | `export_requests` | `test_export_batch_idempotency_under_concurrency_same_key`, `test_the_repeated_export_returns_the_prior_batch_and_is_counted` | query 06 (INJ-11: 7 repeats) | verified (local) |
| P05-TEST-12 matched marked paid | no `paid` column, `FIELD_UNEXPECTED` | `test_a_paid_flag_attempt_is_refused_and_no_command_can_mark_an_invoice_paid` | INJ-12 replay-only | verified (local) |
| P05-ART-01..10 | this directory | `tests/test_artifacts.py` | `artifacts/CHECKSUMS.txt` | verified (local); the hosted run of `test_artifacts.py` is not part of `invoicebridge-ci.yml` |
| P05-REL-01..04, 09, 17, 18 (site, routes, live check, links both ways) | `web/`, `docs/program/release-manifest.json` | live-check workflow | run `40406631388` (`be20031`, portfolio `3cff603`) | verified (hosted); the republish `188e409`: CI and live check pending |
| P05-REL-14..24 (portfolio entry, rollback) | `/invoicebridge/project.json` on `unified-portfolio` | the portfolio build | `release-package.md` | built and published; integration and rollback documented |

## 5. Deferred and open (stated, not hidden)
* **C06 `correct-extraction` returns 501.** There is no versioned correction row and no extraction-correction screen; P05-TEST-10 is held by the immutability trigger and the 409 `DUPLICATE_ID` refusal, not by a working correction. A `needs_review` invoice (a byte-twin with other extracted fields) has **no command that resolves it**: a person acts outside the API.
* **The intake, exceptions, approvals and exports screens of the public site act on nothing** (browser memory only, a refresh restores the snapshot) and say so; the transactional behaviour is verified on hosted runners against a transient PostgreSQL, not served by GitHub Pages.
* **No receipt command.** Receipts are reference data; a reversal is the one UPDATE the schema allows and the derived view warns (`WORKFLOW_STATE_DIFFERS`) when the stored workflow has fallen behind.
* **Policy limits have no currency** (compared with the invoice total in its own currency, no conversion).
* **Five of the twelve injected defects are replay-only** (INJ-06, 07, 08, 10, 12): they are attempts through the API that the commands refuse and that leave no row in a snapshot, so the SQL signatures find 0 by design; the evidence is the adversarial tests and the replay events.
* **The generator's choices are outcome-selected**: it approves only uninterrupted matches, rejects only never-matched invoices and closes each period with a batch of everything approved, so the approval mix, the rejection mix and the zero export difference are not findings (D-07, D-09.17, R5-22).
* **Hosted evidence for `2dcc460`:** the local suite, the SQL reconciliation and the artifact checks are recorded; the hosted CI and live-check runs for the republished release are pending. The hosted artifact tests are not part of `invoicebridge-ci.yml`.
* **Not run:** Microsoft Excel (the workbook was recalculated by LibreOffice), Power BI Desktop (no `.pbix`), any DAX engine, and `npm run e2e`, `npm run check` and the hosted workflows by this artifact pass (their results are the earlier recorded runs).
