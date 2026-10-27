import type { ReactElement } from "react";
import { Layout } from "./components/layout";
import { useRoute } from "./router";
import { ROUTES } from "./routes";
import { BackfillView } from "./views/backfill";
import { BenchmarkView } from "./views/benchmark";
import { CaseStudy } from "./views/case-study";
import { DagView } from "./views/dag";
import { EvidenceView } from "./views/evidence";
import { GateView } from "./views/gate";
import { IncidentsView } from "./views/incidents";
import { Landing } from "./views/landing";
import { NotFound } from "./views/not-found";
import { OverviewView } from "./views/overview";
import { QuarantineView } from "./views/quarantine";
import { RunsView } from "./views/runs";
import { SourcesView } from "./views/sources";

const VIEWS: Record<string, () => ReactElement> = {
  "": Landing, overview: OverviewView, dag: DagView, runs: RunsView, sources: SourcesView, quarantine: QuarantineView, gate: GateView, backfill: BackfillView,
  incidents: IncidentsView, benchmark: BenchmarkView, evidence: EvidenceView, "case-study": CaseStudy,
};

export function App() {
  const route = useRoute();
  const def = route === null ? null : ROUTES.find((r) => r.path === route)!;
  const View = route === null ? NotFound : VIEWS[route]!;
  return <Layout route={route} title={def?.title ?? "Not found"}><View /></Layout>;
}
