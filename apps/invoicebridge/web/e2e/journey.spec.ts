import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { expectNoOverflow, readData, ready, watch } from "./support";

interface Rows<T> { rows: T[] }
const manifest = readData<{ dataset_version: string; dataset_hash: string; generated_at: string }>("manifest.json");
const ref = JSON.parse(readFileSync("scripts/snapshot-reference.json", "utf8")).stored; // the Python domain's results over the snapshot
const goldenInv = readData<Rows<Record<string, string>>>("golden/invoices.json").rows;
const fig = (page: Page, name: string) => page.locator(`[data-figure="${name}"] dd`).first();
const ROUTES = ["intake", "invoices", "matching", "duplicates", "exceptions", "approvals", "vendors", "exports", "audit", "case-study"];

test("landing: honesty labels, the manifest strip, the back-link, the decision and the snapshot note", async ({ page, request }) => {
  const errors = watch(page);
  await page.goto("./");
  await ready(page);
  await expect(page).toHaveTitle(/InvoiceBridge/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("InvoiceBridge");
  await expect(page.getByTestId("synthetic-badge")).toHaveText("Synthetic data, demo mode");
  await expect(page.getByTestId("honesty")).toContainText("Nothing is approved, exported or paid from this site");
  await expect(page.getByTestId("honesty")).toContainText("no live activity");
  const strip = page.getByTestId("manifest-strip");
  await expect(strip.locator("[data-k=dataset_version]")).toHaveText(manifest.dataset_version);
  await expect(strip.locator("[data-k=dataset_hash]")).toHaveAttribute("title", manifest.dataset_hash);
  await expect(strip.locator("[data-k=generated_at]")).toHaveText(manifest.generated_at);
  await expect(strip.locator("[data-k=code_sha]")).toBeVisible();
  await expect(page.getByTestId("footer-honesty")).toContainText("Nothing here is live");
  await expect(page.getByTestId("decision")).toContainText("Which invoices may advance, and which require exception review?");
  await expect(page.getByTestId("snapshot-note")).toContainText("12-month snapshot");
  await expect(page.getByTestId("snapshot-note")).toContainText("2026-10-01T02:00:00Z");
  await expect(page.getByTestId("snapshot-note")).toContainText("training-free");
  await expect(page.getByTestId("backlink")).toHaveAttribute("href", "https://mrrishit909.github.io/projects-site/");
  expect(await page.locator('link[rel="author"]').getAttribute("href")).toBe("https://mrrishit909.github.io/projects-site/");
  const html = await (await request.get("./")).text();
  expect(html).toMatch(/<noscript[^>]*>[\s\S]*https:\/\/mrrishit909\.github\.io\/projects-site\/[\s\S]*<\/noscript>/);
  expect(html).toContain('<link rel="author" href="https://mrrishit909.github.io/projects-site/"');
  expect(html).toContain("/projects-site/labs/invoicebridge/assets/");
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("landing: the eleven metric keys in contract order, equal to the Python domain's figures", async ({ page }) => {
  const errors = watch(page);
  await page.goto("./");
  await ready(page);
  const sheet = page.getByTestId("metric-sheet");
  await expect(sheet.locator("tbody tr")).toHaveCount(11);
  expect(await sheet.locator("tbody tr").evaluateAll((els) => els.map((e) => e.getAttribute("data-metric")))).toEqual(
    ["matched", "obligations", "exceptions", "duplicates", "quantities", "snapshots", "rates", "processing", "approvals", "payable", "export"]);
  const sm = ref.small_metrics;
  for (const k of ["invoice_count", "amount_before_tax", "tax", "total"]) await expect(fig(page, `matched.${k}`)).toHaveText(String(sm.matched[k]));
  await expect(fig(page, "obligations.count")).toHaveText(String(sm.obligations.count));
  await expect(fig(page, "obligations.total")).toHaveText(sm.obligations.total);
  await expect(fig(page, "exceptions.open_count")).toHaveText(String(ref.exceptions.open_count));
  await expect(fig(page, "exceptions.unowned_count")).toHaveText(String(ref.exceptions.unowned_count));
  for (const [c, n] of Object.entries(ref.exceptions.by_reason)) await expect(fig(page, `exceptions.by_reason.${c}`)).toHaveText(String(n));
  for (const k of ["groups_detected", "rows_merged", "unresolved_groups"]) await expect(fig(page, `duplicates.${k}`)).toHaveText(String(sm.duplicates[k]));
  for (const [k, v] of Object.entries(sm.quantities)) await expect(fig(page, `quantities.${k}`)).toHaveText(String(v));
  for (const k of ["eligible_invoices", "straight_through_rate", "exception_rate"]) await expect(fig(page, `rates.${k}`)).toHaveText(String(sm.rates[k]));
  for (const k of ["approved_count", "mean_minutes", "pending_count"]) await expect(fig(page, `processing.${k}`)).toHaveText(String(sm.processing[k]));
  for (const k of ["approved_total", "credit_total", "approved_payable"]) await expect(fig(page, `payable.${k}`)).toHaveText(sm.payable[k]);
  for (const k of ["accepted_export_total", "eligible_approved_total", "difference"]) await expect(fig(page, `export.${k}`)).toHaveText(ref.export[k]);
  // the cutoffs table: three snapshot columns, then the headline; the as-of column equals the quantities metric
  const cut = page.getByTestId("cutoffs");
  await expect(cut.locator("thead th[data-cutoff]")).toHaveCount(3);
  expect(await cut.locator("thead th[data-cutoff]").allInnerTexts()).toEqual(["2026-03-31T23:59:59Z", "2026-06-30T23:59:59Z", "2026-10-01T02:00:00Z"]);
  for (const [i, [cutoff, q]] of Object.entries(sm.snapshots).entries() as Iterable<[number, [string, Record<string, string>]]>) {
    for (const [k, v] of Object.entries(q)) await expect(cut.locator(`tr[data-quantity="${k}"] td`).nth(i), `${cutoff} ${k}`).toHaveText(v);
  }
  for (const k of Object.keys(sm.quantities)) expect(await cut.locator(`tr[data-quantity="${k}"] td`).nth(2).innerText(), `cutoff at as_of equals the headline for ${k}`).toBe(await cut.locator(`tr[data-quantity="${k}"] td`).nth(3).innerText());
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("every route is reachable by direct entry and reload on the nested base path", async ({ page }) => {
  const errors = watch(page);
  for (const path of ROUTES) {
    await page.goto(`${path}/`);
    await ready(page);
    await page.reload();
    await ready(page);
    expect(new URL(page.url()).pathname).toBe(`/projects-site/labs/invoicebridge/${path}/`);
    await expect(page.getByTestId("synthetic-badge")).toBeVisible();
    await expect(page.getByTestId("honesty")).toContainText("Synthetic data, demo mode");
  }
  await page.goto("no-such-route/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Not found");
  expect(errors.filter((e) => !e.includes("no-such-route"))).toEqual([]);
});

test("the golden pair on the invoice desk: evidence beside decision, the figures the browser computed", async ({ page }) => {
  const errors = watch(page);
  await page.goto("invoices/?dataset=golden");
  await ready(page);
  await expect(page.getByTestId("golden-flag")).toContainText("golden fixture");
  await expect(page.getByTestId("manifest-strip").locator("[data-k=dataset_version]")).toHaveText("golden-v1");
  await expect(page.getByTestId("golden-pair-note")).toContainText("QUANTITY_BLOCKED");
  const d1 = page.getByTestId("desk-inv-001"), d2 = page.getByTestId("desk-inv-002");
  await expect(d1).toBeVisible();
  await expect(d2).toBeVisible();
  // inv-001: matched 120.00 + 12.00 = 132.00
  await expect(d1.locator("[data-figure=subtotal]")).toHaveText("120.00");
  await expect(d1.locator("[data-figure=tax]")).toHaveText("12.00");
  await expect(d1.locator("[data-figure=total]")).toHaveText("132.00");
  await expect(d1.locator("[data-figure=rounding_difference]")).toHaveText("0.00");
  await expect(d1.getByTestId("verdict")).toContainText("Matched: 120.00 before tax, 12.00 tax, total 132.00");
  await expect(d1.locator(".pair__head [data-chip]")).toHaveAttribute("data-chip", "exported");
  await expect(d1.getByTestId("doc-fields")).toContainText("INV-1001");
  await expect(d1.getByTestId("lineage")).toContainText(goldenInv.find((r) => r.invoice_id === "inv-001")!.source_sha256!);
  const m1 = d1.locator('[data-line="il-001"]').locator("td");
  await expect(m1.nth(1)).toHaveText("10.0000");
  await expect(m1.nth(2)).toHaveText("6.0000");
  await expect(m1.nth(3)).toHaveText("0.0000");
  await expect(m1.nth(4)).toHaveText("6.0000");
  await expect(m1.nth(5)).toHaveText("6.0000");
  await expect(m1.nth(6)).toHaveText("0.0000");
  await expect(m1.nth(8)).toContainText("matched");
  await expect(d1.getByTestId("approval-trail")).toContainText("usr-rev01");
  await expect(d1.getByTestId("approval-trail")).toContainText("pol-v1: reviewer up to 5000.00");
  await expect(d1.getByTestId("approval-trail")).toContainText("different from the creator");
  await expect(d1.getByTestId("approval-trail").locator("[data-chip=COUNTED]")).toBeVisible();
  await expect(d1.getByTestId("export-row")).toContainText("exp-bat-001-inv-001");
  await expect(d1.getByTestId("export-row")).toContainText("7776efc65bc163e1b9a09ab336a0fcd12b52aba6ccfdefe49c06baf0b3df6779");
  await expect(d1.getByTestId("payable")).toContainText("132.00");
  await expect(d1.getByTestId("merged-in")).toContainText("inv-003");
  await expect(d1.getByTestId("merged-in")).toContainText("different bytes");
  await expect(d1.getByTestId("no-credits")).toBeVisible();
  // inv-002: QUANTITY_BLOCKED, 4 units
  await expect(d2.locator("[data-figure=total]")).toHaveText("88.00");
  await expect(d2.getByTestId("verdict")).toContainText("QUANTITY_BLOCKED");
  await expect(d2.getByTestId("verdict")).toContainText("4.0000 invoiced against 0.0000 available (4.0000 over)");
  const m2 = d2.locator('[data-line="il-002"]').locator("td");
  await expect([await m2.nth(1).innerText(), await m2.nth(2).innerText(), await m2.nth(3).innerText(), await m2.nth(4).innerText(), await m2.nth(5).innerText(), await m2.nth(6).innerText(), await m2.nth(7).innerText()]).toEqual(["10.0000", "6.0000", "6.0000", "4.0000", "0.0000", "4.0000", "0.0000"]);
  await expect(m2.nth(8)).toContainText("QUANTITY_BLOCKED");
  await expect(d2.getByTestId("exceptions")).toContainText("exc-001");
  await expect(d2.getByTestId("exceptions")).toContainText("open, unowned");
  await expect(d2.getByTestId("no-approvals")).toBeVisible();
  await expect(d2.getByTestId("no-export")).toContainText("only an approved invoice can be exported");
  await expect(d2.locator(".pair__head [data-chip]")).toHaveAttribute("data-chip", "exception");
  // evidence is left of the decision at desktop width
  const a = await d1.locator(".doc").boundingBox(), b = await d1.locator(".decision").boundingBox();
  const vw = page.viewportSize()!.width;
  if (vw >= 1100) expect(a!.x).toBeLessThan(b!.x);
  // the re-sent copy
  await page.getByRole("button", { name: /the re-sent copy/ }).click();
  await expect(page.getByTestId("desk-inv-003").getByTestId("merge-note")).toContainText("DUPLICATE_IDENTITY");
  expect(new URL(page.url()).searchParams.get("invoice")).toBe("inv-003");
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("the golden dataset on the landing page: metrics, cutoffs, the switch persists across routes", async ({ page }) => {
  const errors = watch(page);
  await page.goto("./?dataset=golden");
  await ready(page);
  await expect(page.getByTestId("golden-flag")).toBeVisible();
  const expected = JSON.parse(readFileSync("public/data/golden/expected.json", "utf8")).metrics;
  await expect(fig(page, "matched.invoice_count")).toHaveText("1");
  await expect(fig(page, "matched.amount_before_tax")).toHaveText("120.00");
  await expect(fig(page, "matched.tax")).toHaveText("12.00");
  await expect(fig(page, "matched.total")).toHaveText("132.00");
  await expect(fig(page, "obligations.count")).toHaveText("1");
  await expect(fig(page, "obligations.total")).toHaveText("132.00");
  await expect(fig(page, "exceptions.open_count")).toHaveText("1");
  await expect(fig(page, "exceptions.unowned_count")).toHaveText("1");
  await expect(fig(page, "exceptions.by_reason.QUANTITY_BLOCKED")).toHaveText("1");
  await expect(fig(page, "duplicates.groups_detected")).toHaveText("1");
  await expect(fig(page, "duplicates.rows_merged")).toHaveText("1");
  await expect(fig(page, "rates.straight_through_rate")).toHaveText("0.500000");
  await expect(fig(page, "rates.exception_rate")).toHaveText("0.500000");
  await expect(fig(page, "processing.mean_minutes")).toHaveText("390.0000");
  await expect(fig(page, "processing.pending_count")).toHaveText("1");
  await expect(fig(page, "payable.approved_payable")).toHaveText("132.00");
  await expect(fig(page, "export.requests_received")).toHaveText("2");
  await expect(fig(page, "export.batches_created")).toHaveText("1");
  await expect(fig(page, "export.repeat_requests_returned_prior")).toHaveText("1");
  await expect(fig(page, "export.difference")).toHaveText("0.00");
  for (const [k, v] of Object.entries(expected.quantities)) await expect(fig(page, `quantities.${k}`)).toHaveText(String(v));
  const cut = page.getByTestId("cutoffs");
  await expect(cut.locator('thead th[data-cutoff="2026-10-05T23:00:00Z"]')).toBeVisible();
  await expect(cut.locator('tr[data-quantity="received_not_invoiced_value"] td').first()).toHaveText("120.00");
  await expect(cut.locator('tr[data-quantity="received_not_invoiced_quantity"] td').first()).toHaveText("6.0000");
  await expect(cut.locator('tr[data-quantity="open_to_invoice_quantity"] td').first()).toHaveText("10.0000");
  await page.getByRole("link", { name: "Matching" }).first().click();
  expect(new URL(page.url()).searchParams.get("dataset")).toBe("golden");
  await expect(page.getByTestId("matching-table").locator("tbody tr")).toHaveCount(3);
  await expect(page.locator('[data-testid=reconciliation] tr[data-agree="false"]')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("invoice desk on the snapshot: finder, quick picks, lineage, merge, trail and an independent recomputation", async ({ page }) => {
  const errors = watch(page);
  await page.goto("invoices/");
  await ready(page);
  await page.getByTestId("doc-fields").first().waitFor();
  await expect(page.getByTestId("merged-in")).toContainText("later import");
  await expect(page.getByTestId("approval-trail")).toBeVisible();
  await expect(page.getByTestId("export-row")).toBeVisible();
  // an independent recomputation of the chosen invoice from the raw rows, in BigInt
  const id = await page.locator("[data-invoice]").first().getAttribute("data-invoice");
  const inv = readData<Rows<Record<string, string>>>("invoices.json").rows.find((r) => r.invoice_id === id)!;
  const lines = readData<Rows<Record<string, string>>>("invoice_lines.json").rows.filter((r) => r.invoice_id === id);
  const sc = (s: string, dp: number): bigint => { const [i = "0", f = ""] = s.split("."); return BigInt(i + f.padEnd(dp, "0").slice(0, dp)); };
  const raw = lines.reduce((t, l) => t + sc(l.quantity!, 4) * sc(l.unit_price!, 6), 0n); // 1e-10
  const half = (n: bigint, d: bigint): bigint => (2n * (n % d) >= d ? n / d + 1n : n / d);
  const sub = half(raw, 10n ** 8n), tax = half(raw * sc(inv.tax_rate!, 6), 10n ** 14n);
  const total = sub + tax + sc(inv.freight!, 2) - sc(inv.invoice_discount!, 2);
  const f = (c: bigint): string => `${c / 100n}.${String(c % 100n).padStart(2, "0")}`;
  const desk = page.locator(`[data-invoice="${id}"]`);
  await expect(desk.locator("[data-figure=subtotal]")).toHaveText(f(sub));
  await expect(desk.locator("[data-figure=tax]")).toHaveText(f(tax));
  await expect(desk.locator("[data-figure=total]")).toHaveText(f(total));
  await expect(desk.getByTestId("lineage")).toContainText(inv.source_sha256!);
  // finder
  await page.getByLabel("Find an invoice by id, number or vendor").fill("inv-0007");
  await page.getByTestId("finder-hits").getByRole("button").first().click();
  expect(new URL(page.url()).searchParams.get("invoice")).toBe("inv-0007");
  await expect(page.locator('[data-invoice="inv-0007"]')).toBeVisible();
  await page.goto("invoices/?invoice=inv-9999");
  await ready(page);
  await expect(page.getByTestId("unknown-invoice")).toContainText("inv-9999");
  // quick picks reach an exception with assignment history and a rejected invoice
  await page.getByRole("button", { name: /an assigned exception/ }).click();
  await expect(page.getByTestId("exceptions")).toBeVisible();
  await expect(page.getByTestId("assignment-history").first()).toBeVisible();
  await page.getByRole("button", { name: /a rejected invoice/ }).click();
  await expect(page.getByTestId("verdict")).toContainText("Rejected by a valid reviewer decision");
  await page.getByRole("button", { name: /an adjusted \(credited\) invoice/ }).click();
  await expect(page.getByTestId("credits")).toContainText("credits");
  await expect(page.getByTestId("payable")).toContainText("credits");
  await page.getByRole("button", { name: /a PRICE_VARIANCE invoice/ }).click();
  await expect(page.getByTestId("match-lines")).toContainText("PRICE_VARIANCE");
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("intake: the import replays in order, duplicates are merged by identity or bytes, re-sends leave one obligation", async ({ page }) => {
  const errors = watch(page);
  await page.goto("intake/");
  await ready(page);
  const counts = page.getByTestId("running-counts");
  const n = async (k: string): Promise<number> => Number((await counts.locator(`[data-figure=${k}] dd`).innerText()).split("\n")[0]);
  expect(await n("imported")).toBe(300);
  const merged0 = (await n("merged_identity")) + (await n("merged_bytes"));
  expect(await n("distinct")).toBe(300 - merged0);
  await page.getByRole("button", { name: "Next 100" }).click();
  expect(await n("imported")).toBe(400);
  await expect(page.getByTestId("import-log").locator("tbody tr")).toHaveCount(10);
  // re-send the file of the newest row: same bytes, one obligation
  const before = await n("distinct");
  await page.getByTestId("import-log").getByRole("button", { name: "Re-send this file" }).first().click();
  await expect(page.getByTestId("resend-results")).toContainText("DUPLICATE_SOURCE_BYTES");
  await expect(page.getByTestId("resend-results")).toContainText(`Distinct invoices stay at ${before}`);
  expect(await n("distinct")).toBe(before);
  await page.getByRole("button", { name: "Import all" }).click();
  expect(await n("imported")).toBe(2800);
  expect(await n("merged_identity")).toBe(95);
  expect(await n("merged_bytes")).toBe(3);
  expect(await n("groups")).toBe(98);
  expect(await n("distinct")).toBe(2702);
  await expect(page.getByTestId("identity-groups")).toBeVisible();
  await expect(page.getByTestId("bytes-groups")).toBeVisible();
  await expect(fig(page, "imported")).toHaveText("2800");
  await page.getByRole("button", { name: "Reset" }).click();
  expect(await n("imported")).toBe(0);
  await expect(page.getByTestId("nothing-imported")).toBeVisible();
  await page.locator("#pos").fill("1500");
  expect(await n("imported")).toBe(1500);
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
  // golden: the pair and the re-sent copy
  await page.goto("intake/?dataset=golden");
  await ready(page);
  expect(await n("imported")).toBe(3);
  expect(await n("merged_identity")).toBe(1);
  expect(await n("distinct")).toBe(2);
  await expect(page.getByTestId("identity-groups")).toContainText("ven-001|INV1001|2026-10-06|132.00");
});

test("matching: filters, ven-02x and ven-007 relationships, totals reconcile to the overview", async ({ page }) => {
  const errors = watch(page);
  await page.goto("matching/");
  await ready(page);
  await expect(page.getByTestId("filter-totals").locator("[data-figure='f.invoices'] dd")).toHaveText("2,800");
  await expect(page.locator('[data-testid=reconciliation] tbody tr')).toHaveCount(8);
  await expect(page.locator('[data-testid=reconciliation] tr[data-agree="false"]')).toHaveCount(0);
  await expect(page.locator('[data-testid=reconciliation] tr[data-agree="true"]')).toHaveCount(8);
  // DR-01 and DR-02
  await expect(page.locator("[data-figure='dr1.02x']")).toHaveText("163 of 538");
  await expect(page.locator("[data-figure='dr1.other']")).toHaveText("30 of 2107");
  await expect(page.locator("[data-figure='dr2.share']")).toHaveText("30 of 32");
  await expect(page.getByTestId("dr-007")).toContainText("2026-03");
  await page.getByRole("button", { name: "Show ven-02x blocked invoices" }).click();
  expect(new URL(page.url()).searchParams.get("vendor")).toBe("ven-02x");
  await expect(page.getByTestId("filter-totals").locator("[data-figure='f.invoices'] dd")).toHaveText("163");
  expect(await page.getByTestId("matching-table").locator("tbody tr").evaluateAll((els) => els.every((e) => /^ven-02\d$/.test(e.getAttribute("data-vendor")!)))).toBe(true);
  await page.getByTestId("f-reason").selectOption("all");
  await page.getByTestId("f-vendor").selectOption("ven-007");
  const v7 = Number(await page.getByTestId("filter-totals").locator("[data-figure='f.invoices'] dd").innerText());
  expect(v7).toBeGreaterThan(100);
  await page.getByTestId("f-reason").selectOption("PRICE_VARIANCE");
  await expect(page.getByTestId("filter-totals").locator("[data-figure='f.invoices'] dd")).toHaveText("30");
  await page.getByTestId("f-month").selectOption("2026-03");
  expect(Number(await page.getByTestId("filter-totals").locator("[data-figure='f.invoices'] dd").innerText())).toBeGreaterThan(0);
  await page.getByRole("button", { name: "Clear filters" }).click();
  await expect(page.getByTestId("filter-totals").locator("[data-figure='f.invoices'] dd")).toHaveText("2,800");
  await page.getByRole("button", { name: "Next" }).first().click();
  await expect(page.getByTestId("pager")).toContainText("Rows 26-50 of 2,800");
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("exceptions: the open queue by reason and owner, with assignment history", async ({ page }) => {
  const errors = watch(page);
  await page.goto("exceptions/");
  await ready(page);
  await expect(page.locator('td[data-figure="exceptions.open_count"]')).toHaveText(String(ref.exceptions.open_count));
  await expect(page.locator('td[data-figure="exceptions.unowned_count"]')).toHaveText(String(ref.exceptions.unowned_count));
  for (const [c, nn] of Object.entries(ref.exceptions.by_reason)) await expect(page.locator(`[data-testid=by-reason] tr[data-reason="${c}"] td`).nth(1)).toHaveText(String(nn));
  await page.getByTestId("f-owner").selectOption("unowned");
  await expect(page.getByTestId("pager")).toContainText(`of ${ref.exceptions.unowned_count}`);
  await page.getByTestId("f-owner").selectOption("all");
  await page.getByTestId("f-reason").selectOption("PRICE_VARIANCE");
  await expect(page.getByTestId("pager")).toContainText(`of ${ref.exceptions.by_reason.PRICE_VARIANCE}`);
  await page.getByTestId("f-reason").selectOption("all");
  const owned = page.locator('[data-testid=queue-table] tbody tr:has(td:nth-child(6):text-is("1"))').first();
  await owned.getByRole("button", { name: "Show" }).click();
  await expect(page.getByTestId("selected-exception")).toBeVisible();
  await expect(page.getByTestId("selected-exception").getByTestId("assignment-history")).toContainText("usr-");
  expect(new URL(page.url()).searchParams.get("exception")).toMatch(/^exc-/);
  await page.goto("exceptions/?dataset=golden");
  await ready(page);
  await expect(page.getByTestId("queue-table").locator("tbody tr")).toHaveCount(1);
  await expect(page.getByTestId("queue-table")).toContainText("inv-002");
  await expect(page.getByTestId("queue-table")).toContainText("unowned");
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("approvals, exports, duplicates, vendors and audit: read-only views over the derived data", async ({ page }) => {
  const errors = watch(page);
  await page.goto("approvals/");
  await ready(page);
  await expect(fig(page, "approvals.valid_count")).toContainText(String(ref.approvals.valid_count).replace(/(\d)(\d{3})$/, "$1,$2"));
  await expect(page.getByTestId("policies")).toContainText("pol-v2");
  await expect(page.getByTestId("policies")).toContainText("8000.00");
  await expect(page.getByTestId("not-built")).toContainText("read-only");
  await expect(fig(page, "approvals.self")).toContainText("0");
  await page.goto("exports/");
  await ready(page);
  await expect(fig(page, "export.difference")).toHaveText("0.00");
  await expect(fig(page, "export.batches_created")).toHaveText("52");
  await expect(page.getByTestId("exclusions")).toContainText("EXCEPTION_OPEN");
  await expect(page.getByTestId("batch-table")).toContainText("bat-001");
  await expect(page.getByTestId("export-rows").locator("tbody tr").first().locator("td").last()).toHaveAttribute("title", /^[0-9a-f]{64}$/);
  await page.goto("duplicates/");
  await ready(page);
  await expect(fig(page, "duplicates.groups_detected")).toContainText("98");
  await expect(page.getByTestId("dr3")).toContainText("of 95 identity duplicates");
  await page.goto("vendors/");
  await ready(page);
  await expect(page.getByTestId("vendor-table").locator("tbody tr")).toHaveCount(40);
  await expect(page.locator('[data-vendor="ven-007"]')).toContainText("price list change");
  await expect(page.locator('[data-vendor="ven-025"]')).toContainText("ven-02x");
  await page.goto("audit/");
  await ready(page);
  expect(await page.getByTestId("timeline").locator("li").count()).toBeGreaterThan(3);
  await expect(page.getByTestId("timeline")).toContainText("Imported");
  await expect(page.getByTestId("timeline")).toContainText("Exported in");
  await page.goto("audit/?dataset=golden");
  await ready(page);
  await expect(page.getByTestId("timeline")).toContainText("inv-003 re-sent and merged into this invoice");
  await expect(page.getByTestId("timeline")).toContainText("Approval by usr-rev01");
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});

test("case study: what is built, what is not, and C06", async ({ page }) => {
  const errors = watch(page);
  await page.goto("case-study/");
  await ready(page);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Case study");
  await expect(page.getByTestId("built")).toContainText("The contract");
  await expect(page.getByTestId("c06")).toContainText("C06");
  await expect(page.getByTestId("c06")).toContainText("501");
  await expect(page.getByTestId("not-built-list")).toContainText("Payments and bank connections");
  await expect(page.getByTestId("tech-p1")).toContainText("never pays");
  await expect(page.getByTestId("provenance")).toContainText(manifest.dataset_version);
  await expect(page.getByTestId("honesty")).toContainText("Synthetic data, demo mode");
  await expectNoOverflow(page);
  expect(errors).toEqual([]);
});
