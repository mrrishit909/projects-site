// Mirrors domain/revenue_atlas/ingest.py (D-06 C01). Pure: same input gives an equal result.
import { ACCEPTED_INPUT_CONTRACTS, CONTRACT_VERSION, CURRENCY_RE, KNOWN_CURRENCIES } from "./contract";
import * as D from "./decimal";
import {
  CONTRACT_MISMATCH, CREDIT_SIGN_REVERSED, CURRENCY_NOT_ISO4217, DomainError, MALFORMED_RECORD, ORPHAN_REFERENCE,
  SHIPMENT_LINE_ORDER_MISMATCH, SHIPPED_EXCEEDS_ORDERED, cmpStr,
} from "./errors";
import {
  ENTITIES, type Accepted, type EntityCounts, type EntityName, type PipelineInputs, type RejectedRecord,
} from "./types";

type Row = Record<string, unknown>;

/** Currency must match the three-letter pattern AND the configured list. */
export function currencyOk(code: unknown): boolean {
  return typeof code === "string" && CURRENCY_RE.test(code) && KNOWN_CURRENCIES.has(code);
}

const TS_RE = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})$/;
const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** Timestamp with an explicit zone -> UTC epoch milliseconds. */
export function parseTimestamp(v: unknown): number {
  if (typeof v !== "string" || !TS_RE.test(v)) throw new Error("timestamp with timezone required");
  const ms = Date.parse(v.replace(" ", "T"));
  if (Number.isNaN(ms)) throw new Error("invalid timestamp");
  return ms;
}

/** Calendar date YYYY-MM-DD (validated), returned unchanged. */
export function parseDate(v: unknown): string {
  const m = typeof v === "string" ? DATE_RE.exec(v) : null;
  if (!m) throw new Error("date must be YYYY-MM-DD");
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const t = new Date(Date.UTC(y, mo - 1, d));
  if (t.getUTCFullYear() !== y || t.getUTCMonth() !== mo - 1 || t.getUTCDate() !== d) throw new Error("invalid date");
  return v as string;
}

/** UTC calendar date of an epoch-ms instant. */
export const utcDate = (ms: number): string => new Date(ms).toISOString().slice(0, 10);

const int = (v: unknown, min: number): number => {
  if (typeof v !== "number" || !Number.isInteger(v) || v < min) throw new Error(`integer >= ${min} required`);
  return v;
};
const str = (v: unknown): string => {
  if (typeof v !== "string" || v === "") throw new Error("non-empty string required");
  return v;
};
const money = (v: unknown): D.Dec => D.parse(v as string); // throws on non-strings and non-decimals
const req = (r: Row, k: string): unknown => {
  if (!(k in r)) throw new Error(`missing ${k}`);
  return r[k];
};
const optStr = (r: Row, k: string): string | null => (r[k] === undefined || r[k] === null ? null : (r[k] as string));

const PARSERS: Record<EntityName, (r: Row) => unknown> = {
  customers: (r) => ({ customer_id: str(r.customer_id), customer_name: req(r, "customer_name"), region_id: req(r, "region_id"), segment: req(r, "segment"), effective_from: parseDate(r.effective_from) }),
  products: (r) => ({ product_id: str(r.product_id), sku: req(r, "sku"), category_id: req(r, "category_id"), unit_of_measure: req(r, "unit_of_measure"), active: Boolean(req(r, "active")) }),
  orders: (r) => ({ order_id: str(r.order_id), customer_id: str(r.customer_id), order_date: parseDate(r.order_date), currency: req(r, "currency"), status: str(r.status) }),
  order_lines: (r) => ({ line_id: str(r.line_id), order_id: str(r.order_id), product_id: str(r.product_id), quantity: int(r.quantity, 1), unit_price: money(r.unit_price) }),
  discounts: (r) => ({ discount_id: str(r.discount_id), line_id: str(r.line_id), discount_amount: money(r.discount_amount), reason_code: req(r, "reason_code"), approved_by: req(r, "approved_by") }),
  shipments: (r) => ({ shipment_id: str(r.shipment_id), order_id: str(r.order_id), shipped_at: parseTimestamp(r.shipped_at), shipping_cost: money(r.shipping_cost), currency: req(r, "currency") }),
  shipment_lines: (r) => ({ shipment_line_id: str(r.shipment_line_id), shipment_id: str(r.shipment_id), line_id: str(r.line_id), shipped_quantity: int(r.shipped_quantity, 0), cost_version_id: optStr(r, "cost_version_id") }),
  returns: (r) => ({ return_id: str(r.return_id), shipment_line_id: str(r.shipment_line_id), returned_quantity: int(r.returned_quantity, 1), credit_amount: money(r.credit_amount), credit_date: parseDate(r.credit_date) }),
  cost_versions: (r) => ({ cost_version_id: str(r.cost_version_id), product_id: str(r.product_id), unit_cost: money(r.unit_cost), valid_from: parseDate(r.valid_from), valid_to: r.valid_to === undefined || r.valid_to === null ? null : parseDate(r.valid_to) }),
  exchange_rates: (r) => ({ rate_id: str(r.rate_id), currency: req(r, "currency"), reporting_currency: req(r, "reporting_currency"), rate_date: parseDate(r.rate_date), rate: money(r.rate) }),
};

const ID_FIELD: Record<EntityName, string> = {
  customers: "customer_id", products: "product_id", orders: "order_id", order_lines: "line_id",
  discounts: "discount_id", shipments: "shipment_id", shipment_lines: "shipment_line_id",
  returns: "return_id", cost_versions: "cost_version_id", exchange_rates: "rate_id",
};
const sortFields = (e: EntityName): string[] => (e === "customers" ? ["customer_id", "effective_from"] : [ID_FIELD[e]]);

export interface IngestResult {
  accepted: Accepted;
  rejected: RejectedRecord[];
  counts: Record<EntityName, EntityCounts>;
  /** Original raw rows by entity then id, kept so quarantine can preserve them. */
  raw: Record<EntityName, Map<string, Row>>;
}

/**
 * Validate and parse a raw batch (D-06 C01). A bad order currency rejects the order and every
 * dependent (lines, discounts, shipments, shipment lines, returns) with CURRENCY_NOT_ISO4217; a bad
 * shipment currency rejects the shipment and its lines and returns. Raw rows are kept.
 * D-08: an order line whose shipment lines ship more than the ordered quantity is rejected with
 * SHIPPED_EXCEEDS_ORDERED together with its discounts, shipment lines and their returns; a shipment line
 * whose order line belongs to another order than its shipment is rejected with SHIPMENT_LINE_ORDER_MISMATCH
 * (and its returns); a return whose credit_amount is "-0.00" is rejected with CREDIT_SIGN_REVERSED.
 */
export function validateBatch(raw: PipelineInputs): IngestResult {
  if (!ACCEPTED_INPUT_CONTRACTS.has(raw.contract ?? CONTRACT_VERSION)) {
    throw new DomainError(CONTRACT_MISMATCH, `expected contract ${CONTRACT_VERSION}`, { got: raw.contract });
  }
  const parsed = {} as Record<EntityName, Array<{ row: Row; rec: any }>>;
  const rejected = new Map<string, RejectedRecord>();
  const reject = (entity: EntityName, row: Row, code: string): void => {
    const id = row[ID_FIELD[entity]] === undefined ? "" : String(row[ID_FIELD[entity]]);
    const key = `${entity}\u0000${id}`;
    if (!rejected.has(key)) rejected.set(key, { entity, id, reason_code: code, raw_row: structuredClone(row) });
  };

  for (const ent of ENTITIES) {
    parsed[ent] = [];
    for (const row of (raw[ent] ?? []) as unknown as Row[]) {
      try {
        parsed[ent].push({ row, rec: PARSERS[ent](row) });
      } catch {
        reject(ent, row, MALFORMED_RECORD);
      }
    }
  }

  const badOrders = new Set<string>();
  for (const { row, rec } of parsed.orders) {
    if (!currencyOk(rec.currency)) {
      badOrders.add(rec.order_id);
      reject("orders", row, CURRENCY_NOT_ISO4217);
    }
  }
  const orderIds = new Set(parsed.orders.map((x) => x.rec.order_id as string));

  const badShipments = new Set<string>();
  for (const { row, rec } of parsed.shipments) {
    if (badOrders.has(rec.order_id) || !currencyOk(rec.currency)) {
      badShipments.add(rec.shipment_id);
      reject("shipments", row, CURRENCY_NOT_ISO4217);
    } else if (!orderIds.has(rec.order_id)) reject("shipments", row, ORPHAN_REFERENCE);
  }
  const shipIds = new Set(parsed.shipments.map((x) => x.rec.shipment_id as string));

  // D-08 (R-06, R-01): shipment lines whose order line belongs to another order, and order lines whose
  // (otherwise valid) shipment lines ship more than the ordered quantity.
  const shipOrder = new Map<string, string>(parsed.shipments.map((x) => [x.rec.shipment_id as string, x.rec.order_id as string]));
  const lineOrder = new Map<string, string>(parsed.order_lines.map((x) => [x.rec.line_id as string, x.rec.order_id as string]));
  const lineQty = new Map<string, number>(parsed.order_lines.map((x) => [x.rec.line_id as string, x.rec.quantity as number]));
  const currencyBadLines = new Set<string>(parsed.order_lines.filter((x) => badOrders.has(x.rec.order_id)).map((x) => x.rec.line_id as string));
  const mismatched = new Set<string>();
  const shippedByLine = new Map<string, number>();
  for (const { rec } of parsed.shipment_lines) {
    if (badShipments.has(rec.shipment_id) || currencyBadLines.has(rec.line_id)) continue;
    if (!shipOrder.has(rec.shipment_id) || !lineOrder.has(rec.line_id)) continue; // orphan, reported below
    if (lineOrder.get(rec.line_id) !== shipOrder.get(rec.shipment_id)) {
      mismatched.add(rec.shipment_line_id);
      continue;
    }
    shippedByLine.set(rec.line_id, (shippedByLine.get(rec.line_id) ?? 0) + (rec.shipped_quantity as number));
  }
  const overLines = new Set<string>();
  for (const [k, total] of shippedByLine) if (total > lineQty.get(k)!) overLines.add(k);

  const badLines = new Set<string>();
  for (const { row, rec } of parsed.order_lines) {
    if (badOrders.has(rec.order_id)) {
      badLines.add(rec.line_id);
      reject("order_lines", row, CURRENCY_NOT_ISO4217);
    } else if (!orderIds.has(rec.order_id)) reject("order_lines", row, ORPHAN_REFERENCE);
    else if (overLines.has(rec.line_id)) reject("order_lines", row, SHIPPED_EXCEEDS_ORDERED);
  }
  const lineIds = new Set(parsed.order_lines.map((x) => x.rec.line_id as string));

  for (const { row, rec } of parsed.discounts) {
    if (badLines.has(rec.line_id)) reject("discounts", row, CURRENCY_NOT_ISO4217);
    else if (!lineIds.has(rec.line_id)) reject("discounts", row, ORPHAN_REFERENCE);
    else if (overLines.has(rec.line_id)) reject("discounts", row, SHIPPED_EXCEEDS_ORDERED);
  }

  const badSls = new Map<string, string>(); // shipment_line_id -> reason code its returns inherit
  for (const { row, rec } of parsed.shipment_lines) {
    if (badShipments.has(rec.shipment_id) || badLines.has(rec.line_id)) {
      badSls.set(rec.shipment_line_id, CURRENCY_NOT_ISO4217);
      reject("shipment_lines", row, CURRENCY_NOT_ISO4217);
    } else if (!shipIds.has(rec.shipment_id) || !lineIds.has(rec.line_id)) reject("shipment_lines", row, ORPHAN_REFERENCE);
    else if (mismatched.has(rec.shipment_line_id)) {
      badSls.set(rec.shipment_line_id, SHIPMENT_LINE_ORDER_MISMATCH);
      reject("shipment_lines", row, SHIPMENT_LINE_ORDER_MISMATCH);
    } else if (overLines.has(rec.line_id)) {
      badSls.set(rec.shipment_line_id, SHIPPED_EXCEEDS_ORDERED);
      reject("shipment_lines", row, SHIPPED_EXCEEDS_ORDERED);
    }
  }
  const slIds = new Set(parsed.shipment_lines.map((x) => x.rec.shipment_line_id as string));

  for (const { row, rec } of parsed.returns) {
    if (badSls.has(rec.shipment_line_id)) reject("returns", row, badSls.get(rec.shipment_line_id)!);
    else if (!slIds.has(rec.shipment_line_id)) reject("returns", row, ORPHAN_REFERENCE);
    else if (D.isZero(rec.credit_amount) && /^\s*-/.test(row.credit_amount as string)) reject("returns", row, CREDIT_SIGN_REVERSED); // "-0.00" (D-08)
  }

  const accepted = {} as Record<EntityName, unknown[]>;
  const counts = {} as Record<EntityName, EntityCounts>;
  const rawById = {} as Record<EntityName, Map<string, Row>>;
  for (const ent of ENTITIES) {
    const idf = ID_FIELD[ent];
    const byId = new Map<string, Row>();
    const keep = parsed[ent].filter(({ row }) => {
      byId.set(String(row[idf]), row);
      return !rejected.has(`${ent}\u0000${String(row[idf])}`);
    });
    const fields = sortFields(ent);
    keep.sort((a, b) => {
      for (const f of fields) {
        const c = cmpStr(String(a.rec[f]), String(b.rec[f]));
        if (c !== 0) return c;
      }
      return 0;
    });
    accepted[ent] = keep.map((k) => k.rec);
    let nrej = 0;
    for (const r of rejected.values()) if (r.entity === ent) nrej++;
    counts[ent] = { accepted: keep.length, rejected: nrej, quarantined: 0 };
    rawById[ent] = byId;
  }
  const rejList = [...rejected.values()].sort((a, b) => cmpStr(a.entity, b.entity) || cmpStr(a.id, b.id));
  return { accepted: accepted as unknown as Accepted, rejected: rejList, counts, raw: rawById };
}
