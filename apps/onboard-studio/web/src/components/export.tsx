// CSV export of the visible population: a download, not a mutation. A '#' header block records provenance and the filters.
import "../styles/screens.css";

/** Spreadsheet formula injection: a cell that starts with = + - @ (or tab / CR) gets a single leading quote. */
export function neutralise(cell: string): string {
  return /^[=+\-@\t\r]/.test(cell) ? `'${cell}` : cell;
}
export function csvCell(raw: string): string {
  const c = neutralise(raw);
  return /[",\n\r]/.test(c) ? `"${c.replace(/"/g, '""')}"` : c;
}
const header = (s: string): string => `# ${s.replace(/[\r\n]+/g, " ")}`;

export function buildCsv(headerLines: readonly string[], columns: readonly string[], rows: readonly (readonly string[])[]): string {
  const lines = [...headerLines.map(header), columns.map(csvCell).join(",")];
  for (const r of rows) lines.push(r.map(csvCell).join(","));
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

export function ExportButton({ filename, build, rowCount }: { filename: string; build: () => string; rowCount: number }) {
  return (
    <div className="actions export">
      <button type="button" className="btn btn--primary" onClick={() => download(filename, build())} disabled={rowCount === 0} data-testid="export-csv">
        Export CSV ({rowCount} {rowCount === 1 ? "case" : "cases"})
      </button>
      <span className="small muted">Downloads the visible population to your device. Nothing is sent anywhere and nothing is changed.</span>
    </div>
  );
}
