"""Return validation and credit arithmetic (D-06 C03, D-03)."""
from __future__ import annotations

from decimal import Decimal

from .errors import CREDIT_SIGN_REVERSED, RETURN_EXCEEDS_REMAINING, DomainError
from .models import Return, ShipmentLine, ShipmentLineFact
from .money import cents


def validate_return(shipment_line: ShipmentLine, prior_returns: list[Return],
                    returned_quantity: int, credit_amount: Decimal) -> None:
    """Raise unless qty <= shipped - already returned and credit >= 0 (D-06)."""
    if credit_amount < 0 or (credit_amount == 0 and credit_amount.is_signed()):  # "-0.00" too (D-08)
        raise DomainError(CREDIT_SIGN_REVERSED, "credit_amount must not be negative",
                          details={"credit_amount": str(credit_amount)})
    remaining = shipment_line.shipped_quantity - sum(r.returned_quantity for r in prior_returns)
    if returned_quantity > remaining:
        raise DomainError(RETURN_EXCEEDS_REMAINING,
                          f"returning {returned_quantity}, only {remaining} remaining",
                          details={"remaining": remaining, "requested": returned_quantity})


def expected_credit(fact: ShipmentLineFact, returned_quantity: int) -> Decimal:
    """qty * (unit_price - allocated_discount / shipped_quantity), in cents."""
    return cents(returned_quantity
                 * (fact.unit_price - fact.allocated_discount / fact.shipped_quantity))


def recoverable_cost(fact: ShipmentLineFact, returned_quantity: int) -> Decimal:
    """qty * unit cost at the line's own cost version (D-03)."""
    return returned_quantity * fact.unit_cost
