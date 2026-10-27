// SVG charts. Every label printed on a chart is a string the domain produced; the only numbers here are pixel positions derived from those
// strings (geometry), which is why this is the one file that may use Math.* and toFixed. Each chart has an accessible table next to it in its view.
import type { CalBin } from "../domain/metrics";
import { minus } from "../lib/format";

const g = (s: string | null): number => (s === null ? 0 : Number(s));
const f1 = (x: number): string => x.toFixed(1);

const NICE = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1];
const niceMax = (v: number): number => NICE.find((n) => n >= v * 1.08) ?? 1;
const ticks = (max: number): number[] => { const step = max <= 0.2 ? 0.05 : max <= 0.5 ? 0.1 : max <= 0.8 ? 0.2 : 0.25; const t: number[] = []; for (let x = 0; x <= max + 1e-9; x += step) t.push(x); return t; };
const tickLabel = (x: number): string => x.toFixed(2);

export function Legend({ items }: { items: { label: string; color: string; dash?: boolean }[] }) {
  return <p className="legend" aria-hidden="true">{items.map((i) => <span key={i.label}><i className={i.dash ? "dash" : ""} style={{ borderTopColor: i.color }} />{i.label}</span>)}</p>;
}

// ------------------------------------------------------------------------------------------------ the reliability curve
export function ReliabilityChart({ bins, active, onPick, zoom, caption }: { bins: CalBin[]; active: number | null; onPick: (i: number) => void; zoom: "auto" | "full"; caption: string }) {
  const filled = bins.filter((b) => b.count > 0);
  const top = Math.max(0.1, ...filled.flatMap((b) => [g(b.mean_predicted), g(b.observed_rate)]));
  const max = zoom === "full" ? 1 : niceMax(top);
  const L = 58, R = 540, T = 16, B = 300, HT = 350, HB = 440;
  const W = R - L, H = B - T;
  const x = (v: number): number => L + (v / max) * W;
  const y = (v: number): number => B - (v / max) * H;
  const maxN = Math.max(1, ...bins.map((b) => b.count));
  const pts = filled.map((b) => ({ b, cx: x(g(b.mean_predicted)), cy: y(g(b.observed_rate)), r: 4 + 9 * Math.sqrt(b.count / maxN) }));
  return (
    <svg className="chart" viewBox="0 0 560 470" role="img" aria-label={caption} data-testid="reliability-chart" data-axis-max={String(max)}>
      {ticks(max).map((t) => <g key={t}><line className="grid-line" x1={L} x2={R} y1={y(t)} y2={y(t)} /><text x={L - 6} y={y(t) + 4} textAnchor="end">{tickLabel(t)}</text><text x={x(t)} y={B + 14} textAnchor="middle">{tickLabel(t)}</text></g>)}
      <line className="axis" x1={L} x2={R} y1={B} y2={B} /><line className="axis" x1={L} x2={L} y1={T} y2={B} />
      <line className="ref" x1={x(0)} y1={y(0)} x2={x(max)} y2={y(max)} />
      <text x={x(max) - 4} y={y(max) + 14} textAnchor="end" style={{ fill: "#7fc8b8" }}>perfect calibration</text>
      <polyline className="obs" points={pts.map((p) => `${f1(p.cx)},${f1(p.cy)}`).join(" ")} />
      {pts.map(({ b, cx, cy, r }) => (
        <g key={b.index} onClick={() => onPick(b.index)} style={{ cursor: "pointer" }}>
          <circle className="obs-pt" cx={f1(cx)} cy={f1(cy)} r={f1(r)} style={b.count < 30 ? { fill: "none", stroke: "#ef7a6a", strokeWidth: 2 } : undefined} />
          {active === b.index && <circle className="active" cx={f1(cx)} cy={f1(cy)} r={f1(r + 5)} />}
          <text x={f1(cx + r + 3)} y={f1(cy - r - 1)} className="lab-strong">{`n=${b.count}`}</text>
        </g>
      ))}
      <text x={(L + R) / 2} y={B + 30} textAnchor="middle">mean predicted risk (x) against observed churn rate (y), both 0 to {max}</text>
      <line className="axis" x1={L} x2={R} y1={HB} y2={HB} />
      {bins.filter((b) => g(b.lower) < max).map((b) => {
        const x0 = x(g(b.lower)), x1 = x(Math.min(max, g(b.upper))), h = 70 * Math.sqrt(b.count / maxN);
        return (
          <g key={b.index} onClick={() => onPick(b.index)} style={{ cursor: "pointer" }}>
            <rect className={active === b.index ? "bar bar--cream" : "bar"} x={f1(x0 + 2)} y={f1(HB - h)} width={f1(Math.max(1, x1 - x0 - 4))} height={f1(h)} />
            <text x={f1((x0 + x1) / 2)} y={f1(HB - h - 4)} textAnchor="middle">{b.count}</text>
          </g>
        );
      })}
      <text x={L} y={HT + 4}>rows per bin (square-root height; the count is printed)</text>
    </svg>
  );
}

// ------------------------------------------------------------------------------------------------ precision and recall at capacity
export function PrCapacityChart({ n, hits, k, markers, prevalence, caption }: { n: number; hits: number[]; k: number | null; markers: number[]; prevalence: string | null; caption: string }) {
  const L = 52, R = 540, T = 14, B = 290;
  const W = R - L, H = B - T;
  const lg = Math.log(Math.max(2, n));
  const x = (kk: number): number => L + (Math.log(Math.max(1, kk)) / lg) * W;
  const y = (v: number): number => B - v * H;
  const total = hits.length ? hits[hits.length - 1]! : 0;
  const ks: number[] = [];
  for (let kk = 1; kk <= n; kk = kk < 40 ? kk + 1 : Math.max(kk + 1, Math.round(kk * 1.04))) ks.push(kk);
  if (ks[ks.length - 1] !== n && n > 0) ks.push(n);
  const prec = ks.map((kk) => `${f1(x(kk))},${f1(y(hits[kk - 1]! / kk))}`).join(" ");
  const rec = total > 0 ? ks.map((kk) => `${f1(x(kk))},${f1(y(hits[kk - 1]! / total))}`).join(" ") : "";
  const tk = [1, 10, 100, 1000, 10000].filter((t) => t <= n);
  return (
    <svg className="chart" viewBox="0 0 560 340" role="img" aria-label={caption} data-testid="pr-chart">
      {[0, 0.25, 0.5, 0.75, 1].map((t) => <g key={t}><line className="grid-line" x1={L} x2={R} y1={y(t)} y2={y(t)} /><text x={L - 6} y={y(t) + 4} textAnchor="end">{t.toFixed(2)}</text></g>)}
      {tk.map((t) => <g key={t}><line className="grid-line" x1={x(t)} x2={x(t)} y1={T} y2={B} /><text x={x(t)} y={B + 14} textAnchor="middle">{t}</text></g>)}
      <line className="axis" x1={L} x2={R} y1={B} y2={B} /><line className="axis" x1={L} x2={L} y1={T} y2={B} />
      {prevalence !== null && <g><line className="ref" x1={L} x2={R} y1={y(g(prevalence))} y2={y(g(prevalence))} /><text x={R - 2} y={y(g(prevalence)) - 5} textAnchor="end" style={{ fill: "#7fc8b8" }}>prevalence {prevalence}</text></g>}
      <polyline className="obs" points={prec} /><polyline className="pred" points={rec} />
      {markers.filter((m) => m <= n).map((m) => <g key={m}><line className="grid-line" x1={x(m)} x2={x(m)} y1={B - 6} y2={B} style={{ stroke: "#e3c58a" }} /><text x={x(m)} y={B + 26} textAnchor="middle" style={{ fill: "#e3c58a" }}>{m}</text></g>)}
      {k !== null && k >= 1 && k <= n && <g>
        <line className="active" x1={x(k)} x2={x(k)} y1={T} y2={B} style={{ strokeDasharray: "3 3", strokeWidth: 1.5 }} />
        <circle className="obs-pt" cx={f1(x(k))} cy={f1(y(hits[k - 1]! / k))} r="5" />
        {total > 0 && <circle cx={f1(x(k))} cy={f1(y(hits[k - 1]! / total))} r="5" fill="#7fc8b8" stroke="#2a1630" strokeWidth="1.5" />}
      </g>}
      <text x={(L + R) / 2} y={B + 46} textAnchor="middle">capacity K (log scale, ranked by risk), 1 to {n}</text>
    </svg>
  );
}

// ------------------------------------------------------------------------------------------------ horizontal bars
export interface BarRow { label: string; value: string | null; tone?: "coral" | "teal" | "cream" | "muted"; note?: string }
export function HBars({ rows, max: maxIn, ref, caption, testid }: { rows: BarRow[]; max?: number; ref?: { label: string; value: string } | undefined; caption: string; testid?: string }) {
  const max = maxIn ?? Math.max(0.05, ...rows.map((r) => g(r.value)), ref ? g(ref.value) : 0) * 1.15;
  const L = 190, R = 540, rowH = 34, H = rows.length * rowH + 30;
  const x = (v: number): number => L + (Math.max(0, v) / max) * (R - L);
  return (
    <svg className="chart" viewBox={`0 0 560 ${H}`} role="img" aria-label={caption} {...(testid ? { "data-testid": testid } : {})}>
      {rows.map((r, i) => (
        <g key={r.label}>
          <text x={L - 8} y={i * rowH + 22} textAnchor="end" className="lab-strong">{r.label}</text>
          {r.value !== null && <rect className={`bar bar--${r.tone ?? "muted"}`} x={L} y={i * rowH + 8} width={f1(x(g(r.value)) - L)} height="18" rx="2" />}
          <text x={r.value === null ? L + 6 : f1(x(g(r.value)) + 6)} y={i * rowH + 22}>{r.value === null ? "no value" : minus(r.value)}{r.note ? `  ${r.note}` : ""}</text>
        </g>
      ))}
      <line className="axis" x1={L} x2={L} y1={4} y2={rows.length * rowH + 4} />
      {ref && <g><line className="ref" x1={f1(x(g(ref.value)))} x2={f1(x(g(ref.value)))} y1={2} y2={rows.length * rowH + 6} /><text x={f1(x(g(ref.value)))} y={rows.length * rowH + 22} textAnchor="middle" style={{ fill: "#7fc8b8" }}>{ref.label} {ref.value}</text></g>}
    </svg>
  );
}

// ------------------------------------------------------------------------------------------------ churn per cutoff, with the censored tail
export interface Col { label: string; rate: string | null; eligible: number; mature: number; censored: number; range: string | null }
export function ChurnColumns({ cols, caption }: { cols: Col[]; caption: string }) {
  const L = 44, R = 548, T = 16, B = 230;
  const topv = Math.max(0.05, ...cols.map((c) => g(c.rate)));
  const max = niceMax(topv);
  const w = (R - L) / Math.max(1, cols.length);
  const y = (v: number): number => B - (v / max) * (B - T);
  return (
    <svg className="chart" viewBox="0 0 560 290" role="img" aria-label={caption} data-testid="churn-chart">
      <defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="#2a1630" /><line x1="0" y1="0" x2="0" y2="6" stroke="#bfae9f" strokeWidth="2" /></pattern></defs>
      {ticks(max).map((t) => <g key={t}><line className="grid-line" x1={L} x2={R} y1={y(t)} y2={y(t)} /><text x={L - 5} y={y(t) + 4} textAnchor="end">{tickLabel(t)}</text></g>)}
      <line className="axis" x1={L} x2={R} y1={B} y2={B} />
      {cols.map((c, i) => {
        const x0 = L + i * w + 2, bw = Math.max(2, w - 4);
        const full = c.mature === 0;
        return (
          <g key={c.label}>
            {full ? <rect x={f1(x0)} y={T} width={f1(bw)} height={B - T} fill="url(#hatch)" stroke="#bfae9f" strokeDasharray="3 2" />
              : <rect className={c.range === "test" ? "bar bar--coral" : "bar bar--cream"} x={f1(x0)} y={f1(y(g(c.rate)))} width={f1(bw)} height={f1(B - y(g(c.rate)))} />}
            {!full && c.censored > 0 && <rect x={f1(x0)} y={T} width={f1(bw)} height="18" fill="url(#hatch)" stroke="#bfae9f" />}
            <text transform={`translate(${f1(x0 + bw / 2 + 3)},${B + 8}) rotate(60)`}>{c.label}</text>
          </g>
        );
      })}
      <text x={L} y="10">churn rate of mature eligible rows; hatched = censored (outcome not yet known, never counted as no churn)</text>
    </svg>
  );
}

// ------------------------------------------------------------------------------------------------ lines over the cutoffs
export interface Series { key: string; label: string; color: string; dash?: boolean; values: (string | null)[]; marks?: boolean[] }
export function LineSeries({ labels, series, threshold, caption, testid }: { labels: string[]; series: Series[]; threshold?: string; caption: string; testid?: string }) {
  const L = 48, R = 548, T = 14, B = 220;
  const all = series.flatMap((s) => s.values.map(g));
  const max = niceMax(Math.max(0.25, ...all));
  const n = Math.max(1, labels.length - 1);
  const x = (i: number): number => L + (i / n) * (R - L);
  const y = (v: number): number => B - (v / max) * (B - T);
  return (
    <svg className="chart" viewBox="0 0 560 290" role="img" aria-label={caption} {...(testid ? { "data-testid": testid } : {})}>
      {ticks(max).map((t) => <g key={t}><line className="grid-line" x1={L} x2={R} y1={y(t)} y2={y(t)} /><text x={L - 5} y={y(t) + 4} textAnchor="end">{tickLabel(t)}</text></g>)}
      <line className="axis" x1={L} x2={R} y1={B} y2={B} />
      {threshold && <g><line className="thr" x1={L} x2={R} y1={y(g(threshold))} y2={y(g(threshold))} /><text x={R - 2} y={y(g(threshold)) - 4} textAnchor="end" style={{ fill: "#e3c58a" }}>threshold {threshold}</text></g>}
      {series.map((s) => (
        <g key={s.key}>
          <polyline fill="none" stroke={s.color} strokeWidth="2" strokeDasharray={s.dash ? "5 4" : undefined} points={s.values.map((v, i) => (v === null ? null : `${f1(x(i))},${f1(y(g(v)))}`)).filter(Boolean).join(" ")} />
          {s.values.map((v, i) => v !== null && (s.marks?.[i] ? <circle key={i} cx={f1(x(i))} cy={f1(y(g(v)))} r="4" fill={s.color} stroke="#2a1630" /> : null))}
        </g>
      ))}
      {labels.map((l, i) => (i % Math.ceil(labels.length / 11) === 0 ? <text key={l} transform={`translate(${f1(x(i) + 3)},${B + 8}) rotate(60)`}>{l}</text> : null))}
    </svg>
  );
}

// ------------------------------------------------------------------------------------------------ a point-in-time timeline
export interface TimelineEvent { id: string; lane: "usage" | "billing" | "support" | "subscription"; at: number; avail: number; late: boolean; inWindow: boolean }
export function Timeline({ events, start, cutoff, end, caption }: { events: TimelineEvent[]; start: number; cutoff: number; end: number; caption: string }) {
  const L = 92, R = 548, lanes = ["usage", "billing", "support", "subscription"] as const;
  const x = (t: number): number => L + ((t - start) / Math.max(1, end - start)) * (R - L);
  const H = 40 + lanes.length * 34;
  return (
    <svg className="chart" viewBox={`0 0 560 ${H + 30}`} role="img" aria-label={caption} data-testid="timeline">
      {lanes.map((l, i) => <g key={l}><line className="grid-line" x1={L} x2={R} y1={30 + i * 34 + 14} y2={30 + i * 34 + 14} /><text x={L - 8} y={30 + i * 34 + 18} textAnchor="end">{l}</text></g>)}
      <line className="active" x1={f1(x(cutoff))} x2={f1(x(cutoff))} y1="8" y2={H - 4} /><text x={f1(x(cutoff))} y="8" textAnchor="middle" className="lab-strong">cutoff</text>
      {events.map((e) => {
        const cy = 30 + lanes.indexOf(e.lane) * 34 + 14;
        return (
          <g key={e.id}>
            {e.late && <line className="late" x1={f1(x(e.at))} x2={f1(Math.min(R, x(e.avail)))} y1={cy} y2={cy} strokeDasharray="3 3" />}
            {e.late ? <circle className="late" cx={f1(x(e.at))} cy={cy} r="5" /> : <circle cx={f1(x(e.at))} cy={cy} r="4" fill={e.inWindow ? "#7fc8b8" : "#bfae9f"} />}
            {e.late && x(e.avail) <= R && <circle cx={f1(x(e.avail))} cy={cy} r="3" fill="#ef7a6a" />}
          </g>
        );
      })}
      <text x={L} y={H + 22}>filled = used; hollow with a dashed line = occurred before the cutoff, arrived after it (excluded, counted as arrived late)</text>
    </svg>
  );
}

// ------------------------------------------------------------------------------------------------ signed contributions
export function Diverging({ rows, caption }: { rows: { label: string; value: string }[]; caption: string }) {
  const L = 200, R = 548, mid = (L + R) / 2, rowH = 30;
  const maxAbs = Math.max(0.01, ...rows.map((r) => Math.abs(g(r.value))));
  const half = (R - L) / 2 - 40;
  return (
    <svg className="chart" viewBox={`0 0 560 ${rows.length * rowH + 20}`} role="img" aria-label={caption} data-testid="contributions-chart">
      <line className="axis" x1={mid} x2={mid} y1="0" y2={rows.length * rowH + 6} />
      {rows.map((r, i) => {
        const v = g(r.value), w = (Math.abs(v) / maxAbs) * half;
        return (
          <g key={r.label}>
            <text x={L - 8} y={i * rowH + 20} textAnchor="end" className="lab-strong">{r.label}</text>
            <rect className={v >= 0 ? "bar bar--coral" : "bar bar--teal"} x={f1(v >= 0 ? mid : mid - w)} y={i * rowH + 6} width={f1(Math.max(1, w))} height="18" rx="2" />
            <text x={f1(v >= 0 ? mid + w + 5 : mid - w - 5)} y={i * rowH + 20} textAnchor={v >= 0 ? "start" : "end"}>{minus(r.value)}</text>
          </g>
        );
      })}
    </svg>
  );
}
