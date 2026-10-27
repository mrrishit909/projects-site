import type { ReactElement } from "react";
import { Layout } from "./components/layout";
import { useRoute } from "./router";
import { ROUTES } from "./routes";
import { CaseStudy } from "./views/case-study";
import { CatalogView } from "./views/catalog";
import { DuplicatesView } from "./views/duplicates";
import { EvidenceView } from "./views/evidence";
import { GlossaryView } from "./views/glossary";
import { ImpactView } from "./views/impact";
import { IssuesView } from "./views/issues";
import { Landing } from "./views/landing";
import { LineageView } from "./views/lineage";
import { MergesView } from "./views/merges";
import { NotFound } from "./views/not-found";
import { RulesView } from "./views/rules";
import { ScorecardView } from "./views/scorecard";

const VIEWS: Record<string, () => ReactElement> = {
  "": Landing, catalog: CatalogView, glossary: GlossaryView, scorecard: ScorecardView, rules: RulesView, issues: IssuesView, lineage: LineageView,
  duplicates: DuplicatesView, merges: MergesView, impact: ImpactView, evidence: EvidenceView, "case-study": CaseStudy,
};

export function App() {
  const route = useRoute();
  const def = route === null ? null : ROUTES.find((r) => r.path === route)!;
  const View = route === null ? NotFound : VIEWS[route]!;
  return <Layout route={route} title={def?.title ?? "Not found"}><View /></Layout>;
}
