import type { ReactElement } from "react";
import { Layout } from "./components/layout";
import { useRoute } from "./router";
import { ROUTES } from "./routes";
import { Landing } from "./views/landing";
import { PortfolioView } from "./views/portfolio";
import { BusinessCaseView } from "./views/business-case";
import { BaselineView } from "./views/baseline";
import { SensitivityView } from "./views/sensitivity";
import { RoadmapView } from "./views/roadmap";
import { ImpactView } from "./views/impact";
import { ReadinessView } from "./views/readiness";
import { BenefitsView } from "./views/benefits";
import { ForecastView } from "./views/forecast";
import { CaseStudy } from "./views/case-study";
import { EvidenceView } from "./views/evidence";
import { NotFound } from "./views/not-found";

const VIEWS: Record<string, () => ReactElement> = {
  "": Landing, portfolio: PortfolioView, baseline: BaselineView, "business-case": BusinessCaseView, sensitivity: SensitivityView, roadmap: RoadmapView, impact: ImpactView,
  readiness: ReadinessView, benefits: BenefitsView, forecast: ForecastView, evidence: EvidenceView, "case-study": CaseStudy,
};

export function App() {
  const route = useRoute();
  const def = route === null ? null : ROUTES.find((r) => r.path === route)!;
  const View = route === null ? NotFound : VIEWS[route]!;
  return <Layout route={route} title={def?.title ?? "Not found"}><View /></Layout>;
}
