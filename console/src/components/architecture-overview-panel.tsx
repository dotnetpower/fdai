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
  const views = graph.views ?? [];
  if (views.length === 0 && !graph.truncated) return null;
  return (
    <aside class="architecture-overview-panel" aria-label={t("mapOverview")}>
      {views.length > 0 ? <label class="architecture-view-picker">
        <span>{t("scope")}</span>
        <select
          value={graph.active_view ?? views[0]?.id ?? ""}
          onChange={(event) => onViewScopeChange((event.target as HTMLSelectElement).value)}
        >
          {(["fdai", "service", "resource_group"] as const).map((kind) => {
            const scopedViews = views.filter((view) => view.kind === kind);
            if (scopedViews.length === 0) return null;
            return (
              <optgroup label={t(kind === "fdai" ? "viewGroup.fdai" : kind === "service" ? "viewGroup.service" : "viewGroup.resourceGroup")}>
                {scopedViews.map((view) => <option value={view.id}>{view.label}</option>)}
              </optgroup>
            );
          })}
        </select>
      </label> : null}
      {graph.truncated ? (
        <span class="architecture-partial-badge" role="status">{t("partialTitle")}</span>
      ) : null}
    </aside>
  );
}
