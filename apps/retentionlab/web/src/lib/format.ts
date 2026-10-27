// Display helpers. Published figures arrive as strings from the domain; these only re-lay them out (no arithmetic on a figure).
export const short = (s: string, n: number): string => (s.length > n ? `${s.slice(0, n)}…` : s);
/** Typographic minus for a signed decimal string. */
export const minus = (s: string): string => s.replace(/^-/, "−");
export const day = (iso: string): string => iso.slice(0, 10);
export const dayTime = (iso: string): string => `${iso.slice(0, 10)} ${iso.slice(11, 16)}Z`;
export const n0 = (n: number): string => n.toLocaleString("en-US");
/** A null figure is shown as an em dash with a word for why, never as 0. */
export const orDash = (s: string | null | undefined, why = "unknown"): string => (s === null || s === undefined ? `— (${why})` : minus(s));
/** A signed percentage-point string with its unit. */
export const pp = (s: string | null): string => (s === null ? "—" : `${s.startsWith("-") ? "−" : "+"}${s.replace(/^-/, "")} pp`);
export const usd = (s: string): string => (s.startsWith("-") ? `−$${s.slice(1)}` : `$${s}`);
/** The file name part of a label. */
export const slug = (s: string): string => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

/** A comma-separated file with a header of comment lines (contract version, scope, dataset hash, generated timestamp) so that an export matches what the page shows. */
export function csvText(meta: [string, string][], header: string[], rows: (string | number | null)[][]): string {
  const cell = (v: string | number | null): string => { const s = v === null ? "" : String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  return [...meta.map(([k, v]) => `# ${k}: ${v}`), header.map(cell).join(","), ...rows.map((r) => r.map(cell).join(","))].join("\n") + "\n";
}
export function downloadText(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
