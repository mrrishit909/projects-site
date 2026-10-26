import type { ReactElement } from "react";
import { Layout } from "./components/layout";
import { useRoute } from "./router";
import { ROUTES } from "./routes";
import { AtlasProvider } from "./state/atlas";
import { Bridge } from "./views/bridge";
import { CaseStudy } from "./views/case-study";
import { Customers } from "./views/customers";
import { Discounts } from "./views/discounts";
import { Evidence } from "./views/evidence";
import { Landing } from "./views/landing";
import { NotFound } from "./views/not-found";
import { Overview } from "./views/overview";
import { Products } from "./views/products";
import { Regions } from "./views/regions";
import { Returns } from "./views/returns";
import { Scenarios } from "./views/scenarios";

const VIEWS: Record<string, () => ReactElement> = {
  "": Landing, overview: Overview, bridge: Bridge, products: Products, customers: Customers,
  regions: Regions, returns: Returns, discounts: Discounts, evidence: Evidence, scenarios: Scenarios,
  "case-study": CaseStudy,
};

export function App() {
  const route = useRoute();
  const View = route === null ? NotFound : VIEWS[route]!;
  const title = route === null ? "Not found" : ROUTES.find((r) => r.path === route)!.title;
  return (
    <AtlasProvider>
      <Layout route={route} title={title}><View /></Layout>
    </AtlasProvider>
  );
}
