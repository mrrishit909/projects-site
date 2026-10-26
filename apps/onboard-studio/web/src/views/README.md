# Views

Built (part 2): `cases` (case timeline), `workflow` (canvas), `sla` (SLA explorer), `queue` (read-only work queue), `case-study`.
Stubs shown as "in progress" in the nav: intake, documents, bottlenecks, versions, simulation (`stub.tsx`).

- Filters and view settings (`from`, `to`, `segment`, `region`, `wf`, `pause`, `case`, `v`) live in the URL query (`src/state/filters.ts`); they never change the dataset.
- Figures come from `src/domain` (exact 4-decimal strings). The pause toggle recomputes with `runOnPopulation` using a policy override.
- Every chart has a table or ordered list built from the same data. Evidence: `npm run e2e` writes `evidence/*.png` and `evidence/index.json`.
