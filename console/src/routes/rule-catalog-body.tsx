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
import { t } from "../i18n";
import { FacetChips } from "./rule-catalog-components";
import type { RuleFilters as Filters, RuleSelection as Selection } from "./rule-catalog-state";
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
              value: selectedDetail.explanation.description ?? selectedDetail.explanation.title ?? "(none)",
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
              : "not evaluated",
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
        routeLabel: "Rules",
        purpose:
          "The versioned rule catalog the deterministic engine (T0) evaluates - " +
          "each rule normalized to id/severity/category/resource-type/check/" +
          "remediation with provenance. Filter by origin, category, severity, " +
          "or source. Read-only reference.",
        glossary: composeGlossary([TERMS.actionType, TERMS.tier, TERMS.mode]),
        headline:
          selected !== null
            ? `Rule ${selected.id} selected - ${data.total} rules (${active} active, ${collected} collected)`
            : `${data.total} rules (${active} active, ${collected} collected)`,
        capturedAt: new Date().toISOString(),
        facts: [
          { key: "total_rules", value: data.total, group: "catalog" },
          { key: "active_rules", value: active, group: "catalog" },
          { key: "collected_rules", value: collected, group: "catalog" },
          { key: "filtered_total", value: data.filtered_total, group: "catalog" },
          { key: "resource_types", value: data.resource_type_count, group: "catalog" },
          {
            key: "categories_available",
            value: Object.keys(data.facets.by_category).join(", ") || "(none)",
            group: "catalog",
          },
          { key: "search_query", value: filters.q || "(none)", group: "filter" },
          { key: "filter_origin", value: filters.origin || "(all)", group: "filter" },
          { key: "filter_category", value: filters.category || "(all)", group: "filter" },
          { key: "filter_severity", value: filters.severity || "(all)", group: "filter" },
          { key: "filter_source", value: filters.source || "(all)", group: "filter" },
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
        header: "Rule",
        render: (rule) => (
          <span class="rule-table-identity">
            <code>{rule.id}</code>
            <small>provenance: {rule.provenance.source_url || rule.source}</small>
          </span>
        ),
      },
      {
        key: "origin",
        header: "Origin",
        render: (rule) => (
          <StatusPill kind={rule.origin === "active" ? "enforce" : "neutral"} label={rule.origin} />
        ),
      },
      {
        key: "severity",
        header: "Severity",
        render: (rule) => (
          <StatusPill kind={SEVERITY_PILL[rule.severity] ?? "neutral"} label={rule.severity} />
        ),
      },
      {
        key: "category",
        header: "Category",
        render: (rule) => <span class={`rule-category-pill is-${rule.category}`}>{rule.category}</span>,
      },
      {
        key: "resource_type",
        header: "Resource",
        render: (rule) => rule.resource_type,
        cellClass: "mono",
      },
      { key: "source", header: "Source", render: (rule) => rule.source },
      { key: "version", header: "Version", render: (rule) => rule.version, cellClass: "mono" },
      {
        key: "affected",
        header: "Affected",
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

  return (
    <div class="stack">
      <div class="governance-readonly-banner">
        <strong>Catalog-as-code.</strong>
        <span>Every rule is a versioned artifact. This page renders active and collected entries; changes land through the catalog PR pipeline.</span>
      </div>
      <KpiGrid>
        <KpiCard label="Total rules" value={data.total} />
        <KpiCard label="Active catalog" value={active} hint="Curated - T0 evaluates these" />
        <KpiCard label="Collected corpus" value={collected} hint="Imported upstream sources" />
        <KpiCard label="Resource types" value={data.resource_type_count} />
      </KpiGrid>

      <section class="stack-section">
        <div class="rule-facet-toolbar">
          <FacetChips label="Origin" value={filters.origin} counts={data.facets.by_origin} onChange={(value) => onFilter({ origin: value })} />
          <FacetChips label="Category" value={filters.category} counts={data.facets.by_category} onChange={(value) => onFilter({ category: value })} />
          <FacetChips label="Severity" value={filters.severity} counts={data.facets.by_severity} onChange={(value) => onFilter({ severity: value })} />
          <FacetChips label="Source" value={filters.source} counts={data.facets.by_source} onChange={(value) => onFilter({ source: value })} />
          <label class="rule-facet-search">
            <span class="sr-only">Search id or resource</span>
            <input
              type="search"
              value={searchInput}
              placeholder="e.g. disk.unattached"
              onInput={(event) => onSearch((event.target as HTMLInputElement).value)}
            />
          </label>
        </div>

        <div class="table-toolbar">
          <p class="muted">
            {data.filtered_total === 0
              ? "No rules match the current filters."
              : `Showing ${pageStart}-${pageEnd} of ${data.filtered_total} filtered (${data.total} total)`}
            {loading ? <span class="muted"> - updating...</span> : null}
          </p>
          <div class="pager">
            <button type="button" class="btn" disabled={loading || !hasPrev} onClick={() => onPage(Math.max(0, data.offset - data.limit))}>
              Prev
            </button>
            <button type="button" class="btn" disabled={loading || !hasNext} onClick={() => onPage(data.offset + data.limit)}>
              Next
            </button>
          </div>
        </div>

        <div class={loading ? "is-refreshing" : undefined} aria-busy={loading}>
          <DataTable<RuleDto>
            columns={columns}
            rows={data.rules}
            keyOf={(rule) => `${rule.origin}:${rule.id}`}
            empty="No rules match the current filters."
            onRowClick={(rule) => onSelect({ id: rule.id, origin: rule.origin })}
            isRowActive={(rule) => selected !== null && selected.id === rule.id && selected.origin === rule.origin}
          />
        </div>
      </section>
    </div>
  );
}
