// Reorder workbench (P03-UI-06): every SKU x location row with its position, reorder point, target and the arithmetic that
// ends in a draft quantity. Sortable, filterable (the filters live in the address), exportable as CSV. A draft, never a
// purchase order.
import { useMemo, useState } from "react";
import { Definition } from "../components/definition";
import { buildCsv, ExportButton } from "../components/export";
import { FilterBar, ScenarioBar } from "../components/filters";
import { Link } from "../components/link";
import { ViewHead } from "../components/layout";
import { Gate } from "../components/status";
import { DataTable, sortRows, type Column, type Sort } from "../components/table";
import { reorderRows, type PairRow } from "../domain/metrics";
import { isoZ } from "../domain/time";
import { describeFilters, useViewState } from "../state/filters";
import { useScenarioOf } from "../state/scenario";
import type { Ready } from "../state/atlas";

export function Reorder() {
  return <Gate>{(s) => <Body s={s} />}</Gate>;
}

/** The golden arithmetic in one line: target - position = raw -> MOQ -> pack. */
export function arithmetic(r: PairRow): string {
  return r.triggered
    ? `${r.target_position} − ${r.position} = ${r.raw_order} → MOQ ${r.moq}: ${r.order_after_moq} → pack ${r.pack_size}: ${r.order_quantity}`
    : `position ${r.position} ≥ ROP ${r.reorder_point}: 0`;
}

const COLUMNS: Column<PairRow>[] = [
  { id: "sku", label: "SKU", value: (r) => r.sku, render: (r) => <Link to={`skus?sku=${encodeURIComponent(r.product_id)}&loc=${encodeURIComponent(r.location_id)}`}>{r.sku}</Link> },
  { id: "loc", label: "Location", value: (r) => r.location_id },
  { id: "supplier", label: "Supplier", value: (r) => r.supplier_id },
  { id: "on_hand", label: "On hand", value: (r) => r.on_hand, num: true },
  { id: "on_order", label: "On order", value: (r) => r.on_order, num: true },
  { id: "backorders", label: "Backorders", value: (r) => r.backorders, num: true },
  { id: "position", label: "Position", value: (r) => r.position, num: true },
  { id: "rop", label: "ROP", value: (r) => r.reorder_point, num: true },
  { id: "target", label: "Target", value: (r) => r.target_position, num: true },
  { id: "raw", label: "Raw", value: (r) => r.raw_order, num: true },
  { id: "moq", label: "MOQ", value: (r) => r.moq, num: true },
  { id: "after_moq", label: "After MOQ", value: (r) => r.order_after_moq, num: true },
  { id: "pack", label: "Pack", value: (r) => r.pack_size, num: true },
  { id: "draft", label: "Draft qty", value: (r) => r.order_quantity, num: true, render: (r) => <strong>{r.order_quantity}</strong> },
  { id: "triggered", label: "Triggered", value: (r) => (r.triggered ? "yes" : "no") },
  { id: "calc", label: "Arithmetic", value: (r) => arithmetic(r), render: (r) => <span className="mono">{arithmetic(r)}</span> },
];
const CSV_COLUMNS = ["status", "sku", "product_id", "location_id", "supplier_id", "on_hand", "on_order", "backorders", "position", "reorder_point", "target_position", "reorder_triggered", "raw_order", "moq", "order_after_moq", "pack_size", "order_quantity"] as const;

function Body({ s }: { s: Ready }) {
  const view = useViewState();
  const sc = useScenarioOf(s, view);
  const pop = s.result.population;
  const m = s.snapshot.manifest;
  const all = useMemo(() => reorderRows(pop, sc.asOf, sc.state), [pop, sc.asOf, sc.state]);
  const f = view.filters;
  const visible = useMemo(() => {
    const q = f.q.trim().toLowerCase();
    return all.filter((r) => (!f.loc || r.location_id === f.loc) && (!f.sup || r.supplier_id === f.sup) && (f.trig !== "yes" || r.triggered) && (f.trig !== "no" || !r.triggered) &&
      (!q || r.sku.toLowerCase().includes(q) || r.product_id.toLowerCase().includes(q)));
  }, [all, f.loc, f.sup, f.trig, f.q]);
  const [sort, setSort] = useState<Sort | null>({ id: "draft", dir: "desc" });
  const ordered = useMemo(() => sortRows(visible, COLUMNS, sort), [visible, sort]);
  const draftUnits = visible.reduce((a, r) => a + r.order_quantity, 0);
  const triggered = visible.filter((r) => r.triggered).length;
  const csv = (): string => buildCsv(
    [
      "SupplyScope reorder workbench: DRAFT recommendation rows, never a purchase order",
      `contract_version: ${m.contract_version}`, `dataset_version: ${m.dataset_version}`, `dataset_hash: ${m.dataset_hash}`,
      `as_of: ${isoZ(sc.asOf)}`, `fixture_state: ${sc.stateName || "none (accepted population)"}`,
      `filters: ${describeFilters(f)}`, `sort: ${sort ? `${sort.id} ${sort.dir}` : "none"}`, `row_count: ${ordered.length}`,
    ],
    CSV_COLUMNS,
    ordered.map((r) => [r.status, r.sku, r.product_id, r.location_id, r.supplier_id, r.on_hand, r.on_order, r.backorders, r.position, r.reorder_point, r.target_position, r.triggered, r.raw_order, r.moq, r.order_after_moq, r.pack_size, r.order_quantity].map(String)),
  );
  return (
    <article>
      <ViewHead eyebrow="P03-UI-06" title="Reorder workbench">
        <p className="lede">Every SKU x location row at the chosen date, with the arithmetic that turns a position below its reorder point into a draft quantity: target minus position gives the raw order, the minimum order quantity lifts it, and whole packs round it up.</p>
      </ViewHead>
      <p className="banner" data-testid="draft-banner"><strong>Draft, never a purchase order.</strong> Each row is a recommendation (status: draft) for an analyst to review; nothing here becomes a supplier commitment.</p>
      <ScenarioBar view={view} sc={sc} />
      <FilterBar view={view} pop={pop} rows={all} shown={visible.length} total={all.length} />
      <p className="summary-line" data-testid="reorder-summary"><strong>{triggered}</strong> of {visible.length} visible rows are triggered; <strong>{draftUnits}</strong> draft units in total.</p>
      <DataTable caption="Reorder workbench: draft quantities by SKU x location" columns={COLUMNS} rows={visible} rowKey={(r) => `${r.product_id}:${r.location_id}`} testId="reorder-table"
        sort={sort} onSort={setSort} empty="No row matches these filters. Clear the filters to see every row." />
      <ExportButton filename={`supplyscope-reorder-draft-${m.dataset_version}-${sc.text}.csv`} build={csv} rowCount={ordered.length} />
      <Definition only={["Inventory position", "Reorder, raw, MOQ, pack"]} />
    </article>
  );
}
