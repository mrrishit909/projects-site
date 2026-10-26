import type { ReactElement } from "react";
import { Layout } from "./components/layout";
import { useRoute } from "./router";
import { ROUTES } from "./routes";
import { AtlasProvider } from "./state/atlas";
import { CaseStudy } from "./views/case-study";
import { Forecast } from "./views/forecast";
import { Landing } from "./views/landing";
import { NotFound } from "./views/not-found";
import { Overview } from "./views/overview";
import { Reorder } from "./views/reorder";
import { Skus } from "./views/skus";
import { Stub } from "./views/stub";

const VIEWS: Record<string, () => ReactElement> = { "": Landing, overview: Overview, skus: Skus, forecast: Forecast, reorder: Reorder, "case-study": CaseStudy };

export function App() {
  const route = useRoute();
  const def = route === null ? null : ROUTES.find((r) => r.path === route)!;
  const View = route === null ? NotFound : VIEWS[route] ?? (() => <Stub route={def!} />);
  return (
    <AtlasProvider>
      <Layout route={route} title={def?.title ?? "Not found"}><View /></Layout>
    </AtlasProvider>
  );
}
