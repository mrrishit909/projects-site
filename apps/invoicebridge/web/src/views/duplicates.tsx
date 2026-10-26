import { useMemo } from "react";
import type { PipelineResult } from "../domain/pipeline";
import { ViewHead } from "../components/layout";
import { Chip, Def, InvoiceLink, Scroll, usePager, WithData } from "../components/ui";
import { pct, short } from "../lib/format";
import { useParam } from "../router";

const monthEndDays = (sec: number): boolean => {
  const d = new Date(sec * 1000);
  const last = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0)).getUTCDate();
  return d.getUTCDate() >= last - 2;
};

function Dups({ result }: { result: PipelineResult }) {
  const [reason, setReason] = useParam("reason", "all");
  const b = result.book, m = result.metrics;
  const groups = useMemo(() => {
    const g = new Map<string, { canonical: string; members: { id: string; reason: string; key: string }[] }>();
    for (const r of b.mergedRecords) (g.get(r.merged_into) ?? g.set(r.merged_into, { canonical: r.merged_into, members: [] }).get(r.merged_into)!).members.push({ id: r.id, reason: r.reason_code, key: r.group_key });
    return [...g.values()].sort((x, y) => (x.canonical < y.canonical ? -1 : 1));
  }, [b]);
  const rows = groups.filter((g) => reason === "all" || g.members.some((x) => x.reason === reason));
  const { page, ui } = usePager(rows, 20);
  const byReason = (c: string): number => b.mergedRecords.filter((r) => r.reason_code === c).length;
  const identity = b.mergedRecords.filter((r) => r.reason_code === "DUPLICATE_IDENTITY");
  const resentMonthEnd = identity.filter((r) => monthEndDays(b.invoices.get(r.id)!.imported_at)).length;
  const allMonthEnd = [...b.invoices.values()].filter((i) => monthEndDays(i.imported_at)).length;
  return (
    <>
      <dl className="glance" data-testid="dup-summary">
        <div data-figure="duplicates.groups_detected"><dt>Groups detected</dt><dd>{m.duplicates.groups_detected}<small>counted once</small></dd></div>
        <div data-figure="duplicates.rows_merged"><dt>Rows merged</dt><dd>{m.duplicates.rows_merged}</dd></div>
        <div data-figure="duplicates.unresolved_groups"><dt>Unresolved groups</dt><dd>{m.duplicates.unresolved_groups}<small>exact identity merges automatically</small></dd></div>
        <div><dt>By identity</dt><dd>{byReason("DUPLICATE_IDENTITY")}<small>different bytes, same obligation</small></dd></div>
        <div><dt>By same bytes</dt><dd>{byReason("DUPLICATE_SOURCE_BYTES")}<small>same file, other name</small></dd></div>
      </dl>
      <section className="panel" aria-labelledby="dr3-h">
        <h2 id="dr3-h">Re-sent PDFs cluster at month ends</h2>
        <p data-testid="dr3">{resentMonthEnd} of {identity.length} identity duplicates ({pct(resentMonthEnd, identity.length)}) were imported in the last three days of a month, against {pct(allMonthEnd, b.invoices.size)} of all invoices. This is a pattern planted in the synthetic data; the site recomputes it from the import times.</p>
      </section>
      <section className="panel" aria-labelledby="g-h">
        <h2 id="g-h">Groups <Def term="what a group is">A group is the canonical (earliest) invoice and every later import merged into it. Detection is an exact rule, not a similarity score: near-duplicates with a different number, date or total are different obligations here.</Def></h2>
        <div className="filters"><label>Rule <select value={reason} onChange={(e) => setReason(e.target.value)} data-testid="f-reason"><option value="all">All rules</option><option value="DUPLICATE_IDENTITY">DUPLICATE_IDENTITY</option><option value="DUPLICATE_SOURCE_BYTES">DUPLICATE_SOURCE_BYTES</option></select></label></div>
        <Scroll label="Duplicate groups">
          <table className="grid" data-testid="dup-table">
            <caption className="sr">Duplicate groups</caption>
            <thead><tr><th scope="col">Canonical</th><th scope="col">Merged into it</th><th scope="col">Rule</th><th scope="col">Group key</th></tr></thead>
            <tbody>{page.map((g) => (
              <tr key={g.canonical}>
                <td><InvoiceLink id={g.canonical} /></td>
                <td>{g.members.map((x, i) => <span key={x.id}>{i > 0 && ", "}<InvoiceLink id={x.id} /></span>)}</td>
                <td>{[...new Set(g.members.map((x) => x.reason))].map((x) => <Chip key={x} v={x} />)}</td>
                <td className="mono" title={g.members[0]!.key}>{short(g.members[0]!.key, 44)}</td>
              </tr>))}</tbody>
          </table>
        </Scroll>
        {ui}
      </section>
    </>
  );
}
export function DuplicatesView() {
  return (
    <>
      <ViewHead eyebrow="Read-only view" title="Duplicate groups">
        <p className="lede">The same obligation arriving more than once, merged into the earliest copy. The merge keeps the later row and its source hash as lineage and consumes no received quantity.</p>
      </ViewHead>
      <WithData>{({ result }) => <Dups result={result} />}</WithData>
    </>
  );
}
