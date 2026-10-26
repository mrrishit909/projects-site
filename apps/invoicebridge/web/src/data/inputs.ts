// Assembles the pipeline inputs from the published entity files (manifest.json + <entity>.json, rows under "rows").
import type { PipelineInputs, Row } from "../domain/types";

export interface Manifest {
  dataset_version: string; dataset_hash: string; generated_at: string; as_of: string; contract_version: string; snapshot_cutoffs: string[];
  tolerances: Row; row_counts: Record<string, number>;
  designed_relationships?: { id: string; name: string; statement: string; realised: Record<string, string | number> }[];
  generator?: { name: string; seed: number; parameters?: Record<string, unknown> };
  window_start?: string; window_end?: string; code_sha?: string;
}
export const INPUT_ENTITIES = ["vendors", "purchase_orders", "po_lines", "receipts", "invoices", "invoice_lines", "credit_notes", "approval_policies", "approvals", "export_requests"] as const;
export const EXTRA_ENTITIES = ["exceptions", "exception_assignments", "export_batches"] as const;
export const ALL_FILES: readonly string[] = [...INPUT_ENTITIES, ...EXTRA_ENTITIES];

export function isManifest(m: unknown): m is Manifest {
  const x = m as Partial<Manifest> | null;
  return !!x && typeof x.dataset_version === "string" && typeof x.dataset_hash === "string" && typeof x.generated_at === "string" && typeof x.as_of === "string"
    && Array.isArray(x.snapshot_cutoffs) && typeof x.row_counts === "object" && x.row_counts !== null && typeof x.tolerances === "object";
}
const rowsOf = (files: ReadonlyMap<string, unknown>, name: string): Row[] => {
  const f = files.get(name) as { rows?: Row[] } | undefined;
  if (!f || !Array.isArray(f.rows)) throw new Error(`${name}.json: no rows array`);
  return f.rows;
};
export function buildInputs(manifest: Manifest, files: ReadonlyMap<string, unknown>): PipelineInputs {
  const inputs: PipelineInputs = { contract_version: 1, as_of: manifest.as_of, snapshot_cutoffs: manifest.snapshot_cutoffs, tolerances: manifest.tolerances };
  for (const e of INPUT_ENTITIES) inputs[e] = rowsOf(files, e);
  inputs.exceptions = rowsOf(files, "exceptions");
  inputs.exception_assignments = rowsOf(files, "exception_assignments");
  return inputs;
}
