"""Step 3: test every method on months it hasn't seen (rolling-origin backtest).

    ./venv/bin/python backtest.py

Pretend it's the end of a quarter between 2022 and mid-2025, fit on the history up to then, forecast 12 months,
and compare with what actually happened. 14 starting points x 12 months x 4 methods.

results/backtest_errors.csv   every single forecast vs actual
results/backtest_summary.csv  MAPE, MASE, bias and interval coverage per method (the scoreboard)
charts/04_backtest.png        MAPE by method
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from explore import HERE, INK, SERIES, CONTEXT, load, style
from models import MODELS

H = 12


def origins(y):
    """Quarter-ends from Mar 2022 on, as long as 12 actual months follow."""
    last_ok = y.index[-1] - pd.DateOffset(months=H)
    return [d for d in pd.date_range("2022-03-01", last_ok, freq="3MS")]


def run(y):
    rows = []
    for origin in origins(y):
        train, actual = y[:origin], y[origin + pd.offsets.MonthBegin():][:H]
        for name, model in MODELS.items():
            fc = model(train, H)
            for i, (month, a) in enumerate(actual.items(), 1):
                r = fc.loc[month]
                rows.append({"model": name, "origin": origin.date(), "h": i, "month": month.date(), "actual": a,
                             "forecast": r["forecast"], "lo80": r.get("lo80"), "hi80": r.get("hi80")})
    return pd.DataFrame(rows)


def summarize(err, y):
    err["pct_error"] = 100 * (err["forecast"] - err["actual"]) / err["actual"]
    err["abs_pct_error"] = err["pct_error"].abs()
    # MASE: error relative to the seasonal-naive error on the training data (below 1 = beats "same month last year")
    scale = (y - y.shift(12)).abs().loc[:"2022-03-01"].mean()
    err["abs_scaled"] = (err["forecast"] - err["actual"]).abs() / scale
    err["in80"] = (err["actual"] >= err["lo80"]) & (err["actual"] <= err["hi80"])
    s = err.groupby("model").agg(mape=("abs_pct_error", "mean"), mase=("abs_scaled", "mean"),
                                 bias_pct=("pct_error", "mean"), n=("forecast", "size"))
    has_pi = err.dropna(subset=["lo80"]).groupby("model")["in80"].mean() * 100
    s["coverage80_pct"] = has_pi
    return s.round(2).sort_values("mape"), err


def main():
    style()
    y = load()
    err = run(y)
    summary, err = summarize(err, y)
    err.round(3).to_csv(HERE / "results" / "backtest_errors.csv", index=False)
    summary.to_csv(HERE / "results" / "backtest_summary.csv")
    by_h = err.pivot_table(index="h", columns="model", values="abs_pct_error", aggfunc="mean").round(2)
    by_h.to_csv(HERE / "results" / "backtest_by_horizon.csv")

    fig, ax = plt.subplots(figsize=(11, 3.8))
    best = summary.index[0]
    names = list(summary.index)[::-1]
    bars = ax.barh(names, summary.loc[names, "mape"], height=0.5, color=[SERIES if n == best else CONTEXT for n in names])
    for b, v in zip(bars, summary.loc[names, "mape"]):
        ax.text(v + 0.05, b.get_y() + b.get_height() / 2, f"{v:.2f}%", va="center", color=INK, fontsize=11)
    ax.set_title(f"Average forecast error, 12 months ahead (MAPE, {len(origins(y))} starting points, 2022-2025)")
    ax.grid(axis="x"); ax.grid(axis="y", visible=False); ax.set_xlim(0, summary["mape"].max() * 1.2)
    fig.tight_layout(); fig.savefig(HERE / "charts" / "04_backtest.png", dpi=160); plt.close(fig)
    print(summary.to_string())
    print("\nMAPE by months ahead:\n", by_h.to_string())


if __name__ == "__main__":
    main()
