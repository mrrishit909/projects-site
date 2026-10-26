// Duplicate detection and merge (duplicates.py): same source bytes first, then identity. The CANONICAL copy is the first in
// processing order: committed invoices first (an invoice with a valid approval cannot be displaced by a later import, D-09),
// by their commit instant, then the others by (imported_at, invoice_id). A byte-twin whose extracted fields differ from the
// canonical's is held for review (BYTES_FIELDS_CONFLICT) and seeds neither map.
import { DUPLICATE_IDENTITY, DUPLICATE_SOURCE_BYTES } from "./contract";
import { identityKey } from "./amounts";
import { cmp } from "./order";
import type { Invoice } from "./types";

export const groupKeyFor = (reason: string, inv: Invoice): string => (reason === DUPLICATE_IDENTITY ? identityKey(inv) : `sha256:${inv.source_sha256}`);
export interface MergedRecord { entity: "invoices"; id: string; status: "merged"; reason_code: string; merged_into: string; group_key: string; source_sha256: string }
/** One step of the import, in processing order: what the desk decided for this file. */
export interface ImportEvent { seq: number; invoice_id: string; imported_at: number; verdict: "new" | "merged" | "review"; reason: string | null; canonical: string; identity: string }
/** The commit instant of a committed invoice: (decided_at, approval_id). */
export type Commit = readonly [number, string];

export const byImport = (a: Invoice, b: Invoice): number => a.imported_at - b.imported_at || cmp(a.invoice_id, b.invoice_id);

/** The import sequence the desk performs; ``detectDuplicates`` is derived from it, so the simulation cannot drift from the rule. */
export function importSequence(invoices: readonly Invoice[], committed: ReadonlyMap<string, Commit> = new Map()): ImportEvent[] {
  const byId = new Map(invoices.map((i) => [i.invoice_id, i]));
  const byKey = new Map<string, string>(), bySha = new Map<string, string>();
  const out: ImportEvent[] = [];
  const order = [...invoices].sort((a, b) => {
    const ca = committed.get(a.invoice_id), cb = committed.get(b.invoice_id);
    if (ca && cb) return ca[0] - cb[0] || cmp(ca[1], cb[1]);
    if (ca) return -1;
    if (cb) return 1;
    return byImport(a, b);
  });
  for (const inv of order) {
    const key = identityKey(inv);
    let canon = bySha.get(inv.source_sha256);
    let reason: string | null = DUPLICATE_SOURCE_BYTES;
    if (canon !== undefined && identityKey(byId.get(canon)!) !== key) {       // same bytes, other fields: a human decides
      out.push({ seq: out.length + 1, invoice_id: inv.invoice_id, imported_at: inv.imported_at, verdict: "review", reason: "BYTES_FIELDS_CONFLICT", canonical: canon, identity: key });
      continue;
    }
    if (canon === undefined) { canon = byKey.get(key); reason = DUPLICATE_IDENTITY; }
    let verdict: "new" | "merged" = "merged";
    if (canon === undefined) { canon = inv.invoice_id; verdict = "new"; reason = null; }
    if (!byKey.has(key)) byKey.set(key, canon);
    if (!bySha.has(inv.source_sha256)) bySha.set(inv.source_sha256, canon);
    out.push({ seq: out.length + 1, invoice_id: inv.invoice_id, imported_at: inv.imported_at, verdict, reason, canonical: canon, identity: key });
  }
  return out;
}

export function detectDuplicates(invoices: readonly Invoice[], committed: ReadonlyMap<string, Commit> = new Map()): { mergedInto: Map<string, string>; records: MergedRecord[]; groups: number; review: Map<string, string> } {
  const byId = new Map(invoices.map((i) => [i.invoice_id, i]));
  const mergedInto = new Map<string, string>();
  const review = new Map<string, string>();
  const records: MergedRecord[] = [];
  for (const e of importSequence(invoices, committed)) {
    if (e.verdict === "review") { review.set(e.invoice_id, e.canonical); continue; }
    if (e.verdict !== "merged") continue;
    const inv = byId.get(e.invoice_id)!;
    mergedInto.set(e.invoice_id, e.canonical);
    records.push({ entity: "invoices", id: e.invoice_id, status: "merged", reason_code: e.reason!, merged_into: e.canonical, group_key: groupKeyFor(e.reason!, inv), source_sha256: inv.source_sha256 });
  }
  records.sort((a, b) => cmp(a.id, b.id));
  return { mergedInto, records, groups: new Set(mergedInto.values()).size, review };
}
