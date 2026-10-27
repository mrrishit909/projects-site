// ONE ASCII-only pattern set with FULL-MATCH semantics for money, quantity and timestamp fields (docs/contracts.md D-09, R8-04). The same set lives in
// the Python domain (`re.fullmatch` with `re.ASCII`), in data/sql/reference_metrics.sql (`\A ... \Z` with `[0-9]`) and in tests/reference_check.py (written
// by hand, no regular expression): the four must agree on every input, which tests/fixtures/divergence/cases.json states case by case.
// Here: `^...$` with the `u` flag and no `m` flag (so `$` can only match at the very end) plus an explicit refusal of any newline.

export const MONEY_RE = /^-?[0-9]+(?:\.[0-9]{1,2})?$/u;
export const TIMESTAMP_RE = /^([0-9]{4})-([0-9]{2})-([0-9]{2})[T ]([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]+))?(Z|[+-][0-9]{2}:[0-9]{2})$/u;
/** The largest magnitude of an integer a JSON consumer using doubles reads back exactly. */
export const MAX_SAFE_INTEGER = 9007199254740992;

const noNewline = (s: string): boolean => !s.includes("\n") && !s.includes("\r");
/** A money string: optional minus, digits, optionally a point and one or two decimals; nothing before, after or between. */
export const isMoney = (v: unknown): v is string => typeof v === "string" && noNewline(v) && MONEY_RE.test(v);
/** A quantity: a JSON integer (never a bool, never a float such as 3.0 - parseJsonExact keeps those as JsonNumber) of magnitude at most 2**53. */
export const isQuantity = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v) && Math.abs(v) <= MAX_SAFE_INTEGER;
export const matchTimestamp = (v: string): RegExpExecArray | null => (noNewline(v) ? TIMESTAMP_RE.exec(v) : null);
