import type { ReactElement } from "react";
import { Layout } from "./components/layout";
import { useRoute } from "./router";
import { ROUTES } from "./routes";
import { Store } from "./state/store";
import { CaseStudy } from "./views/case-study";
import { Evidence } from "./views/evidence";
import { Landing } from "./views/landing";
import { NotFound } from "./views/not-found";
import { Overview } from "./views/overview";
import { Simulation } from "./views/simulation";
import { Sla } from "./views/sla";
import { Staffing } from "./views/staffing";
import { Stub } from "./views/stub";
import { Tickets } from "./views/tickets";

const VIEWS: Record<string, () => ReactElement> = { "": Landing, overview: Overview, tickets: Tickets, staffing: Staffing, sla: Sla, simulation: Simulation, evidence: Evidence, "case-study": CaseStudy };

export function App() {
  const route = useRoute();
  const def = route === null ? null : ROUTES.find((r) => r.path === route)!;
  const View = route === null ? NotFound : VIEWS[route] ?? (() => <Stub route={def!} />);
  return (
    <Store>
      <Layout route={route} title={def?.title ?? "Not found"}><View /></Layout>
    </Store>
  );
}
