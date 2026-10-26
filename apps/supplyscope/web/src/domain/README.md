# SupplyScope TypeScript domain (contract v1, D-01..D-06)

A re-implementation of `apps/supplyscope/domain/supplyscope/*.py` for the static site (Mode B). Same rules, same reason codes,
same metric keys (`METRIC_KEYS`, in `expected.json` order).

* Units are integers. Money is a decimal string held as BigInt cents (`money.ts`); rates are exact ratios (`Rat`) rounded half-up
  to 6 places; forecasts use exact decimals (`Dec`, BigInt), so MAE and WAPE equal the Python `Fraction` results.
* Instants are UTC epoch ms, dates are day numbers or `YYYY-MM-DD` (`time.ts`). Sub-millisecond fractions are truncated.
* `runPipeline(inputs, state)` = ingest -> population -> `computeMetrics`; `reorderRows` gives one draft row per parameter row;
  `pairSeries` the daily trajectory; `forecastDemand` the rolling-origin evaluation (per-fold scores are an addition).
* Checked by `npm run golden` (golden fixture both states, both variants, then the full snapshot).

## Mirrored Python behaviour that looks like a defect (not corrected here)
1. `forecast.promo_factor` multiplies the EWMA level by `planned_uplift` (e.g. 0.97) whereas the generator applies `1 + uplift`.
2. `ingest.ORDER` loads products before suppliers, so a product row with `supplier_id` would be rejected UNKNOWN_REFERENCE
   (the published products carry none).
3. Purchase orders with status `closed` never count as on order even when a line is partly received (INJ-03 lines).
