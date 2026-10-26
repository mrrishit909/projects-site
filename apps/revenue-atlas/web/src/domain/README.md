# Domain (TypeScript mirror of the Python reference)

Recomputes every Revenue Atlas metric in the browser from the published snapshot, to the same
contract (`../../docs/contracts.md`, D-01..D-06) as `../../../domain/revenue_atlas/`.
`npm run golden` (`scripts/golden-check.ts`) asserts the hand-derived golden answers, the rejected
and empty variants, and runs the full snapshot under a 2 s budget.

## Decimal implementation (`decimal.ts`)

A value is a `BigInt` numerator `u` and a decimal scale `s` (value = `u / 10^s`). Input is parsed from
the JSON decimal strings, so no number ever passes through a binary float.

* `add`, `sub`, `mul` are exact (scales align or add).
* `roundTo` / `divToScale` round **half up, away from zero** (Python `ROUND_HALF_UP`). `divToScale`
  divides the exact integers and rounds once, so there is no intermediate loss. `cents` is 2 dp,
  `rate6` is 6 dp.
* `toString` / `fixed` print text; zero never prints a minus sign (Python can print `-0.00`).
* `toPlotNumber` is the only lossy exit and is for chart geometry only.
* Rounding happens at the same two points as the contract: allocation (discount and freight, to cents)
  and presentation (metrics). Everything between is full precision.

## Mirrors

| TypeScript | Python (`domain/revenue_atlas/`) |
|---|---|
| `decimal.ts` | `money.py` (`parse_money`, `cents`, `rate6`, `money_str`, `rate_str`) |
| `money.ts` | `money.py` (`largest_remainder`) |
| `contract.ts`, `errors.ts` | `contract.py`, `errors.py` |
| `types.ts` | `models.py` |
| `ingest.ts` | `ingest.py` (`validate_batch`, currency rule, dependent rejection, counts) |
| `fx.ts` | `fx.py` (`rate_for`) |
| `costing.ts` | `costing.py` (`resolve_cost_version`) |
| `allocation.ts` | `allocation.py` (`allocate_discounts`, `allocate_freight`) |
| `returns.ts` | `returns.py` (`validate_return`, `expected_credit`, `recoverable_cost`) |
| `metrics.ts` | `metrics.py` (`compute_metrics`, `group_metrics`, half-open windows) |
| `pipeline.ts` | `pipeline.py` (`run_pipeline`, quarantine, region by customer version) |

## Differences, on purpose

* Lookups use index maps (rates, cost versions, customers, lines, shipments) instead of list scans.
* Windows are UTC epoch milliseconds, half-open `[from, to)`.
* Ratios divide the exact integers once; Python divides at 28 significant digits then rounds. The two
  can differ only when a quotient sits within 1e-28 of a rounding tie. On the published snapshot
  every metric, count, quarantine and rejection matches the Python run exactly.
