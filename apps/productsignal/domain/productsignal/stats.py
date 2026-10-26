"""Exact numerics for the published figures (D-04, D-05): no float anywhere.

Ratios are ``Fraction``s; special functions use ``Decimal`` series under a local 80-digit context (decimal contexts are per
thread, and nothing here touches the global one). Square roots are integer Newton iterations (error below 1e-20, the
contract needs 1e-8). Rounding is ROUND_HALF_UP, once, on the unrounded value (D-P6-1); ``-0.00`` is written ``0.00``.
"""
from __future__ import annotations

import functools
from decimal import ROUND_HALF_UP, Context, Decimal as D, localcontext
from fractions import Fraction as F

PREC = 80
CTX = Context(prec=PREC, rounding=ROUND_HALF_UP)


def exact(fn):
    @functools.wraps(fn)
    def wrapper(*a, **k):
        with localcontext(CTX):
            return fn(*a, **k)
    return wrapper


def isqrt_newton(n: int) -> int:
    """floor(sqrt(n)) by integer Newton iteration."""
    if n < 2:
        return n
    x = 1 << ((n.bit_length() + 1) // 2)
    while True:
        y = (x + n // x) // 2
        if y >= x:
            return x
        x = y


def sqrt_frac(x: F) -> F:
    """sqrt of a nonnegative Fraction, truncated at 1e-20."""
    return F(isqrt_newton((x.numerator * 10 ** 40) // x.denominator), 10 ** 20)


@exact
def dsqrt(x: D) -> D:
    """sqrt of a nonnegative Decimal at 60 decimals by integer Newton."""
    return D(isqrt_newton(int(x * D(10) ** 120))) / D(10) ** 60


def dec(x) -> D:
    return x if isinstance(x, D) else D(x.numerator) / D(x.denominator) if isinstance(x, F) else D(x)


@exact
def q(x, places: int) -> str:
    """ROUND_HALF_UP to ``places`` as a string; never '-0.00'."""
    s = str(dec(x).quantize(D(1).scaleb(-places), rounding=ROUND_HALF_UP))
    return s[1:] if s.startswith("-") and not any(c in "123456789" for c in s) else s


def ratio(n: int, d: int) -> F | None:
    return None if d == 0 else F(n, d)


def q6(x) -> str | None:
    return None if x is None else q(x, 6)


@exact
def d_atan(x: D) -> D:
    k = 0
    while abs(x) > D("0.2"):
        x = x / (1 + dsqrt(1 + x * x))
        k += 1
    s, t, n = D(0), x, 0
    while abs(t) > D(10) ** -70:
        s += t / (2 * n + 1)
        t = -t * x * x
        n += 1
    return s * (2 ** k)


@functools.lru_cache(maxsize=1)
def pi() -> D:
    with localcontext(CTX):
        return 16 * d_atan(D(1) / 5) - 4 * d_atan(D(1) / 239)


@exact
def d_erf(x: D) -> D:
    s, term, n = D(0), x, 0
    while abs(term) > D(10) ** -70:
        s += term / (2 * n + 1)
        n += 1
        term = -term * x * x / n
    return 2 * s / dsqrt(pi())


@exact
def erfc_half_sqrt(stat) -> D:
    """P(Z^2 > stat) = erfc(sqrt(stat / 2)) for one degree of freedom; 0 beyond 100 (below 1e-20)."""
    if stat <= 0:
        return D(1)
    if stat > 100:
        return D(0)
    return 1 - d_erf(dsqrt(dec(stat) / 2))


chi2_sf_df1 = erfc_half_sqrt


@exact
def normal_two_sided_p(z: F) -> D:
    """P(|Z| > |z|) = erfc(|z| / sqrt(2)) for a standard normal Z."""
    z = abs(z)
    if z > 10:
        return D(0)
    return 1 - d_erf(dec(z) / dsqrt(D(2)))


@functools.lru_cache(maxsize=64)
def z_crit(confidence: str) -> D:
    """Two-sided normal critical value for a confidence level (a decimal string), by bisection on erfc."""
    with localcontext(CTX):
        want = 1 - D(confidence)
        lo, hi = D(0), D(40)
        for _ in range(90):
            mid = (lo + hi) / 2
            if normal_two_sided_p(F(mid)) > want:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2


@exact
def t_two_sided(t: D, nu: int) -> D:
    """P(|T| < t) for integer nu (Abramowitz and Stegun 26.7.3-4 finite sums)."""
    r = dsqrt(D(nu) + t * t)
    sin, cos = t / r, dsqrt(D(nu)) / r
    if nu % 2 == 1:
        theta = d_atan(t / dsqrt(D(nu)))
        c, tot, p = D(1), D(0), cos
        for k in range((nu - 1) // 2):
            tot += c * p
            c = c * (2 * k + 2) / (2 * k + 3)
            p = p * cos * cos
        return 2 / pi() * (theta + sin * tot)
    d, tot, p = D(1), D(0), D(1)
    for k in range(nu // 2):
        tot += d * p
        d = d * (2 * k + 1) / (2 * k + 2)
        p = p * cos * cos
    return sin * tot


@functools.lru_cache(maxsize=4096)
def t_crit(nu: int, conf: str = "0.95") -> D:
    """Two-sided critical value by bisection on the exact t CDF (no table)."""
    with localcontext(CTX):
        c = D(conf)
        lo, hi = D(0), D(1000)
        for _ in range(90):
            mid = (lo + hi) / 2
            if t_two_sided(mid, nu) < c:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2


def wilson(x: int, n: int, z: F) -> tuple[F, F, F]:
    p = F(x, n)
    z2 = z * z
    denom = 1 + z2 / n
    centre = p + z2 / (2 * n)
    half = z * sqrt_frac(p * (1 - p) / n + z2 / (4 * n * n))
    return p, (centre - half) / denom, (centre + half) / denom


def newcombe(x1: int, n1: int, x2: int, n2: int, z: F) -> tuple[F, F, F]:
    """Hybrid score interval for p1 - p2 (group 1 = treatment, 2 = control)."""
    p1, l1, u1 = wilson(x1, n1, z)
    p2, l2, u2 = wilson(x2, n2, z)
    d = p1 - p2
    low = d - sqrt_frac((p1 - l1) ** 2 + (u2 - p2) ** 2)
    high = d + sqrt_frac((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return d, low, high
