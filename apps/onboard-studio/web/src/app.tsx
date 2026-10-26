import type { ReactElement } from "react";
import { Layout } from "./components/layout";
import { useRoute } from "./router";
import { ROUTES } from "./routes";
import { StudioProvider } from "./state/studio";
import { Landing } from "./views/landing";
import { NotFound } from "./views/not-found";
import { Stub } from "./views/stub";
import { Cases } from "./views/cases";
import { CaseStudy } from "./views/case-study";
import { Queue } from "./views/queue";
import { Sla } from "./views/sla";
import { Workflow } from "./views/workflow";

const VIEWS: Record<string, () => ReactElement> = { "": Landing, cases: Cases, workflow: Workflow, sla: Sla, queue: Queue, "case-study": CaseStudy };

export function App() {
  const route = useRoute();
  const def = route === null ? null : ROUTES.find((r) => r.path === route)!;
  const View = route === null ? NotFound : VIEWS[route] ?? (() => <Stub route={def!} />);
  return (
    <StudioProvider>
      <Layout route={route} title={def?.title ?? "Not found"}><View /></Layout>
    </StudioProvider>
  );
}
