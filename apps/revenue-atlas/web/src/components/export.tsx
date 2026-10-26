// CSV export (a download, not a mutation). A '#' header block records provenance and the applied filters.
import "../styles/screens.css";
import { UNASSIGNED_REGION } from "../domain/contract";
import type { Manifest, ShipmentLineFact } from "../domain/types";
import { describeFilters } from "./filters";
import { COLUMNS } from "./ledger-table";
import type { Filters, Population } from "../state/filters";

type Lookups = Extract<Population, { status: "ready" }>["lookups"];

/** Spreadsheet formula injection: a cell that starts with = + - @ (or tab/CR) gets a single leading quote. */
export function neutralise(cell: string): string {
  return /^[=+\-@\t\r]/.test(cell) ? `'${cell}` : cell;
}
export function csvCell(raw: string): string {
  const c = neutralise(raw);
  return /[",\n\r]/.test(c) ? `"${c.replace(/"/g, '""')}"` : c;
}
const header = (s: string): string => `# ${s.replace(/[\r\n]+/g, " ")}`;

export function buildCsv(opts: { manifest: Manifest; filters: Filters; facts: readonly ShipmentLineFact[]; lookups: Lookups; scope: "filtered" | "full"; creditRows?: number }): string {
  const { manifest: m, filters, facts, lookups, scope, creditRows = 0 } = opts;
  const lines = [
    header("Revenue Atlas ledger export. Synthetic data."),
    header(`contract_version: ${m.contract_version}`),
    header(`dataset_version: ${m.dataset_version}`),
    header(`dataset_hash: ${m.dataset_hash}`),
    header(`code_sha: ${m.code_sha ?? "not recorded"}`),
    header(`generated_at: ${m.generated_at}`),
    header(`scope: ${scope === "full" ? "full population (filters ignored)" : "current filtered population"}`),
    header(`filters: ${scope === "full" ? "none" : describeFilters(filters)}`),
    header("window: shipment date, UTC, half-open [from, to)"),
    header("currency: USD (reporting currency)"),
    header(`row_count: ${facts.length}`),
    header(scope === "full" ? "credit column: every credit of the line, whatever its credit date" : "credit column: credits dated inside the window only (D-01a, D-09)"),
    header(`credit_rows_outside_window: ${creditRows} (credits dated in the window for lines shipped outside it; see the ledger screen)`),
    COLUMNS.map((c) => csvCell(c.label)).join(","),
  ];
  for (const f of facts) lines.push(COLUMNS.map((c) => csvCell(c.id === "region" ? f.region_id || UNASSIGNED_REGION : c.num ? c.text(f, lookups).replace(/,/g, "") : c.text(f, lookups))).join(","));
  return `${lines.join("\r\n")}\r\n`;
}

function download(name: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function ExportButtons({ pop }: { pop: Extract<Population, { status: "ready" }> }) {
  const m = pop.snapshot.manifest;
  const run = (scope: "filtered" | "full"): void => {
    const facts = scope === "full" ? pop.result.facts : pop.facts;
    download(`revenue-atlas-${scope}-${m.dataset_version}.csv`, buildCsv({ manifest: m, filters: pop.filters, facts, lookups: pop.lookups, scope, creditRows: scope === "full" ? 0 : pop.outside.length }));
  };
  return (
    <div className="actions" role="group" aria-label="Export">
      <button type="button" className="btn btn--primary" onClick={() => run("filtered")} disabled={pop.facts.length === 0} data-testid="export-filtered">
        Export CSV, current filters ({pop.facts.length} lines)
      </button>
      <button type="button" className="btn" onClick={() => run("full")} data-testid="export-full">
        Export full population ({pop.result.facts.length} lines, filters ignored)
      </button>
      <span className="small muted">These buttons download a file to your device; nothing is sent anywhere and nothing is changed.</span>
    </div>
  );
}
