import type { OperatorApiClient } from "../api";
import { ErrorState, PageHeader } from "../components/ui";
import type { ConsoleDataMode } from "../console-data-mode";
import { t } from "../i18n";
import { currentRoute, navigate, routeHref } from "../router";
import { OnboardingRoute } from "./onboarding";
import { ProvisionRoute } from "./provision";
import "./environment-deployment.css";

export type EnvironmentDeploymentTab = "readiness" | "deployment";

const ENVIRONMENT_DEPLOYMENT_TABS: readonly EnvironmentDeploymentTab[] = [
  "readiness",
  "deployment",
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

export function environmentDeploymentHref(tab: EnvironmentDeploymentTab): string {
  return routeHref("settings-environment", {
    segments: tab === "readiness" ? [] : [tab],
  });
}

export function EnvironmentDeploymentRoute({
  client,
  dataMode,
}: {
  readonly client: OperatorApiClient;
  readonly dataMode: ConsoleDataMode;
}) {
  const requestedTab = environmentDeploymentTabFromSegment(currentRoute().segments[0]);
  const activeTab = requestedTab ?? "readiness";

  const selectTab = (tab: EnvironmentDeploymentTab): void => {
    navigate(environmentDeploymentHref(tab));
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
          const next = nextEnvironmentDeploymentTab(activeTab, event.key);
          if (next === activeTab) return;
          event.preventDefault();
          selectTab(next);
          requestAnimationFrame(() => {
            document.getElementById(`environment-deployment-tab-${next}`)?.focus();
          });
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
            tabIndex={activeTab === tab ? 0 : -1}
            onClick={() => selectTab(tab)}
          >
            {t(`environmentDeployment.${tab}Tab`)}
          </button>
        ))}
      </div>
      {requestedTab === null ? (
        <ErrorState message={t("environmentDeployment.invalidTab")} />
      ) : (
        <section
          id={`environment-deployment-panel-${activeTab}`}
          class="environment-deployment-panel"
          role="tabpanel"
          aria-labelledby={`environment-deployment-tab-${activeTab}`}
        >
          {activeTab === "readiness"
            ? <OnboardingRoute client={client} dataMode={dataMode} embedded />
            : <ProvisionRoute client={client} dataMode={dataMode} embedded />}
        </section>
      )}
    </div>
  );
}
