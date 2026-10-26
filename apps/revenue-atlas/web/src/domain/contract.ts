// Contract constants (docs/contracts.md, version v1); mirrors domain/revenue_atlas/contract.py.
export const CONTRACT_VERSION = "v1";
export const REPORTING_CURRENCY = "USD";
export const CURRENCY_RE = /^[A-Z]{3}$/;
export const KNOWN_CURRENCIES: ReadonlySet<string> = new Set(["USD", "EUR", "GBP", "CAD", "MXN", "JPY"]);
export const ELIGIBLE_ORDER_STATUSES: ReadonlySet<string> = new Set(["shipped", "partially_returned"]);
export const UNASSIGNED_REGION = "UNASSIGNED";
