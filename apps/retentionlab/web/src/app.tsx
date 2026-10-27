import type { ReactElement } from "react";
import { Layout } from "./components/layout";
import { useRoute } from "./router";
import { ROUTES } from "./routes";
import { AccountView } from "./views/account";
import { CalibrationView } from "./views/calibration";
import { CapacityView } from "./views/capacity";
import { CaseStudy } from "./views/case-study";
import { CohortsView } from "./views/cohorts";
import { EvidenceView } from "./views/evidence";
import { FeaturesView } from "./views/features";
import { Landing } from "./views/landing";
import { ModelsView } from "./views/models";
import { MonitoringView } from "./views/monitoring";
import { NotFound } from "./views/not-found";
import { OverviewView } from "./views/overview";
import { QueueView } from "./views/queue";

const VIEWS: Record<string, () => ReactElement> = {
  "": Landing, overview: OverviewView, cohorts: CohortsView, features: FeaturesView, models: ModelsView, calibration: CalibrationView, capacity: CapacityView,
  account: AccountView, queue: QueueView, monitoring: MonitoringView, evidence: EvidenceView, "case-study": CaseStudy,
};

export function App() {
  const route = useRoute();
  const def = route === null ? null : ROUTES.find((r) => r.path === route)!;
  const View = route === null ? NotFound : VIEWS[route]!;
  return <Layout route={route} title={def?.title ?? "Not found"}><View /></Layout>;
}
