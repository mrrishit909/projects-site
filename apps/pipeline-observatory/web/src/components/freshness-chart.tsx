import type { FreshnessRow } from "../domain/world";
import { dur } from "../lib/format";

const W = 760, LEFT = 150, RIGHT = 20, ROW = 62, TOP = 26;
/** Freshness (newest accepted event) beside ingestion age (last committed batch) per source, on one time axis. The table beside it holds the same numbers. */
export function FreshnessChart({ rows }: { rows: FreshnessRow[] }) {
  const maxSec = Math.max(1, ...rows.flatMap((r) => [r.freshness_seconds ?? 0, r.ingestion_age_seconds ?? 0]));
  const step = 86400, axisMax = Math.ceil(maxSec / step) * step;
  const x = (s: number): number => LEFT + ((W - LEFT - RIGHT) * s) / axisMax;
  const H = TOP + rows.length * ROW + 24;
  const ticks = Array.from({ length: axisMax / step + 1 }, (_, i) => i * step);
  return (
    <figure className="chart" data-testid="freshness-chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-labelledby="fc-t fc-d" className="chart__svg">
        <title id="fc-t">Freshness beside ingestion age, per source</title>
        <desc id="fc-d">For each source, one bar for how old its newest accepted event is and one bar for how long ago its last batch committed, on an axis in days. The same numbers are in the table below.</desc>
        <defs>
          <pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="var(--amber)" /><rect width="2.5" height="6" fill="var(--bg)" /></pattern>
        </defs>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={TOP - 6} y2={H - 22} className="chart__grid" />
            <text x={x(t)} y={H - 6} textAnchor="middle" className="chart__tick">{t === 0 ? "0" : `${t / 86400} d`}</text>
          </g>
        ))}
        {rows.map((r, i) => {
          const y = TOP + i * ROW;
          const f = r.freshness_seconds, a = r.ingestion_age_seconds;
          const targetIn = r.target_seconds !== null && r.target_seconds <= axisMax;
          return (
            <g key={r.source_id} data-source={r.source_id}>
              <text x={LEFT - 10} y={y + 17} textAnchor="end" className="chart__label">{r.source_id}</text>
              <text x={LEFT - 10} y={y + 33} textAnchor="end" className="chart__sub">{r.cadence}</text>
              {f !== null && (
                <g>
                  <rect x={LEFT} y={y + 4} width={Math.max(2, x(f) - LEFT)} height={16} fill={r.silent || r.past_target ? "url(#hatch)" : "var(--cyan)"} className="chart__bar chart__bar--f" data-bar="freshness"><title>{`${r.source_id}: newest accepted event is ${dur(f)} old`}</title></rect>
                  <text x={Math.min(x(f) + 6, W - 70)} y={y + 17} className="chart__val">{dur(f)}</text>
                </g>
              )}
              {a !== null && (
                <g>
                  <rect x={LEFT} y={y + 25} width={Math.max(2, x(a) - LEFT)} height={11} className="chart__bar chart__bar--a" data-bar="ingestion-age"><title>{`${r.source_id}: last batch committed ${dur(a)} ago`}</title></rect>
                  <text x={Math.min(x(a) + 6, W - 70)} y={y + 35} className="chart__val chart__val--a">{dur(a)}</text>
                </g>
              )}
              {r.target_seconds !== null && (targetIn
                ? <g><line x1={x(r.target_seconds)} x2={x(r.target_seconds)} y1={y} y2={y + 42} className="chart__target" /><text x={x(r.target_seconds)} y={y + 53} textAnchor="middle" className="chart__sub">target {dur(r.target_seconds)}</text></g>
                : <text x={W - RIGHT} y={y + 53} textAnchor="end" className="chart__sub">target {dur(r.target_seconds)} →</text>)}
            </g>
          );
        })}
      </svg>
      <figcaption className="legend">
        <span><i className="sw sw--f" />freshness: now minus the newest accepted event</span>
        <span><i className="sw sw--h" />hatched: silent or past its target</span>
        <span><i className="sw sw--a" />ingestion age: now minus the last committed batch</span>
        <span><i className="sw sw--t" />the source&apos;s own freshness target</span>
      </figcaption>
    </figure>
  );
}
