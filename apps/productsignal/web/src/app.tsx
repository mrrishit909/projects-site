import type { ReactElement } from "react";
import { Layout } from "./components/layout";
import { useRoute } from "./router";
import { ROUTES } from "./routes";
import { CaseStudy } from "./views/case-study";
import { CohortsView } from "./views/cohorts";
import { DecisionView } from "./views/decision";
import { EvidenceView } from "./views/evidence";
import { ExperimentsView } from "./views/experiments";
import { FunnelView } from "./views/funnel";
import { Landing } from "./views/landing";
import { NotFound } from "./views/not-found";
import { OverviewView } from "./views/overview";
import { PopulationView } from "./views/population";
import { ResultView } from "./views/result";
import { SegmentsView } from "./views/segments";
import { TrackingView } from "./views/tracking";

const VIEWS: Record<string, () => ReactElement> = {
  "": Landing, overview: OverviewView, funnel: FunnelView, cohorts: CohortsView, tracking: TrackingView, experiments: ExperimentsView, result: ResultView,
  population: PopulationView, segments: SegmentsView, decision: DecisionView, evidence: EvidenceView, "case-study": CaseStudy,
};

export function App() {
  const route = useRoute();
  const def = route === null ? null : ROUTES.find((r) => r.path === route)!;
  const View = route === null ? NotFound : VIEWS[route]!;
  return <Layout route={route} title={def?.title ?? "Not found"}><View /></Layout>;
}
