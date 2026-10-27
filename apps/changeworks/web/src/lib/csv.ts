// A CSV of exactly the rows on screen (R20: an export matches its scope). Values are the displayed strings; nothing is recomputed.
const cell = (v: string | number | null): string => { const s = v === null ? "" : String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
export const toCsv = (head: readonly string[], rows: readonly (readonly (string | number | null)[])[]): string => [head, ...rows].map((r) => r.map(cell).join(",")).join("\n") + "\n";
export function downloadHref(csv: string): string { return `data:text/csv;charset=utf-8,${encodeURIComponent(csv)}`; }
