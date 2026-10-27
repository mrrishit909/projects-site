import { useMemo } from "react";
import { CohortGrid } from "../components/charts";
import { Chip, CutoffPicker, Choice, Def, Fig, ViewHead, WithData, useCutoff } from "../components/ui";
import type { Dataset } from "../data/dataset";
import { Ctx, GRID_COLUMNS, retentionGrid } from "../domain/metrics";
import { dayIso, isoZ, weekdayOf } from "../domain/time";
import { useParam } from "../router";
import { n0, pct } from "../lib/format";

const ZONES = ["all", "America/New_York", "America/Los_Angeles", "Europe/London"];

function Cohorts({ ds }: { ds: Dataset }) {
  const [cut, options, setCut] = useCutoff(ds);
  const [tz, setTz] = useParam("tz", "all");
  const zone = ZONES.includes(tz) ? tz : "all";
  const comp = ds.at(cut.at);
  const rows = useMemo(() => {
    const allowed = zone === "all" ? null : new Set(ds.population.accounts.filter((a) => a.timezone === zone).map((a) => a.account_id));
    const ctx = new Ctx(ds.population, cut.at, ds.canonAt(cut.at), allowed);
    return retentionGrid(ctx, [...ctx.signupAt.keys()], (_a, d) => d - weekdayOf(d));
  }, [ds, cut.at, zone]);
  const r = comp.metrics.retention;
  const blank = rows.reduce((n, x) => n + Object.values(x.cells).filter((c) => c.mature_accounts === 0).length, 0);
  const columns = GRID_COLUMNS.map((c) => ({ name: c.name, from_day: c.lo, to_day: c.hi }));
  return (
    <>
      <ViewHead eyebrow="Cohort laboratory" title="Who comes back, and when we can tell">
        <p className="lede">Accounts grouped by the week they signed up, in the calendar of their own timezone. A cell is filled only when its day has fully passed at the cutoff; until then it is blank, not zero.</p>
      </ViewHead>
      <div className="controls">
        <CutoffPicker options={options} value={cut.value} onChange={setCut} />
        <Choice name="tz" legend="Calendar and accounts" value={zone} onChange={setTz} testid="tz-picker" options={ZONES.map((z) => ({ value: z, label: z === "all" ? "All accounts, each in its own timezone" : z }))} />
      </div>
      <section className="block" aria-labelledby="grid">
        <h2 id="grid">Retention by signup week at {isoZ(cut.at)}</h2>
        <p className="legend" data-testid="legend"><Chip v="OK">filled</Chip> every account of the week is mature · <span className="swatch swatch--partial" aria-hidden="true" /> <strong>partial*</strong> only some accounts are mature (the cell counts the mature ones) · <span className="swatch swatch--blank" aria-hidden="true" /> <strong>blank</strong> immature, no account has reached the day. {n0(blank)} blank cell{blank === 1 ? "" : "s"} here.</p>
        <CohortGrid rows={rows} columns={columns} weekLabel={dayIso} />
        <p className="muted">Each cell is retained ÷ mature accounts of that signup week: <Def term="exact day vs. on-or-after">Day N is an exact calendar day in the account's timezone (day 0 is the signup day): a session that starts on that date. "Day 7 or later" is a separate figure and is never mixed into day 7. Days 28 to 34 are the week-4 window. Maturity: day N is mature once day N+1 has begun in the account's timezone.</Def> Internal accounts and bots are excluded; sessions after the cutoff do not exist for the run.</p>
      </section>
      <section className="block" data-testid="cohort-window">
        <h2>The contract's cohort window</h2>
        <p className="muted">Signup dates [{r.signup_window.from}, {r.signup_window.to}) in each account's calendar: {r.cohort_accounts} accounts, {r.excluded_internal_accounts} internal excluded.</p>
        <dl className="facts">
          <div><dt>Day-7 retention (exactly day 7)</dt><dd><Fig k="retention.day7">{r.day7.rate ?? "n/a"}</Fig> <span className="muted mono">{r.day7.retained} of {r.day7.mature_accounts} mature ({pct(r.day7.rate)}); {r.day7.immature_excluded} immature</span></dd></div>
          <div><dt>On or after day 7 (a separate figure)</dt><dd><Fig k="retention.on_or_after">{r.on_or_after_day7.rate ?? "n/a"}</Fig> <span className="muted mono">{r.on_or_after_day7.retained} of {r.on_or_after_day7.mature_accounts}</span></dd></div>
          <div><dt>Week-4 retention (days 28 to 34)</dt><dd><Fig k="retention.week4">{r.week4.rate ?? "n/a"}</Fig> <span className="muted mono">{r.week4.retained} of {r.week4.mature_accounts} mature; {r.week4.immature_excluded} immature</span></dd></div>
        </dl>
      </section>
    </>
  );
}
export function CohortsView() { return <WithData>{(ds) => <Cohorts ds={ds} />}</WithData>; }
