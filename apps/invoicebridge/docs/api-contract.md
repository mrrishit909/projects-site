# InvoiceBridge — API route inventory (backend contract, Mode A only)

Same envelopes, identity headers (roles clerk|reviewer|admin) and status codes as the other
apps; lock order and 409 on deadlock; actor-bound idempotency. Prefix `/api/v1/invoicebridge`.

| ID | Method and path | Transition | Hard validation | Milestone |
|---|---|---|---|---|
| C01 | POST …/commands/import-invoice | absent → received | idempotency key + source hash; same bytes = one obligation | slice |
| C02 | POST …/commands/validate-invoice | received → valid/invalid | decimal totals, required fields | slice |
| C03 | POST …/commands/find-duplicates | valid → candidate review | explained matching fields | slice |
| C04 | POST …/commands/match-three-way | valid → matched/exception | PO, receipts, cumulative invoices | slice |
| C05 | POST …/commands/assign-exception | unowned → assigned | assignment history kept | slice |
| C06 | POST …/commands/correct-extraction | original → versioned correction | never overwrites source | extension |
| C07 | POST …/commands/approve-invoice | matched/resolved → approved | separation of duties; policy version | slice |
| C08 | POST …/commands/reject-invoice | reviewable → rejected | reason required | slice |
| C09 | POST …/commands/export-payable | approved → exported | idempotent batch | slice |
| C10 | POST …/commands/apply-credit-note | approved → adjusted | once per credit; no cash | slice |
| R | GET …/data/{entity} | reads | stable ordering | slice |
| M | GET …/metrics?from=&to=&cutoff=&group_by= | straight-through, exception rate, processing time, duplicates, payable, export reconciliation, backlog | half-open window | slice |

## D-09 changes (review A-038)
* C07 and C08 take no `decided_at`: the server stamps the decision (a payload carrying it is 422 `FIELD_UNEXPECTED`). C01 clamps an `imported_at`
  later than the server clock (warning `IMPORTED_AT_CLAMPED`); C09 refuses an `exported_at` earlier than an approval (422 `EXPORTED_BEFORE_APPROVAL`).
* C01 answers a byte-twin with other extracted fields with 200 status `needs_review` (reason and warning `BYTES_FIELDS_CONFLICT`); no command advances it.
* C07, C09 and C10 re-derive the match: 409 `STALE_MATCH` (rule `NOT_MATCHED`) when a receipt was reversed; 409 `DUPLICATE_PENDING` for a copy the
  derivation has merged into a committed invoice. C08 by the invoice's creator is 403 `SELF_DECISION`.
* Idempotency is bound to actor id, role and payload; a role change under the same key is 409 `IDEMPOTENCY_KEY_REUSED`.
* `GET /metrics` adds `data.export_reconciliation` (derived rows against the stored `export_rows`) and the warning `EXPORT_ROWS_DIFFER`.

