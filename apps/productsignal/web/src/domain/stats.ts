// Mirror of domain/productsignal/stats.py: Wilson and Newcombe intervals with exact square roots (truncated at 1e-20, the
// contract needs 1e-8), the chi-square tail by an erfc series, the normal and Student t critical values by bisection.
import { ONE, S, absB, add, absF, div, fr, fxDiv, fxInt, fxMul, fxOf, fxSqrt, gt, isqrt, mul, pow10, sub, type Frac, type Fx, fxFrac, fracOf } from "./num";

/** sqrt of a nonnegative rational, truncated at 1e-20. */
export function sqrtFrac(x: Frac): Frac {
  return fr(isqrt((x.n * pow10(40)) / x.d), pow10(20));
}

export function wilson(x: number, n: number, z: Frac): [Frac, Frac, Frac] {
  const p = fr(x, n);
  const z2 = mul(z, z);
  const denom = add(ONE, div(z2, fr(n)));
  const centre = add(p, div(z2, fr(2 * n)));
  const half = mul(z, sqrtFrac(add(div(mul(p, sub(ONE, p)), fr(n)), div(z2, fr(4n * BigInt(n) * BigInt(n))))));
  return [p, div(sub(centre, half), denom), div(add(centre, half), denom)];
}

/** Hybrid score interval for p1 - p2 (group 1 = treatment, 2 = control). */
export function newcombe(x1: number, n1: number, x2: number, n2: number, z: Frac): [Frac, Frac, Frac] {
  const [p1, l1, u1] = wilson(x1, n1, z);
  const [p2, l2, u2] = wilson(x2, n2, z);
  const d = sub(p1, p2);
  const sq = (a: Frac): Frac => mul(a, a);
  const low = sub(d, sqrtFrac(add(sq(sub(p1, l1)), sq(sub(u2, p2)))));
  const high = add(d, sqrtFrac(add(sq(sub(u1, p1)), sq(sub(p2, l2)))));
  return [d, low, high];
}

// ------------------------------------------------------------------------------------------------ special functions
function dAtan(x0: Fx): Fx {
  let x = x0, k = 0;
  const lim = S / 5n; // 0.2
  while (absB(x) > lim) { x = fxDiv(x, S + fxSqrt(S + fxMul(x, x))); k++; }
  let s = 0n, t = x, n = 0n;
  while (absB(t) > 0n) {
    s += t / (2n * n + 1n);
    t = -fxMul(fxMul(t, x), x);
    n++;
  }
  return s * (1n << BigInt(k));
}
let PI_CACHE: Fx | null = null;
export function pi(): Fx {
  return (PI_CACHE ??= 16n * dAtan(S / 5n) - 4n * dAtan(S / 239n));
}
function dErf(x: Fx): Fx {
  let s = 0n, term = x, n = 0n;
  while (absB(term) > 0n) {
    s += term / (2n * n + 1n);
    n++;
    term = -(fxMul(term, fxMul(x, x))) / n;
  }
  return fxDiv(2n * s, fxSqrt(pi()));
}

/** P(Z^2 > stat) = erfc(sqrt(stat / 2)) for one degree of freedom; 0 beyond 100 (below 1e-20); a fixed-point value. */
export function chi2SfDf1(stat: Frac): Fx {
  if (stat.n <= 0n) return S;
  if (gt(stat, fr(100))) return 0n;
  return S - dErf(fxSqrt(fxOf(div(stat, fr(2)))));
}

/** P(|Z| > |z|) for a standard normal Z. */
export function normalTwoSidedP(z: Frac): Fx {
  const a = absF(z);
  if (gt(a, fr(10))) return 0n;
  return S - dErf(fxDiv(fxOf(a), fxSqrt(fxInt(2))));
}

const Z_CACHE = new Map<string, Fx>();
/** Two-sided normal critical value for a confidence level (a decimal string), by bisection on erfc. */
export function zCrit(confidence: string): Fx {
  const hit = Z_CACHE.get(confidence);
  if (hit !== undefined) return hit;
  const want = fxOf(sub(ONE, fracOf(confidence)));
  let lo = 0n, hi = fxInt(40);
  for (let i = 0; i < 90; i++) {
    const mid = (lo + hi) / 2n;
    if (normalTwoSidedP(fxFrac(mid)) > want) lo = mid; else hi = mid;
  }
  const r = (lo + hi) / 2n;
  Z_CACHE.set(confidence, r);
  return r;
}

/** P(|T| < t) for integer nu (Abramowitz and Stegun 26.7.3-4 finite sums). */
function tTwoSided(t: Fx, nu: number): Fx {
  const nuF = fxInt(nu);
  const r = fxSqrt(nuF + fxMul(t, t));
  const sin = fxDiv(t, r), cos = fxDiv(fxSqrt(nuF), r);
  const cos2 = fxMul(cos, cos);
  if (nu % 2 === 1) {
    const theta = dAtan(fxDiv(t, fxSqrt(nuF)));
    let c = S, tot = 0n, p = cos;
    for (let k = 0; k < (nu - 1) / 2; k++) {
      tot += fxMul(c, p);
      c = (c * BigInt(2 * k + 2)) / BigInt(2 * k + 3);
      p = fxMul(p, cos2);
    }
    return fxMul(fxDiv(2n * S, pi()), theta + fxMul(sin, tot));
  }
  let d = S, tot = 0n, p = S;
  for (let k = 0; k < nu / 2; k++) {
    tot += fxMul(d, p);
    d = (d * BigInt(2 * k + 1)) / BigInt(2 * k + 2);
    p = fxMul(p, cos2);
  }
  return fxMul(sin, tot);
}

const T_CACHE = new Map<string, Fx>();
/** Two-sided critical value by bisection on the exact t CDF (no table). */
export function tCrit(nu: number, conf = "0.95"): Fx {
  const key = `${nu}|${conf}`;
  const hit = T_CACHE.get(key);
  if (hit !== undefined) return hit;
  const c = fxOf(fracOf(conf));
  let lo = 0n, hi = fxInt(1000);
  for (let i = 0; i < 90; i++) {
    const mid = (lo + hi) / 2n;
    if (tTwoSided(mid, nu) < c) lo = mid; else hi = mid;
  }
  const r = (lo + hi) / 2n;
  T_CACHE.set(key, r);
  return r;
}
