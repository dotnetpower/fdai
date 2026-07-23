import { useMemo } from "preact/hooks";
import { Tooltip } from "../components/tooltip";
import {
  DataTable,
  KpiCard,
  KpiGrid,
  StatusPill,
  type Column,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { routeHref } from "../router";
import { displayValue, t } from "./i18n/governance";
import { FacetChips } from "./rule-catalog-components";
import { ruleCatalogHref, type RuleFilters as Filters, type RuleSelection as Selection } from "./rule-catalog-state";
import {
  SEVERITY_PILL,
  type DetailState,
  type FindingsState,
  type RuleCatalogResponse,
  type RuleDto,
} from "./rule-catalog-types";

export interface RuleCatalogBodyProps {
  readonly data: RuleCatalogResponse;
  readonly filters: Filters;
  readonly searchInput: string;
  readonly loading: boolean;
  readonly selected: Selection | null;
  readonly detail: DetailState;
  readonly findings: FindingsState;
  readonly affectedCounts: Readonly<Record<string, number>>;
  readonly onSelect: (selection: Selection) => void;
  readonly onFilter: (patch: Partial<Filters>) => void;
  readonly onSearch: (next: string) => void;
  readonly onPage: (offset: number) => void;
}

export function RuleCatalogBody({
  data,
  filters,
  searchInput,
  loading,
  selected,
  detail,
  findings,
  affectedCounts,
  onSelect,
  onFilter,
  onSearch,
  onPage,
}: RuleCatalogBodyProps) {
  const active = data.facets.by_origin["active"] ?? 0;
  const collected = data.facets.by_origin["collected"] ?? 0;

  usePublishViewContext(
    () => {
      const selectionFacts: { key: string; value: string | number | boolean | null; group?: string }[] = [];
      const selectionRecords: Record<string, readonly Record<string, unknown>[]> = {};
      if (selected !== null) {
        selectionFacts.push(
          { key: "selected_rule", value: selected.id, group: "selection" },
          { key: "selected_origin", value: selected.origin, group: "selection" },
        );
        if (detail.status === "ready") {
          const selectedDetail = detail.data;
          selectionFacts.push(
            { key: "selected_severity", value: selectedDetail.severity, group: "selection" },
            { key: "selected_category", value: selectedDetail.category, group: "selection" },
            { key: "selected_resource_type", value: selectedDetail.resource_type, group: "selection" },
            { key: "selected_source", value: selectedDetail.source, group: "selection" },
            { key: "selected_remediation", value: selectedDetail.remediation.template_ref, group: "selection" },
            {
              key: "selected_monthly_cost_usd",
              value: selectedDetail.remediation.cost_impact_monthly_usd,
              group: "selection",
            },
            {
              key: "selected_explanation",
              value: selectedDetail.explanation.description ?? selectedDetail.explanation.title ?? t("governance.common.parentheticalNone"),
              group: "selection",
            },
            { key: "selected_remediates", value: selectedDetail.remediates, group: "selection" },
          );
        } else {
          selectionFacts.push({
            key: "selected_rule_detail",
            value: detail.status,
            group: "selection",
          });
        }
        if (findings.status === "ready") {
          const selectedFindings = findings.data;
          selectionFacts.push({
            key: "selected_affected_count",
            value: selectedFindings.evaluated
              ? (selectedFindings.finding_count ?? selectedFindings.findings.length)
              : t("governance.common.notEvaluated"),
            group: "selection",
          });
          if (selectedFindings.findings.length > 0) {
            selectionRecords["selected_findings"] = selectedFindings.findings.map((finding) => ({
              resource_id: finding.resource_id,
              resource_name: finding.resource_name ?? "-",
              severity: finding.severity ?? "-",
              problem: finding.problem ?? "-",
              observed_at: finding.observed_at ?? "-",
            }));
          }
        }
      }
      return {
        routeId: "rules",
        routeLabel: t("governance.rules.context.routeLabel"),
        purpose: t("governance.rules.context.purpose"),
        glossary: composeGlossary([TERMS.actionType, TERMS.tier, TERMS.mode]),
        headline:
          selected !== null
            ? t("governance.rules.context.selectedHeadline", {
                id: selected.id,
                total: data.total,
                active,
                collected,
              })
            : t("governance.rules.context.headline", {
                total: data.total,
                active,
                collected,
              }),
        capturedAt: new Date().toISOString(),
        facts: [
          { key: "total_rules", value: data.total, group: "catalog" },
          { key: "active_rules", value: active, group: "catalog" },
          { key: "collected_rules", value: collected, group: "catalog" },
          { key: "filtered_total", value: data.filtered_total, group: "catalog" },
          { key: "resource_types", value: data.resource_type_count, group: "catalog" },
          {
            key: "categories_available",
            value: Object.keys(data.facets.by_category).join(", ") || t("governance.common.parentheticalNone"),
            group: "catalog",
          },
          { key: "search_query", value: filters.q || t("governance.common.parentheticalNone"), group: "filter" },
          { key: "filter_origin", value: filters.origin || t("governance.common.parentheticalAll"), group: "filter" },
          { key: "filter_category", value: filters.category || t("governance.common.parentheticalAll"), group: "filter" },
          { key: "filter_severity", value: filters.severity || t("governance.common.parentheticalAll"), group: "filter" },
          { key: "filter_source", value: filters.source || t("governance.common.parentheticalAll"), group: "filter" },
          ...selectionFacts,
        ],
        records: {
          rules: data.rules.map((rule) => ({
            id: rule.id,
            origin: rule.origin,
            severity: rule.severity,
            category: rule.category,
            resource_type: rule.resource_type,
            source: rule.source,
            remediation: rule.remediation.template_ref,
            monthly_cost_usd: rule.remediation.cost_impact_monthly_usd,
          })),
          ...selectionRecords,
        },
      };
    },
    [data, active, collected, filters, selected, detail, findings],
  );

  const columns: readonly Column<RuleDto>[] = useMemo(
    () => [
      {
        key: "id",
        header: t("governance.rules.column.rule"),
        render: (rule) => (
          <span class="rule-table-identity">
            <code>{rule.id}</code>
            <small>{t("governance.rules.column.provenance")}: {rule.provenance.source_url || rule.source}</small>
          </span>
        ),
      },
      {
        key: "origin",
        header: t("governance.rules.column.origin"),
        render: (rule) => (
          <StatusPill kind={rule.origin === "active" ? "enforce" : "neutral"} label={displayValue("origin", rule.origin)} />
        ),
      },
      {
        key: "severity",
        header: t("governance.rules.column.severity"),
        render: (rule) => (
          <StatusPill kind={SEVERITY_PILL[rule.severity] ?? "neutral"} label={displayValue("severity", rule.severity)} />
        ),
      },
      {
        key: "category",
        header: t("governance.rules.column.category"),
        render: (rule) => <span class={`rule-category-pill is-${rule.category}`}>{displayValue("category", rule.category)}</span>,
      },
      {
        key: "resource_type",
        header: t("governance.rules.column.resource"),
        render: (rule) => rule.resource_type,
        cellClass: "mono",
      },
      { key: "source", header: t("governance.rules.column.source"), render: (rule) => rule.source },
      { key: "version", header: t("governance.common.version"), render: (rule) => rule.version, cellClass: "mono" },
      {
        key: "affected",
        header: t("governance.rules.column.affected"),
        headerClass: "num",
        cellClass: "num",
        render: (rule) => {
          const count = affectedCounts[rule.id];
          return count ? (
            <Tooltip content={t("tooltip.affectedResources", { count })}>
              <span class="affected-badge">{count}</span>
            </Tooltip>
          ) : null;
        },
      },
      {
        key: "chevron",
        header: "",
        headerClass: "chevron-col",
        cellClass: "chevron-col",
        render: () => <span class="row-chevron" aria-hidden="true">›</span>,
      },
    ],
    [affectedCounts],
  );

  const pageStart = data.filtered_total === 0 ? 0 : data.offset + 1;
  const pageEnd = Math.min(data.offset + data.limit, data.filtered_total);
  const hasPrev = data.offset > 0;
  const hasNext = data.offset + data.limit < data.filtered_total;
  const tableFragment = "#rule-catalog-table";

  return (
    <div class="stack">
      <div class="governance-readonly-banner">
        <strong>{t("governance.rules.banner.title")}</strong>
        <span>{t("governance.rules.banner.body")}</span>
      </div>
      <KpiGrid>
        <KpiCard href={`${routeHref("rules")}${tableFragment}`} label={t("governance.rules.kpi.total")} value={data.total} />
        <KpiCard href={`${ruleCatalogHref({ ...filters, origin: "active" }, 0, null)}${tableFragment}`} label={t("governance.rules.kpi.active")} value={active} hint={t("governance.rules.kpi.activeHint")} />
        <KpiCard href={`${ruleCatalogHref({ ...filters, origin: "collected" }, 0, null)}${tableFragment}`} label={t("governance.rules.kpi.collected")} value={collected} hint={t("governance.rules.kpi.collectedHint")} />
        <KpiCard href={`${routeHref("rules")}${tableFragment}`} label={t("governance.rules.kpi.resourceTypes")} value={data.resource_type_count} />
      </KpiGrid>

      <section class="stack-section">
        <div class="rule-facet-toolbar">
          <FacetChips label={t("governance.rules.filter.origin")} value={filters.origin} counts={data.facets.by_origin} displayGroup="origin" onChange={(value) => onFilter({ origin: value })} />
          <FacetChips label={t("governance.rules.filter.category")} value={filters.category} counts={data.facets.by_category} displayGroup="category" onChange={(value) => onFilter({ category: value })} />
          <FacetChips label={t("governance.rules.filter.severity")} value={filters.severity} counts={data.facets.by_severity} displayGroup="severity" onChange={(value) => onFilter({ severity: value })} />
          <FacetChips label={t("governance.rules.filter.source")} value={filters.source} counts={data.facets.by_source} onChange={(value) => onFilter({ source: value })} />
          <label class="rule-facet-search">
            <span class="sr-only">{t("governance.rules.filter.searchAria")}</span>
            <input
              type="search"
              value={searchInput}
              placeholder={t("governance.rules.filter.searchPlaceholder")}
              onInput={(event) => onSearch((event.target as HTMLInputElement).value)}
            />
          </label>
        </div>

        <div class="table-toolbar">
          <p class="muted">
            {data.filtered_total === 0
              ? t("governance.rules.result.empty")
              : t("governance.rules.result.showing", {
                  start: pageStart,
                  end: pageEnd,
                  filtered: data.filtered_total,
                  total: data.total,
                })}
            {loading ? <span class="muted">{t("governance.rules.result.updating")}</span> : null}
          </p>
          <div class="pager">
            <button type="button" class="btn" disabled={loading || !hasPrev} onClick={() => onPage(Math.max(0, data.offset - data.limit))}>
              {t("governance.rules.result.previous")}
            </button>
            <button type="button" class="btn" disabled={loading || !hasNext} onClick={() => onPage(data.offset + data.limit)}>
              {t("governance.rules.result.next")}
            </button>
          </div>
        </div>

        <div id="rule-catalog-table" class={loading ? "is-refreshing" : undefined} aria-busy={loading}>
          <DataTable<RuleDto>
            columns={columns}
            rows={data.rules}
            keyOf={(rule) => `${rule.origin}:${rule.id}`}
            empty={t("governance.rules.result.empty")}
            onRowClick={(rule) => onSelect({ id: rule.id, origin: rule.origin })}
            isRowActive={(rule) => selected !== null && selected.id === rule.id && selected.origin === rule.origin}
          />
        </div>
      </section>
    </div>
  );
}
