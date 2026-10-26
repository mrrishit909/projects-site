# Onboard Studio TypeScript domain (Mode B)

A re-implementation of `domain/onboard_studio/` (Python, verified in CI) for the static demo. It implements
`docs/contracts.md` D-01..D-06 and is checked against `tests/fixtures/golden/` by `scripts/golden-check.ts`.

| File | Mirrors | Role |
|---|---|---|
| `time.ts` | `timeutil.py` | UTC parsing (zone required), integer-ms durations, hours at 4 dp and rates at 6 dp from exact BigInt ratios (ROUND_HALF_UP); no floating-point arithmetic on durations |
| `calendar.ts` | `calendar.py` | half-open interval merge, holiday subtraction, overlap (binary-searched) |
| `types.ts` / `contract.ts` / `errors.ts` | `models.py`, `contract.py`, `errors.py` | records, constants, reason codes, `DomainError` |
| `ingest.ts` | `ingest.py` | strict parsing, dependent rejection in the same reason order, `DECISION_CONFLICT`, duplicate ids; raw rows kept |
| `workflow.ts` | `workflow.py` | Kahn topological order, definition hash (sha256 of compact sorted-key JSON), readiness, approval, pause and completion checks |
| `metrics.ts` | `metrics.py` | `computeMetrics` (exactly the keys of `expected.json`), `computeWithFlags`, `groupMetrics` by organization / segment / region / workflow_version |
| `pipeline.ts` | `pipeline.py` | `runPipeline(inputs, state, { cutoffs, window })` -> `{ ingest, population, cases, rejected, flags, metrics, perCase }` |

Indexes are `Map`s keyed by id; nothing scans nested lists, so the 740-case snapshot runs in about 0.3 s.

Known, intended difference from the Python reference: Python's `Decimal` accumulates 28-digit rounding error
when it sums per-case `seconds / 3600` values, so a mean that is an exact tie at the fourth decimal can round
down there. The TypeScript mean is exact (total milliseconds over `3 600 000 x n`), so it rounds half-up as the
contract states. Sub-millisecond timestamp digits are dropped on parsing.
