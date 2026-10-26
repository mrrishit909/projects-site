# Views (part 2: overview, bridge, evidence, case study)

* `overview.tsx` `bridge.tsx` `evidence.tsx` all read `usePopulation()` (`state/filters.ts`): the pipeline facts filtered by
  the URL query (`?from=&to=&region=&segment=&category=`), so a deep link reproduces a view. Totals come from
  `computeMetrics` over that population; the ledger totals are summed independently from the fact columns, and the e2e
  asserts the two agree.
* `?hl=<step>` highlights the ledger columns behind a bridge step; `?dataset=golden` loads `public/data/golden/`
  (written by `scripts/golden-to-snapshot.ts`).
* Unallocated freight (D-04) is added to shipping cost only for the unfiltered population; it cannot be attributed to a
  partial window or region. It is 0.00 in the published dataset.
* Charts are inline SVG sized to their container; each has an adjacent table. No mutating controls exist here; the CSV
  export is a download.
