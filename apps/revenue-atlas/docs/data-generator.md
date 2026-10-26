# Revenue Atlas — synthetic data generator specification (P01-WORK-03)

`data/generate.py` (stdlib only) writes the published snapshot deterministically from a
seed and parameters recorded in the manifest (master 14).

* Default demo configuration: seed 20261026, 24 months 2024-10-01 to 2026-09-30 UTC,
  4 regions (`reg-north`, `reg-south`, `reg-east`, `reg-west`), 48 customers in 3 segments,
  36 products in 6 categories, ~2,400 orders, ~6,000 order lines, ~2,500 shipments,
  cost versions that step up twice a year, EUR and CAD orders for ~20 % of customers with
  daily FX rows, quotas per rep per quarter, discounts on ~35 % of lines with reason codes.
* Designed-in relationships (documented, synthetic, not real-world claims): category
  `cat-fixtures` carries rising unit costs from 2026-01 without price changes; region
  `reg-west` has a discount policy change from 2026-03 that doubles its discount rate;
  customer segment `enterprise` has a higher return rate for `cat-apparel`. These are what
  the decision screens should surface, and the generator writes them to
  `data/injection-manifest.json` so a reviewer can check the site finds them.
* Injected defects (listed in the injection manifest, never used as app input):
  3 orders with malformed currency (`US$`, `usd`, `EU`), 2 overlapping cost versions,
  1 product with no cost version in a month, 2 missing FX dates, 1 duplicate shipment line
  row, 4 returns exceeding remaining quantity, 1 negative credit, 2 customers with a
  territory change mid-series, 3 customers with no effective version at their first
  shipment (UNASSIGNED), 5 cancelled orders before shipment, 2 orders with zero gross and
  nonzero freight.
* Output: `web/public/data/<entity>.json` plus `manifest.json` with `dataset_version`
  (`ra-<seed>-<yyyymmdd>`), `dataset_hash` (sha256 over the sorted entity files),
  `generated_at`, row counts and the parameters; CI data must stay below 5 MB total.
* The same generator feeds the PostgreSQL seed for Mode A verification.
