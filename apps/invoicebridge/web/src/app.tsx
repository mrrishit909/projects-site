import type { ReactElement } from "react";
import { Layout } from "./components/layout";
import { useRoute } from "./router";
import { ROUTES } from "./routes";
import { Store } from "./state/store";
import { ApprovalsView } from "./views/approvals";
import { AuditView } from "./views/audit";
import { CaseStudy } from "./views/case-study";
import { DuplicatesView } from "./views/duplicates";
import { ExceptionsView } from "./views/exceptions";
import { ExportsView } from "./views/exports";
import { IntakeView } from "./views/intake";
import { Invoices } from "./views/invoices";
import { Landing } from "./views/landing";
import { MatchingView } from "./views/matching";
import { NotFound } from "./views/not-found";
import { VendorsView } from "./views/vendors";

const VIEWS: Record<string, () => ReactElement> = {
  "": Landing, intake: IntakeView, invoices: Invoices, matching: MatchingView, duplicates: DuplicatesView, exceptions: ExceptionsView,
  approvals: ApprovalsView, vendors: VendorsView, exports: ExportsView, audit: AuditView, "case-study": CaseStudy,
};

export function App() {
  const route = useRoute();
  const def = route === null ? null : ROUTES.find((r) => r.path === route)!;
  const View = route === null ? NotFound : VIEWS[route]!;
  return (
    <Store>
      <Layout route={route} title={def?.title ?? "Not found"}><View /></Layout>
    </Store>
  );
}
