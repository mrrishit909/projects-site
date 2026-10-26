# Revenue Atlas — API route inventory (backend contract, Mode A only)

These routes are implemented by `api/app.py` and exercised on GitHub-hosted runners against
a transient PostgreSQL service. They are **not** served by GitHub Pages; the static site
reads the published snapshot in `web/public/data/` instead (spec section 11).

Envelopes: reads return `{data, meta, warnings}` with `meta = {dataset_version, code_sha,
contract_version, generated_at, applied_filters, total_count, next_cursor}`; errors return
`{error: {code, message, details}, request_id}`; commands take `{request_id,
dataset_version, idempotency_key, input}` and return `{command_id, status, result,
warnings, version}`.

| ID | Method and path | Transition / population | Hard validation | Status |
|---|---|---|---|---|
| C01 | POST /api/v1/revenue-atlas/commands/ingest-sales | unvalidated batch → validated batch | ISO-4217 currency; shipped <= ordered per order line (`SHIPPED_EXCEEDS_ORDERED`); shipment line in its shipment's order (`SHIPMENT_LINE_ORDER_MISMATCH`); raw rows preserved; idempotent by key. A violation seen only by the database (a later batch) is a 422 with the same rule id (D-08) | slice |
| C02 | POST /api/v1/revenue-atlas/commands/resolve-historical-cost | shipped line → costed line | exactly one cost version at shipped_at | slice |
| C03 | POST /api/v1/revenue-atlas/commands/post-a-partial-return | shipped → partially returned | qty ≤ remaining; credit ≥ 0 (`-0.00` is `CREDIT_SIGN_REVERSED`, D-08) | slice |
| C04 | POST /api/v1/revenue-atlas/commands/allocate-freight | order freight → line allocations | residual 0.00; unique per shipment line; freight only over lines not quarantined; same shipment again is 409 unless the eligible set changed, then status `reallocated` (re-spread, D-08); discount split of the whole order line upserted | slice |
| C05 | POST /api/v1/revenue-atlas/commands/investigate-margin-decline | overview → segment → transactions | scope and time basis echoed | extension |
| C06 | POST /api/v1/revenue-atlas/commands/compare-regional-results | regions → reconciled comparison | UNASSIGNED row explicit | extension |
| C07 | POST /api/v1/revenue-atlas/commands/create-scenario | baseline → draft scenario | baseline immutable | extension |
| C08 | POST /api/v1/revenue-atlas/commands/adjust-discounts | draft → recalculated | never writes historical rows | extension |
| C09 | POST /api/v1/revenue-atlas/commands/export-findings | analysis → export | filters + versions embedded | extension |
| C10 | POST /api/v1/revenue-atlas/commands/publish-snapshot | verified run → static snapshot | source and build hashes | extension |
| R | GET /api/v1/revenue-atlas/data/{entity} | entity read with filters, limit ≤ 200, cursor | stable ordering by key | slice |
| M | GET /api/v1/revenue-atlas/metrics?from=&to=&group_by= | metric read over the population | half-open window; reversed range → 422 | slice |

Status codes: 422 validation (`error.details[].path`, `rule_id`), 409 stale version or
idempotency-key reuse with a different payload, 404 unknown resource, 401/403 on the
verified backend when identity headers are absent or forbidden (never claimed from the
static site).
