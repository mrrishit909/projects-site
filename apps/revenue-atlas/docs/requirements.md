# Revenue Atlas — requirements and traceability (P01-ART-02)

Functional requirements are the spec's addressable IDs (`P01-*`). This file keeps the
project-level stories and the requirement → code → test → evidence table. Status values:
verified | failed | blocked | not_checked (master 18). The verification ledger
(`docs/program/verification-ledger.json`) is the machine-readable record; this table is
the readable one and is updated with it.

## User stories (observable acceptance)
1. As an analyst I open the overview and see monthly net sales and contribution with the
   date basis (shipped_at, UTC, half-open) printed next to the chart. *Accept:* the two
   series equal `compute_metrics` grouped by month on the published snapshot.
2. As a controller I open the margin bridge and every step from gross sales to contribution
   is a contract metric and the steps sum to the total. *Accept:* bridge total equals the
   golden contribution on the golden fixture (70.00; 40.00 after the return).
3. As an analyst I drill from the bridge to a region and then to the transaction ledger and
   the ledger's totals equal the bridge step I came from. *Accept:* reconciliation within
   0.00 after rounding.
4. As a returns lead I post a partial return that exceeds the remaining quantity and it is
   rejected with the rule ID. *Accept:* 422 `RETURN_EXCEEDS_REMAINING` on the backend;
   the same message in the browser simulation.
5. As a reviewer I export the current view and the file carries the filters, contract
   version, dataset hash and generated time. *Accept:* header fields present and equal to
   the on-screen values.

## Nonfunctional
Static site first contentful paint under 2 s on a throttled mid-range profile (measured,
recorded in evidence); no WebGL; keyboard operable; reduced-motion honoured; no console
errors on the four evidence routes at four widths; published data under 5 MB.

## Traceability
| Requirement | Code | Test | Evidence | Status |
|---|---|---|---|---|
| P01-GOLD-01..10 | tests/fixtures/golden/* | tests/reference_check.py | CI job "Mode A" step "Independent reference check" | verified (local run exit 0; CI pending) |
| P01-MET-01..12 R02 | domain/revenue_atlas/metrics.py | tests/test_golden_domain.py | CI Mode A pytest | not_checked |
| P01-FLOW-01 (C01) | domain/revenue_atlas/ingest.py, api/app.py | tests/test_api_commands.py | CI Mode A | not_checked |
| P01-FLOW-02 (C02) | domain/revenue_atlas/costing.py | tests/test_rules.py | CI Mode A | not_checked |
| P01-FLOW-03 (C03) | domain/revenue_atlas/returns.py | tests/test_rules.py | CI Mode A | not_checked |
| P01-FLOW-04 (C04) | domain/revenue_atlas/allocation.py | tests/test_rules.py | CI Mode A | not_checked |
| P01-TEST-01..12 | (see verification ledger) | tests/test_adversarial.py | CI Mode A | not_checked |
| P01-UI-01/02/08/10 | web/src/routes/* | web/e2e/journey.spec.ts | CI Mode B screenshots | not_checked |
| P01-REL-01..24 | .github/workflows/revenue-atlas-ci.yml, labs/revenue-atlas | release-manifest.json | Actions run + live check job | not_checked |
