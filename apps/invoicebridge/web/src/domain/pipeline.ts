// End to end (pipeline.py): ingest -> validate -> derive -> metrics (D-01..D-05).
import { invoiceAmounts, validateInvoice } from "./amounts";
import { derive, type Book } from "./book";
import { CONTRACT_VERSION, METRIC_KEYS } from "./contract";
import { populationOf, validateBatch, type IngestResult } from "./ingest";
import { asRow } from "./match";
import { metricsFromBook, type Metrics } from "./metrics";
import { s2 } from "./num";
import { isoZ, parseTs } from "./time";
import type { PipelineInputs, Population, Row } from "./types";

export interface PipelineResult { ingest: IngestResult; population: Population; metrics: Metrics; snapshotCutoffs: string[]; book: Book; asOf: number | null; /** stored exception rows (created_at, status, resolved_at) when read with ``stored`` */ exceptionRows: Row[] }
export interface RunOptions { asOf?: string | null; cutoffs?: string[]; /** read the stored exception ids and assignments (the API's read path) */ stored?: boolean }

/** Mark each invoice valid or invalid with the C02 rules. */
export function validatePopulation(pop: Population): Population {
  const vendors = new Map(pop.vendors.map((v) => [v.vendor_id, v]));
  pop.invoices = pop.invoices.map((i) => ({ ...i, valid: validateInvoice(i, vendors.get(i.vendor_id)).length === 0 }));
  return pop;
}

export function runPipeline(inputs: PipelineInputs, opts: RunOptions = {}): PipelineResult {
  const ing = validateBatch(inputs);
  const stored = opts.stored ? { exceptions: inputs.exceptions ?? [], assignments: inputs.exception_assignments ?? [] } : undefined;
  const pop = validatePopulation(populationOf(ing, stored));
  const asOfText = opts.asOf ?? inputs.as_of ?? null;
  const asOf = asOfText ? parseTs(asOfText) : null;
  const cuts = (opts.cutoffs ?? inputs.snapshot_cutoffs ?? []).map((c) => parseTs(c));
  const book = derive(pop, asOf);
  const metrics = metricsFromBook(pop, book, cuts);
  if (Object.keys(metrics).join() !== METRIC_KEYS.join()) throw new Error("metric keys differ from the contract");
  return { ingest: ing, population: pop, metrics, snapshotCutoffs: cuts.map(isoZ), book, asOf, exceptionRows: opts.stored ? (inputs.exceptions ?? []) : [] };
}

const cmp = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);
/** Per-invoice documents and the match results of the book (the shape of expected.json ``documents``). */
export function documents(r: PipelineResult): { invoices: Record<string, Row>; match_results: Row[] } {
  const { book } = r, run = book.run;
  const docs: Record<string, Row> = {};
  for (const iid of [...book.invoices.keys()].sort(cmp)) {
    const inv = book.invoices.get(iid)!;
    const st = run.invoices.get(iid);
    const [sub, tax, total] = st ? [st.subtotal, st.tax, st.total] : invoiceAmounts(inv);
    const diff = st ? st.rounding_difference : (inv.declared_total - total < 0n ? total - inv.declared_total : inv.declared_total - total);
    const d: Row = { status: book.status.get(iid), subtotal: s2(sub), tax: s2(tax), freight: s2(inv.freight), invoice_discount: s2(inv.invoice_discount), total: s2(total), declared_total: s2(inv.declared_total), rounding_difference: s2(diff), exception_types: st ? [...st.reasons] : [] };
    if (book.mergedInto.has(iid)) d.merged_into = book.mergedInto.get(iid);
    docs[iid] = d;
  }
  return { invoices: docs, match_results: [...run.lines].sort((a, b) => cmp(a.invoice_line_id, b.invoice_line_id)).map(asRow) };
}

/** The shape of expected.json. */
export function goldenOf(r: PipelineResult): Row {
  return {
    contract_version: CONTRACT_VERSION,
    ingest: { counts: r.ingest.counts, rejected_records: r.ingest.rejected, merged_records: r.ingest.merged_records },
    documents: documents(r), metrics: r.metrics,
  };
}
