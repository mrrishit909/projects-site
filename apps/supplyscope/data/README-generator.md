# SupplyScope synthetic data generator

`data/generate.py` (stdlib only, specification: `docs/data-generator.md`) writes the published synthetic snapshot. A
master `random.Random(seed)` hands one child stream to each purpose (latent demand per SKU, the supply simulation, the
extras), dates are `datetime.date` arithmetic and nothing iterates a set of strings, so the same seed gives
byte-identical entity files and the same `dataset_hash` (checked under three `PYTHONHASHSEED` values).

```sh
python data/generate.py --seed 20261026 --out web/public/data     # about 0.6 s, 4.33 MB (4,327,859 bytes)
python data/generate.py --profile golden-shape-check               # field names vs tests/fixtures/golden
python -m pytest tests/test_generator.py                           # DATABASE_URL set: also seeds Postgres (about 25 s)
```

Options: `--data-dir` (where `injection-manifest.json` and `injection-events.json` go, default `data/`).

## Output

| File | Content |
|---|---|
| `web/public/data/<entity>.json` | `{"entity", "dataset_version", "rows"}` for the 19 entities the pipeline reads (the 15 counted ones plus `cost_versions`, `calendar_closures`, `latent_demand`, `lost_sales`). Field names equal `tests/fixtures/golden/inputs.json` (and `data/seed.py` COLUMNS for entities empty there). |
| `web/public/data/manifest.json` | `dataset_version` (`ss-<seed>-20261026`), `dataset_hash`, `generated_at` (real UTC, not hashed), `contract_version`, `generator` (name, seed, every parameter), `row_counts`, `designed_relationships`, `injection_manifest`, `stats`. |
| `data/injection-manifest.json` (+ copy in `web/public/data/`) | `INJ-01..11` as `{id, test, entity, location, record_ids, description, expected_handling}` and the designed relationships. |
| `data/injection-events.json` | `EV-01..07`: replay-only events (command input, `expected_reason` / `expected_status`, `expected_handling`) for defects that cannot sit in a clean entity file. |

`dataset_hash` = sha256 over the concatenation, in entity-name order, of `json.dumps(rows, sort_keys=True,
separators=(",", ":"))` of each entity file (19 files).

## The simulated world

* 2025-04-01 .. 2026-09-30 daily (548 days), snapshot cut `2026-09-30T23:59:59Z` (`as_of`). 3 locations (`loc-01` Main DC,
  `loc-02` Overflow DC, `loc-03` East Cross-dock), 60 SKUs (8 class A, 16 B, 36 C of which 12 are intermittent), each
  stocked at one home location (60 SKU x location pairs), 4 suppliers (`sup-01..04`, quoted lead 5 / 12 / 9 / 21 days).
* Latent demand: gamma-mixed Poisson (negative binomial, shape 8) x weekly profile x annual swing x `1 + realised
  uplift` inside promotion windows; intermittent SKUs draw an event with probability 5-10 % x a lumpy size.
* Each day follows D-01: receipts (08:00Z), then backlog fills and demand (12:00Z), then the review (17:00Z) that places
  an order when position < reorder point (`pack_round_up(max(target - position, MOQ))`). Observed sales are
  `min(stock, latent)`; the gap is a `lost_sales` row (backorder at `loc-03`, the one location whose policy of record is
  backlog). Stock is never negative.
* Supplier lead time is counted on the supplier calendar (`cal-02` is closed 2026-01-05 .. 2026-01-18); a purchase order is
  late with the supplier's probability (sup-03 0.30), by 1-7 open days, and never early (no receipt before the lead time).
  8 % of lines are delivered in two parts; 4 lines ordered in the last 25 days were short-shipped and stay open; 1.5 % of
  orders are cancelled.
* Unit cost steps once: +6 % on the 15 `sup-04` products from 2026-02-01 (`cost_versions`; PO lines carry the cost at
  order time). 45 promotions: 3 ten-day windows on each of 15 SKUs (all 8 class A, 7 class B), announced 14 days ahead.
* Forecasts: 14 pairs (8 class A, 4 intermittent, 2 promoted B) at 4 cutoffs (2026-06-30, 07-31, 08-31, 09-16), horizon
  14 days, models naive, seasonal-naive (period 7) and EWMA (alpha 0.3), `selected_model` from a four-origin rolling
  backtest (a model other than seasonal-naive is chosen only when it beats it).
* 4 policy scenarios: service 0.95 / 0.98 x lost_sale / backlog, one seed (20261026), warm-up 28, 100 replications.

## Size and the volume cap

Total under 5 MB (4.33 MB). Sales and movements are aggregated to SKU x location x day: one sale row and one sale
movement per pair-day with sales, one movement per receipt, one opening `adjustment` per pair (2025-03-31T23:00Z). The cap
that keeps the budget: only the 8 class-A pairs sell on nearly every day; B pairs sell on about 20-45 % of days, slow C
pairs on 8-20 %, intermittent pairs on 5-10 %; every SKU has one home location (60 of the 180 possible pairs are active);
`latent_demand` is published for class A, promoted and intermittent pairs (27 pairs), positive days only (an absent day is
0). The knobs are the class means in `setup_skus`.

## Designed relationships (numbers in `manifest.designed_relationships`)

* Class A promoted SKUs show censoring during stockouts: ROP/target ignore promotions, so uplift windows exhaust stock;
  observed sales fall below latent on exactly the days with a `lost_sales` / `backorders` row.
* `sup-03` is late on 31.9 % of receipts (others 13-17 %; the second part of a split delivery also counts).
* `loc-02` is capacity-bound: `storage_capacity` is 62 % of the summed targets, orders are cut to the room left (609
  blocked reviews), its fill rate is the lowest (0.888 vs 0.96) and its stockout-day share the highest.

## Defects: where each one lives

| Defect | In entity files | In events |
|---|---|---|
| INJ-01 duplicate movement ids (3 exact replays) | yes, end of `inventory_movements` | |
| INJ-02 receipt before its order date | yes, `rcpt-01309` / `po-0998` | EV-02 (API replay) |
| INJ-03 partial receipt flagged complete | yes, 2 `closed` sup-03 POs | EV-03 |
| INJ-04 lead time spanning the closure | yes, 8 sup-02 receipts | |
| INJ-05 intermittent SKU, zero-demand folds | yes, 12 SKUs | |
| INJ-06 unit-cost change in a valuation period | yes, `cost_versions` | |
| INJ-07 reserved stock a naive position double-subtracts | yes, 6 open reservations | EV-04 |
| INJ-08 duplicate movement conflict | | EV-01 |
| INJ-09 receipt before lead time | | EV-06 |
| INJ-10 two policies with different seeds | | EV-05 |
| INJ-11 pack rounding below MOQ | | EV-07 |

## Domain behaviours found while generating (unchanged, recorded for the owners of `domain/`)

* `validate_batch` loads `products` before `suppliers`, so a product row with `supplier_id` is rejected
  `UNKNOWN_REFERENCE`; the generator therefore omits `products.supplier_id` and states the supplier on
  `replenishment_params` (which `supplier_of` also reads).
* `latent_demand` rows are keyed by `product_id` alone in ingest (`ID_FIELD`), so only the first row of a product is
  accepted (`DUPLICATE_ID` for the rest) and `seed.py` loads one latent row per product. The published file is complete;
  the tests read latent demand from the file and through `censored_vs_latent` with rows parsed from it.
