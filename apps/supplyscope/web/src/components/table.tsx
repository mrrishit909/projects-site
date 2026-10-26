import { useMemo, useState, type ReactNode } from "react";

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
export interface Sort { id: string; dir: "asc" | "desc" }

const compare = (a: string | number | null, b: string | number | null): number => {
  if (a === b) return 0;
  if (a === null) return 1; // empty values sort last in both directions
  if (b === null) return -1;
  return typeof a === "number" && typeof b === "number" ? a - b : String(a).localeCompare(String(b), "en", { numeric: true });
};
/** Rows in the order of `sort` (a copy); the same order the table shows, so an export can follow it. */
export function sortRows<T>(rows: readonly T[], columns: readonly Column<T>[], sort: Sort | null): T[] {
  const col = sort ? columns.find((c) => c.id === sort.id) : undefined;
  if (!sort || !col) return [...rows];
  const dir = sort.dir === "asc" ? 1 : -1;
  return [...rows].sort((x, y) => {
    const a = col.value(x), b = col.value(y);
    return a === null || b === null ? compare(a, b) : dir * compare(a, b);
  });
}

interface Props<T> {
  caption: string;
  columns: readonly Column<T>[];
  rows: readonly T[];
  rowKey: (row: T, index: number) => string;
  /** Column id and direction to start with. Pass `sort` and `onSort` to hold the sort state outside (for an export). */
  initialSort?: Sort;
  sort?: Sort | null;
  onSort?: (s: Sort | null) => void;
  sortable?: boolean;
  testId?: string;
  empty?: ReactNode;
}

/** A scrollable, captioned table. Sort with the header buttons (Enter or Space); the sorted column is announced via aria-sort. */
export function DataTable<T>({ caption, columns, rows, rowKey, initialSort, sort: controlled, onSort, sortable = true, testId, empty }: Props<T>) {
  const [own, setOwn] = useState<Sort | null>(initialSort ?? null);
  const sort = controlled !== undefined ? controlled : own;
  const sorted = useMemo(() => sortRows(rows, columns, sort), [rows, columns, sort]);
  const toggle = (id: string): void => {
    const next: Sort = sort && sort.id === id ? { id, dir: sort.dir === "asc" ? "desc" : "asc" } : { id, dir: "asc" };
    if (onSort) onSort(next); else setOwn(next);
  };
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
