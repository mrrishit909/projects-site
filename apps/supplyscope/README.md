# SupplyScope (Mode A backend)

Python domain + PostgreSQL + FastAPI for the Business Data Lab project 03. Synthetic data only. Contract:
`docs/contracts.md` (v1, D-01..D-06); routes: `docs/api-contract.md`. Independent of the other apps (no shared code).

| Path | What it is |
|---|---|
| `domain/supplyscope/` | Pure standard-library domain. `models` (typed rows, parsers), `ingest` (`validate_batch`, `screen_movements`), `ledger` (`reconstruct`, day order), `replenishment` (position, trigger, MOQ, `pack_round_up`, supplier-calendar lead time, safety stock), `demand` (fill rate, stockout days, unmet policy, censored vs latent, common random numbers), `forecast` (naive, seasonal-naive, EWMA, rolling-origin folds, MAE/WAPE), `suppliers` (on-time rate, open lines), `metrics` (`compute_metrics`, `group_metrics`), `pipeline` (`run_pipeline(inputs, state)`) |
| `data/` | `migrate.py`, `seed.py`, `migrations/0001_schema.sql`, `0002_constraints.sql`, `sql/reference_metrics.sql` (independent SQL recomputation), see `data/README.md` |
| `api/` | FastAPI app, prefix `/api/v1/supplyscope` |
| `tests/` | golden, variants, rules, migrations, SQL reference, API commands and reads, adversarial (`test_p03_test_NN_*`) |

## Run

    python -m venv .venv && .venv/bin/pip install -r requirements.txt
    export DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/supplyscope
    python data/migrate.py                       # idempotent; --reset drops this project's tables first
    python data/seed.py tests/fixtures/golden/inputs.json
    python -m pytest -q                          # database tests skip cleanly when DATABASE_URL is unset
    python -I tests/reference_check.py           # the independent oracle (never edited)
    uvicorn api.app:create_app --factory

## Rules in one place

* Units are integers; money is a Decimal string at 2 dp; rates are 6 dp from exact Fractions (ROUND_HALF_UP).
* Day order inside a date: receipts, then sales, then review/other; the sort key is (date, rank, event_at, movement_id).
  A negative reconstruction is flagged `NEGATIVE_STOCK` and valued at zero. A movement after `as_of` is excluded.
* Position = on hand + confirmed open order lines - open backorders (reserved is NOT subtracted). Quantity =
  `pack_round_up(max(target - position, MOQ))` when position < reorder point, else 0 (raw, MOQ and pack are 0 when not
  triggered; with no parameter row the replenishment fields are null).
* Lead time is counted in open days of the supplier calendar; closures extend it (and the lead-time demand).
  Safety stock = ceil(z x sqrt(daily residual variance x lead days)) with z from 0.90/0.95/0.98/0.99.
* Forecast at cutoff c uses sales sold at or before c and promotion *schedules* announced by c, never a promotion
  outcome (`realised_uplift`). Naive and seasonal-naive (period 7) are always computed; EWMA is reported as beating them
  only when its MAE is lower on the same rolling-origin folds. WAPE is null when the actuals sum to 0.
* Unmet demand is a backorder (backlog policy) or a lost sale (lost_sale policy), never both (database trigger on
  `demand_ref`). Receipts: before the order is `RECEIPT_BEFORE_ORDER`; over the ordered quantity is
  `RECEIPT_EXCEEDS_ORDERED`; a partial receipt leaves the line open.
* Ingest reasons: `MALFORMED_RECORD`, `DUPLICATE_ID`, `DUPLICATE_MOVEMENT_ID` (exact replay, first kept),
  `DUPLICATE_MOVEMENT_CONFLICT` (same id, different payload: every occurrence rejected), `UNKNOWN_REFERENCE`,
  `RECEIPT_BEFORE_ORDER`, `RECEIPT_EXCEEDS_ORDERED`. Raw rows are kept in `rejected_records`.

## API

Commands: `{request_id, dataset_version, idempotency_key, input}` with `X-Actor-Id` and `X-Actor-Role`
(`planner|buyer|admin`; 401 without id, 403 for another role). Atomic with its audit event; the same key, actor and
payload replays (`Idempotent-Replay: true`); another payload or another actor under the same key is 409. A deadlock
is retried, then `409 CONCURRENT_UPDATE`.

| Command | What it does |
|---|---|
| C01 `load-movements` | validates a batch; accepted rows go to the immutable ledger, the raw batch and rejected rows are kept |
| C02 `reconstruct-stock` | `as_of` -> one `stock_snapshots` row per (product, location), idempotent |
| C03 `forecast-demand` | `cutoff`, `horizon_days` -> `forecast_runs` + `forecast_points` (all three models); 422 if the cutoff is after the data end |
| C05 `calculate-replenishment` | `as_of`, `scenario_id` -> `draft_orders` (status always `draft`) with the arithmetic fields |
| C06 `simulate-arrival` | PO line + `at` -> a receipt and its ledger movement; 422 before the order or the lead time; partial allowed |
| C07 `record-unmet-demand` | the scenario policy decides: a backorder or a lost sale |
| C08 `compare-policies` | read-only simulation on common random numbers; scenarios with different seeds are refused |
| C09 `review-supplier` | on-time rate from receipts up to `as_of`, open and partially received lines |
| C10 `export-buying-plan` | draft orders to CSV text; `#` header lines carry contract version, dataset version, as_of, scenario, filters, row count; formula-leading cells get an apostrophe |
| C04 `classify-skus` | `501 NOT_IMPLEMENTED` (extension milestone) |

Reads: `GET /data/{entity}` (limit <= 200, opaque cursor, half-open `[from, to)`, whitelisted equality filters) and
`GET /metrics?as_of=&from=&to=&state=&group_by=` (`state` names a stored fixture state; `group_by` is product,
location, supplier or abc_class).
