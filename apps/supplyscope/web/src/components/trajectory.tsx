// Inline SVG charts. The principal representation of SupplyScope is the inventory trajectory: stock on hand, inventory
// position, reorder point and target over time, with receipts and stockout days marked. Every mark is also in a table
// beside it (built by the view). Colour is never the only carrier: lines differ in dash and weight, marks in shape.
import type { PairSeries } from "../domain/metrics";
import { dayStr } from "../domain/time";

const W = 960;
const M = { l: 54, r: 70, t: 16, b: 66 };

function niceMax(v: number): number {
  if (v <= 4) return 4;
  const p = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}
function xTicks(days: readonly number[]): { i: number; text: string }[] {
  const n = days.length;
  const out: { i: number; text: string }[] = [];
  if (n > 60) {
    const step = n > 200 ? 2 : 1;
    let k = 0;
    days.forEach((d, i) => { const s = dayStr(d); if (s.endsWith("-01")) { if (k++ % step === 0) out.push({ i, text: s.slice(0, 7) }); } });
  } else days.forEach((d, i) => { if (i % 7 === 0) out.push({ i, text: dayStr(d).slice(5) }); });
  return out;
}

export function Trajectory({ series, rop, target, name }: { series: PairSeries; rop: number | null; target: number | null; name: string }) {
  const H = 360;
  const n = series.days.length;
  const lo = Math.min(0, ...series.position, ...series.on_hand);
  const hi = niceMax(Math.max(1, ...series.on_hand, ...series.position, rop ?? 0, target ?? 0));
  const iw = W - M.l - M.r, ih = H - M.t - M.b;
  const x = (i: number): number => M.l + (n <= 1 ? iw / 2 : (i / (n - 1)) * iw);
  const y = (v: number): number => M.t + ih - ((v - lo) / (hi - lo)) * ih;
  const line = (vs: readonly number[]): string => vs.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const ticks = [0, 1, 2, 3, 4].map((k) => lo + ((hi - lo) * k) / 4);
  const slot = n <= 1 ? iw : iw / (n - 1);
  const rail = H - M.b + 44;
  const idx = new Map(series.days.map((d, i) => [d, i] as const));
  const last = n - 1;
  const desc = `${name}: on hand ends at ${series.on_hand[last] ?? 0} units and inventory position at ${series.position[last] ?? 0}; ` +
    `${rop === null ? "no reorder point is set" : `reorder point ${rop}, target ${target}`}; ${series.receipts.length} receipts and ${series.stockout_days.length} stockout days are marked. The table below lists them.`;
  return (
    <figure className="chart">
      <div className="chart__scroll" role="region" aria-label={`Trajectory of ${name} (scrollable)`} tabIndex={0}>
        <svg className="chart__svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-labelledby="traj-title traj-desc" data-testid="trajectory">
          <title id="traj-title">Inventory trajectory of {name}</title>
          <desc id="traj-desc">{desc}</desc>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={M.l} x2={W - M.r} y1={y(t)} y2={y(t)} className="chart__grid" />
              <text x={M.l - 8} y={y(t) + 4} textAnchor="end" className="chart__tick">{Math.round(t)}</text>
            </g>
          ))}
          {xTicks(series.days).map((t) => (
            <g key={t.i}>
              <line x1={x(t.i)} x2={x(t.i)} y1={M.t + ih} y2={M.t + ih + 5} className="chart__axis" />
              <text x={x(t.i)} y={M.t + ih + 18} textAnchor="middle" className="chart__tick">{t.text}</text>
            </g>
          ))}
          <line x1={M.l} x2={W - M.r} y1={M.t + ih} y2={M.t + ih} className="chart__axis" />
          {series.stockout_days.map((d) => (
            <rect key={d} className="chart__stockout" x={x(idx.get(d)!) - Math.max(slot, 1.5) / 2} y={M.t} width={Math.max(slot, 1.5)} height={ih}><title>{`Stockout day ${dayStr(d)}`}</title></rect>
          ))}
          {target !== null && <g><line x1={M.l} x2={W - M.r} y1={y(target)} y2={y(target)} className="chart__target" /><text x={W - M.r + 6} y={y(target) + 4} className="chart__label">target {target}</text></g>}
          {rop !== null && <g><line x1={M.l} x2={W - M.r} y1={y(rop)} y2={y(rop)} className="chart__rop" /><text x={W - M.r + 6} y={y(rop) + 4} className="chart__label">ROP {rop}</text></g>}
          <polyline className="chart__position" points={line(series.position)} fill="none" />
          <polyline className="chart__onhand" points={line(series.on_hand)} fill="none" />
          <line x1={M.l} x2={W - M.r} y1={rail - 10} y2={rail - 10} className="chart__grid" />
          <text x={M.l - 8} y={rail - 6} textAnchor="end" className="chart__tick">events</text>
          {series.receipts.map((r) => {
            const cx = x(idx.get(r.day)!);
            return <polygon key={r.receipt_id} className="chart__receipt" points={`${cx},${rail - 12} ${cx - 5},${rail + 2} ${cx + 5},${rail + 2}`}><title>{`Receipt ${r.receipt_id}: +${r.quantity} on ${dayStr(r.day)}`}</title></polygon>;
          })}
          {series.stockout_days.map((d) => {
            const cx = x(idx.get(d)!);
            return <path key={d} className="chart__stockout-mark" d={`M${cx - 3.5},${rail + 6} L${cx + 3.5},${rail + 13} M${cx + 3.5},${rail + 6} L${cx - 3.5},${rail + 13}`}><title>{`Stockout day ${dayStr(d)}`}</title></path>;
          })}
        </svg>
      </div>
      <figcaption>
        <ul className="legend" aria-label="Legend">
          <li><svg width="30" height="10" aria-hidden="true"><line x1="0" x2="30" y1="5" y2="5" className="chart__onhand" /></svg> On hand</li>
          <li><svg width="30" height="10" aria-hidden="true"><line x1="0" x2="30" y1="5" y2="5" className="chart__position" /></svg> Inventory position</li>
          <li><svg width="30" height="10" aria-hidden="true"><line x1="0" x2="30" y1="5" y2="5" className="chart__rop" /></svg> Reorder point</li>
          <li><svg width="30" height="10" aria-hidden="true"><line x1="0" x2="30" y1="5" y2="5" className="chart__target" /></svg> Target position</li>
          <li><svg width="12" height="12" aria-hidden="true"><polygon className="chart__receipt" points="6,1 1,11 11,11" /></svg> Receipt</li>
          <li><svg width="12" height="12" aria-hidden="true"><rect className="chart__stockout" x="3" y="0" width="6" height="12" /></svg> Stockout day (unmet demand opened)</li>
        </ul>
      </figcaption>
    </figure>
  );
}

/** Observed (censored) daily sales beside the generator's published latent demand, stockout days marked. */
export function DemandChart({ days, observed, latent, stockoutDays, name }: { days: readonly number[]; observed: readonly number[]; latent: readonly (number | null)[]; stockoutDays: ReadonlySet<number>; name: string }) {
  const H = 250;
  const n = days.length;
  const hasLatent = latent.some((v) => v !== null);
  const hi = niceMax(Math.max(1, ...observed, ...latent.map((v) => v ?? 0)));
  const iw = W - M.l - 20, ih = H - M.t - 40;
  const slot = iw / Math.max(n, 1);
  const y = (v: number): number => M.t + ih - (v / hi) * ih;
  const bw = Math.max(slot * (hasLatent ? 0.38 : 0.7), 1);
  const ticks = [0, 1, 2, 3, 4].map((k) => (hi * k) / 4);
  return (
    <figure className="chart">
      <div className="chart__scroll" role="region" aria-label={`Demand of ${name} (scrollable)`} tabIndex={0}>
        <svg className="chart__svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-labelledby="dem-title dem-desc" data-testid="demand-chart">
          <title id="dem-title">Observed sales and latent demand of {name}</title>
          <desc id="dem-desc">{`Daily units for ${n} days. ${hasLatent ? "Bars outlined are the published latent demand; filled bars are observed sales, censored on stockout days." : "Filled bars are observed sales, censored on stockout days; no latent demand is published for this SKU."} ${stockoutDays.size} stockout days are shaded. The table below lists them.`}</desc>
          {ticks.map((t) => (<g key={t}><line x1={M.l} x2={W - 20} y1={y(t)} y2={y(t)} className="chart__grid" /><text x={M.l - 8} y={y(t) + 4} textAnchor="end" className="chart__tick">{Math.round(t)}</text></g>))}
          {days.map((d, i) => {
            const cx = M.l + i * slot;
            return (
              <g key={d}>
                {stockoutDays.has(d) && <rect className="chart__stockout" x={cx} y={M.t} width={Math.max(slot, 1.5)} height={ih}><title>{`Stockout day ${dayStr(d)}`}</title></rect>}
                {hasLatent && latent[i] !== null && <rect className="bar bar--latent" x={cx + slot * 0.08} y={y(latent[i]!)} width={bw} height={Math.max(y(0) - y(latent[i]!), 0)} />}
                <rect className="bar bar--observed" x={cx + slot * (hasLatent ? 0.08 + 0.42 : 0.15)} y={y(observed[i]!)} width={bw} height={Math.max(y(0) - y(observed[i]!), 0)}><title>{`${dayStr(d)}: observed ${observed[i]}${latent[i] !== null ? `, latent ${latent[i]}` : ""}`}</title></rect>
              </g>
            );
          })}
          <line x1={M.l} x2={W - 20} y1={y(0)} y2={y(0)} className="chart__axis" />
          {days.map((d, i) => (i % Math.max(Math.round(n / 8), 1) === 0 ? <text key={d} x={M.l + i * slot} y={y(0) + 18} textAnchor="middle" className="chart__tick">{dayStr(d).slice(5)}</text> : null))}
        </svg>
      </div>
      <figcaption>
        <ul className="legend" aria-label="Legend">
          <li><svg width="12" height="12" aria-hidden="true"><rect className="bar bar--observed" x="1" y="1" width="10" height="10" /></svg> Observed sales (censored on stockout days)</li>
          {hasLatent && <li><svg width="12" height="12" aria-hidden="true"><rect className="bar bar--latent" x="1" y="1" width="10" height="10" /></svg> Latent demand (generator's published truth)</li>}
          <li><svg width="12" height="12" aria-hidden="true"><rect className="chart__stockout" x="3" y="0" width="6" height="12" /></svg> Stockout day</li>
        </ul>
      </figcaption>
    </figure>
  );
}
