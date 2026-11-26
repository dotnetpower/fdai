import { useEffect, useState } from "preact/hooks";
import { Nav } from "./components/nav";
import { tr, useHubLocale } from "./locale";
import { currentRoute, subscribe, type Route } from "./router";
import { AuditPage } from "./routes/audit";
import { BundleImportPage } from "./routes/bundle-import";
import { CatalogPage } from "./routes/catalog";
import { CommandsPage } from "./routes/commands";
import { ConfirmationsPage } from "./routes/confirmations";
import { EnrollmentsPage } from "./routes/enrollments";
import { InstallationPage } from "./routes/installation";
import { InstallationsPage } from "./routes/installations";
import { ConfigurationsPage, ReleasesPage } from "./routes/inventory";
import { PlanPage } from "./routes/plan";
import { UpdatesPage } from "./routes/updates";

function useRoute(): Route {
  const [route, setRoute] = useState<Route>(currentRoute());
  useEffect(() => subscribe(() => setRoute(currentRoute())), []);
  return route;
}

function Screen({ route }: { route: Route }) {
  const [locale] = useHubLocale();
  switch (route.kind) {
    case "catalog":
      return <CatalogPage />;
    case "updates":
      return <UpdatesPage />;
    case "releases":
      return <ReleasesPage />;
    case "configurations":
      return <ConfigurationsPage />;
    case "confirmations":
      return <ConfirmationsPage />;
    case "bundle-import":
      return <BundleImportPage />;
    case "commands":
      return <CommandsPage />;
    case "audit":
      return <AuditPage />;
    case "installations":
      return <InstallationsPage />;
    case "installation":
      return <InstallationPage installationId={route.installationId} />;
    case "plan":
      return <PlanPage installationId={route.installationId} planId={route.planId} />;
    case "enrollments":
      return <EnrollmentsPage selectedId={null} />;
    case "enrollment":
      return <EnrollmentsPage selectedId={route.installationId} />;
    case "not-found":
      return (
        <p class="empty">
          {tr(locale, `No screen matches ${route.path}.`, `${route.path} 경로에 해당하는 화면이 없습니다.`)}
        </p>
      );
  }
}

export function App() {
  const route = useRoute();
  const [locale] = useHubLocale();
  return (
    <div class="app" lang={locale}>
      <Nav route={route} />
      <main class="main">
        <Screen route={route} />
      </main>
    </div>
  );
}
