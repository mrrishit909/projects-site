// Contract constants (docs/contracts.md, version v1.1); mirrors domain/revenue_atlas/contract.py.
export const CONTRACT_VERSION = "v1.1";
// Input batches written under v1 have the same shape; v1.1 only changes how windows treat returns (D-01a).
export const ACCEPTED_INPUT_CONTRACTS: ReadonlySet<string> = new Set(["v1", "v1.1"]);
export const REPORTING_CURRENCY = "USD";
export const CURRENCY_RE = /^[A-Z]{3}$/;
export const KNOWN_CURRENCIES: ReadonlySet<string> = new Set(["USD", "EUR", "GBP", "CAD", "MXN", "JPY"]);
export const ELIGIBLE_ORDER_STATUSES: ReadonlySet<string> = new Set(["shipped", "partially_returned"]);
export const UNASSIGNED_REGION = "UNASSIGNED";
