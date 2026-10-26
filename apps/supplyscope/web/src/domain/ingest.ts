// Batch validation (D-01, D-04, D-06). Pure: the same input gives an equal result. Raw rows of rejected records are kept.
// Reasons: MALFORMED_RECORD, DUPLICATE_ID (any entity), DUPLICATE_MOVEMENT_ID (an exact replay of a movement id: the first
// occurrence is kept), DUPLICATE_MOVEMENT_CONFLICT (the same id with different payloads: EVERY occurrence is rejected),
// UNKNOWN_REFERENCE, RECEIPT_BEFORE_ORDER, RECEIPT_EXCEEDS_ORDERED, REPLENISHMENT_PARAMS_INVALID (target below reorder
// point, R3-06). Mirrors domain/supplyscope/{models,ingest}.py, including its parent-before-child ORDER (suppliers first, S-02).
import {
  ACCEPTED_INPUT_CONTRACTS, ENTITIES, EXTRA_ENTITIES, MOVEMENT_TYPES, PO_STATUSES, UNMET_POLICIES, type EntityName,
} from "./contract";
import {
  CONTRACT_MISMATCH, DUPLICATE_ID, DUPLICATE_MOVEMENT_CONFLICT, DUPLICATE_MOVEMENT_ID, DomainError, MALFORMED_RECORD,
  RECEIPT_BEFORE_ORDER, RECEIPT_EXCEEDS_ORDERED, REPLENISHMENT_PARAMS_INVALID, UNKNOWN_REFERENCE,
} from "./errors";
import { parseMoney, parseDec, pow10 } from "./money";
import { paramsValid } from "./replenishment";
import { isoZ, parseDay, parseTs } from "./time";
import type { IngestResult, Movement, PipelineInputs, PoLine, PurchaseOrder, Population, Receipt, RejectedRecord, Row } from "./types";

// ---- scalar parsers (a ValueError in Python is a thrown Error here) -----------------------------------------------
const id = (r: Row, k: string): string => {
  const v = r[k];
  if (typeof v !== "string" || v.trim() === "" || v.length > 128) throw new Error(`${k} must be a non-empty string`);
  return v;
};
const optId = (r: Row, k: string): string | null => (r[k] === null || r[k] === undefined ? null : id(r, k));
const int = (r: Row, k: string, lo: number | null = null, hi = 1e9): number => {
  const v = r[k];
  if (typeof v !== "number" || !Number.isInteger(v) || (lo !== null && v < lo) || v > hi || v < -hi) throw new Error(`${k} must be an integer${lo !== null ? ` >= ${lo}` : ""}`);
  return v;
};
const bool = (r: Row, k: string): boolean => {
  if (typeof r[k] !== "boolean") throw new Error(`${k} must be a boolean`);
  return r[k] as boolean;
};
const ts = (r: Row, k: string): number => parseTs(r[k]);
const optTs = (r: Row, k: string): number | null => (r[k] === null || r[k] === undefined ? null : parseTs(r[k]));
const date = (r: Row, k: string): string => { parseDay(r[k]); return r[k] as string; };
const money = (r: Row, k: string): string => parseMoney(r[k]);
/** A non-negative decimal up to `hi`, from a string or an integer (never a float); kept as the canonical text. */
const ratioText = (r: Row, k: string, hi = 1000): string => {
  const v = r[k];
  if (typeof v !== "string" && !(typeof v === "number" && Number.isInteger(v))) throw new Error(`${k} must be a decimal string`);
  const text = String(v).trim();
  const d = parseDec(text);
  if (d.n < 0n || d.n > BigInt(hi) * pow10(d.s)) throw new Error(`${k} is out of range`);
  return text;
};
const text = (r: Row, k: string): string => {
  const v = r[k];
  if (typeof v !== "string" || v.length > 500) throw new Error(`${k} must be a string`);
  return v;
};

type Parser = (r: Row) => unknown;
const PARSERS: Record<EntityName, Parser> = {
  products: (r) => ({ product_id: id(r, "product_id"), sku: id(r, "sku"), unit_cost: money(r, "unit_cost"), pack_size: int(r, "pack_size", 1), minimum_order_quantity: int(r, "minimum_order_quantity", 0), abc_class: optId(r, "abc_class"), supplier_id: optId(r, "supplier_id") }),
  locations: (r) => ({ location_id: id(r, "location_id"), location_name: text(r, "location_name"), timezone: text(r, "timezone"), storage_capacity: int(r, "storage_capacity", 0), active: bool(r, "active") }),
  suppliers: (r) => ({ supplier_id: id(r, "supplier_id"), supplier_name: text(r, "supplier_name"), calendar_id: id(r, "calendar_id"), quoted_lead_days: int(r, "quoted_lead_days", 0, 3650), active: bool(r, "active") }),
  sales: (r) => ({ sale_id: id(r, "sale_id"), product_id: id(r, "product_id"), location_id: id(r, "location_id"), sold_at: ts(r, "sold_at"), quantity: int(r, "quantity", 1) }),
  inventory_movements: (r) => {
    const kind = r["movement_type"];
    if (typeof kind !== "string" || !(MOVEMENT_TYPES as readonly string[]).includes(kind)) throw new Error("unknown movement_type");
    const delta = int(r, "quantity_delta");
    if (delta === 0 || ((kind === "receipt" || kind === "return") && delta < 0) || (kind === "sale" && delta > 0)) throw new Error("quantity_delta is zero or has the wrong sign for its movement_type");
    return { movement_id: id(r, "movement_id"), product_id: id(r, "product_id"), location_id: id(r, "location_id"), quantity_delta: delta, event_at: ts(r, "event_at"), movement_type: kind };
  },
  purchase_orders: (r) => {
    if (typeof r["status"] !== "string" || !(PO_STATUSES as readonly string[]).includes(r["status"])) throw new Error("unknown purchase order status");
    return { purchase_order_id: id(r, "purchase_order_id"), supplier_id: id(r, "supplier_id"), ordered_at: ts(r, "ordered_at"), status: r["status"], currency: text(r, "currency") };
  },
  purchase_order_lines: (r) => ({ po_line_id: id(r, "po_line_id"), purchase_order_id: id(r, "purchase_order_id"), product_id: id(r, "product_id"), ordered_quantity: int(r, "ordered_quantity", 1), unit_cost: money(r, "unit_cost") }),
  receipts: (r) => ({ receipt_id: id(r, "receipt_id"), po_line_id: id(r, "po_line_id"), location_id: id(r, "location_id"), received_quantity: int(r, "received_quantity", 1), received_at: ts(r, "received_at") }),
  promotions: (r) => {
    const s = ts(r, "starts_at"), e = ts(r, "ends_at");
    if (e < s) throw new Error("a promotion ends before it starts");
    return { promotion_id: id(r, "promotion_id"), product_id: id(r, "product_id"), starts_at: s, ends_at: e, planned_uplift: ratioText(r, "planned_uplift"), announced_at: ts(r, "announced_at"), realised_uplift: r["realised_uplift"] === null || r["realised_uplift"] === undefined ? null : ratioText(r, "realised_uplift"), location_id: optId(r, "location_id") };
  },
  forecast_runs: (r) => ({ forecast_run_id: id(r, "forecast_run_id"), product_id: id(r, "product_id"), location_id: id(r, "location_id"), cutoff: ts(r, "cutoff"), horizon_days: int(r, "horizon_days", 1, 366), selected_model: id(r, "selected_model") }),
  forecast_points: (r) => ({ forecast_point_id: id(r, "forecast_point_id"), forecast_run_id: id(r, "forecast_run_id"), model: id(r, "model"), target_date: date(r, "target_date"), forecast_value: ratioText(r, "forecast_value", 1e9) }),
  policy_scenarios: (r) => {
    if (typeof r["unmet_policy"] !== "string" || !(UNMET_POLICIES as readonly string[]).includes(r["unmet_policy"])) throw new Error("unmet_policy is lost_sale or backlog");
    return { scenario_id: id(r, "scenario_id"), scenario_name: text(r, "scenario_name"), service_target: ratioText(r, "service_target"), unmet_policy: r["unmet_policy"], seed: int(r, "seed", 0), warmup_days: int(r, "warmup_days", 0), replications: int(r, "replications", 1, 10000) };
  },
  backorders: (r) => {
    const o = ts(r, "opened_at"), c = optTs(r, "closed_at");
    if (c !== null && c < o) throw new Error("a backorder closes before it opens");
    return { backorder_id: id(r, "backorder_id"), product_id: id(r, "product_id"), location_id: id(r, "location_id"), quantity: int(r, "quantity", 1), opened_at: o, closed_at: c, scenario_id: optId(r, "scenario_id") };
  },
  reservations: (r) => ({ reservation_id: id(r, "reservation_id"), product_id: id(r, "product_id"), location_id: id(r, "location_id"), quantity: int(r, "quantity", 1), reserved_at: ts(r, "reserved_at"), released_at: optTs(r, "released_at") }),
  replenishment_params: (r) => ({ product_id: id(r, "product_id"), location_id: id(r, "location_id"), reorder_point: int(r, "reorder_point", 0), target_position: int(r, "target_position", 0), supplier_id: optId(r, "supplier_id") }),
  cost_versions: (r) => ({ cost_version_id: id(r, "cost_version_id"), product_id: id(r, "product_id"), unit_cost: money(r, "unit_cost"), effective_from: ts(r, "effective_from") }),
  lost_sales: (r) => ({ lost_sale_id: id(r, "lost_sale_id"), product_id: id(r, "product_id"), location_id: id(r, "location_id"), quantity: int(r, "quantity", 1), occurred_at: ts(r, "occurred_at"), scenario_id: optId(r, "scenario_id") }),
  calendar_closures: (r) => {
    const a = date(r, "closed_from"), b = date(r, "closed_to");
    if (b < a) throw new Error("a closure ends before it starts");
    return { closure_id: id(r, "closure_id"), calendar_id: id(r, "calendar_id"), closed_from: a, closed_to: b };
  },
  latent_demand: (r) => ({ product_id: id(r, "product_id"), location_id: id(r, "location_id"), demand_date: date(r, "demand_date"), latent_quantity: int(r, "latent_quantity", 0) }),
};

const ID_FIELD: Record<EntityName, string> = {
  products: "product_id", locations: "location_id", sales: "sale_id", inventory_movements: "movement_id", purchase_orders: "purchase_order_id",
  purchase_order_lines: "po_line_id", receipts: "receipt_id", suppliers: "supplier_id", promotions: "promotion_id", forecast_runs: "forecast_run_id",
  forecast_points: "forecast_point_id", policy_scenarios: "scenario_id", backorders: "backorder_id", reservations: "reservation_id",
  replenishment_params: "product_id", cost_versions: "cost_version_id", lost_sales: "lost_sale_id", calendar_closures: "closure_id", latent_demand: "product_id",
};

/** Parse one raw row; a thrown Error means MALFORMED_RECORD. */
export function parseRow<T = Record<string, unknown>>(entity: EntityName, row: unknown): T {
  if (row === null || typeof row !== "object" || Array.isArray(row)) throw new Error("a record must be an object");
  return PARSERS[entity](row as Row) as T;
}
/** The id to report for a raw row (best effort for malformed rows). */
export function rowId(entity: EntityName, row: unknown): string {
  if (row !== null && typeof row === "object" && !Array.isArray(row)) {
    const v = (row as Row)[ID_FIELD[entity]];
    if (typeof v === "string") return v;
    if (v !== null && v !== undefined) return String(v);
  }
  return "?";
}

/** Parents before children (S-02: suppliers load before products, which may reference one). */
const ORDER: readonly EntityName[] = [
  "suppliers", "locations", "products", "calendar_closures", "policy_scenarios", "cost_versions", "purchase_orders",
  "purchase_order_lines", "receipts", "inventory_movements", "sales", "promotions", "backorders", "reservations",
  "replenishment_params", "lost_sales", "latent_demand", "forecast_runs", "forecast_points",
];
/** entity -> [field, parent entity, optional][] */
const REFS: Partial<Record<EntityName, readonly (readonly [string, EntityName, boolean])[]>> = {
  products: [["supplier_id", "suppliers", true]],
  sales: [["product_id", "products", false], ["location_id", "locations", false]],
  inventory_movements: [["product_id", "products", false], ["location_id", "locations", false]],
  purchase_orders: [["supplier_id", "suppliers", false]],
  purchase_order_lines: [["purchase_order_id", "purchase_orders", false], ["product_id", "products", false]],
  receipts: [["po_line_id", "purchase_order_lines", false], ["location_id", "locations", false]],
  promotions: [["product_id", "products", false], ["location_id", "locations", true]],
  forecast_runs: [["product_id", "products", false], ["location_id", "locations", false]],
  forecast_points: [["forecast_run_id", "forecast_runs", false]],
  backorders: [["product_id", "products", false], ["location_id", "locations", false], ["scenario_id", "policy_scenarios", true]],
  reservations: [["product_id", "products", false], ["location_id", "locations", false]],
  replenishment_params: [["product_id", "products", false], ["location_id", "locations", false], ["supplier_id", "suppliers", true]],
  cost_versions: [["product_id", "products", false]],
  lost_sales: [["product_id", "products", false], ["location_id", "locations", false], ["scenario_id", "policy_scenarios", true]],
  latent_demand: [["product_id", "products", false], ["location_id", "locations", false]],
};

const reject = (entity: EntityName, rid: string, reason: string, raw: unknown, message = ""): RejectedRecord =>
  ({ entity, id: rid, status: "rejected", reason_code: reason, raw_row: raw, message });

/** The identity of a movement independent of how its instant was spelled. */
const movementPayload = (m: Movement): string =>
  JSON.stringify([m.movement_id, m.product_id, m.location_id, m.quantity_delta, isoZ(m.event_at), m.movement_type]);

function screenMovements(rows: readonly unknown[], products: ReadonlySet<string>, locations: ReadonlySet<string>) {
  const rejected: RejectedRecord[] = [];
  const parsed: { row: Row; m: Movement }[] = [];
  for (const row of rows) {
    try { parsed.push({ row: row as Row, m: parseRow<Movement>("inventory_movements", row) }); }
    catch (e) { rejected.push(reject("inventory_movements", rowId("inventory_movements", row), MALFORMED_RECORD, row, (e as Error).message)); }
  }
  const payloads = new Map<string, Set<string>>();
  for (const { m } of parsed) {
    const s = payloads.get(m.movement_id) ?? new Set<string>();
    s.add(movementPayload(m));
    payloads.set(m.movement_id, s);
  }
  const seen = new Set<string>();
  const accepted: { row: Row; obj: Movement }[] = [];
  for (const { row, m } of parsed) {
    if (payloads.get(m.movement_id)!.size > 1) rejected.push(reject("inventory_movements", m.movement_id, DUPLICATE_MOVEMENT_CONFLICT, row, "the same movement_id carries different payloads"));
    else if (seen.has(m.movement_id)) rejected.push(reject("inventory_movements", m.movement_id, DUPLICATE_MOVEMENT_ID, row, "an exact replay of a movement already loaded"));
    else if (!products.has(m.product_id) || !locations.has(m.location_id)) rejected.push(reject("inventory_movements", m.movement_id, UNKNOWN_REFERENCE, row, "unknown product or location"));
    else accepted.push({ row, obj: m });
    seen.add(m.movement_id);
  }
  return { accepted, rejected };
}

/** RECEIPT_BEFORE_ORDER if received before the order date; RECEIPT_EXCEEDS_ORDERED if it would over-receive the line. */
export function receiptReason(receipt: Receipt, line: PoLine, order: PurchaseOrder, receivedBefore: number): string | null {
  if (receipt.received_at < order.ordered_at) return RECEIPT_BEFORE_ORDER;
  if (receivedBefore + receipt.received_quantity > line.ordered_quantity) return RECEIPT_EXCEEDS_ORDERED;
  return null;
}

export function checkContract(inputs: PipelineInputs): void {
  const v = inputs.contract_version ?? 1;
  if (!ACCEPTED_INPUT_CONTRACTS.includes(v)) throw new DomainError(CONTRACT_MISMATCH, `contract_version ${JSON.stringify(v)} is not supported`, "contract_version");
}

const cmp = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);

export function validateBatch(inputs: PipelineInputs): IngestResult {
  checkContract(inputs);
  const res: IngestResult = { accepted: {}, acceptedRows: {}, rejected: [], counts: {}, extraCounts: {} };
  const ids = Object.fromEntries(ORDER.map((e) => [e, new Set<string>()])) as Record<EntityName, Set<string>>;
  const objects = Object.fromEntries(ORDER.map((e) => [e, new Map<string, unknown>()])) as Record<EntityName, Map<string, unknown>>;
  for (const ent of ORDER) {
    const raw = inputs[ent] ?? [];
    if (!Array.isArray(raw)) throw new DomainError(MALFORMED_RECORD, `${ent} must be a list`, ent);
    let accepted: { row: Row; obj: unknown }[];
    if (ent === "inventory_movements") {
      const s = screenMovements(raw, ids.products, ids.locations);
      res.rejected.push(...s.rejected);
      accepted = s.accepted;
    } else {
      const seen = new Set<string>();
      const received = new Map<string, number>();
      let pending: [number, Row][] = raw.map((row, i) => [i, row as Row]);
      if (ent === "receipts") { // cumulative quantity is judged in time order, output stays in input order
        const keyed = pending.map(([i, row]) => {
          let at: number | null = null;
          try { at = parseRow<Receipt>("receipts", row).received_at; } catch { at = null; }
          return { at, rid: at === null ? "None" : String((row as Row)["receipt_id"]), i, row };
        });
        keyed.sort((a, b) => (a.at === null ? 1 : 0) - (b.at === null ? 1 : 0) || (a.at !== null && b.at !== null ? a.at - b.at : 0) || cmp(a.rid, b.rid) || a.i - b.i);
        pending = keyed.map((k) => [k.i, k.row]);
      }
      const keep: { i: number; row: Row; obj: unknown }[] = [];
      for (const [i, row] of pending) {
        let obj: Record<string, unknown>;
        try { obj = parseRow(ent, row); }
        catch (e) { res.rejected.push(reject(ent, rowId(ent, row), MALFORMED_RECORD, row, (e as Error).message)); continue; }
        const rid = rowId(ent, row);
        if (ent === "replenishment_params" && !paramsValid(obj["reorder_point"] as number, obj["target_position"] as number)) {
          res.rejected.push(reject(ent, rid, REPLENISHMENT_PARAMS_INVALID, row, "target_position must be at least reorder_point"));
          continue;
        }
        const key = ent === "replenishment_params" ? `${obj["product_id"]}:${obj["location_id"]}`
          : ent === "latent_demand" ? `${obj["product_id"]}:${obj["location_id"]}:${row["demand_date"]}` : rid;
        if (seen.has(key)) { res.rejected.push(reject(ent, rid, DUPLICATE_ID, row, "duplicate id; the first kept")); continue; }
        seen.add(key);
        const missing = (REFS[ent] ?? []).filter(([f, parent, optional]) => (obj[f] !== null || !optional) && !ids[parent].has(obj[f] as string)).map(([f]) => f);
        if (missing.length) { res.rejected.push(reject(ent, rid, UNKNOWN_REFERENCE, row, `unknown reference: ${missing.join(", ")}`)); continue; }
        if (ent === "receipts") {
          const rcpt = obj as unknown as Receipt;
          const line = objects.purchase_order_lines.get(rcpt.po_line_id) as PoLine;
          const reason = receiptReason(rcpt, line, objects.purchase_orders.get(line.purchase_order_id) as PurchaseOrder, received.get(line.po_line_id) ?? 0);
          if (reason) { res.rejected.push(reject(ent, rid, reason, row, reason)); continue; }
          received.set(line.po_line_id, (received.get(line.po_line_id) ?? 0) + rcpt.received_quantity);
        }
        keep.push({ i, row, obj });
      }
      accepted = keep.sort((a, b) => a.i - b.i);
    }
    for (const { row, obj } of accepted) {
      const rid = rowId(ent, row);
      ids[ent].add(rid);
      objects[ent].set(rid, obj);
    }
    res.accepted[ent] = accepted.map((a) => a.obj);
    res.acceptedRows[ent] = accepted.map((a) => a.row);
  }
  for (const ent of ORDER) {
    const c = { accepted: res.accepted[ent]!.length, rejected: res.rejected.filter((r) => r.entity === ent).length };
    if ((ENTITIES as readonly string[]).includes(ent)) res.counts[ent] = c; else res.extraCounts[ent] = c;
  }
  res.counts = Object.fromEntries(ENTITIES.map((e) => [e, res.counts[e]!]));
  res.rejected.sort((a, b) => cmp(a.entity, b.entity) || cmp(a.id, b.id) || cmp(a.reason_code, b.reason_code));
  return res;
}

/** The accepted rows as a typed population. */
export function populationOf(ing: IngestResult): Population {
  const pop: Record<string, unknown[]> = {};
  for (const ent of [...ENTITIES, ...EXTRA_ENTITIES]) pop[ent] = [...(ing.accepted[ent] ?? [])];
  return pop as unknown as Population;
}
