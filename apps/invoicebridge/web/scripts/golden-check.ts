// Golden check: the TypeScript domain must reproduce the hand-derived oracle (expected.json) key by key for the golden fixture
// and its two variants, the per-entity golden copy the site serves (through the same loader code as the browser), the spec
// sentence in words, the arithmetic and SHA-256 primitives, and the PYTHON domain's results over the published snapshot
// (scripts/snapshot-reference.json, produced once by scripts/make-snapshot-reference.py). Prints "ALL OK (N checks)" or exits 1.
import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { buildInputs, isManifest, INPUT_ENTITIES, EXTRA_ENTITIES } from "../src/data/inputs";
import { ENTITIES, EXCEPTION_CODES, METRIC_KEYS } from "../src/domain/contract";
import { importSequence } from "../src/domain/duplicates";
import { documents, goldenOf, runPipeline } from "../src/domain/pipeline";
import { fmt, fracStr, parseDec, roundDiv } from "../src/domain/num";
import { sha256, sha256Bytes } from "../src/domain/sha256";
import { invoiceView } from "../src/domain/view";
import { isoZ, parseTs } from "../src/domain/time";
import type { PipelineInputs } from "../src/domain/types";

const ROOT = new URL("../../", import.meta.url);
const WEB = new URL("../", import.meta.url);
const readJson = (u: URL): any => JSON.parse(readFileSync(u, "utf8"));

let failures = 0, checks = 0;
const canon = (v: unknown): string => JSON.stringify(v, (_k, x) =>
  x && typeof x === "object" && !Array.isArray(x) ? Object.fromEntries(Object.entries(x).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))) : typeof x === "bigint" ? x.toString() : x);
function eq(label: string, got: unknown, want: unknown): void {
  checks++;
  if (canon(got) === canon(want)) console.log(`OK       ${label}`);
  else { failures++; console.log(`MISMATCH ${label}: got ${canon(got).slice(0, 300)} want ${canon(want).slice(0, 300)}`); }
}
const yes = (label: string, cond: boolean, detail = ""): void => { checks++; if (cond) console.log(`OK       ${label}`); else { failures++; console.log(`MISMATCH ${label} ${detail}`); } };
// Same canonical form as the Python side (json.dumps(sort_keys=True, separators=(",", ":"))): sorted keys, no spaces.
const digest = (v: unknown): string => createHash("sha256").update(canon(v)).digest("hex");

function checkFixture(name: string, inputs: PipelineInputs, expected: any): void {
  const r = runPipeline(inputs);
  const g = goldenOf(r) as any;
  for (const k of METRIC_KEYS) eq(`${name} metric ${k}`, g.metrics[k], expected.metrics[k]);
  eq(`${name} metric key set`, Object.keys(g.metrics).sort(), Object.keys(expected.metrics).sort());
  eq(`${name} metric key order is the contract order`, Object.keys(g.metrics), [...METRIC_KEYS]);
  for (const e of ENTITIES) eq(`${name} ingest counts ${e}`, g.ingest.counts[e], expected.ingest.counts[e]);
  eq(`${name} rejected records (entity, id, status, reason, raw row)`, g.ingest.rejected_records, expected.ingest.rejected_records);
  eq(`${name} merged records`, g.ingest.merged_records, expected.ingest.merged_records);
  eq(`${name} contract_version`, g.contract_version, expected.contract_version);
  eq(`${name} document ids`, Object.keys(g.documents.invoices), Object.keys(expected.documents.invoices));
  for (const id of Object.keys(expected.documents.invoices)) eq(`${name} document ${id}`, g.documents.invoices[id], expected.documents.invoices[id]);
  eq(`${name} match results`, g.documents.match_results, expected.documents.match_results);
  eq(`${name} the whole golden object`, g, expected);
}

// ---- fixtures under tests/fixtures: the golden case and its variants --------------------------------------------------
const fixtureDirs: [string, string][] = [["golden", ""]];
for (const v of ["variant-rejected", "variant-empty"]) if (existsSync(new URL(`tests/fixtures/golden/${v}/inputs.json`, ROOT))) fixtureDirs.push([v, `${v}/`]);
yes("both variants exist under tests/fixtures/golden", fixtureDirs.length === 3);
for (const [name, dir] of fixtureDirs) {
  const base = new URL(`tests/fixtures/golden/${dir}`, ROOT);
  checkFixture(name, readJson(new URL("inputs.json", base)), readJson(new URL("expected.json", base)));
}

// ---- the per-entity copy the site serves, built through the same loader code as the browser -----------------------------
function loadDir(dir: string) {
  const manifest = readJson(new URL(`public/data/${dir}manifest.json`, WEB));
  if (!isManifest(manifest)) throw new Error("manifest is not valid");
  const files = new Map<string, unknown>();
  for (const n of Object.keys(manifest.row_counts)) files.set(n, readJson(new URL(`public/data/${dir}${n}.json`, WEB)));
  return { manifest, files, inputs: buildInputs(manifest, files) };
}
{
  const { manifest, inputs } = loadDir("golden/");
  checkFixture("golden (per-entity copy)", inputs, readJson(new URL("public/data/golden/expected.json", WEB)));
  eq("golden copy equals tests/fixtures expected.json", readJson(new URL("public/data/golden/expected.json", WEB)), readJson(new URL("tests/fixtures/golden/expected.json", ROOT)));
  eq("golden manifest cutoffs", manifest.snapshot_cutoffs, ["2026-10-05T23:00:00Z"]);
  eq("every manifest row_count file is an entity the loader reads", Object.keys(manifest.row_counts).sort(), [...INPUT_ENTITIES, ...EXTRA_ENTITIES].sort());
}

// ---- the spec sentence in words (P05-GOLD-01) ------------------------------------------------------------------------------
{
  const inputs = readJson(new URL("tests/fixtures/golden/inputs.json", ROOT));
  const r = runPipeline(inputs);
  const d = documents(r).invoices;
  eq("P05-GOLD-01 first invoice: 6 x 20.00 = 120.00, tax 12.00, total 132.00", [d["inv-001"]!.subtotal, d["inv-001"]!.tax, d["inv-001"]!.total, d["inv-001"]!.status], ["120.00", "12.00", "132.00", "exported"]);
  const mr = documents(r).match_results as any[];
  eq("second invoice for 4 units is QUANTITY_BLOCKED (available 0, variance 4)", [mr[1].reason_code, mr[1].available_quantity, mr[1].quantity_variance], ["QUANTITY_BLOCKED", "0.0000", "4.0000"]);
  eq("the re-sent PDF (different sha256) is merged into inv-001 by identity", [d["inv-003"]!.status, d["inv-003"]!.merged_into, r.ingest.merged_records[0]!.reason_code], ["merged", "inv-001", "DUPLICATE_IDENTITY"]);
  eq("one obligation of 132.00 results from the pair", [r.metrics.obligations.count, r.metrics.obligations.total], [1, "132.00"]);
  eq("content_hash of the export row", r.metrics.export.rows[0]!.content_hash, createHash("sha256").update("inv-001|ven-001|INV-1001|2026-10-06|USD|132.00").digest("hex"));
  eq("processing time 6.5 h = 390.0000 minutes", r.metrics.processing.mean_minutes, "390.0000");
  const snap = runPipeline(inputs, { asOf: "2026-10-05T23:00:00Z" });
  eq("at 2026-10-05T23:00Z the receipt is in and nothing is invoiced yet: 6.0000 / 120.00 received-not-invoiced", [snap.metrics.quantities.received_not_invoiced_quantity, snap.metrics.quantities.received_not_invoiced_value, snap.metrics.quantities.open_to_invoice_quantity], ["6.0000", "120.00", "10.0000"]);
  const v1 = invoiceView(r, "inv-001")!, v2 = invoiceView(r, "inv-002")!, v3 = invoiceView(r, "inv-003")!;
  eq("view inv-001: matched line, exported, one valid approval by usr-rev01 under pol-v1", [v1.status, v1.lines[0]!.reason_code, v1.approvals[0]!.verdict, v1.approvals[0]!.policy_id, v1.export?.amount], ["exported", null, "COUNTED", "pol-v1", "132.00"]);
  eq("view inv-001 sees inv-003 merged into it", v1.merged_in.map((m) => m.invoice_id), ["inv-003"]);
  eq("view inv-002: QUANTITY_BLOCKED with ordered 10, net received 6, previously invoiced 6, this invoice 4", [v2.lines[0]!.reason_code, v2.lines[0]!.ordered, v2.lines[0]!.net_received, v2.lines[0]!.previously_invoiced, v2.lines[0]!.quantity], ["QUANTITY_BLOCKED", "10.0000", "6.0000", "6.0000", "4.0000"]);
  eq("view inv-003: merged into inv-001, its line is not matched (it consumes nothing)", [v3.status, v3.merged_into, v3.lines.map((l) => l.status)], ["merged", "inv-001", ["not matched"]]);
  const rep = runPipeline(readJson(new URL("tests/fixtures/golden/variant-rejected/inputs.json", ROOT)));
  eq("variant-rejected: the book is unchanged by the rejections (one obligation 132.00, net received 6, accepted invoiced 6)", [rep.metrics.obligations.total, rep.metrics.quantities.net_received_quantity, rep.metrics.quantities.accepted_invoiced_quantity, rep.metrics.rates.straight_through_rate], ["132.00", "6.0000", "6.0000", "1.000000"]);
  const emp = runPipeline(readJson(new URL("tests/fixtures/golden/variant-empty/inputs.json", ROOT)));
  eq("variant-empty: rates and mean processing are null, not zero", [emp.metrics.rates.straight_through_rate, emp.metrics.rates.exception_rate, emp.metrics.processing.mean_minutes], [null, null, null]);
}

// ---- arithmetic and hash primitives ----------------------------------------------------------------------------------------
{
  eq("roundDiv: half away from zero", [roundDiv(5n, 10n), roundDiv(4n, 10n), roundDiv(-5n, 10n), roundDiv(15n, 10n), roundDiv(25n, 10n), roundDiv(-14n, 10n)], [1n, 0n, -1n, 2n, 3n, -1n]);
  eq("fracStr: half up at 6 dp and 4 dp", [fracStr(1n, 3n, 6), fracStr(2n, 3n, 6), fracStr(1n, 2n, 0), fracStr(5n, 20000n, 4), fracStr(0n, 7n, 4), fracStr(1n, 1n, 6)], ["0.333333", "0.666667", "1", "0.0003", "0.0000", "1.000000"]);
  eq("fmt pads and signs", [fmt(5n, 2), fmt(-5n, 2), fmt(12345n, 4), fmt(7n, 0), fmt(0n, 2)], ["0.05", "-0.05", "1.2345", "7", "0.00"]);
  eq("parseDec accepts strings and integers, pads decimals", [parseDec("10", "q", 4), parseDec("20.00", "p", 6), parseDec(" 1.5000 ", "q", 4), parseDec("0.100000", "r", 6)], [100000n, 20000000n, 15000n, 100000n]);
  for (const bad of [1.5, "1.23456", "abc", "", "1e3", true, null, "1000000000000.00"]) {
    let code = "";
    try { parseDec(bad, "x", 4); } catch (e) { code = (e as { code?: string }).code ?? "other"; }
    yes(`parseDec refuses ${JSON.stringify(bad)} (MALFORMED_RECORD, never rounded)`, code === "MALFORMED_RECORD");
  }
  // tax rounding at document level on the unrounded subtotal, half up: 3 lines of 0.333333 x 3 at 10.5 %
  const mk = (qty: string, price: string, rate: string, n = 3): PipelineInputs => ({
    vendors: [{ vendor_id: "v", vendor_name: "V", tax_reference: "t", currency: "USD", active: true }],
    purchase_orders: [{ po_id: "p", vendor_id: "v", ordered_at: "2026-01-01T00:00:00Z", status: "open", currency: "USD" }],
    po_lines: Array.from({ length: n }, (_, i) => ({ po_line_id: `pl${i}`, po_id: "p", product_code: "X", quantity: "100", unit_price: price })),
    receipts: Array.from({ length: n }, (_, i) => ({ receipt_id: `r${i}`, po_line_id: `pl${i}`, received_quantity: "100", received_at: "2026-01-02T00:00:00Z", reversed: false })),
    invoices: [{ invoice_id: "i", vendor_id: "v", invoice_number: "A", invoice_date: "2026-01-03", currency: "USD", tax_rate: rate, freight: "1.00", invoice_discount: "0.50", declared_total: "0.00", created_by: "u", source_sha256: "a".repeat(64), source_filename: "a.pdf", idempotency_key: "k", imported_at: "2026-01-03T00:00:00Z" }],
    invoice_lines: Array.from({ length: n }, (_, i) => ({ invoice_line_id: `l${i}`, invoice_id: "i", po_line_id: `pl${i}`, quantity: qty, unit_price: price })),
    approval_policies: [], approvals: [], export_requests: [],
  });
  const t = documents(runPipeline(mk("1.0000", "0.333333", "0.105000"))).invoices["i"]!;
  eq("multi-line tax is document level: 3 x 0.333333 = 0.999999 -> 1.00, tax 0.104999895 -> 0.10, total 1.00 + 0.10 + 1.00 - 0.50", [t.subtotal, t.tax, t.total], ["1.00", "0.10", "1.60"]);
  const t2 = documents(runPipeline(mk("1.0000", "0.005000", "0.500000", 1))).invoices["i"]!;
  eq("0.005 rounds half up to 0.01 (subtotal), tax 0.0025 -> 0.00", [t2.subtotal, t2.tax], ["0.01", "0.00"]);
  const lens = [0, 1, 55, 56, 63, 64, 119, 120, 1000];
  for (const n of lens) { const s = "x".repeat(n); yes(`SHA-256 equals Node's for ${n} bytes`, sha256(s) === createHash("sha256").update(s).digest("hex")); }
  const bytes = new Uint8Array([0, 255, 128, 7, 200]);
  yes("SHA-256 of raw bytes equals Node's", sha256Bytes(bytes) === createHash("sha256").update(bytes).digest("hex"));
  eq("time: parse and format round-trip, offsets honoured", [isoZ(parseTs("2026-10-06T09:00:00Z")), isoZ(parseTs("2026-10-06T11:00:00+02:00"))], ["2026-10-06T09:00:00Z", "2026-10-06T09:00:00Z"]);
}

// ---- the published snapshot: the TypeScript domain against the Python domain's reference -------------------------------
{
  const { manifest, inputs } = loadDir("");
  const ref = readJson(new URL("scripts/snapshot-reference.json", WEB));
  eq("reference was produced for this dataset", [ref.dataset_hash, ref.dataset_version, ref.as_of], [manifest.dataset_hash, manifest.dataset_version, manifest.as_of]);
  for (const [mode, stored] of [["pipeline", false], ["stored", true]] as const) {
    const r = runPipeline(inputs, { stored });
    const want = ref[mode];
    for (const k of METRIC_KEYS) eq(`snapshot ${mode}: metric ${k} digest equals Python's`, digest(r.metrics[k]), want.metric_digests[k]);
    for (const k of Object.keys(want.small_metrics)) eq(`snapshot ${mode}: ${k} equals Python's figures`, (r.metrics as any)[k], want.small_metrics[k]);
    eq(`snapshot ${mode}: exceptions open / unowned / by reason`, { open_count: r.metrics.exceptions.open_count, unowned_count: r.metrics.exceptions.unowned_count, by_reason: r.metrics.exceptions.by_reason }, want.exceptions);
    const inv = r.metrics.approvals.invalid_records;
    eq(`snapshot ${mode}: valid and invalid approvals`, { valid_count: r.metrics.approvals.valid_count, invalid_count: inv.length, invalid_by_code: Object.fromEntries([...new Set(inv.map((x) => x.reason_code))].sort().map((c) => [c, inv.filter((x) => x.reason_code === c).length])) }, want.approvals);
    const e = r.metrics.export;
    eq(`snapshot ${mode}: export figures`, { requests_received: e.requests_received, batches_created: e.batches_created, repeat_requests_returned_prior: e.repeat_requests_returned_prior, accepted_export_total: e.accepted_export_total, eligible_approved_total: e.eligible_approved_total, difference: e.difference, row_count: e.rows.length, exclusion_count: e.exclusions.length }, want.export);
    const sc: Record<string, number> = {};
    for (const s of r.book.status.values()) sc[s] = (sc[s] ?? 0) + 1;
    eq(`snapshot ${mode}: invoice status counts`, sc, want.status_counts);
    eq(`snapshot ${mode}: documents and match results digest equals Python's`, digest(documents(r)), want.documents_digest);
    eq(`snapshot ${mode}: ingest counts`, r.ingest.counts, want.ingest_counts);
    eq(`snapshot ${mode}: rejected count`, r.ingest.rejected.length, want.rejected_count);
    eq(`snapshot ${mode}: merged records digest`, digest(r.ingest.merged_records), want.merged_records_digest);
  }
  // identities the site relies on (reconciliation of the matching panel to the overview)
  const r = runPipeline(inputs, { stored: true });
  const m = r.metrics;
  const sc = (s: string): number => [...r.book.status.values()].filter((x) => x === s).length;
  eq("overview reconciles: matched count = matched + approved + exported + adjusted statuses", m.matched.invoice_count, sc("matched") + sc("approved") + sc("exported") + sc("adjusted"));
  eq("overview reconciles: exception records = by-reason sum", m.exceptions.open_count, EXCEPTION_CODES.reduce((t, c) => t + m.exceptions.by_reason[c]!, 0));
  eq("overview reconciles: eligible = in-book invoices", m.rates.eligible_invoices, r.book.inBook.length);
  eq("export reconciliation difference is 0.00", m.export.difference, "0.00");
  // the import simulation: the incremental decisions equal the batch rule
  const seq = importSequence(r.population.invoices);
  eq("import simulation: merged steps = duplicates.rows_merged", seq.filter((e) => e.verdict === "merged").length, m.duplicates.rows_merged);
  eq("import simulation: distinct canonicals = duplicates.groups_detected", new Set(seq.filter((e) => e.verdict === "merged").map((e) => e.canonical)).size, m.duplicates.groups_detected);
  eq("import simulation: 95 identity merges and 3 same-bytes merges (D-07)", [seq.filter((e) => e.reason === "DUPLICATE_IDENTITY").length, seq.filter((e) => e.reason === "DUPLICATE_SOURCE_BYTES").length], [95, 3]);
  // designed relationships (manifest) recomputed from the derived data
  const dr = Object.fromEntries((manifest.designed_relationships ?? []).map((d) => [d.id, d.realised]));
  const qbBy = (pred: (v: string) => boolean): [number, number] => {
    const invs = [...r.book.invoices.values()].filter((i) => pred(i.vendor_id) && r.book.run.invoices.has(i.invoice_id));
    return [invs.filter((i) => r.book.run.invoices.get(i.invoice_id)!.reasons.includes("QUANTITY_BLOCKED")).length, invs.length];
  };
  const is02x = (v: string): boolean => /^ven-02\d$/.test(v);
  const a = qbBy(is02x), b = qbBy((v) => !is02x(v));
  eq("DR-01 ven-02x quantity-blocked invoices and in-book invoices", [a[0], a[1]], [dr["DR-01"]!.ven_02x_quantity_blocked, dr["DR-01"]!.ven_02x_invoices]);
  eq("DR-01 other vendors quantity-blocked invoices and in-book invoices", [b[0], b[1]], [dr["DR-01"]!.other_quantity_blocked, dr["DR-01"]!.other_invoices]);
  const pv = r.book.exceptions.filter((e) => e.exception_type === "PRICE_VARIANCE");
  eq("DR-02 PRICE_VARIANCE invoices: all and ven-007", [pv.length, pv.filter((e) => r.book.invoices.get(e.invoice_id)!.vendor_id === "ven-007").length], [dr["DR-02"]!.all_price_variance_invoices, dr["DR-02"]!.price_variance_invoices]);
  // derived views never throw and agree with the book
  let bad = 0;
  for (const id of r.book.invoices.keys()) { const v = invoiceView(r, id)!; if (v.status !== r.book.status.get(id)) bad++; }
  eq("invoiceView status equals the book status for every invoice", bad, 0);
}

if (failures > 0) { console.log(`\n${failures} of ${checks} checks failed`); process.exitCode = 1; }
else console.log(`\nALL OK (${checks} checks)`);
