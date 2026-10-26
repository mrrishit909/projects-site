# SupplyScope — API route inventory (backend contract, Mode A only)

Same envelopes, identity headers (roles planner|buyer|admin) and status codes as Revenue Atlas.
Prefix `/api/v1/supplyscope`. Not served by GitHub Pages.

| ID | Method and path | Transition | Hard validation | Milestone |
|---|---|---|---|---|
| C01 | POST …/commands/load-movements | raw movements → validated ledger | duplicate movement_id rejected; raw rows kept | slice |
| C02 | POST …/commands/reconstruct-stock | ledger → as-of inventory | complete historical order; day order receipts→demand→review | slice |
| C03 | POST …/commands/forecast-demand | cutoff → horizon | only information known at cutoff; baselines always | slice |
| C04 | POST …/commands/classify-skus | annual consumption → ABC | value-based ranking, documented thresholds | extension |
| C05 | POST …/commands/calculate-replenishment | position below trigger → draft order | packs, MOQ, supplier calendar | slice |
| C06 | POST …/commands/simulate-arrival | outstanding PO → receipt | no receipt before lead time; receipt ≥ order date | slice |
| C07 | POST …/commands/record-unmet-demand | demand > stock → lost sale or backlog | scenario selects one policy; `occurred_at` required; the event is keyed by (product, location, occurred_at) so the same event under two scenarios is a 409 (R3-02) | slice |
| C08 | POST …/commands/compare-policies | common random paths → outcomes | same seed for every policy | extension |
| C09 | POST …/commands/review-supplier | promised vs actual → reliability | no future receipt leakage | extension |
| C10 | POST …/commands/export-buying-plan | reviewed drafts → CSV | never a real PO; filters and versions embedded; every draft re-validated against the current ledger, stale rows marked `stale` (D-07) | slice |
| R | GET …/data/{entity} | reads, limit ≤ 200, cursor | stable ordering | slice |
| M | GET …/metrics?as_of=&from=&to=&group_by=&scenario= | position, availability, fill rate, stockout days (SKU-day rate) and calendar share, WAPE, working capital | half-open window; as-of instant; scenario rows only when `scenario` names them (R3-02) | slice |

Every command carries `dataset_version`; when the database has a current `dataset_versions` row and the request names a
different one, the answer is `409 STALE_DATASET_VERSION` and nothing is written (D-07). An idempotent replay of a stored
command returns the stored answer without the check.
