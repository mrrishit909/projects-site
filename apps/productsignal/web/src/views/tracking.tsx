import { useEffect, useState } from "react";
import { Link } from "../components/link";
import { Chip, CutoffPicker, Def, Fig, NotBuilt, Scroll, ViewHead, WithData, useCutoff } from "../components/ui";
import type { Dataset } from "../data/dataset";
import { fr, q6, ratio } from "../domain/num";
import { isoZ } from "../domain/time";
import { n0 } from "../lib/format";

interface Injection { id: string; test: string; handling_kind: string; entity: string; description: string; expected_handling: string }
const KIND_TEXT: Record<string, string> = {
  excluded_and_counted: "handled by the domain: excluded and counted", merged: "handled by the domain: merged", late_event: "handled by the domain: a late event changes a later run only",
  accepted_time_aware: "handled by the domain: accepted, time-aware", accepted_separate_figures: "handled by the domain: kept as separate figures",
  replay_only: "an API replay (Mode A): not run in the static site",
};

function Injections() {
  const [state, setState] = useState<{ status: "loading" } | { status: "error"; error: string } | { status: "ready"; list: Injection[] }>({ status: "loading" });
  useEffect(() => {
    let live = true;
    fetch(`${import.meta.env.BASE_URL}data/injection-manifest.json`).then(async (r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = (await r.json()) as { injections?: Injection[] };
      if (!Array.isArray(j.injections)) throw new Error("no injections array");
      if (live) setState({ status: "ready", list: j.injections });
    }).catch((e: unknown) => { if (live) setState({ status: "error", error: e instanceof Error ? e.message : String(e) }); });
    return () => { live = false; };
  }, []);
  if (state.status === "loading") return <p className="notice" role="status">Loading the injection manifest…</p>;
  if (state.status === "error") return <p className="notice notice--bad" role="alert">The injection manifest did not load: {state.error}</p>;
  const replay = state.list.filter((i) => i.handling_kind === "replay_only").length;
  return (
    <>
    <p className="muted" data-testid="injection-summary">{state.list.length} known problems ({state.list[0]?.id} to {state.list[state.list.length - 1]?.id}) were planted in the snapshot so each rule has something to catch. The domain handles the {state.list.length - replay} that live in the data; the other {replay} are request sequences against the API in Mode A. <Chip v="simulated">not replayed here</Chip></p>
    <Scroll label="Injected tracking problems">
      <table data-testid="injections">
        <thead><tr><th scope="col">Id</th><th scope="col">Test</th><th scope="col">What was injected</th><th scope="col">Handling</th></tr></thead>
        <tbody>{state.list.map((i) => <tr key={i.id} data-injection={i.id}><th scope="row" className="mono">{i.id}</th><td className="mono">{i.test}</td><td className="basis">{i.description}</td><td className="basis">{KIND_TEXT[i.handling_kind] ?? i.handling_kind}</td></tr>)}</tbody>
      </table>
    </Scroll>
    </>
  );
}

function Tracking({ ds }: { ds: Dataset }) {
  const [cut, options, setCut] = useCutoff(ds);
  const c = ds.at(cut.at);
  const tq = c.tracking_quality, id = c.identity;
  const share = (n: number, d: number): string => q6(ratio(n, d) ?? fr(0)) ?? "n/a";
  const rows: { key: string; label: string; n: number; note: string }[] = [
    { key: "rows_total", label: "Rows in the event log", n: tq.rows_total, note: "every well-formed row; the log is append-only" },
    { key: "received_after_cutoff", label: "Received after the cutoff", n: tq.received_after_cutoff, note: "not in this run" },
    { key: "duplicates_dropped", label: "Duplicates dropped", n: tq.duplicates_dropped, note: "re-sent under a new id with the same user, name, instant and properties" },
    { key: "canonical", label: "Canonical events", n: tq.canonical, note: "received by the cutoff, after de-duplication" },
    { key: "delayed_over_24h", label: "Delayed more than 24 h", n: tq.delayed_over_24h, note: "received_at − event_at > 24 h; kept, because event_at is the business instant" },
    { key: "unknown_identity", label: "Unknown identity", n: tq.unknown_identity, note: "excluded" },
    { key: "bot_events_excluded", label: "Bot events", n: tq.bot_events_excluded, note: "excluded" },
    { key: "internal_events_excluded", label: "Internal-account events", n: tq.internal_events_excluded, note: "excluded" },
    { key: "analysed", label: "Analysed events", n: tq.analysed, note: "what every metric reads" },
  ];
  return (
    <>
      <ViewHead eyebrow="Tracking quality" title="Can the events be trusted?">
        <p className="lede">The counts behind every figure: what was dropped, delayed or excluded before a metric was computed. Late events change a later run, never a published one.</p>
      </ViewHead>
      <CutoffPicker options={options} value={cut.value} onChange={setCut} />
      <section className="block" aria-labelledby="tq">
        <h2 id="tq">Event log at {isoZ(cut.at)}</h2>
        <Scroll label="Tracking quality">
          <table data-testid="tracking-table">
            <thead><tr><th scope="col">Figure</th><th scope="col" className="num">Events</th><th scope="col" className="num">Share of log rows</th><th scope="col">Meaning</th></tr></thead>
            <tbody>{rows.map((r) => <tr key={r.key} data-tq={r.key}><th scope="row">{r.label}</th><td className="num mono" data-k="n">{n0(r.n)}</td><td className="num mono">{share(r.n, tq.rows_total)}</td><td className="basis">{r.note}</td></tr>)}</tbody>
          </table>
        </Scroll>
      </section>
      <section className="block" data-testid="identity-block">
        <h2>Identity resolution</h2>
        <p>Anonymous events analysed: <Fig k="anonymous_events">{n0(id.anonymous_events)}</Fig>; attributed to a user by a link, only for events at or after the link: <Fig k="attributed">{n0(id.attributed_by_link)}</Fig>; still anonymous: <Fig k="remain">{n0(id.remain_anonymous)}</Fig>. <Def term="time-aware identity">A link attributes an anonymous id's events to a user only from linked_at onward; events before the link stay anonymous. The earliest link of an anonymous id fixes its user.</Def></p>
      </section>
      <section className="block" aria-labelledby="inj">
        <h2 id="inj">What the generator injected on purpose</h2>
        <Injections />
      </section>
      <NotBuilt>Live event ingestion, the replay of the API request sequences, and any editing of the event log. The log is a published file, read-only. <Link to="evidence">Evidence</Link> lists what the browser does verify.</NotBuilt>
    </>
  );
}
export function TrackingView() { return <WithData>{(ds) => <Tracking ds={ds} />}</WithData>; }
