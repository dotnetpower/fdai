import { t } from "../routes/i18n/architecture";
import {
  type InventoryGraphResponse,
} from "./architecture-map.model";

interface Props {
  readonly graph: InventoryGraphResponse;
  readonly onViewScopeChange: (scope: string) => void;
}

export function ArchitectureOverviewPanel({
  graph,
  onViewScopeChange,
}: Props) {
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
    </aside>
  );
}
