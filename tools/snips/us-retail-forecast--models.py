"""The four forecasting methods, all with the same shape: fit on a history, return the next `h` months.

Each returns a DataFrame indexed by month with columns `forecast`, and for the two statistical models
`lo80`, `hi80`, `lo95`, `hi95` (prediction intervals). Series are in $ billions.
"""
import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.exponential_smoothing.ets import ETSModel
from statsmodels.tsa.statespace.sarimax import SARIMAX

warnings.filterwarnings("ignore")      # statsmodels convergence chatter; results are checked by the backtest instead


def _future(y, h):
    return pd.date_range(y.index[-1] + pd.offsets.MonthBegin(), periods=h, freq="MS")


def seasonal_naive(y, h=12):
    """Next July = last July."""
    return pd.DataFrame({"forecast": y.iloc[-12:].values[:h]}, index=_future(y, h))


def naive_growth(y, h=12):
    """Same month last year, times the growth of the last 12 months over the 12 before them."""
    growth = y.iloc[-12:].sum() / y.iloc[-24:-12].sum()
    return pd.DataFrame({"forecast": y.iloc[-12:].values[:h] * growth}, index=_future(y, h))


def ets(y, h=12):
    """Holt-Winters as a state-space model: multiplicative error and seasonality, damped additive trend."""
    np.random.seed(0)          # its intervals come from simulation; a fixed seed makes every run identical
    fit = ETSModel(y, error="mul", trend="add", damped_trend=True, seasonal="mul", seasonal_periods=12).fit(disp=False)
    p = fit.get_prediction(start=len(y), end=len(y) + h - 1)
    f80, f95 = p.summary_frame(alpha=0.20), p.summary_frame(alpha=0.05)
    out = pd.DataFrame({"forecast": f80["mean"].values, "lo80": f80["pi_lower"].values, "hi80": f80["pi_upper"].values,
                        "lo95": f95["pi_lower"].values, "hi95": f95["pi_upper"].values}, index=_future(y, h))
    return out


def sarima(y, h=12):
    """SARIMA(1,1,1)(0,1,1)12 on log sales; intervals come back through exp, so they stay positive and skewed."""
    fit = SARIMAX(np.log(y), order=(1, 1, 1), seasonal_order=(0, 1, 1, 12)).fit(disp=False)
    fc = fit.get_forecast(h)
    ci80, ci95 = fc.conf_int(alpha=0.20), fc.conf_int(alpha=0.05)
    return pd.DataFrame({"forecast": np.exp(fc.predicted_mean.values),
                         "lo80": np.exp(ci80.iloc[:, 0].values), "hi80": np.exp(ci80.iloc[:, 1].values),
                         "lo95": np.exp(ci95.iloc[:, 0].values), "hi95": np.exp(ci95.iloc[:, 1].values)}, index=_future(y, h))


def average(y, h=12):
    """The mean of the ETS and SARIMA forecasts; intervals are the mean of their bounds (an approximation)."""
    return (ets(y, h) + sarima(y, h)) / 2


MODELS = {"Seasonal naive": seasonal_naive, "Last year x growth": naive_growth,
          "Holt-Winters (ETS)": ets, "SARIMA": sarima, "ETS + SARIMA average": average}
