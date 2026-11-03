import { useEffect, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { ErrorState, PageHeader } from "../components/ui";
import type { ConsoleDataMode } from "../console-data-mode";
import { t } from "../i18n";
import { currentRoute, hasTransientRoute, navigate, replaceRouteState, routeHref } from "../router";
import { OnboardingRoute } from "./onboarding";
import { ProvisionRoute } from "./provision";
import type { ProvisionViewId } from "./provision-view";
import { EnvironmentDeploymentObservers } from "./environment-deployment-observers";
import { environmentUxText } from "./environment-deployment.i18n";
import "./environment-deployment.css";

export type EnvironmentDeploymentTab = "readiness" | "deployment" | "observers";

const ENVIRONMENT_DEPLOYMENT_TABS: readonly EnvironmentDeploymentTab[] = [
  "readiness",
  "deployment",
  "observers",
];

export function environmentDeploymentTabFromSegment(
  segment: string | undefined,
): EnvironmentDeploymentTab | null {
  if (segment === undefined) return "readiness";
  return ENVIRONMENT_DEPLOYMENT_TABS.includes(segment as EnvironmentDeploymentTab)
    ? segment as EnvironmentDeploymentTab
    : null;
}

export function nextEnvironmentDeploymentTab(
  current: EnvironmentDeploymentTab,
  key: string,
): EnvironmentDeploymentTab {
  if (key === "Home") return ENVIRONMENT_DEPLOYMENT_TABS[0]!;
  if (key === "End") {
    return ENVIRONMENT_DEPLOYMENT_TABS[ENVIRONMENT_DEPLOYMENT_TABS.length - 1]!;
  }
  if (key !== "ArrowLeft" && key !== "ArrowRight") return current;
  const direction = key === "ArrowRight" ? 1 : -1;
  const currentIndex = ENVIRONMENT_DEPLOYMENT_TABS.indexOf(current);
  return ENVIRONMENT_DEPLOYMENT_TABS[
    (currentIndex + direction + ENVIRONMENT_DEPLOYMENT_TABS.length)
      % ENVIRONMENT_DEPLOYMENT_TABS.length
  ]!;
}

export function environmentDeploymentHref(
  tab: EnvironmentDeploymentTab,
  dataMode?: ConsoleDataMode,
  search = new URLSearchParams(),
): string {
  const view = environmentDeploymentViewFromSearch(search);
  const locale = search.get("locale");
  return routeHref("settings-environment", {
    segments: tab === "readiness" ? [] : [tab],
    params: {
      data: dataMode === "sample" ? "sample" : null,
      locale: locale === "en" || locale === "ko" ? locale : null,
      "deployment-view": view === "stages" ? null : view,
    },
  });
}

export function environmentDeploymentViewFromSearch(search: URLSearchParams): ProvisionViewId {
  const value = search.get("deployment-view");
  return value === "readiness" || value === "resources" ? value : "stages";
}

export function EnvironmentDeploymentRoute({
  client,
  dataMode,
}: {
  readonly client: OperatorApiClient;
  readonly dataMode: ConsoleDataMode;
}) {
  const route = currentRoute();
  const requestedTab = environmentDeploymentTabFromSegment(route.segments[0]);
  const activeTab = requestedTab ?? "readiness";
  const [focusedTab, setFocusedTab] = useState(activeTab);
  const [deploymentGeneration, setDeploymentGeneration] = useState(0);
  const [deploymentView, setDeploymentView] = useState<ProvisionViewId>(environmentDeploymentViewFromSearch(route.search));
  useEffect(() => { setFocusedTab(activeTab); }, [activeTab]);

  const selectTab = (tab: EnvironmentDeploymentTab): void => {
    navigate(environmentDeploymentHref(tab, dataMode, currentRoute().search));
  };
  const selectDeploymentView = (view: ProvisionViewId): void => {
    setDeploymentView(view);
    const search = new URLSearchParams(currentRoute().search);
    search.set("deployment-view", view);
    const href = environmentDeploymentHref("deployment", dataMode, search);
    if (hasTransientRoute()) navigate(href, true);
    else replaceRouteState(href);
  };

  return (
    <div class="stack settings-route environment-deployment-route">
      <PageHeader
        title={t("route.settingsEnvironment")}
        subtitle={t("environmentDeployment.subtitle")}
      />
      <div
        class="settings-tabs environment-deployment-tabs"
        role="tablist"
        aria-label={t("environmentDeployment.tabsLabel")}
        onKeyDown={(event) => {
          const next = nextEnvironmentDeploymentTab(focusedTab, event.key);
          if (next === focusedTab) return;
          event.preventDefault();
          setFocusedTab(next);
          document.getElementById(`environment-deployment-tab-${next}`)?.focus();
        }}
      >
        {ENVIRONMENT_DEPLOYMENT_TABS.map((tab) => (
          <button
            key={tab}
            id={`environment-deployment-tab-${tab}`}
            type="button"
            role="tab"
            class={requestedTab !== null && activeTab === tab ? "is-active" : undefined}
            aria-selected={requestedTab !== null && activeTab === tab}
            aria-controls={`environment-deployment-panel-${tab}`}
            tabIndex={focusedTab === tab ? 0 : -1}
            onFocus={() => setFocusedTab(tab)}
            onClick={() => selectTab(tab)}
          >
            {t(`environmentDeployment.${tab}Tab`)}
          </button>
        ))}
      </div>
      {requestedTab === null ? (
        <div class="stack"><ErrorState message={t("environmentDeployment.invalidTab")} />
          <a class="btn secondary" href={environmentDeploymentHref("readiness", dataMode, route.search)}>{environmentUxText("recover")}</a>
        </div>
      ) : (
        <section
          id={`environment-deployment-panel-${activeTab}`}
          class="environment-deployment-panel"
          role="tabpanel"
          aria-labelledby={`environment-deployment-tab-${activeTab}`}
          tabIndex={0}
        >
          {activeTab === "readiness"
            ? <OnboardingRoute client={client} dataMode={dataMode} embedded />
            : activeTab === "deployment"
              ? <>
                <div class="settings-actions"><button type="button" class="btn secondary"
                  aria-describedby="deployment-reload-hint"
                  onClick={() => setDeploymentGeneration((value) => value + 1)}>{environmentUxText("retrySource")}</button>
                  <small id="deployment-reload-hint">{environmentUxText("retrySourceHint")}</small>
                </div>
                <ProvisionRoute key={deploymentGeneration} client={client} dataMode={dataMode} embedded
                  evidenceView={deploymentView} onEvidenceViewChange={selectDeploymentView} />
              </>
              : <EnvironmentDeploymentObservers client={client} dataMode={dataMode} />}
        </section>
      )}
    </div>
  );
}
