// Fixed-point decimal on BigInt. value = u / 10^s. No floating point is ever involved.
// Rounding is ROUND_HALF_UP in the Python `decimal` sense: ties go away from zero.

export interface Dec {
  readonly u: bigint;
  readonly s: number;
}

const POW: bigint[] = [];
function pow10(n: number): bigint {
  if (n < 0) throw new RangeError("negative scale");
  return (POW[n] ??= 10n ** BigInt(n));
}

export const ZERO: Dec = { u: 0n, s: 0 };
export const ONE: Dec = { u: 1n, s: 0 };

const DECIMAL_RE = /^([+-]?)(\d+)(?:\.(\d+))?$/;

/** Parse a decimal string such as "123.45", "-0.5" or "1". Anything else throws. */
export function parse(text: string): Dec {
  if (typeof text !== "string") throw new TypeError(`money must be a decimal string, got ${typeof text}`);
  const m = DECIMAL_RE.exec(text);
  if (!m) throw new SyntaxError(`not a decimal: ${JSON.stringify(text)}`);
  const frac = m[3] ?? "";
  const u = BigInt(m[2]! + frac);
  return { u: m[1] === "-" ? -u : u, s: frac.length };
}

export function fromInt(n: number | bigint): Dec {
  if (typeof n === "number" && !Number.isInteger(n)) throw new TypeError("fromInt needs an integer");
  return { u: BigInt(n), s: 0 };
}

function align(a: Dec, b: Dec): [bigint, bigint, number] {
  if (a.s === b.s) return [a.u, b.u, a.s];
  if (a.s < b.s) return [a.u * pow10(b.s - a.s), b.u, b.s];
  return [a.u, b.u * pow10(a.s - b.s), a.s];
}

export function add(a: Dec, b: Dec): Dec {
  const [x, y, s] = align(a, b);
  return { u: x + y, s };
}
export function sub(a: Dec, b: Dec): Dec {
  const [x, y, s] = align(a, b);
  return { u: x - y, s };
}
export function neg(a: Dec): Dec {
  return { u: -a.u, s: a.s };
}
export function mul(a: Dec, b: Dec): Dec {
  return { u: a.u * b.u, s: a.s + b.s };
}
export function cmp(a: Dec, b: Dec): -1 | 0 | 1 {
  const [x, y] = align(a, b);
  return x < y ? -1 : x > y ? 1 : 0;
}
export const eq = (a: Dec, b: Dec): boolean => cmp(a, b) === 0;
export const isZero = (a: Dec): boolean => a.u === 0n;
export const isNegative = (a: Dec): boolean => a.u < 0n;

export function sum(items: Iterable<Dec>): Dec {
  let acc = ZERO;
  for (const x of items) acc = add(acc, x);
  return acc;
}

/** Integer division of bigints rounding half away from zero. */
function divRoundHalfUp(n: bigint, d: bigint): bigint {
  if (d === 0n) throw new RangeError("division by zero");
  const negative = (n < 0n) !== (d < 0n);
  const an = n < 0n ? -n : n;
  const ad = d < 0n ? -d : d;
  let q = an / ad;
  if ((an % ad) * 2n >= ad) q += 1n;
  return negative ? -q : q;
}

/** Round to `scale` decimals, half up (away from zero on ties). The result has exactly `scale`. */
export function roundTo(x: Dec, scale: number): Dec {
  if (x.s === scale) return x;
  if (x.s < scale) return { u: x.u * pow10(scale - x.s), s: scale };
  return { u: divRoundHalfUp(x.u, pow10(x.s - scale)), s: scale };
}

/** a / b rounded half up at `scale` decimals, computed on exact integers (no intermediate loss). */
export function divToScale(a: Dec, b: Dec, scale: number): Dec {
  if (b.u === 0n) throw new RangeError("division by zero");
  return { u: divRoundHalfUp(a.u * pow10(scale + b.s), b.u * pow10(a.s)), s: scale };
}

/** Quantize to cents (0.01), ROUND_HALF_UP. */
export const cents = (x: Dec): Dec => roundTo(x, 2);
/** Quantize to six decimals, ROUND_HALF_UP. */
export const rate6 = (x: Dec): Dec => roundTo(x, 6);

/** Exact text at the value's own scale. A zero never carries a minus sign. */
export function toString(x: Dec): string {
  const negative = x.u < 0n;
  const digits = (negative ? -x.u : x.u).toString().padStart(x.s + 1, "0");
  const body = x.s === 0 ? digits : `${digits.slice(0, -x.s)}.${digits.slice(-x.s)}`;
  return negative ? `-${body}` : body;
}

/** Round to `scale` decimals then print, e.g. fixed(x, 2) -> "225.00". */
export const fixed = (x: Dec, scale: number): string => toString(roundTo(x, scale));

/**
 * Lossy conversion for chart GEOMETRY ONLY (axis positions, bar heights). Never feed the result
 * back into money arithmetic or print it as a figure; use `fixed`/`toString` for text.
 */
export function toPlotNumber(x: Dec): number {
  return Number(toString(x));
}
