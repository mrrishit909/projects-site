import { Diverging } from "../components/charts";
import { Chip, Fig, ParamSelect, Related, Scroll, ScopeStrip, ViewHead, WithData } from "../components/ui";
import { Link } from "../components/link";
import type { Dataset } from "../data/dataset";
import { MODELS } from "../domain/contract";
import { contributions, queueAt, rankScored } from "../lib/account";
import { minus, n0, orDash } from "../lib/format";
import { useParam } from "../router";

export function AccountView() {
  return <WithData>{(ds) => <Account ds={ds} />}</WithData>;
}

function Account({ ds }: { ds: Dataset }) {
  const w = ds.primary.world;
  const qat = queueAt(ds);
  const ranked = rankScored(ds, qat);
  const accounts = ranked.map((r) => r.account_id);
  const [sel] = useParam("account", String(accounts[0] ?? ""));
  const account = accounts.map(String).includes(sel) ? sel : String(accounts[0] ?? "");
  const acct = accounts.find((a) => String(a) === account);
  // the cutoffs at which this account was scored, newest first
  const cutoffs = acct === undefined ? [] : w.acc.prediction_cutoffs.filter((c) => c["account_id"] === acct && w.pred(ds.runId, c["cutoff_id"])).map((c) => c["prediction_at"] as string).sort().reverse();
  const [at0] = useParam("cutoff", cutoffs[0] ?? "");
  const at = cutoffs.includes(at0) ? at0 : (cutoffs[0] ?? "");
  const row = acct === undefined || !at ? null : w.setRows(at).find((r) => r.account_id === acct) ?? null;
  const pr = row ? w.pred(ds.runId, row.cutoff_id) : undefined;
  const rankAt = row ? rankScored(ds, at) : [];
  const rank = row ? rankAt.findIndex((r) => r.cutoff_id === row.cutoff_id) + 1 : 0;
  const run = w.runs.get(ds.runId);
  const contrib = row?.features ? contributions(run?.["config"], row.features) : null;
  const a = acct === undefined ? undefined : w.accounts.get(acct);
  if (accounts.length === 0 || !row || !pr) return <><ViewHead mark="07 · Account" title="Account explanation" contracts="P10-FLOW-07, P10-FLOW-08, P10-TEST-09"><p className="notice" data-testid="no-account">This dataset has no scored account to explain.</p></ViewHead><Related /></>;
  const others = ds.modelKeys.map((m) => ({ m, p: ds.evals[m]!.world.pred(ds.runId, row.cutoff_id)?.["probability"] as string | undefined }));
  return (
    <>
      <ViewHead mark="07 · Account" title="Account explanation" contracts="P10-FLOW-07, P10-FLOW-08, P10-TEST-09, P10-DOMAIN-05">
        <p className="lede">Why does the model rank this account where it does? The factors below are the fitted model's own arithmetic on this account's features. They describe an association in the data; they do not say why the account would leave, and they do not say what would keep it.</p>
      </ViewHead>
      <ScopeStrip ds={ds} items={[["account", String(acct)], ["cutoff", at.slice(0, 10)], ["model", ds.id === "snapshot" ? "logistic regression, before Platt scaling for the factors" : "frozen predictions"], ["queue date", qat.slice(0, 10)]]} />
      <div className="controls">
        <ParamSelect name="account" label={`Account (the ${n0(accounts.length)} scored at ${qat.slice(0, 10)}, riskiest first)`} dflt={String(accounts[0])} options={accounts.map((x, i) => ({ value: String(x), label: `${x} (rank ${i + 1})` }))} testid="account-select" />
        <ParamSelect name="cutoff" label="Cutoff" dflt={cutoffs[0] ?? ""} options={cutoffs.map((c) => ({ value: c, label: c.slice(0, 10) }))} testid="cutoff-select" />
      </div>
      <div className="grid" data-testid="account-figures">
        <div className="card"><div className="big"><Fig k="risk">{pr["probability"]}</Fig><small>risk: the frozen probability of cancelling within {ds.inputs["label_version"]["horizon_days"]} days</small></div></div>
        <div className="card"><div className="big"><Fig k="rank">{rank}</Fig><small>of {n0(rankAt.length)} scored eligible accounts at {at.slice(0, 10)} (risk descending, ties by account id)</small></div></div>
        <div className="card"><div className="big"><Fig k="outcome">{row.mature ? (row.churned ? "churned" : "stayed") : "unknown"}</Fig><small>{row.mature ? "outcome in the closed window" : "censored: the outcome window is still open, so it is not counted as staying"}</small></div></div>
        <div className="card"><div className="big"><Fig k="plan">{a ? `${a["segment"]} · ${a["region"]}` : "—"}</Fig><small>plan and region</small></div></div>
      </div>
      <section aria-labelledby="fac-h">
        <h2 id="fac-h">Risk factors, as the model arithmetic</h2>
        {contrib ? (
          <>
            <div className="two">
              <figure className="figure">
                <Diverging rows={contrib.terms.map((t) => ({ label: t.term, value: t.value }))} caption={`Signed contributions to the log-odds of account ${String(acct)} at ${at.slice(0, 10)}`} />
                <figcaption>Coral bars push the model's log-odds up, teal bars push it down. Unit: log-odds, six places. The terms add up to the model's log-odds <Fig k="logit">{minus(contrib.logit)}</Fig> before Platt scaling.</figcaption>
              </figure>
              <div>
                <p className="note" data-testid="no-causal"><strong>Not a cause, not a cure.</strong> A factor that raises the score is correlated with leaving in the training data. It is not shown to cause leaving, and a high risk is not treatment responsiveness: nothing here says this account would respond to an offer.</p>
                <p>Each term is the coefficient times the standardised feature (value minus the training mean, over the training deviation). A missing value takes the training median and the missing-indicator coefficient applies.</p>
              </div>
            </div>
            <Scroll label="Contributions to the log-odds">
              <table data-testid="contributions">
                <caption>Ordered by the size of the contribution, then in the registry's order.</caption>
                <thead><tr><th scope="col">Term</th><th scope="col">Contribution to log-odds</th><th scope="col">How it was computed</th></tr></thead>
                <tbody>{contrib.terms.map((t) => <tr key={t.term} data-term={t.term}><td className="l">{t.term}</td><td data-k="value" className={t.value.startsWith("-") ? "pos" : "neg"}>{minus(t.value)}</td><td className="t">{t.detail}</td></tr>)}</tbody>
              </table>
            </Scroll>
          </>
        ) : <p className="notice" data-testid="no-factors">This dataset carries no preprocessing statistics, so the factors cannot be computed; only the frozen risk is shown.</p>}
      </section>
      <section aria-labelledby="feat-h">
        <h2 id="feat-h">Features at the cutoff, and the same row under each model</h2>
        <Scroll label="Features and model risks">
          <table data-testid="account-features">
            <caption>Feature values as of the cutoff (point in time) and the frozen risk of each model for this row.</caption>
            <thead><tr><th scope="col">Item</th><th scope="col">Value</th></tr></thead>
            <tbody>
              {Object.entries(row.features ?? {}).map(([k, v]) => <tr key={k}><td className="l">{k}</td><td>{v === null ? "— (missing)" : String(v)}</td></tr>)}
              {others.filter((o) => o.p !== undefined).map((o) => <tr key={o.m}><td className="l">risk, {o.m.replace(/_/g, " ")}</td><td data-k={`risk-${o.m}`}>{orDash(o.p ?? null)}</td></tr>)}
              <tr><td className="l">events that arrived after the cutoff (excluded)</td><td>{row.arrived_late ? Object.values(row.arrived_late).reduce((x, y) => x + y, 0) : 0}</td></tr>
            </tbody>
          </table>
        </Scroll>
        <p>The features are rebuilt point-in-time from the events (see <Link to="features">feature evidence</Link>); this account's place in the draft queue is on <Link to="queue">the outreach queue</Link>. <Chip kind="hatch">{MODELS.length} models scored it</Chip></p>
      </section>
      <Related also={["queue", "features"]} />
    </>
  );
}
