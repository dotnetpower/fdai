import { t } from "../routes/i18n/architecture";
import {
  RESOURCE_COLOR_TOKENS,
  resourceColorTokenOf,
  type ArchitectureResourceColorToken,
  type InventoryGraphResponse,
  type InventoryResource,
} from "./architecture-map.model";

interface Props {
  readonly graph: InventoryGraphResponse;
  readonly onViewScopeChange: (scope: string) => void;
}

interface ResourceLegendEntry {
  readonly token: ArchitectureResourceColorToken;
  readonly label: string;
  readonly color: string;
}

export function architectureResourceLegendEntries(
  resources: readonly InventoryResource[],
): readonly ResourceLegendEntry[] {
  const tokens = new Set<ArchitectureResourceColorToken>();
  for (const resource of resources) {
    tokens.add(resourceColorTokenOf(resource));
  }
  return [...tokens].map((token) => ({
    token,
    label: RESOURCE_COLOR_TOKENS[token].label,
    color: RESOURCE_COLOR_TOKENS[token].color,
  })).sort((first, second) => first.label.localeCompare(second.label));
}

export function ArchitectureOverviewPanel({
  graph,
  onViewScopeChange,
}: Props) {
  const legendEntries = architectureResourceLegendEntries(graph.resources);

  return (
    <aside class="architecture-overview-panel" aria-label={t("mapOverview")}>
      <label class="architecture-view-picker">
        <span>{t("scope")}</span>
        <select
          value={graph.active_view ?? graph.views?.[0]?.id ?? ""}
          onChange={(event) => onViewScopeChange((event.target as HTMLSelectElement).value)}
        >
          {(["fdai", "service", "resource_group"] as const).map((kind) => {
            const views = (graph.views ?? []).filter((view) => view.kind === kind);
            if (views.length === 0) return null;
            return (
              <optgroup label={t(kind === "fdai" ? "viewGroup.fdai" : kind === "service" ? "viewGroup.service" : "viewGroup.resourceGroup")}>
                {views.map((view) => <option value={view.id}>{view.label}</option>)}
              </optgroup>
            );
          })}
        </select>
      </label>
      {graph.truncated ? (
        <span class="architecture-partial-badge" role="status">{t("partialTitle")}</span>
      ) : null}
      <details class="architecture-resource-legend" open>
        <summary>{t("resourceLegend")}</summary>
        <div class="architecture-color-legend" aria-label={t("resourceTypeColors")}>
          {legendEntries.map((entry) => (
            <div key={entry.token} class="architecture-legend-entry">
              <i style={{ backgroundColor: entry.color }} aria-hidden="true" />
              <span>{entry.label}</span>
            </div>
          ))}
        </div>
      </details>
    </aside>
  );
}
