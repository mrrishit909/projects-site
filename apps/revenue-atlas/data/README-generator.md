# Revenue Atlas synthetic data generator

`data/generate.py` (stdlib only, specification: `docs/data-generator.md`) writes the published
synthetic snapshot. One `random.Random(seed)` stream and integer-cent money make it deterministic:
the same seed gives byte-identical entity files and the same `dataset_hash`.

```sh
python data/generate.py --seed 20261026 --out web/public/data     # about 4 s, 2.7 MB
python data/generate.py --profile golden-shape-check               # field names vs tests/fixtures/golden
```

Options: `--data-dir` (where `injection-manifest.json` and `injection-events.json` go, default `data/`).

## Output

| File | Content |
|---|---|
| `web/public/data/<entity>.json` | `{"entity", "dataset_version", "rows"}` for customers, products, orders, order_lines, discounts, shipments, shipment_lines, returns, cost_versions, exchange_rates, quotas. Money is a 2-decimal string, FX rates 6 decimals, quantities integers. Shapes equal `tests/fixtures/golden/inputs.json` (`shipment_lines.cost_version_id` is `null`: command C02 sets it). Quotas have no golden shape: `quota_id, rep_id, period, period_start, period_end, quota_amount, currency`. |
| `web/public/data/manifest.json` | `dataset_version` (`ra-<seed>-20261026`), `dataset_hash`, `generated_at` (real UTC; not hashed), `contract_version`, `generator` (name, seed, all parameters), `row_counts`, `designed_relationships`, `injection_manifest`. |
| `data/injection-manifest.json` (+ copy in `web/public/data/`) | The eleven injected defects `INJ-01..11` as `{id, test, entity, record_ids, description, expected_handling}` plus the designed relationships. |
| `data/injection-events.json` | Command inputs for the defects that cannot live in the entity files (below). |

`dataset_hash` = sha256 over the concatenation, in entity-name order, of
`json.dumps(rows, sort_keys=True, separators=(",", ":"))` for each entity file.

## Where each defect lives

In the entity files (the pipeline must reject or quarantine them): INJ-01 malformed currency (3 orders and
their dependents), INJ-02 overlapping cost versions, INJ-03 missing cost version, INJ-04 missing FX dates,
INJ-08 territory changes, INJ-09 UNASSIGNED customers, INJ-10 cancelled orders, INJ-11 zero-gross orders.

In `data/injection-events.json` only (replay them through the API commands): INJ-05 the duplicate shipment
line row (C01 replay plus a repeated C04), INJ-06 four returns exceeding the remaining quantity (C03),
INJ-07 one negative credit (C03). The duplicate would collide on the primary key when seeding, and the
database `CHECK (credit_amount >= 0)` would fail the seed on the negative credit. Event inputs assume a fresh
database seeded with the entity files and `expected_version` 1. Their shipment lines have no generated return.

## Designed relationships

* `cat-fixtures` unit costs step about +18 % on 2026-01-01 (prices never change).
* `reg-west` discounts: from 2026-03-01 probability 0.35 to 0.55 and depth about x1.45, reason `promo`: the
  discount rate roughly doubles.
* `enterprise` in `cat-apparel`: return probability 0.156 vs 0.052 per shipment line.

## Notes

* Customers have a `customers` row per type-2 version; the three UNASSIGNED customers start 20 days after
  their first shipment. Customer names include four of 60+ characters; product names are carried in the
  (descriptive) `sku` because the golden product shape has no name field, two SKUs are 60+ characters.
* Returns are only generated when the credit date falls inside the window, so FX rows end on 2026-09-30.
* `generate.py` imports nothing from `domain/`; `tests/test_generator.py` checks it against the pipeline.
