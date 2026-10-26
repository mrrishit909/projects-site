// Quick picks for the invoice desk, found in the derived data (never hard-coded ids for the snapshot).
import { cmp } from "../domain/order";
import type { PipelineResult } from "../domain/pipeline";

export interface Pick { label: string; id: string }
export function picks(r: PipelineResult): Pick[] {
  const b = r.book;
  const out: Pick[] = [];
  const add = (label: string, id: string | undefined): void => { if (id && !out.some((p) => p.id === id)) out.push({ label, id }); };
  const sorted = (xs: Iterable<string>): string[] => [...xs].sort(cmp);
  add("a merged duplicate", b.mergedRecords[0]?.id);
  add("its canonical copy", b.mergedRecords[0]?.merged_into);
  add("an adjusted (credited) invoice", sorted(b.status.keys()).find((i) => b.status.get(i) === "adjusted"));
  add("a rejected invoice", sorted(b.rejected)[0]);
  const withOwner = b.exceptions.find((e) => e.owner_id !== null);
  add("an assigned exception", withOwner?.invoice_id);
  add("a QUANTITY_BLOCKED invoice", b.exceptions.find((e) => e.exception_type === "QUANTITY_BLOCKED")?.invoice_id);
  add("a PRICE_VARIANCE invoice", b.exceptions.find((e) => e.exception_type === "PRICE_VARIANCE")?.invoice_id);
  add("a CURRENCY_MISMATCH invoice", b.exceptions.find((e) => e.exception_type === "CURRENCY_MISMATCH")?.invoice_id);
  add("a matched invoice awaiting approval", sorted(b.status.keys()).find((i) => b.status.get(i) === "matched"));
  return out;
}
/** The invoice shown when none is chosen: the canonical copy of the first merge (it has a merge, an approval trail and an export), else the first invoice. */
export function defaultInvoice(r: PipelineResult, golden: boolean): string[] {
  if (golden && r.book.invoices.has("inv-001")) return r.book.invoices.has("inv-002") ? ["inv-001", "inv-002"] : ["inv-001"];
  const canon = r.book.mergedRecords[0]?.merged_into;
  return [canon ?? [...r.book.invoices.keys()].sort(cmp)[0] ?? ""].filter(Boolean);
}
