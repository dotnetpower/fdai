import { useEffect, useState } from "preact/hooks";
import { Nav } from "./components/nav";
import { currentRoute, subscribe, type Route } from "./router";
import { AuditPage } from "./routes/audit";
import { CatalogPage } from "./routes/catalog";
import { CommandsPage } from "./routes/commands";
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
  switch (route.kind) {
    case "catalog":
      return <CatalogPage />;
    case "updates":
      return <UpdatesPage />;
    case "releases":
      return <ReleasesPage />;
    case "configurations":
      return <ConfigurationsPage />;
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
      return <p class="empty">No screen matches {route.path}.</p>;
  }
}

export function App() {
  const route = useRoute();
  return (
    <div class="app">
      <Nav route={route} />
      <main class="main">
        <Screen route={route} />
      </main>
    </div>
  );
}
