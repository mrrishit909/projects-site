import type { ReactElement } from "react";
import { Layout } from "./components/layout";
import { useRoute } from "./router";
import { ROUTES } from "./routes";
import { StudioProvider } from "./state/studio";
import { Landing } from "./views/landing";
import { NotFound } from "./views/not-found";
import { Stub } from "./views/stub";

const VIEWS: Record<string, () => ReactElement> = { "": Landing };

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
