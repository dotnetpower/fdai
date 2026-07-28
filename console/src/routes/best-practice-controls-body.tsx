import { useMemo } from "preact/hooks";
import {
  DataTable,
  KpiCard,
  KpiGrid,
  StatusPill,
  type Column,
  type PillKind,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { composeGlossary } from "../deck/glossary";
import {
  bestPracticeHref,
  type BestPracticeControl,
  type BestPracticeFilters,
  type BestPracticeResponse,
  type ControlStatus,
} from "./best-practice-controls.model";
import { displayValue, t } from "./i18n/governance";
import { FacetChips } from "./rule-catalog-components";
import { SEVERITY_PILL } from "./rule-catalog-types";

const EMPTY_FILTERS: BestPracticeFilters = { pillar: "", status: "", q: "" };
export const CONTROL_STATUS_PILL: Readonly<Record<ControlStatus, PillKind>> = {
  satisfied: "success",
  failed: "danger",
  stale: "warning",
  unknown: "neutral",
  not_applicable: "info",
};

export function BestPracticeControlsBody({
  data,
  filters,
  searchInput,
  loading,
  selected,
  onFilter,
  onSearch,
  onSelect,
}: {
  readonly data: BestPracticeResponse;
  readonly filters: BestPracticeFilters;
  readonly searchInput: string;
  readonly loading: boolean;
  readonly selected: string | null;
  readonly onFilter: (patch: Partial<BestPracticeFilters>) => void;
  readonly onSearch: (value: string) => void;
  readonly onSelect: (id: string) => void;
}) {
  const columns: readonly Column<BestPracticeControl>[] = useMemo(
    () => [
      {
        key: "control",
        header: t("governance.rules.controls.column.control"),
        render: (control) => (
          <span class="control-table-identity">
            <code>{control.control_id}</code>
            <span>{control.title}</span>
          </span>
        ),
      },
      {
        key: "pillar",
        header: t("governance.rules.controls.column.pillar"),
        cellClass: "control-column-secondary",
        headerClass: "control-column-secondary",
        render: (control) => displayValue("controlPillar", control.pillar),
      },
      {
        key: "severity",
        header: t("governance.rules.column.severity"),
        cellClass: "control-column-secondary",
        headerClass: "control-column-secondary",
        render: (control) => (
          <StatusPill
            kind={SEVERITY_PILL[control.severity] ?? "neutral"}
            label={displayValue("severity", control.severity)}
          />
        ),
      },
      {
        key: "requirements",
        header: t("governance.rules.controls.column.requirements"),
        cellClass: "num control-column-secondary",
        headerClass: "num control-column-secondary",
        render: (control) => control.requirement_count,
      },
      {
        key: "owner",
        header: t("governance.rules.controls.column.owner"),
        cellClass: "control-column-owner",
        headerClass: "control-column-owner",
        render: (control) => control.owner ?? "-",
      },
      {
        key: "status",
        header: t("governance.rules.controls.column.status"),
        render: (control) => (
          <StatusPill
            kind={CONTROL_STATUS_PILL[control.status]}
            label={displayValue("controlStatus", control.status)}
          />
        ),
      },
      {
        key: "chevron",
        header: "",
        headerClass: "chevron-col",
        cellClass: "chevron-col",
        render: () => <span class="row-chevron" aria-hidden="true">›</span>,
      },
    ],
    [],
  );
  const reliability = data.facets.by_pillar["reliability"] ?? 0;
  const operations = data.facets.by_pillar["operational_excellence"] ?? 0;
  const unknown = data.facets.by_status["unknown"] ?? 0;

  usePublishViewContext(
    () => ({
      routeId: "rules",
      routeLabel: t("governance.rules.controls.context.routeLabel"),
      purpose: t("governance.rules.controls.context.purpose"),
      glossary: composeGlossary([]),
      headline: t("governance.rules.controls.context.headline", {
        total: data.total,
        unknown,
      }),
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "control_definition_count", value: data.total, group: "catalog" },
        { key: "filtered_control_count", value: data.filtered_total, group: "catalog" },
        { key: "reliability_control_count", value: reliability, group: "catalog" },
        { key: "operational_excellence_control_count", value: operations, group: "catalog" },
        { key: "unknown_control_count", value: unknown, group: "evidence" },
        { key: "evaluation_source", value: data.evaluation_source, group: "evidence" },
        { key: "filter_pillar", value: filters.pillar || "all", group: "filter" },
        { key: "filter_status", value: filters.status || "all", group: "filter" },
        { key: "search_query", value: filters.q || null, group: "filter" },
        { key: "selected_control", value: selected, group: "selection" },
      ],
      records: {
        controls: data.controls.map((control) => ({
          control_id: control.control_id,
          title: control.title,
          pillar: control.pillar,
          severity: control.severity,
          status: control.status,
          requirement_count: control.requirement_count,
          owner: control.owner,
          evaluation_source: control.evaluation_source,
        })),
      },
    }),
    [data, filters, operations, reliability, selected, unknown],
  );

  return (
    <div class="stack">
      <div class="governance-readonly-banner control-evidence-banner" data-evidence-state="not-connected">
        <strong>{t("governance.rules.controls.banner.title")}</strong>
        <span>{t("governance.rules.controls.banner.body")}</span>
      </div>
      <KpiGrid>
        <KpiCard href="#control-catalog-table" label={t("governance.rules.controls.kpi.total")} value={data.total} />
        <KpiCard href={bestPracticeHref({ ...EMPTY_FILTERS, pillar: "reliability" }, null)} label={t("governance.rules.controls.kpi.reliability")} value={reliability} />
        <KpiCard href={bestPracticeHref({ ...EMPTY_FILTERS, pillar: "operational_excellence" }, null)} label={t("governance.rules.controls.kpi.operations")} value={operations} />
        <KpiCard evidenceState="not-connected" href={bestPracticeHref({ ...EMPTY_FILTERS, status: "unknown" }, null)} label={t("governance.rules.controls.kpi.unknown")} value={unknown} hint={t("governance.rules.controls.kpi.notConnected")} />
      </KpiGrid>
      <section class="stack-section">
        <div class="rule-facet-toolbar">
          <FacetChips label={t("governance.rules.controls.filter.pillar")} value={filters.pillar} counts={data.facets.by_pillar} displayGroup="controlPillar" onChange={(pillar) => onFilter({ pillar })} />
          <FacetChips label={t("governance.rules.controls.filter.status")} value={filters.status} counts={data.facets.by_status} displayGroup="controlStatus" onChange={(status) => onFilter({ status })} />
          <label class="rule-facet-search">
            <span class="sr-only">{t("governance.rules.controls.filter.searchAria")}</span>
            <input type="search" value={searchInput} placeholder={t("governance.rules.controls.filter.searchPlaceholder")} onInput={(event) => onSearch((event.target as HTMLInputElement).value)} />
          </label>
        </div>
        <div class="table-toolbar">
          <p class="muted">{t("governance.rules.controls.result.showing", { filtered: data.filtered_total, total: data.total })}{loading ? t("governance.rules.result.updating") : ""}</p>
        </div>
        <div id="control-catalog-table" class={loading ? "is-refreshing" : undefined} aria-busy={loading}>
          <DataTable<BestPracticeControl>
            columns={columns}
            rows={data.controls}
            keyOf={(control) => control.id}
            empty={t("governance.rules.controls.result.empty")}
            onRowClick={(control) => onSelect(control.id)}
            isRowActive={(control) => selected === control.id}
          />
        </div>
      </section>
    </div>
  );
}
