# InvoiceBridge: UAT evidence for the independent review A-038 (fix worker A-040, task T-05-07)

Every finding of the review (R5-01 .. R5-22) with the value before and after, the decision that fixes it (docs/contracts.md D-09) and the
regression test that holds it. "Before" is the code at the review (`git HEAD` of `apps/invoicebridge`), "after" is this branch. The cases
live in `tests/review_cases.json` (written by `tests/make_review_cases.py`, expectations derived by hand and written out in that script);
the same file is read by `tests/test_review_findings.py` (Python), `tests/test_sql_reference.py` (PostgreSQL) and `web/scripts/review-check.ts`
(TypeScript), so the three implementations are held to one set of values. Golden values, `tests/fixtures/*` and `tests/reference_check.py` are
unchanged.

## Commands (from `apps/invoicebridge`)

| Command | Result |
|---|---|
| `../../.venv/bin/python tests/reference_check.py` | ALL OK (412 checks), exit 0 |
| `DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/invoicebridge ../../.venv/bin/python -m pytest -q` | see "Final verification" below |
| `../../.venv/bin/python tests/make_review_cases.py` | writes `tests/review_cases.json` (18 cases) |
| `../../.venv/bin/python data/generate.py` | entity files byte-identical; only `manifest.json` (string parameters, `generated_at`) and `data/injection-events.json` (events 06 and 07 carry no `exported_at`) change |
| `../../.venv/bin/python web/scripts/make-snapshot-reference.py` | refreshes `web/scripts/snapshot-reference.json` |
| `cd web && npm run check` | typecheck, golden (227 checks) and review (41 checks) |
| `cd web && npm run build:pages`, `npm run e2e` | see "Final verification" below |
| the reviewer's harness, `review05/harness.py cases/<case>.json` | every case: Python, SQL and TypeScript agree (table below) |
| `review05/fuzz.py 1000 1060` | `seeds with disagreement: []` |

## The findings

| ID | Defect and reproduction | Before | After | Decision (D-09) and test |
|---|---|---|---|---|
| R5-01 | A back-dated invoice displaces a committed one (`c05_backdated`: inv-late approved 10-06T15:00 and exported 10-07T08:00; inv-back, invoice date 10-05, imported 10-08) | inv-late `exception` (QUANTITY_BLOCKED), inv-back `matched`, obligations 0, the approval invalid NOT_MATCHED, export row dropped | inv-late `exported`, inv-back `exception` (QUANTITY_BLOCKED, variance 6), obligations 1 = 132.00, `invoiced_not_received` 6.0000 | 1, 2: committed invoices consume first by commit instant. `back_dated_after_export`; API `test_a_back_dated_invoice_cannot_take_the_quantity_of_an_exported_one`; reviewer B1: match back 200 `matched` -> `exception`, approve back 200 -> 409, export back 200 -> 409, 1 export row |
| R5-02 | A canonical copy that is approved or exported is displaced by a later import (`api_attacks4`: b imported with an earlier `imported_at`) | inv-a derived `merged`; inv-b matched, approved and exported (2 export rows for one obligation); C03 409 | inv-b merges into inv-a (`committed_canonical_is_not_displaced`: a `approved`, b `merged`); C03 200 merged, C04 409, C07 409, C09 409, one export row, no `WORKFLOW_STATE_DIFFERS` | 3: committed copy first in the group. `committed_canonical_is_not_displaced`, `test_two_committed_copies_...`, API `test_an_earlier_stamped_copy_cannot_displace_...`, `test_an_invalid_earlier_stamped_copy_...`, `test_a_derived_duplicate_cannot_advance_...` |
| R5-03 | A receipt reversed after export un-exports (`c04_reversed_after_export`, `api_attacks2` B2) | `exception`, obligations 0, no export row derived (stored row 132.00 outside the metrics), C09 and C10 on a reversed invoice 200 | `exported` + QUANTITY_BLOCKED exception on it, obligations 1 = 132.00, difference 0.00; approved-only: still NOT_MATCHED and obligation 0; C09 and C10: 409 `STALE_MATCH` | 5: the export row is a committed fact, the reversal an exception on the exported invoice. `receipt_reversed_after_export`, `receipt_reversed_after_approval_only`, API `test_a_reversed_receipt_refuses_export_and_credit_...`, `test_an_exported_invoice_stays_exported_...` |
| R5-04 | `decided_at` chosen by the client (`c07` inv-early; B3) | approval before the import valid: `mean_minutes` -7740.0000 (domain), -50940.0000 (API, a back-dated `decided_at` picked the looser policy v1) | `BEFORE_IMPORT`, invalid, no negative minutes; the API has no `decided_at` (422 `FIELD_UNEXPECTED`) and stamps the server clock | 7. `approval_before_import`, `test_processing_minutes_are_never_negative_...`, API `test_a_decision_instant_chosen_by_the_client_is_refused`, `test_the_server_stamps_the_decision_...` |
| R5-05 | Duplicates merge into an invalid canonical (`c02b`) | inv-q merged into inv-p (invalid): nobody in the book, eligible 0 | inv-q `matched`, eligible 1, no merge | 3. `merge_into_invalid_canonical`, `test_an_invalid_invoice_never_anchors_a_group_...` |
| R5-06 | Vendor mismatch (`c06` inv-5: ven-1 bills ven-2's PO line) | `matched`, consumed 10 | `exception` NO_PO_LINE, consumed 0 | 8: NO_PO_LINE (no sixth reason, the golden `by_reason` keys and the DB checks are unchanged). `vendor_mismatch` |
| R5-07 | Duplicates ignore the cutoff and the window (`c09`, `window.py`) | as of 2026-10-07T00:00Z: inv-003 `merged`, `rows_merged` 1 although it was imported at 10-07T09:00 | inv-003 `received`, `rows_merged` 0; a window before the re-send counts no merge | 3. `duplicates_respect_the_cutoff`, `test_a_window_before_the_resent_pdf_does_not_count_the_merge` |
| R5-08 | An invalid self-approval blocks a valid rejection (`c07` inv-ir) | inv-ir `matched` (the rejection listed REJECT_AFTER_APPROVAL), 2 eligible | inv-ir `rejected`, 1 eligible; a valid earlier approval still blocks (inv-rar) | 9: only an earlier VALID approval blocks. `rejection_after_invalid_approval` (SQL CTE changed too) |
| R5-09 | Exports are not checked against approvals; the batch content moves (`c08` inv-4 approved 10-08, exported 10-07) | inv-4 `exported` at 154.00, difference -22.00 | row invalid and listed (`EXPORT_BEFORE_APPROVAL`), accepted 132.00, difference -44.00 = inv-2 and inv-4, each an exclusion | 6. `export_needs_a_prior_approval`, `test_a_book_never_changes_under_a_later_fact_...`, API `test_an_export_cannot_be_stamped_before_the_approval` |
| R5-10 | "Straight-through" says "never had an exception" but computes "not blocked at the cutoff" | golden 0.500000; snapshot 0.912287 against 0.772401 never-excepted (602 of 2,645 ever excepted) | the published rate keeps its meaning (golden unchanged); the site says "not blocked at the cutoff"; `straight_through_never_excepted_rate` and `ever_excepted_rate` are added where a stored history adds invoices (snapshot: 0.772401 / 0.227599) | 10. **Not substituted** (the history is stored, not a fact at a cutoff; the golden value is unchanged either way). Rejected invoices stay outside the denominator (57 on the snapshot). `exception_history_rates`, `golden_rates_have_no_history_pair`, `test_rejected_invoices_are_outside_the_denominator` |
| R5-11 | Money summed across currencies (snapshot: USD, EUR, GBP) | one total each for matched, obligations, payable, export | `by_currency` where the figures span currencies (snapshot obligations: USD 1,448,006.25, EUR 457,320.65, GBP 286,543.12); sums labelled "sum across currencies, not converted"; the landing page shows per-currency figures; the golden fixture has no `by_currency` | 11. `byte_twin_with_other_fields_and_two_currencies`, `test_a_single_currency_book_carries_no_by_currency_keys`, SQL `test_sql_by_currency_...` |
| R5-12 | "Credit share 4.0 %" read as a share of approvals | 4.0 % without a denominator | 112 invoices = 4.0 % of 2,800 invoices = 4.9 % of 2,299 approved, stated in `data/README-generator.md` and D-09.17 | 17 |
| R5-13 | The export difference is not explained (`c07` -242.00, `c08` -22.00) | unexplained non-zero differences | every approved invoice not exported is an exclusion (APPROVED_NOT_EXPORTED, EXPORT_BEFORE_APPROVAL); `GET /metrics` reconciles the derived rows with the stored `export_rows` (`export_reconciliation`, warning `EXPORT_ROWS_DIFFER`) | 6. `export_needs_a_prior_approval`, `duplicates_respect_the_cutoff`, API `test_the_export_is_reconciled_against_the_stored_rows_too` |
| R5-14 | PRICE_VARIANCE 93.8 % cited against a different denominator | 30 of 32 (open) quoted as if it were the history | open at the as-of 30 of 32 (93.8 %), ever raised 53 of 57 (93.0 %), both on the matching page (from the stored history) and in the README | 17 |
| R5-15 | Quantity blocks 30.3 % vs 97.4 % | 30.3 % quoted as the share of ven-02x invoices blocked | open 163 of 538 (30.3 %), ever 524 of 538 (97.4 %); elsewhere 30 of 2,107 (1.4 %) open, 39 (1.9 %) ever | 17 |
| R5-16 | TypeScript orders ids by UTF-16 unit (`c10_astral_ids`) | TS and Python/SQL disagreed on which of `inv-￿` and `inv-U+1F600` matches first | one code-point comparator (`src/domain/order.ts`) used by every ordering of the domain; the three agree | 14. `ids_outside_the_bmp` (Python, SQL, TypeScript), `review-check.ts` comparator checks |
| R5-17 | Python accepts `1_0`, `1E+1`, Arabic-indic digits (`c11a/b/c`) | Python matched with 10 units, TypeScript rejected the line | one ASCII-only spelling in `money.dec`, the pydantic schemas (`[0-9]`), `timeutil` and the TS parser; all three reject | 14. `decimal_spelling_*`, `test_only_ascii_decimal_spellings_parse`, API `test_non_ascii_digits_...`, `review-check.ts` |
| R5-18 | A batch naming two groups is counted in each | 2 requests, 1 batch in EVERY group (ven-1 and ven-2: 4 requests in total) | counted once, in the group of its first invoice in the window (2 in total) | 12. `test_a_batch_naming_two_vendors_is_counted_once_across_the_groups` |
| R5-19 | Rejection ignores separation of duties; the idempotency key ignores the role | B5: the creator rejects own invoice 200; same key under another role replays | 403 `SELF_DECISION` (refusal audited) and domain `SELF_DECISION`; another role under the key: 409 `IDEMPOTENCY_KEY_REUSED` | 9, 13. `creator_cannot_reject`, API `test_the_creator_cannot_reject_...`, `test_the_idempotency_key_is_bound_to_the_role_...` |
| R5-20 | A byte-twin with other extracted fields merges and seeds the identity map (`c02` inv-c) | inv-c and, through its identity, inv-d merged into inv-a (3 merges, 2 eligible) | inv-c `needs_review` (`BYTES_FIELDS_CONFLICT`, `unresolved_groups` 1), inv-d its own invoice (1 merge, 3 eligible); API 200 `needs_review` | 4 and migration 0003. `byte_twin_with_other_fields_and_two_currencies`, API `test_same_bytes_with_other_extracted_fields_are_held_for_review` |
| R5-21 | Floats in `manifest.json` parameters; TS disclosures omit tolerated line roundings | `credit_share: 0.04`, `p_short_02x_line: 0.4`, ... ; no `rounding_tolerated_lines` in TS | decimal strings (`"0.040"`, `"0.40"`, `"0.74"`, `"0.075"`, `"0.0202"`); TS lists the lines | 15. `test_the_published_manifest_carries_no_float`, `review-check.ts` |
| R5-22 | "Reconciliation 0.00" and the approval and rejection mix presented as findings | no caveat | stated beside the figures (exports page, metric sheet, case study, `data/README-generator.md`): reconciliation 0.00 by construction of the generator's close batch; approvals and rejections are outcome-selected | 17 |
| (dataset version) | `injection-events.json` carries `ib-20261026-20261026`, the seed wrote `ds-<hash>` | the replay test overwrote the version | `seed(..., dataset_version=)` / `--dataset-version`; EV-01..07 replay as published (events 06 and 07 no longer carry `exported_at`) | 15. `test_generator.py::test_replay_events_behave_as_recorded` |

## Agreement of Python, SQL and TypeScript, per case

`review05/harness.py cases/<case>.json -q` after the fix (DISAGREEMENTS 0 for every case; "hand" = the expectation in `tests/review_cases.json`,
which the three implementations also meet in their own suites):

| Case | Py / SQL / TS agree | Agrees with the hand values |
|---|---|---|
| c01_rounding, c03_cumulative, c06_match_edges, c07b_policy_change | yes | no review expectation (unchanged behaviour; c06 inv-5 is `vendor_mismatch`) |
| c02_duplicates | yes | yes (`byte_twin_with_other_fields_and_two_currencies`) |
| c02b_merge_into_invalid | yes | yes (`merge_into_invalid_canonical`) |
| c04_reversed_after_export | yes | yes (`receipt_reversed_after_export`) |
| c05_backdated | yes | yes (`back_dated_after_export`) |
| c06_match_edges (inv-5) | yes | yes (`vendor_mismatch`) |
| c07_approvals | yes | yes (`approval_before_import`, `rejection_after_invalid_approval`) |
| c08_credit_export | yes | yes (`export_needs_a_prior_approval`) |
| c09_golden_early_asof | yes | yes (`duplicates_respect_the_cutoff`) |
| c10_astral_ids | yes | yes (`ids_outside_the_bmp`) |
| c11a_underscore, c11b_exponent, c11c_arabic_digits | yes | yes (`decimal_spelling_*`) |

## Reviewer API attacks, re-run (`api_attacks*.py`, decisions stamped by the server clock)

| Attack | Before | After |
|---|---|---|
| B1 match / approve / export of the back-dated inv-back | 200 / 200 / 200, two export rows | 200 `exception` / 409 / 409, one export row |
| B2 export and credit after a reversal of an approved invoice | 200 / 200 | 409 `STALE_MATCH` / 409 `STALE_MATCH` |
| B2 reversal after export | `exception`, obligation lost, stored row not in the metrics | stays `exported`, QUANTITY_BLOCKED exception on it, difference 0.00, reconciliation 132.00 = 132.00 |
| B3 `decided_at` in the payload | accepted (policy v1 chosen, minutes -50940) | 422 `FIELD_UNEXPECTED` |
| B5 creator rejects own invoice | 200 `rejected` | 403 `SELF_DECISION` |
| duplicate displacement (b stamped earlier than the exported a) | C03 409, C04/C07/C09 200 | C03 200 (b merged into a), C04/C07/C09 409 |
| invalid variant (b fails C02) | a derived `merged` into an invalid canonical | a stays `exported`, b `invalid`, all commands 409, `rows_merged` 0 |
| same bytes, other number | merged | 200 `needs_review`, `BYTES_FIELDS_CONFLICT` |
| arabic digits in a quantity | 200, stored as 10.0000 | 422 `FIELD_INVALID`, nothing stored |

## What did not change, and what moved on the snapshot

* `tests/fixtures/golden/*`, `tests/reference_check.py`, the eleven metric keys and all golden values: unchanged (golden check ALL OK, 227 checks; reference check ALL OK, 412 checks).
* The generator's entity files (`web/public/data/*.json` except `manifest.json`, `golden/*`) are byte-identical; the manifest's `designed_relationships` are unchanged.
* On the snapshot: matched, obligations, exceptions, approvals, export and credits are unchanged; `quantities.invoiced_not_received_quantity` 9,085.7500 -> 9,256.7500 and
  `..._value` 116,771.18 -> 118,382.45 (and the snapshot cutoffs: 6,256.0000 -> 6,344.0000 and 10,214.0000 -> 10,304.0000 on the two month-ends), because blocked
  lines now see the consumption of the committed invoices; `by_currency` and the history rates are added. `web/scripts/snapshot-reference.json` was regenerated by the Python domain.

## Not fixed, and why

* A `needs_review` invoice has no command that resolves it (C06 is 501 in this milestone); a person acts outside the API.
* "Never had an exception" as a published rate: left as a history pair, not the straight-through rate (D-09.10).
* The SQL reference still takes about 80 s per query on the 2,800-invoice snapshot (one duplicate chain per cutoff was added); no performance change was attempted.
* The stored canonical of concurrent same-bytes imports can still differ from the derived one (D-06, warned); the derivation, not the stored state, decides the metrics.

## Final verification (A-042, run from `apps/invoicebridge` on the final tree)

| Command | Result |
|---|---|
| `../../.venv/bin/python -I tests/reference_check.py` | ALL OK (412 checks), exit 0 |
| `DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/invoicebridge ../../.venv/bin/python -m pytest -q` | 402 passed, exit 0 (7 min; an earlier run that overlapped other database work on the same server failed in `test_adversarial.py`, the same tests pass alone and in the clean full run) |
| `../../.venv/bin/python data/generate.py` | exit 0; every entity file byte-identical (sha256 compared), only `manifest.json` changes (string parameters, `generated_at`) |
| `../../.venv/bin/python web/scripts/make-snapshot-reference.py` | exit 0; `snapshot-reference.json` unchanged |
| `review05/harness.py cases/<each of 15 cases> -q` | `DISAGREEMENTS: 0` for all 15 |
| `review05/api_attacks.py`, `api_attacks2.py`, `api_attacks3.py`, `api_attacks4.py` (a copy that releases the pinned server clock between scenarios) | statuses as in the attack table above |
| `review05/fuzz.py 1000 1060` | `seeds with disagreement: []`, exit 0 |
| `cd web && npm run check` | exit 0: typecheck, golden ALL OK (227 checks), review ALL OK (41 checks) |
| `cd web && npm run build:pages` | exit 0 (11 route copies) |
| `cd web && npm run e2e` | 71 passed, exit 0 |
