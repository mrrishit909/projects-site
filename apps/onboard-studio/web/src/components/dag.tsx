// Workflow canvas: steps as nodes in dependency layers, prerequisites as arrows. The accessible equivalent is
// the ordered list in the workflow view (topological order), built from the same data.
import type { Dependency, StepDefinition } from "../domain/types";
import { clip, label } from "../lib/format";
import "../styles/screens.css";

const NW = 176, NH = 58, GX = 64, GY = 18, PAD = 12;

export interface DagLayout { positions: Map<string, { x: number; y: number; layer: number }>; width: number; height: number }

/** Layer = length of the longest chain of prerequisites; rows inside a layer follow the given topological order. */
export function layoutDag(order: readonly string[], deps: readonly Dependency[]): DagLayout {
  const layer = new Map<string, number>();
  for (const id of order) {
    layer.set(id, Math.max(0, ...deps.filter((d) => d.step_definition_id === id).map((d) => (layer.get(d.prerequisite_id) ?? 0) + 1)));
  }
  const rowIn = new Map<number, number>();
  const positions = new Map<string, { x: number; y: number; layer: number }>();
  for (const id of order) {
    const l = layer.get(id)!;
    const r = rowIn.get(l) ?? 0;
    rowIn.set(l, r + 1);
    positions.set(id, { x: PAD + l * (NW + GX), y: PAD + r * (NH + GY), layer: l });
  }
  const layers = Math.max(0, ...layer.values()) + 1, rows = Math.max(1, ...rowIn.values());
  return { positions, width: PAD * 2 + layers * NW + (layers - 1) * GX, height: PAD * 2 + rows * NH + (rows - 1) * GY };
}

export function Dag({ steps, deps, order, title }: { steps: readonly StepDefinition[]; deps: readonly Dependency[]; order: readonly string[]; title: string }) {
  const { positions, width, height } = layoutDag(order, deps);
  const byId = new Map(steps.map((s) => [s.step_definition_id, s]));
  return (
    <div className="dag" role="region" aria-label="Workflow canvas (scrollable)" tabIndex={0}>
      <svg viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img" aria-labelledby="dag-title dag-desc" className="dag__svg">
        <title id="dag-title">{title}</title>
        <desc id="dag-desc">{`${steps.length} steps and ${deps.length} dependency arrows. Each arrow points from a prerequisite to the step that needs it. The ordered list below gives the same steps in topological order.`}</desc>
        <defs>
          <marker id="dag-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" className="dag__head" /></marker>
        </defs>
        {deps.map((d) => {
          const a = positions.get(d.prerequisite_id), b = positions.get(d.step_definition_id);
          if (!a || !b) return null;
          const x1 = a.x + NW, y1 = a.y + NH / 2, x2 = b.x, y2 = b.y + NH / 2, mx = (x1 + x2) / 2;
          return (
            <path key={d.dependency_id} className={d.dependency_type === "mandatory" ? "dag__edge" : "dag__edge dag__edge--optional"} d={`M${x1} ${y1} C${mx} ${y1} ${mx} ${y2} ${x2} ${y2}`} markerEnd="url(#dag-arrow)">
              <title>{`${label(byId.get(d.prerequisite_id)?.step_name ?? d.prerequisite_id)} before ${label(byId.get(d.step_definition_id)?.step_name ?? d.step_definition_id)} (${d.dependency_type})`}</title>
            </path>
          );
        })}
        {order.map((id, i) => {
          const s = byId.get(id), p = positions.get(id);
          if (!s || !p) return null;
          return (
            <g key={id} transform={`translate(${p.x} ${p.y})`}>
              <rect className={s.required ? "dag__node" : "dag__node dag__node--optional"} width={NW} height={NH} rx={8}><title>{`${i + 1}. ${label(s.step_name)}, ${s.required ? "required" : "optional"}, role ${s.role_key}`}</title></rect>
              <text className="dag__num" x={10} y={20}>{i + 1}</text>
              <text className="dag__name" x={28} y={20}>{clip(label(s.step_name), 19)}</text>
              <text className="dag__meta" x={10} y={42}>{`${s.required ? "required" : "optional"} · role ${clip(s.role_key, 12)}`}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
