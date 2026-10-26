# SupplyScope — synthetic data generator specification (P03-WORK-03)

* Seed 20261026; 18 months 2025-04-01 .. 2026-09-30 daily; 3 locations; 60 SKUs in
  ABC classes with intermittent demand for ~12 of them; 4 suppliers with calendars (one
  with a two-week closure) and quoted lead days 5..21; promotions on ~15 SKUs; latent daily
  demand (Poisson/negative-binomial with weekly seasonality and promo factors) published
  separately from censored observed sales; movements for receipts and sales; purchase orders
  with partial receipts; unit cost versions stepping once; policy scenarios (two service
  targets × two unmet-demand policies).
* Designed relationships: SKUs in class A with promotions show censoring during stockouts;
  supplier `sup-03` is late ~30 % of the time; location `loc-02` has the capacity bind.
* Injected defects (manifest + replay events): duplicate movement ids, a receipt before its
  order date, a partial receipt flagged complete, pack rounding below MOQ, a lead time
  spanning the closure, an intermittent SKU with zero-demand folds, a unit cost change inside
  a valuation period, a reserved-stock double subtraction attempt, two policies with
  different seeds (attempted).
* Output under 5 MB: daily sales and movements are the volume drivers; keep SKU×location
  ×day aggregates, not per-unit rows.
