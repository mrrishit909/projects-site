// Inline-SVG multi-series line chart with a legend, direct end labels and an adjacent data table.
import "../../styles/screens.css";
import { useWidth } from "./use-width";

export interface LineSeries { id: string; label: string; color: string; dash?: string; values: (number | null)[] }
export interface LineChartProps {
  id: string;
  title: string;
  /** Units, population, window and "synthetic data": printed under the chart. */
  caption: string;
  categories: string[];
  /** Short x labels, same order as categories. */
  tickLabels: string[];
  series: LineSeries[];
  /** Optional vertical marker at a category index. */
  marker?: { index: number; label: string } | null;
  tableCaption: string;
  tableHeaders: string[];
  tableRows: string[][];
  yFormat?: (n: number) => string;
  height?: number;
}

const compact = (n: number): string => {
  const a = Math.abs(n);
  const s = a >= 1e6 ? `${(a / 1e6).toFixed(a >= 1e7 ? 0 : 1)}M` : a >= 1e3 ? `${(a / 1e3).toFixed(a >= 1e4 ? 0 : 1)}k` : String(Math.round(a));
  return n < 0 ? `-${s}` : s;
};

function niceTicks(lo: number, hi: number, count = 5): number[] {
  if (hi === lo) return [lo];
  const raw = (hi - lo) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = ([1, 2, 2.5, 5, 10].find((m) => m * mag >= raw) ?? 10) * mag;
  const out: number[] = [];
  for (let v = Math.floor(lo / step) * step; v <= hi + step * 0.999; v += step) { out.push(v); if (v > hi) break; }
  return out;
}

export function LineChart(p: LineChartProps) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const h = p.height ?? 300;
  const m = { l: 52, r: width < 520 ? 12 : 16, t: 14, b: 34 };
  const iw = Math.max(40, width - m.l - m.r);
  const ih = h - m.t - m.b;
  const all = p.series.flatMap((s) => s.values).filter((v): v is number => v !== null);
  const lo = Math.min(0, ...all);
  const hi = Math.max(0, ...all);
  const ticks = niceTicks(lo, hi);
  const dLo = Math.min(lo, ticks[0] ?? lo);
  const dHi = Math.max(hi, ticks[ticks.length - 1] ?? hi);
  const n = p.categories.length;
  const x = (i: number): number => m.l + (n <= 1 ? iw / 2 : (i * iw) / (n - 1));
  const y = (v: number): number => m.t + ih - ((v - dLo) / (dHi - dLo || 1)) * ih;
  const fmt = p.yFormat ?? compact;
  const every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(iw / 58))));
  return (
    <figure className="figure" id={p.id}>
      <figcaption className="small" style={{ color: "var(--ink)", fontWeight: 600, marginBottom: "0.4rem" }}>{p.title}</figcaption>
      <ul className="legend" aria-label="Legend">
        {p.series.map((s) => (
          <li key={s.id}>
            <svg viewBox="0 0 28 10" aria-hidden="true"><line x1="1" y1="5" x2="27" y2="5" stroke={s.color} strokeWidth="2.5" strokeDasharray={s.dash} /></svg>
            {s.label}
          </li>
        ))}
      </ul>
      <div ref={ref}>
        <svg className="chart" width={width} height={h} role="img" aria-labelledby={`${p.id}-t`} data-testid={`${p.id}-svg`}>
          <title id={`${p.id}-t`}>{p.title}. {p.caption} The same values are in the table below the chart.</title>
          <g className="axis">
            {ticks.map((t) => (
              <g key={t}>
                <line className="grid" x1={m.l} x2={m.l + iw} y1={y(t)} y2={y(t)} strokeDasharray={t === 0 ? undefined : "2 3"} style={t === 0 ? { stroke: "var(--ink)" } : undefined} />
                <text x={m.l - 6} y={y(t) + 4} textAnchor="end">{fmt(t)}</text>
              </g>
            ))}
            {p.tickLabels.map((l, i) => (i % every === 0 ? <text key={i} x={x(i)} y={h - 12} textAnchor="middle">{l}</text> : null))}
          </g>
          {p.marker && p.marker.index >= 0 && p.marker.index < n && (
            <g>
              <line x1={x(p.marker.index)} x2={x(p.marker.index)} y1={m.t} y2={m.t + ih} stroke="var(--copper)" strokeWidth="1" strokeDasharray="4 3" />
              <text x={x(p.marker.index) - 4} y={m.t + 10} textAnchor="end" style={{ fontSize: 11 }}>{p.marker.label}</text>
            </g>
          )}
          {p.series.map((s) => {
            let d = "";
            let pen = false;
            s.values.forEach((v, i) => {
              if (v === null) { pen = false; return; }
              d += `${pen ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`;
              pen = true;
            });
            return (
              <g key={s.id}>
                <path d={d} fill="none" stroke={s.color} strokeWidth="2.5" strokeDasharray={s.dash} strokeLinejoin="round" />
                {s.values.map((v, i) => (v === null ? null : (
                  <circle key={i} cx={x(i)} cy={y(v)} r="3" fill="var(--paper)" stroke={s.color} strokeWidth="1.8"><title>{`${s.label}, ${p.categories[i]}: ${v.toFixed(2)}`}</title></circle>
                )))}
              </g>
            );
          })}
        </svg>
      </div>
      <p className="figure__caption small muted" style={{ marginBottom: 0 }}>{p.caption}</p>
      <details className="alt" open>
        <summary>Data table: {p.title}</summary>
        <div className="tablewrap" tabIndex={0} role="region" aria-label={`${p.title} data table`}>
          <table data-testid={`${p.id}-table`}>
            <caption>{p.tableCaption}</caption>
            <thead><tr>{p.tableHeaders.map((hd, i) => <th key={hd} scope="col" className={i > 0 ? "num" : undefined}>{hd}</th>)}</tr></thead>
            <tbody>
              {p.tableRows.map((r, ri) => (
                <tr key={ri}>{r.map((c, ci) => (ci === 0 ? <th key={ci} scope="row">{c}</th> : <td key={ci} className={`num${c.startsWith("-") ? " neg" : ""}`}>{c}</td>))}</tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
