// Duplicate detection and merge (duplicates.py): same source bytes first, then identity; the earliest import is canonical.
import { DUPLICATE_IDENTITY, DUPLICATE_SOURCE_BYTES } from "./contract";
import { identityKey } from "./amounts";
import type { Invoice } from "./types";

export const groupKeyFor = (reason: string, inv: Invoice): string => (reason === DUPLICATE_IDENTITY ? identityKey(inv) : `sha256:${inv.source_sha256}`);
export interface MergedRecord { entity: "invoices"; id: string; status: "merged"; reason_code: string; merged_into: string; group_key: string; source_sha256: string }
/** One step of the import, in (imported_at, invoice_id) order: what the desk decided for this file. */
export interface ImportEvent { seq: number; invoice_id: string; imported_at: number; verdict: "new" | "merged"; reason: string | null; canonical: string; identity: string }

export const byImport = (a: Invoice, b: Invoice): number => a.imported_at - b.imported_at || (a.invoice_id < b.invoice_id ? -1 : a.invoice_id > b.invoice_id ? 1 : 0);

/** The import sequence the desk performs; ``detectDuplicates`` is derived from it, so the simulation cannot drift from the rule. */
export function importSequence(invoices: readonly Invoice[]): ImportEvent[] {
  const byKey = new Map<string, string>(), bySha = new Map<string, string>();
  const out: ImportEvent[] = [];
  for (const inv of [...invoices].sort(byImport)) {
    const key = identityKey(inv);
    let canon = bySha.get(inv.source_sha256);
    let reason: string | null = DUPLICATE_SOURCE_BYTES;
    if (canon === undefined) { canon = byKey.get(key); reason = DUPLICATE_IDENTITY; }
    let verdict: "new" | "merged" = "merged";
    if (canon === undefined) { canon = inv.invoice_id; verdict = "new"; reason = null; }
    if (!byKey.has(key)) byKey.set(key, canon);
    if (!bySha.has(inv.source_sha256)) bySha.set(inv.source_sha256, canon);
    out.push({ seq: out.length + 1, invoice_id: inv.invoice_id, imported_at: inv.imported_at, verdict, reason, canonical: canon, identity: key });
  }
  return out;
}

export function detectDuplicates(invoices: readonly Invoice[]): { mergedInto: Map<string, string>; records: MergedRecord[]; groups: number } {
  const byId = new Map(invoices.map((i) => [i.invoice_id, i]));
  const mergedInto = new Map<string, string>();
  const records: MergedRecord[] = [];
  for (const e of importSequence(invoices)) {
    if (e.verdict !== "merged") continue;
    const inv = byId.get(e.invoice_id)!;
    mergedInto.set(e.invoice_id, e.canonical);
    records.push({ entity: "invoices", id: e.invoice_id, status: "merged", reason_code: e.reason!, merged_into: e.canonical, group_key: groupKeyFor(e.reason!, inv), source_sha256: inv.source_sha256 });
  }
  records.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  return { mergedInto, records, groups: new Set(mergedInto.values()).size };
}
