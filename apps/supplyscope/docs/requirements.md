# SupplyScope — requirements and traceability (P03-ART-02)

Status values: verified | failed | blocked | not_checked; the machine-readable record is
`docs/program/verification-ledger.json`.

## User stories
1. As a planner I open an SKU and see on hand, on order, backorders and position as of the
   cutoff, with the ledger rows that produce them. *Accept:* golden 40 / 30 / 10 / 60.
2. As a planner I see the draft order with its arithmetic: raw 60 → MOQ 60 → pack 72.
   *Accept:* equals the reference check; position 80 → 0.
3. As a buyer I cannot record a receipt before the order date or before the lead time has
   elapsed on the supplier calendar. *Accept:* 422 `RECEIPT_BEFORE_ORDER` / `RECEIPT_BEFORE_LEAD_TIME`.
4. As a data scientist I see WAPE of the model beside seasonal-naive on the same folds, null
   for intermittent SKUs with zero actual demand. *Accept:* fold-level table matches the domain.
5. As a planner I export the buying plan and the file carries the as-of instant, scenario,
   dataset hash and contract version. *Accept:* header fields present; never a real PO.

## Traceability
| Requirement | Code | Test | Evidence | Status |
|---|---|---|---|---|
| P03-GOLD-01..10 | tests/fixtures/golden/* | tests/reference_check.py | CI Mode A | verified (local) |
| P03-MET-01..12 | domain/supplyscope/*.py, data/sql/reference_metrics.sql | tests/test_golden_domain.py, test_sql_reference.py | CI Mode A | not_checked |
| P03-FLOW-01,02,03,05,06,07,10 | api/commands.py | tests/test_api_commands.py | CI Mode A | not_checked |
| P03-FLOW-04,08,09 | api/commands.py | — | — | extension |
| P03-TEST-01..12 | tests/test_adversarial.py, test_rules.py | same | CI Mode A | not_checked |
| P03-UI-01/02/05/06/10 | web/src/views/* | web/e2e/* | CI Mode B | not_checked |
| P03-REL-* | .github/workflows/supplyscope-ci.yml, live-check.yml | release-manifest.json | Actions | not_checked |
