// Regression checks for the independent review A-038 (findings R5-01 .. R5-22; decisions in docs/contracts.md D-09).
// TypeScript twin of tests/test_review_findings.py: it reads the SAME cases and hand-derived expectations
// (tests/review_cases.json, written by tests/make_review_cases.py), so the Python domain, the SQL reference and this mirror are
// held to one set of values. Prints "ALL OK (N checks)" or exits 1. Run by `npm run check` after the golden check.
import { readFileSync } from "node:fs";
import { derive } from "../src/domain/book";
import { disclosures, computeMetrics } from "../src/domain/metrics";
import { cmp } from "../src/domain/order";
import { documents, runPipeline } from "../src/domain/pipeline";
import { parseDec } from "../src/domain/num";
import { parseTs } from "../src/domain/time";
import type { PipelineInputs } from "../src/domain/types";

const ROOT = new URL("../../", import.meta.url);
const read = (rel: string): any => JSON.parse(readFileSync(new URL(rel, ROOT), "utf8"));

let failures = 0, checks = 0;
const show = (v: unknown): string => JSON.stringify(v, (_k, x) => (typeof x === "bigint" ? x.toString() : x)).slice(0, 260);
function yes(label: string, ok: boolean, detail = ""): void {
  checks++;
  if (ok) console.log(`OK       ${label}`);
  else { failures++; console.log(`MISMATCH ${label} ${detail}`); }
}
/** Every key of ``want`` is in ``got`` with an equal (recursively subset) value; lists element by element (tests/test_review_findings.py ``subset``). */
function subset(got: any, want: any, path: string): string | null {
  if (want !== null && typeof want === "object" && !Array.isArray(want)) {
    if (got === null || typeof got !== "object" || Array.isArray(got)) return `${path}: expected an object, got ${show(got)}`;
    for (const [k, v] of Object.entries(want)) {
      if (!(k in got)) return `${path}.${k}: missing (has ${Object.keys(got).join(",")})`;
      const r = subset(got[k], v, `${path}.${k}`);
      if (r) return r;
    }
    return null;
  }
  if (Array.isArray(want)) {
    if (!Array.isArray(got) || got.length !== want.length) return `${path}: expected ${show(want)}, got ${show(got)}`;
    for (let i = 0; i < want.length; i++) { const r = subset(got[i], want[i], `${path}[${i}]`); if (r) return r; }
    return null;
  }
  return got === want ? null : `${path}: expected ${show(want)}, got ${show(got)}`;
}

interface Case { name: string; finding: string; inputs: PipelineInputs & Record<string, any>; expect: any; stored?: { exceptions: any[]; exception_assignments: any[] }; exact_keys?: Record<string, string[]> }
const cases: Case[] = read("tests/review_cases.json").cases;

for (const c of cases) {
  const inputs: PipelineInputs = c.stored ? { ...c.inputs, exceptions: c.stored.exceptions, exception_assignments: c.stored.exception_assignments } : c.inputs;
  const r = runPipeline(inputs, { stored: !!c.stored });
  const docs = documents(r).invoices;
  const want = c.expect;
  let bad: string | null = null;
  for (const [iid, [status, types]] of Object.entries<[string, string[]]>(want.docs ?? {})) {
    const d = docs[iid] as any;
    if (!d || d.status !== status || show(d.exception_types) !== show(types)) bad = bad ?? `${iid}: expected ${status} ${show(types)}, got ${show(d && [d.status, d.exception_types])}`;
  }
  if (want.docs && Object.keys(want.docs).length === 0 && Object.keys(docs).length !== 0) bad = bad ?? `expected no documents, got ${Object.keys(docs).join(",")}`;
  if (want.rejected) {
    const got = r.ingest.rejected.map((x) => [x.entity, x.id, x.reason_code]);
    if (show(got) !== show(want.rejected)) bad = bad ?? `rejected: expected ${show(want.rejected)}, got ${show(got)}`;
  }
  bad = bad ?? subset(JSON.parse(JSON.stringify(r.metrics, (_k, x) => (typeof x === "bigint" ? x.toString() : x))), want.metrics ?? {}, "metrics");
  for (const [path, keys] of Object.entries(c.exact_keys ?? {})) {
    let node: any = r.metrics;
    for (const part of path.split(".").slice(1)) node = node[part];
    if (show(Object.keys(node).sort()) !== show(keys)) bad = bad ?? `${path}: expected keys ${show(keys)}, got ${show(Object.keys(node).sort())}`;
  }
  yes(`${c.finding} case ${c.name}`, bad === null, bad ?? "");
}

// ---- R5-16: code-point order ---------------------------------------------------------------------------------------------------
yes("R5-16 cmp orders U+FFFF before U+1F600 (UTF-16 `<` says the opposite)", cmp("inv-￿", "inv-\u{1F600}") === -1 && cmp("inv-\u{1F600}", "inv-￿") === 1 && ("inv-\u{1F600}" < "inv-￿"));
yes("R5-16 cmp is a total order on equal, prefix and ASCII strings", cmp("a", "a") === 0 && cmp("a", "ab") === -1 && cmp("ab", "a") === 1 && cmp("B", "a") === -1 && cmp("", "a") === -1);
{
  const ids = ["b", "\u{1F600}", "￿", "", "a", "\u{10000}", "z"];
  yes("R5-16 sorting a mixed list by cmp equals Python's code-point sorted() of the same list", show([...ids].sort(cmp)) === show(["a", "b", "z", "", "￿", "\u{10000}", "\u{1F600}"]));
}

// ---- R5-17: ASCII decimals only -------------------------------------------------------------------------------------------------
for (const [text, ok] of [["10", true], ["-1.5", true], ["+2", true], [".5", true], ["5.", true], [" 7 ", true], ["1_0", false], ["1E+1", false], ["1e1", false], ["١٠", false], ["Infinity", false], ["NaN", false], ["", false], ["1 0", false], ["0x10", false], ["１０", false]] as [string, boolean][]) {
  let accepted = true;
  try { parseDec(text, "q", 4); } catch { accepted = false; }
  yes(`R5-17 parseDec(${JSON.stringify(text)}) ${ok ? "parses" : "is refused"}`, accepted === ok);
}

// ---- R5-21: disclosures list the tolerated line roundings ----------------------------------------------------------------
{
  const inputs = read("tests/review_cases.json").cases.find((c: Case) => c.name === "export_needs_a_prior_approval").inputs as PipelineInputs;
  const r = runPipeline({ ...inputs, invoice_lines: (inputs.invoice_lines as any[]).map((l, i) => (i === 0 ? { ...l, line_amount: "119.99" } : l)) });
  const d = disclosures(r.population, r.book) as any;
  yes("R5-21 disclosures carry rounding_tolerated_lines (a 0.01 line difference is tolerated and listed)", Array.isArray(d.rounding_tolerated_lines) && d.rounding_tolerated_lines.length === 1 && d.rounding_tolerated_lines[0].rounding_difference === "0.01" && d.rounding_tolerated_lines[0].invoice_line_id === "il-1", show(d.rounding_tolerated_lines));
}

// ---- derive/compute agree: a book never changes under a fact after its cutoff -----------------------------------------------
{
  const c = cases.find((x) => x.name === "back_dated_after_export")!;
  const r = runPipeline(c.inputs);
  const early = derive(r.population, parseTs("2026-10-07T12:00:00Z"));
  yes("R5-09 the book at 2026-10-07T12:00Z has inv-late exported and inv-back not yet imported", early.status.get("inv-late") === "exported" && early.status.get("inv-back") === "received");
  yes("R5-09 the batch's rows at that cutoff equal the rows of the full book", show(early.exportRows) === show(derive(r.population, null).exportRows));
  const m = computeMetrics(r.population, parseTs("2026-10-07T12:00:00Z"));
  yes("R5-13 the early book's difference is 0.00 (nothing approved-not-exported)", m.export.difference === "0.00" && m.export.exclusions.length === 0, show(m.export.exclusions));
}

if (failures > 0) { console.log(`\n${failures} of ${checks} checks failed`); process.exitCode = 1; }
else console.log(`\nALL OK (${checks} checks)`);
