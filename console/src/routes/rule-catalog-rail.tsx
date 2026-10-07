import { routeHref } from "../router";
import { t } from "./i18n/governance";
import { ruleCatalogHref, type RuleFilters } from "./rule-catalog-state";

export type RulesCatalogRailSelection = "all" | "active" | "collected" | "controls";

export interface RulesCatalogRailCounts {
  readonly total: number;
  readonly active: number;
  readonly collected: number;
}

const EMPTY_FILTERS: RuleFilters = { origin: "", category: "", severity: "", source: "", q: "" };

/**
 * Shared Rules catalog rail. Detection Rules and framework Controls stay in separate groups so the
 * rail never implies that Rule counts measure Control applicability, evaluation, or satisfaction.
 */
export function RulesCatalogRail({
  selection,
  counts,
  filters = EMPTY_FILTERS,
}: {
  readonly selection: RulesCatalogRailSelection;
  readonly counts: RulesCatalogRailCounts | null;
  readonly filters?: RuleFilters;
}) {
  const origins = [
    { key: "all", origin: "", label: t("governance.rules.kpi.total"), hint: t("governance.rules.rail.totalHint"), count: counts?.total },
    { key: "active", origin: "active", label: t("governance.rules.kpi.active"), hint: t("governance.rules.kpi.activeHint"), count: counts?.active },
    { key: "collected", origin: "collected", label: t("governance.rules.kpi.collected"), hint: t("governance.rules.kpi.collectedHint"), count: counts?.collected },
  ] as const;
  return (
    <aside class="rules-catalog-rail">
      <header>
        <h2>{t("governance.rules.workspace.title")}</h2>
        <p>{t("governance.rules.workspace.description")}</p>
      </header>
      <nav aria-label={t("governance.rules.view.aria")}>
        <section class="rules-catalog-rail-group" aria-labelledby="rules-rail-detection">
          <h3 id="rules-rail-detection">{t("governance.rules.rail.detectionTitle")}</h3>
          <p>{t("governance.rules.rail.detectionBody")}</p>
          {origins.map((item) => {
            const active = selection === item.key;
            return (
              <a
                key={item.key}
                class={active ? "is-active" : undefined}
                aria-current={active ? "page" : undefined}
                href={ruleCatalogHref({ ...filters, origin: item.origin }, 0, null)}
              >
                <strong>{item.label}</strong>
                <small>{item.count === undefined ? item.hint : `${item.count} - ${item.hint}`}</small>
              </a>
            );
          })}
        </section>
        <section class="rules-catalog-rail-group" aria-labelledby="rules-rail-assessment">
          <h3 id="rules-rail-assessment">{t("governance.rules.rail.assessmentTitle")}</h3>
          <p>{t("governance.rules.rail.assessmentBody")}</p>
          <a
            class={selection === "controls" ? "is-active" : undefined}
            aria-current={selection === "controls" ? "page" : undefined}
            href={routeHref("rules", { params: { view: "controls" } })}
          >
            <strong>{t("governance.rules.view.controls")}</strong>
            <small>{t("governance.rules.rail.controlsHint")}</small>
          </a>
        </section>
      </nav>
    </aside>
  );
}
