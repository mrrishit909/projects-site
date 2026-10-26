import { useMemo } from "react";
import { ViewHead } from "../components/layout";
import { Link } from "../components/link";
import { Gate } from "../components/status";
import { Definition, Panel, Readout, RULES, V } from "../components/ui";
import { fmtOffset, localClock, shiftGrid, zoneOffsetMinutes } from "../domain/extras";
import { secondsWithin, intervalsOf } from "../domain/events";
import { d4s, fixed } from "../domain/fixed";
import { parseTs } from "../domain/time";
import { useInjections } from "../lib/injections";
import { dayOf, dayStart, hhmm } from "../lib/format";
import { useParam } from "../router";
import type { Ready } from "../state/store";

const VW = 1000, GUTTER = 96, RIGHT = 10, TOP = 36, PITCH = 20;
const pctOf = (num: number, den: number): string | null => (den <= 0 ? null : `${fixed(BigInt(num) * 100n, den, 0)}`);

export function Staffing() {
  return (
    <article>
      <ViewHead eyebrow="Entry route" title="Shift grid">
        <p className="lede">Agents by hour of one UTC day. Each outlined block is a shift as recorded, hatched strips are the recorded breaks, and the shade of a cell is how much of the on-shift time in that hour was active handling.</p>
      </ViewHead>
      <Gate>{(s) => <Body s={s} />}</Gate>
    </article>
  );
}

function Body({ s }: { s: Ready }) {
  const pop = s.result.population, hist = s.result.histories;
  const firstDay = dayOf(s.windows.full[0]), lastDay = dayOf(s.windows.full[1] - 1);
  const dst = s.snapshot.manifest.generator?.parameters?.dst_weekend;
  const dflt = dst && dst.saturday >= firstDay && dst.saturday <= lastDay ? dst.saturday : firstDay;
  const [day, setDay] = useParam("day", dflt);
  const dayKey = /^\d{4}-\d{2}-\d{2}$/.test(day) ? day : dflt;
  const d0 = dayStart(dayKey);
  const inj = useInjections();
  const tags = useMemo(() => {
    const m = new Map<string, string[]>();
    if (inj.status === "ready") for (const i of inj.injections) if (i.entity === "shifts") for (const id of i.record_ids) m.set(id, [...(m.get(id) ?? []), i.id]);
    return m;
  }, [inj]);
  const breaks = useMemo(() => s.snapshot.shiftBreaks.map((b) => ({ shift_id: b.shift_id, agent_id: b.agent_id, starts_at: parseTs(b.starts_at), ends_at: parseTs(b.ends_at) })), [s.snapshot]);
  const grid = useMemo(() => shiftGrid(pop, hist, breaks, d0), [pop, hist, breaks, d0]);
  const ivByAgent = useMemo(() => {
    const m = new Map<string, ReturnType<typeof intervalsOf>>();
    for (const h of hist.values()) for (const iv of intervalsOf(h)) if (iv.agent_id) (m.get(iv.agent_id) ?? m.set(iv.agent_id, []).get(iv.agent_id)!).push(iv);
    return m;
  }, [hist]);
  const zone = new Map(pop.agents.map((a) => [a.agent_id, a.timezone] as const));
  const name = new Map(pop.agents.map((a) => [a.agent_id, a.agent_name] as const));

  const tot = grid.reduce((a, r) => { for (const c of r.cells) { a.on += c.onShiftSeconds; a.h += c.handlingSeconds; a.b += c.breakSeconds; } return a; }, { on: 0, h: 0, b: 0 });
  const working = grid.filter((r) => r.shifts.length > 0).length;
  const shifts = grid.flatMap((r) => r.shifts.map((sh) => ({ sh, brk: breaks.filter((b) => b.shift_id === sh.shift_id) })))
    .sort((a, b) => a.sh.starts_at - b.sh.starts_at || (a.sh.agent_id < b.sh.agent_id ? -1 : 1));
  const plotW = VW - GUTTER - RIGHT, cw = plotW / 24;
  const x = (sec: number): number => GUTTER + (Math.min(Math.max(sec, d0), d0 + 86400) - d0) / 86400 * plotW;
  const height = TOP + grid.length * PITCH + 10;
  const trans = dst ? parseTs(dst.transition_utc) : null;
  const presets: [string, string][] = dst ? [[dst.saturday, "Saturday of the DST weekend"], [dst.sunday, "Sunday of the DST weekend"], [dayOf(parseTs(dst.saturday + "T00:00:00Z") + 2 * 86400), "Monday after"]] : [];

  return (
    <>
      <form className="toolbar" aria-label="Shift grid settings" onSubmit={(e) => e.preventDefault()}>
        <div className="field field--day">
          <label htmlFor="sday">Day (UTC)</label>
          <div className="daybox">
            <button type="button" className="btn btn--small" aria-label="Previous day" disabled={dayKey <= firstDay} onClick={() => setDay(dayOf(d0 - 86400))}>‹</button>
            <input id="sday" type="date" value={dayKey} min={firstDay} max={lastDay} onChange={(e) => e.target.value && setDay(e.target.value)} />
            <button type="button" className="btn btn--small" aria-label="Next day" disabled={dayKey >= lastDay} onClick={() => setDay(dayOf(d0 + 86400))}>›</button>
          </div>
        </div>
        {presets.length > 0 && (
          <div className="field">
            <span className="field__label">Jump to</span>
            <span className="chips" data-testid="day-presets">{presets.map(([d, l]) => <Link key={d} to={`staffing?day=${d}`} className="btn btn--small" aria-current={d === dayKey ? "true" : undefined} title={l}>{d}</Link>)}</span>
          </div>
        )}
      </form>
      <p className="summary" data-testid="grid-summary">{working} of {grid.length} agents have a shift touching {dayKey} (UTC). Grid hours are UTC; local clock times are in the table.</p>

      <dl className="readouts readouts--light" aria-label="The day in figures">
        <Readout id="on_shift" label="Staffed time" value={d4s(tot.on)} unit=" min" note="on shift minus recorded breaks, inside this UTC day" />
        <Readout id="handling" label="Active handling" value={d4s(tot.h)} unit=" min" note="service intervals inside this day" />
        <Readout id="breaks" label="Recorded breaks" value={d4s(tot.b)} unit=" min" note="from shift_breaks, never capacity" />
        <Readout id="occ" label="Occupancy" value={tot.on > 0 ? fixed(tot.h, tot.on, 6) : null} note="handling / staffed time; no value when nobody is staffed" />
      </dl>

      <div className="chart" data-testid="shift-grid">
        <div className="chart__scroll" tabIndex={0} role="region" aria-label="Shift grid, scrolls sideways on narrow screens">
          <svg className="chart__svg sg" viewBox={`0 0 ${VW} ${height}`} role="img" aria-label={`Shift grid of ${grid.length} agents over 24 hours of ${dayKey}; the table below lists the same shifts`} style={{ minWidth: 760 }}>
            <defs>
              <pattern id="brk" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)"><rect width="5" height="5" className="sg-brk-bg" /><line x1="0" y1="0" x2="0" y2="5" className="sg-brk-line" /></pattern>
            </defs>
            {Array.from({ length: 25 }, (_, h) => (
              <g key={h}>
                <line x1={GUTTER + h * cw} x2={GUTTER + h * cw} y1={TOP - 6} y2={height - 6} className={h % 6 === 0 ? "sg-grid sg-grid--6" : "sg-grid"} />
                {h < 24 && h % 2 === 0 && <text x={GUTTER + h * cw + 3} y={TOP - 12} className="sg-tick">{String(h).padStart(2, "0")}</text>}
              </g>
            ))}
            {grid.map((r, i) => {
              const y = TOP + i * PITCH;
              const z = zone.get(r.agent_id) ?? "";
              return (
                <g key={r.agent_id} data-agent={r.agent_id}>
                  <text x="4" y={y + 14} className="sg-label">{r.agent_id}</text>
                  <text x={GUTTER - 6} y={y + 14} className="sg-label sg-label--z" textAnchor="end">{z.startsWith("Europe") ? "BER" : z.startsWith("America") ? "SCL" : "?"}</text>
                  <rect x={GUTTER} y={y + 1} width={plotW} height={PITCH - 2} className="sg-lane" />
                  {r.cells.map((c, h) => {
                    if (c.onShiftSeconds <= 0 && c.breakSeconds <= 0) return null;
                    const occ = c.onShiftSeconds > 0 ? Math.min(1, c.handlingSeconds / c.onShiftSeconds) : 0;
                    const lvl = occ === 0 ? 0 : occ < 0.25 ? 1 : occ < 0.5 ? 2 : occ < 0.75 ? 3 : 4;
                    return (
                      <g key={h}>
                        <rect x={GUTTER + h * cw + 0.5} y={y + 2} width={cw - 1} height={PITCH - 4} className={`sg-c sg-c--${lvl}${c.onShiftSeconds <= 0 ? " sg-c--off" : ""}`} />
                        {c.onShiftSeconds >= 600 && <text x={GUTTER + h * cw + cw / 2} y={y + 14} textAnchor="middle" className="sg-pct">{pctOf(c.handlingSeconds, c.onShiftSeconds)}</text>}
                      </g>
                    );
                  })}
                  {r.breaks.map(([a, b]) => <rect key={a} x={x(a)} y={y + 2} width={Math.max(2, x(b) - x(a))} height={PITCH - 4} className="sg-brk" />)}
                  {r.shifts.map((sh) => <rect key={sh.shift_id} x={x(sh.starts_at)} y={y + 1} width={Math.max(2, x(sh.ends_at) - x(sh.starts_at))} height={PITCH - 2} className={`sg-shift${(tags.get(sh.shift_id) ?? []).length ? " sg-shift--inj" : ""}`} />)}
                  {r.shifts.length === 0 && <text x={GUTTER + 6} y={y + 14} className="sg-off">off</text>}
                </g>
              );
            })}
            {trans !== null && trans >= d0 && trans <= d0 + 86400 && (
              <g data-testid="dst-marker">
                <line x1={x(trans)} x2={x(trans)} y1={TOP - 6} y2={height - 6} className="sg-dst" />
                <text x={x(trans) + 4} y={height - 10} className="sg-dst-label">{dst!.zone} clocks {fmtOffset(zoneOffsetMinutes(dst!.zone, trans - 1))} to {fmtOffset(zoneOffsetMinutes(dst!.zone, trans))} at {hhmm(trans)}Z</text>
              </g>
            )}
          </svg>
        </div>
      </div>
      <ul className="legend" aria-label="Legend" data-testid="grid-legend">
        {[0, 1, 2, 3, 4].map((l) => <li key={l}><svg width="22" height="12" aria-hidden="true"><rect x="1" y="1" width="20" height="10" className={`sg-c sg-c--${l}`} /></svg> {["no handling", "under 25 %", "25 to 50 %", "50 to 75 %", "75 % and over"][l]}</li>)}
        <li><svg width="22" height="12" aria-hidden="true"><rect x="1" y="1" width="20" height="10" className="sg-brk" /></svg> recorded break</li>
        <li><svg width="22" height="12" aria-hidden="true"><rect x="1" y="1" width="20" height="10" className="sg-shift" /></svg> shift as recorded</li>
        <li><svg width="22" height="12" aria-hidden="true"><rect x="1" y="1" width="20" height="10" className="sg-shift sg-shift--inj" /></svg> shift named in the injection manifest</li>
      </ul>

      <Panel title="The same shifts as a table" id="shift-table-panel">
        <p className="panel__note">Recorded minutes are the real elapsed minutes between two UTC instants (D-02), so a daylight-saving night is not stretched. A shift whose zone changes UTC offset between its start and end is flagged. Occupancy here is handling over the shift's minutes inside this UTC day minus the recorded break; the published metric uses D-05 (break deducted only when the window covers the whole shift).</p>
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Shift table, scrolls sideways on narrow screens">
          <table data-testid="shift-table" className="grid-table">
            <caption className="sr-only">Shifts touching {dayKey}</caption>
            <thead><tr>
              <th scope="col">Agent</th><th scope="col">Shift</th><th scope="col">UTC</th><th scope="col">Local clock</th><th scope="col" className="num">Recorded min</th>
              <th scope="col">Offset</th><th scope="col" className="num">Break min (field / recorded)</th><th scope="col" className="num">Handling in day (min)</th><th scope="col" className="num">Occupancy</th><th scope="col">Notes</th>
            </tr></thead>
            <tbody>
              {shifts.length === 0 && <tr><td colSpan={10}>Nobody was on shift in this UTC day.</td></tr>}
              {shifts.map(({ sh, brk }) => {
                const z = zone.get(sh.agent_id) ?? "UTC";
                const o0 = zoneOffsetMinutes(z, sh.starts_at), o1 = zoneOffsetMinutes(z, sh.ends_at - 1);
                const lo = Math.max(sh.starts_at, d0), hi = Math.min(sh.ends_at, d0 + 86400);
                const brkIn = brk.reduce((a, b) => a + Math.max(0, Math.min(b.ends_at, hi) - Math.max(b.starts_at, lo)), 0);
                const handling = (ivByAgent.get(sh.agent_id) ?? []).reduce((a, iv) => a + secondsWithin(iv, lo, hi), 0);
                const on = Math.max(0, hi - lo - brkIn);
                const brkTotal = brk.reduce((a, b) => a + (b.ends_at - b.starts_at), 0);
                const t = tags.get(sh.shift_id) ?? [];
                return (
                  <tr key={sh.shift_id} data-shift={sh.shift_id} className={t.length ? "is-flag" : ""}>
                    <th scope="row">{sh.agent_id}<span className="sub">{name.get(sh.agent_id)}</span></th>
                    <td><code>{sh.shift_id}</code></td>
                    <td>{dayOf(sh.starts_at).slice(5)} {hhmm(sh.starts_at)} to {dayOf(sh.ends_at).slice(5)} {hhmm(sh.ends_at)}</td>
                    <td>{z}<span className="sub">{localClock(z, sh.starts_at)} to {localClock(z, sh.ends_at)}</span></td>
                    <td className="num">{(sh.ends_at - sh.starts_at) / 60}</td>
                    <td>{o0 === o1 ? fmtOffset(o0) : <strong className="flag">{fmtOffset(o0)} to {fmtOffset(o1)}: crosses the clock change</strong>}</td>
                    <td className="num">{sh.break_minutes} / {brkTotal / 60}</td>
                    <td className="num">{d4s(handling)}</td>
                    <td className="num"><V v={on > 0 ? `${fixed(BigInt(handling) * 100n, on, 1)} %` : null} /></td>
                    <td>{t.length ? <span className="chip chip--alert">{t.join(", ")}</span> : null}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {inj.status === "error" && <p className="small muted">The injection manifest could not be read ({inj.error}); shifts are shown without defect tags.</p>}
        {tags.size > 0 && <p className="small">A shift tagged INJ-08 is the defect planted in the Santiago night crew's Saturday: its recorded length is 480 minutes where the real shift crossing the clock change is 420. INJ-05 shifts carry <code>break_minutes</code> 0 although a break was taken (recorded in <code>shift_breaks</code>).</p>}
      </Panel>
      <Definition items={[RULES.occupancy, { name: "Shifts and daylight saving", rule: "D-02, D-07", text: "All instants are UTC and shift length is the difference between two instants, so a daylight-saving day never stretches or shrinks a shift. Santiago moves from UTC-04:00 to UTC-03:00 at 2026-09-06T04:00Z; the night crew's Saturday shift is 420 real minutes." }]} />
    </>
  );
}
