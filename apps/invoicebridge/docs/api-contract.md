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
