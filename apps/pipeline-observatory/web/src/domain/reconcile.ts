// Publication scope, reconciliation with signed exclusions, late events behind the watermark, verified recovery (D-02, D-03, D-P8-05/06/09).
import type { Row } from "./contract";
import { contentHash } from "./hashing";
import { m4, money, ratio, ZERO, add, sub, sumFr, type Fr } from "./num";
import { cmpTuple, sortedBy } from "./py";
import { isoZ, parseTs, secondsBetween } from "./time";

/** An accepted record of a committed batch with its arrival (the checkpoint commit instant of its batch). */
export interface Accepted {
  source_id: string; batch_id: string; key: unknown; event_at: string; arrival: string | null; raw_record_id: string; payload_hash: string; amount: Fr;
  /** The batch whose delete event removed this record from the published snapshot. */
  deleted_in: string | null;
}
/** The records a publication shows: accepted records of its included batches, minus those a delete event of an included batch removed. */
export function publishedRecords(accepted: Iterable<Accepted>, included: Iterable<string>): Accepted[] {
  const inc = new Set(included);
  const out: Accepted[] = [];
  for (const a of accepted) if (inc.has(a.batch_id) && !(a.deleted_in && inc.has(a.deleted_in))) out.push(a);
  return out;
}
export interface Reconciliation { source_total: string; published_total: string; exclusions: { quarantined: string; duplicates: string; deletes: string }; exclusions_total: string; residual: string }
/** Residual = source total - published total - explained exclusions. `srcRows` is (disposition, amount) for every received row of the included
 * batches. Exclusions are signed sums: quarantined, duplicates and deletes (the delete rows' amounts plus the records they remove).
 * `publishedTotal` is the total of the stored published table when the caller has one; otherwise the sum of the published records. */
export function reconcile(srcRows: [string, Fr][], pub: Accepted[], deleteRowsAmount: Fr, removed: Accepted[], publishedTotal: Fr | null = null): Reconciliation {
  const src = sumFr(srcRows.map(([, a]) => a));
  const published = publishedTotal !== null ? publishedTotal : sumFr(pub.map((a) => a.amount));
  const q = sumFr(srcRows.filter(([k]) => k === "quarantined").map(([, a]) => a));
  const d = sumFr(srcRows.filter(([k]) => k === "duplicate").map(([, a]) => a));
  const del = add(deleteRowsAmount, sumFr(removed.map((a) => a.amount)));
  const total = add(add(q, d), del);
  return { source_total: money(src), published_total: money(published), exclusions: { quarantined: money(q), duplicates: money(d), deletes: money(del) },
    exclusions_total: money(total), residual: money(sub(sub(src, published), total)) };
}
export function publicationView(pub: Row, pubd: Accepted[]): { latest: string | null; content_hash: string; lag_seconds: number | null } {
  let latest: string | null = null;
  for (const a of pubd) if (latest === null || parseTs(a.event_at) > parseTs(latest)) latest = a.event_at;
  return { latest, content_hash: contentHash(pubd.map((a) => a.payload_hash)), lag_seconds: latest ? secondsBetween(latest, pub["published_at"]) : null };
}
export interface LateEvent { source_id: string; source_key: unknown; batch_id: string; event_at: string | null; arrival_at: string | null; behind_publication_id: string; watermark: string | null; included_in_publication_id: string | null }
/** An accepted record whose batch committed after the published_at of the latest earlier publication covering its source, and whose event_at
 * is not after that publication's watermark (D-P8-09). Next publication = the first later one that includes its batch. */
export function lateEvents(accepted: Accepted[], pubs: Row[]): LateEvent[] {
  const ordered = sortedBy(pubs, (p) => [parseTs(p["published_at"]), p["publication_id"] as string]).map((p) => ({ p, at: parseTs(p["published_at"]), wm: parseTs(p["watermark"]) }));
  const bySource = new Map<string, typeof ordered>();
  const byBatch = new Map<string, typeof ordered>();
  for (const o of ordered) {
    for (const s of new Set<string>(o.p["source_ids"])) (bySource.get(s) ?? bySource.set(s, []).get(s)!).push(o);
    for (const b of new Set<string>(o.p["included_batch_ids"])) (byBatch.get(b) ?? byBatch.set(b, []).get(b)!).push(o);
  }
  const out: LateEvent[] = [];
  for (const a of accepted) {
    if (a.arrival === null) continue;
    const arrived = parseTs(a.arrival);
    const list = bySource.get(a.source_id) ?? [];
    let lo = 0, hi = list.length;                                        // the last publication of the source published before the arrival
    while (lo < hi) { const mid = (lo + hi) >> 1; if (list[mid]!.at < arrived) lo = mid + 1; else hi = mid; }
    if (lo === 0) continue;
    const before = list[lo - 1]!;
    if (parseTs(a.event_at) <= before.wm) {
      const nxt = (byBatch.get(a.batch_id) ?? []).find((q) => q.at > arrived);
      out.push({ source_id: a.source_id, source_key: a.key, batch_id: a.batch_id, event_at: isoZ(a.event_at), arrival_at: isoZ(a.arrival), behind_publication_id: before.p["publication_id"],
        watermark: isoZ(before.p["watermark"]), included_in_publication_id: nxt ? nxt.p["publication_id"] : null });
    }
  }
  return sortedBy(out, (x) => [parseTs(x.arrival_at), String(x.source_key)]);
}
/** The first run starting at or after `openedAt` that succeeded, passed its gate, published, and whose publication reconciles to 0.00 (D-P8-06). */
export function verifiedRecovery(openedAt: string, runs: Row[], gateOf: Record<string, string>, pubOfRun: Record<string, string>, residualOfPub: Record<string, string>): { run: Row; publication_id: string } | null {
  const opened = parseTs(openedAt);
  for (const run of sortedBy(runs, (r) => [parseTs(r["started_at"]), r["run_id"] as string])) {
    const pid = pubOfRun[run["run_id"]];
    if (parseTs(run["started_at"]) >= opened && run["status"] === "success" && gateOf[run["run_id"]] === "allowed" && pid && residualOfPub[pid] === "0.00") return { run, publication_id: pid };
  }
  return null;
}
export const recoveryMinutes = (seconds: number | null): string | null => (seconds === null ? null : m4(ratio(seconds, 60)));
export const meanMinutes = (totalSeconds: number, n: number): string | null => (n ? m4(ratio(totalSeconds, 60 * n)) : null);
export { ZERO, cmpTuple };
