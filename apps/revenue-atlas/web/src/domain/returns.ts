// Mirrors domain/revenue_atlas/returns.py: return validation and credit arithmetic (D-06 C03, D-03).
import * as D from "./decimal";
import { CREDIT_SIGN_REVERSED, DomainError, RETURN_EXCEEDS_REMAINING } from "./errors";
import type { Return, ShipmentLine, ShipmentLineFact } from "./types";

/** Throw unless qty <= shipped - already returned and credit >= 0 (D-06). */
export function validateReturn(
  shipmentLine: ShipmentLine, priorReturns: readonly Return[], returnedQuantity: number, creditAmount: D.Dec,
): void {
  if (D.isNegative(creditAmount)) {
    throw new DomainError(CREDIT_SIGN_REVERSED, "credit_amount must not be negative", { credit_amount: D.toString(creditAmount) });
  }
  const remaining = shipmentLine.shipped_quantity - priorReturns.reduce((a, r) => a + r.returned_quantity, 0);
  if (returnedQuantity > remaining) {
    throw new DomainError(RETURN_EXCEEDS_REMAINING, `returning ${returnedQuantity}, only ${remaining} remaining`, { remaining, requested: returnedQuantity });
  }
}

/** qty * (unit_price - allocated_discount / shipped_quantity), in cents. */
export function expectedCredit(fact: ShipmentLineFact, returnedQuantity: number): D.Dec {
  const perUnitDiscount = D.divToScale(fact.allocated_discount, D.fromInt(fact.shipped_quantity), 12);
  return D.cents(D.mul(D.fromInt(returnedQuantity), D.sub(fact.unit_price, perUnitDiscount)));
}

/** qty * unit cost at the line's own cost version (D-03). */
export function recoverableCost(fact: ShipmentLineFact, returnedQuantity: number): D.Dec {
  return D.mul(D.fromInt(returnedQuantity), fact.unit_cost);
}
