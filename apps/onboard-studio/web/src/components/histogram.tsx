import { useId } from "react";
import "../styles/screens.css";

export interface Bin { lo: number; hi: number; count: number }

const NICE = [1, 2, 2.5, 5, 10];
function niceWidth(x: number): number {
  if (!(x > 0)) return 1;
  const p = 10 ** Math.floor(Math.log10(x));
  return (NICE.find((m) => m * p >= x) ?? 10) * p;
}

/** Equal-width bins from 0 up to the maximum, at most about 10 of them. Display only: the exact figures stay in the tables. */
export function makeBins(values: readonly number[]): Bin[] {
  if (values.length === 0) return [];
  const max = Math.max(...values);
  const w = niceWidth(max / 10);
  const n = Math.max(1, Math.floor(max / w) + 1);
  const bins: Bin[] = Array.from({ length: n }, (_, i) => ({ lo: i * w, hi: (i + 1) * w, count: 0 }));
  for (const v of values) bins[Math.min(n - 1, Math.floor(v / w))]!.count++;
  return bins;
}

const fmt = (x: number): string => (Number.isInteger(x) ? String(x) : x.toFixed(1));
const W = 420, H = 190, L = 38, R = 8, T = 14, B = 40;

/** Inline SVG histogram. The caller prints a table of the same bins next to it. `limit` draws a dashed amber rule (the SLA). */
export function Histogram({ title, unit, bins, limit, limitLabel }: { title: string; unit: string; bins: readonly Bin[]; limit?: number | null; limitLabel?: string }) {
  const id = useId();
  const total = bins.reduce((n, b) => n + b.count, 0);
  const peak = Math.max(1, ...bins.map((b) => b.count));
  if (bins.length === 0) return <p className="muted small" role="status">{title}: no completed cases in this population.</p>;
  const hi = bins[bins.length - 1]!.hi;
  const x = (v: number): number => L + (v / hi) * (W - L - R);
  const y = (c: number): number => T + (1 - c / peak) * (H - T - B);
  const ticks = [0, Math.ceil(peak / 2), peak].filter((v, i, a) => a.indexOf(v) === i);
  const labelEvery = bins.length > 8 ? 2 : 1;
  return (
    <figure className="hist">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-labelledby={`${id}-t ${id}-d`} className="hist__svg">
        <title id={`${id}-t`}>{title}</title>
        <desc id={`${id}-d`}>Histogram of {total} completed cases in {unit}, {bins.length} bins from 0 to {fmt(hi)}. The same bins are in the table below.</desc>
        {ticks.map((t) => (
          <g key={t}>
            <line className="hist__grid" x1={L} x2={W - R} y1={y(t)} y2={y(t)} />
            <text className="hist__tick" x={L - 6} y={y(t) + 4} textAnchor="end">{t}</text>
          </g>
        ))}
        {bins.map((b, i) => (
          <g key={b.lo}>
            <rect className="hist__bar" x={x(b.lo) + 1} y={y(b.count)} width={Math.max(1, x(b.hi) - x(b.lo) - 2)} height={H - B - y(b.count)}>
              <title>{`${fmt(b.lo)} to under ${fmt(b.hi)} ${unit}: ${b.count} cases`}</title>
            </rect>
            {i % labelEvery === 0 && <text className="hist__tick" x={x(b.lo)} y={H - B + 14} textAnchor="middle">{fmt(b.lo)}</text>}
          </g>
        ))}
        <line className="hist__axis" x1={L} x2={W - R} y1={H - B} y2={H - B} />
        {limit != null && limit <= hi && (
          <g>
            <line className="hist__limit" x1={x(limit)} x2={x(limit)} y1={T} y2={H - B} />
            <text className="hist__limit-text" x={x(limit) + 4} y={T + 10}>{limitLabel ?? `limit ${fmt(limit)}`}</text>
          </g>
        )}
        <text className="hist__label" x={(L + W - R) / 2} y={H - 6} textAnchor="middle">{unit} (bin start)</text>
      </svg>
      <figcaption className="small muted">{title}. Synthetic data. Counts of cases per bin, n = {total}.</figcaption>
    </figure>
  );
}
