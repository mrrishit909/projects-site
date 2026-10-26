"""Generate data/sql/t_quantiles.csv: the two-sided 95 % Student t quantile for df = 1..MAX_DF at 20 decimals.

The quantile is found by bisection on the exact t CDF (Abramowitz and Stegun 26.7.3-4 finite sums, 80-digit Decimal, no
table, no float) by ``productsignal.stats.t_crit``. The SQL reference (reference_metrics.sql) cannot reproduce that
series, so it reads these values from the table t_critical_975 (loaded by data/seed.py) and computes everything else
(means, variances, standard errors, the interval bounds) in SQL. tests/test_sql_reference.py checks the table against textbook
values and against the domain.

Usage: python data/sql/generate_t_quantiles.py   (about two minutes; the CSV is committed)
"""
from __future__ import annotations

import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "domain"))
from productsignal.stats import t_crit  # noqa: E402

MAX_DF = 2000


def main() -> None:
    out = Path(__file__).with_name("t_quantiles.csv")
    lines = ["df,t_975_two_sided"]
    for df in range(1, MAX_DF + 1):
        lines.append(f"{df},{t_crit(df).quantize(Decimal('1e-20'), rounding=ROUND_HALF_UP)}")
    out.write_text("\n".join(lines) + "\n")
    print(f"wrote {out} ({MAX_DF} rows)")


if __name__ == "__main__":
    main()
