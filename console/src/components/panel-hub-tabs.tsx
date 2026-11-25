import type { ConsoleDataMode } from "../console-data-mode";
import { supportsSampleData } from "../console-data-mode";
import { t } from "../i18n";
import { hubPanelsFor } from "../panels";
import { panelPath, routeHref } from "../router";

interface PanelHubTabsProps {
  readonly activePanelId: string;
  readonly dataMode?: ConsoleDataMode;
}

export function PanelHubTabs({ activePanelId, dataMode }: PanelHubTabsProps) {
  const tabs = hubPanelsFor(activePanelId);
  if (tabs.length < 2) return null;

  return (
    <nav class="panel-hub-tabs" aria-label={t("nav.hubTabsLabel")}>
      {tabs.map((tab) => {
        const active = tab.id === activePanelId;
        const href = dataMode === "sample" && supportsSampleData(tab.id)
          ? routeHref(tab.id, { params: { data: "sample" } })
          : panelPath(tab.id);
        return (
          <a
            key={tab.id}
            href={href}
            class={active ? "is-active" : undefined}
            aria-current={active ? "page" : undefined}
          >
            {tab.label}
          </a>
        );
      })}
    </nav>
  );
}
