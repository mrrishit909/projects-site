// Inline-SVG waterfall (horizontal rows: label above its bar) with an adjacent table that carries the drill links.
import type { ReactNode } from "react";
import "../../styles/screens.css";
import { useWidth } from "./use-width";

export interface WaterfallStep {
  id: string;
  /** Short label used inside the chart. */
  short: string;
  /** Full label used in the table. */
  label: string;
  kind: "total" | "delta";
  /** Exact signed decimal string: the step's contribution (delta) or the running total (total). */
  value: string;
  /** Formatted for display (already carries its leading minus). */
  text: string;
}
export interface WaterfallProps {
  id: string;
  title: string;
  caption: string;
  steps: WaterfallStep[];
  onSelect: (id: string) => void;
  /** Table cell for the drill action of a step. */
  drill: (s: WaterfallStep) => ReactNode;
  tableCaption: string;
}

const ROW = 46;

export function Waterfall(p: WaterfallProps) {
  const [ref, width] = useWidth<HTMLDivElement>();
  // Running total after each step; totals reset it to their own value.
  let run = 0;
  const bars = p.steps.map((s) => {
    const v = Number(s.value);
    const from = s.kind === "total" ? 0 : run;
    const to = s.kind === "total" ? v : run + v;
    run = to;
    return { s, a: Math.min(from, to), b: Math.max(from, to), neg: s.kind === "delta" && v < 0, pos: s.kind === "delta" && v > 0 };
  });
  const lo = Math.min(0, ...bars.map((b) => b.a));
  const hi = Math.max(0, ...bars.map((b) => b.b));
  const pad = 2;
  const iw = Math.max(120, width - pad * 2);
  const sx = (v: number): number => pad + ((v - lo) / (hi - lo || 1)) * iw;
  const h = bars.length * ROW + 8;
  return (
    <figure className="figure" id={p.id}>
      <figcaption className="small" style={{ color: "var(--ink)", fontWeight: 600, marginBottom: "0.4rem" }}>{p.title}</figcaption>
      <div ref={ref}>
        <svg className="chart" width={width} height={h} role="img" aria-labelledby={`${p.id}-t`} data-testid={`${p.id}-svg`}>
          <title id={`${p.id}-t`}>{p.title}. {p.caption} Use the table below for the same steps with links to the evidence ledger.</title>
          <line x1={sx(0)} x2={sx(0)} y1={0} y2={h} stroke="var(--ink)" strokeWidth="1" />
          {bars.map(({ s, a, b, neg, pos }, i) => {
            const y0 = i * ROW + 4;
            const x0 = sx(a);
            const w = Math.max(2, sx(b) - sx(a));
            const fill = s.kind === "total" ? "var(--ink)" : neg ? "var(--copper)" : pos ? "#3f6b58" : "var(--muted)";
            return (
              <g key={s.id} className="bar" onClick={() => p.onSelect(s.id)} data-testid={`bar-${s.id}`}>
                <title>{`${s.label}: ${s.text}. Click to open the evidence ledger for this population.`}</title>
                <rect x={0} y={y0} width={width} height={ROW - 4} fill="transparent" />
                <text x={4} y={y0 + 15} style={{ fontSize: 13, fontWeight: s.kind === "total" ? 700 : 400 }}>{s.short}</text>
                <text x={width - 4} y={y0 + 15} textAnchor="end" style={{ fontSize: 13, fontFamily: "var(--mono)", fontWeight: s.kind === "total" ? 700 : 400 }}>{s.text}</text>
                <rect x={x0} y={y0 + 21} width={w} height={14} fill={fill} />
              </g>
            );
          })}
        </svg>
      </div>
      <p className="small muted" style={{ marginBottom: 0 }}>{p.caption}</p>
      <div className="tablewrap" tabIndex={0} role="region" aria-label={`${p.title} table`} style={{ marginTop: "0.8rem" }}>
        <table className="bridge-table" data-testid={`${p.id}-table`}>
          <caption>{p.tableCaption}</caption>
          <thead><tr><th scope="col">Step</th><th scope="col" className="num">Amount (USD)</th><th scope="col">Evidence</th></tr></thead>
          <tbody>
            {p.steps.map((s) => (
              <tr key={s.id} data-step={s.id}>
                <th scope="row" className="step" style={s.kind === "total" ? { fontWeight: 700 } : undefined}>{s.label}</th>
                <td className={`num${s.text.startsWith("-") ? " neg" : ""}`} data-testid={`step-${s.id}`}>{s.text}</td>
                <td>{p.drill(s)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </figure>
  );
}
