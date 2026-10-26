import { useMemo, useState, type ReactNode } from "react";
import "../styles/screens.css";

export interface Column<T> {
  id: string;
  label: string;
  /** Plain value used for sorting and as the default cell text. */
  value: (row: T) => string | number | null;
  render?: (row: T) => ReactNode;
  num?: boolean;
  /** Truncate long text with the full value in a title. */
  truncate?: boolean;
}

interface Props<T> {
  caption: string;
  columns: readonly Column<T>[];
  rows: readonly T[];
  rowKey: (row: T, index: number) => string;
  /** Column id and direction to start with; headers are sort buttons unless sortable is false. */
  initialSort?: { id: string; dir: "asc" | "desc" };
  sortable?: boolean;
  testId?: string;
  empty?: ReactNode;
}

const compare = (a: string | number | null, b: string | number | null): number => {
  if (a === b) return 0;
  if (a === null) return 1; // empty values sort last in both directions
  if (b === null) return -1;
  return typeof a === "number" && typeof b === "number" ? a - b : String(a).localeCompare(String(b), "en", { numeric: true });
};

/** A scrollable, captioned table. Sort with the header buttons (Enter or Space); the sorted column is announced via aria-sort. */
export function DataTable<T>({ caption, columns, rows, rowKey, initialSort, sortable = true, testId, empty }: Props<T>) {
  const [sort, setSort] = useState(initialSort ?? null);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.id === sort.id);
    if (!col) return rows;
    const dir = sort.dir === "asc" ? 1 : -1;
    return [...rows].sort((x, y) => {
      const a = col.value(x), b = col.value(y);
      if (a === null || b === null) return compare(a, b);
      return dir * compare(a, b);
    });
  }, [rows, columns, sort]);
  const toggle = (id: string): void => setSort((s) => (s && s.id === id ? { id, dir: s.dir === "asc" ? "desc" : "asc" } : { id, dir: "asc" }));
  return (
    <div className="table-wrap" role="region" aria-label={`${caption} (scrollable)`} tabIndex={0}>
      <table data-testid={testId}>
        <caption>{caption}</caption>
        <thead>
          <tr>
            {columns.map((c) => {
              const active = sort?.id === c.id ? sort.dir : null;
              return (
                <th key={c.id} scope="col" className={c.num ? "num" : undefined} aria-sort={active === null ? undefined : active === "asc" ? "ascending" : "descending"}>
                  {sortable ? (
                    <button type="button" className="th-sort" onClick={() => toggle(c.id)}>
                      {c.label}<span aria-hidden="true" className="th-sort__mark">{active === "asc" ? " ▲" : active === "desc" ? " ▼" : ""}</span>
                    </button>
                  ) : c.label}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.length === 0 ? (
            <tr><td colSpan={columns.length}>{empty ?? "No rows."}</td></tr>
          ) : sorted.map((r, i) => (
            <tr key={rowKey(r, i)}>
              {columns.map((c) => {
                const v = c.value(r);
                const text = v === null ? "" : String(v);
                return (
                  <td key={c.id} className={[c.num ? "num" : "", c.truncate ? "trunc" : ""].filter(Boolean).join(" ") || undefined} title={c.truncate ? text : undefined}>
                    {c.render ? c.render(r) : text}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
