"""Dated FX lookup (D-02)."""
from __future__ import annotations

from decimal import Decimal

from .contract import REPORTING_CURRENCY
from .errors import FX_RATE_MISSING, DomainError
from .models import ExchangeRate


def rate_for(currency: str, date: str, rates: list[ExchangeRate]) -> Decimal:
    """Rate whose ``rate_date`` equals ``date`` (YYYY-MM-DD).

    Row lookup comes first; USD->USD is 1 without a row. Anything else missing
    raises FX_RATE_MISSING and is never defaulted (D-02).
    """
    for r in rates:
        if (r.currency == currency and r.reporting_currency == REPORTING_CURRENCY
                and r.rate_date == date):
            return r.rate
    if currency == REPORTING_CURRENCY:
        return Decimal("1")
    raise DomainError(FX_RATE_MISSING, f"no {currency}->{REPORTING_CURRENCY} rate on {date}",
                      details={"currency": currency, "date": date})
