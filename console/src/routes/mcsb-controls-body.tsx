import { useMemo } from "preact/hooks";
import { DataTable, KpiCard, KpiGrid, StatusPill, type Column, type PillKind } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { composeGlossary } from "../deck/glossary";
import { displayValue, t } from "./i18n/governance";
import {
  mcsbControlsHref,
  type McsbControl,
  type McsbControlResponse,
  type McsbCoverage,
  type McsbFilters,
  type McsbAssessmentSummary,
  type McsbSatisfaction,
} from "./mcsb-controls.model";
import { FacetChips, FacetSelect } from "./rule-catalog-components";

const EMPTY_FILTERS: McsbFilters = { domain: "", coverage: "", q: "" };
export const MCSB_COVERAGE_PILL: Readonly<Record<McsbCoverage, PillKind>> = {
  automated: "success",
  partial: "warning",
  manual: "info",
  unmapped: "neutral",
};
export const MCSB_SATISFACTION_PILL: Readonly<Record<McsbSatisfaction, PillKind>> = {
  satisfied: "success",
  failed: "danger",
  not_applicable: "info",
  unknown: "neutral",
};

export function mcsbAssessmentSummaryText(summary: McsbAssessmentSummary | null): string {
  if (summary === null) return t("governance.rules.mcsb.assessment.unavailable");
  if (summary.status !== "evaluated") return t(`governance.rules.mcsb.assessment.${summary.status}`);
  const counts = summary.satisfaction_counts;
  return t("governance.rules.mcsb.assessment.evaluated", {
    time: summary.last_evaluated_at ?? "-",
    failed: counts["failed"] ?? 0,
    unknown: counts["unknown"] ?? 0,
    satisfied: counts["satisfied"] ?? 0,
  });
}

export function McsbControlsBody({
  data,
  filters,
  searchInput,
  loading,
  selected,
  onFilter,
  onSearch,
  onSelect,
}: {
  readonly data: McsbControlResponse;
  readonly filters: McsbFilters;
  readonly searchInput: string;
  readonly loading: boolean;
  readonly selected: string | null;
  readonly onFilter: (patch: Partial<McsbFilters>) => void;
  readonly onSearch: (value: string) => void;
  readonly onSelect: (controlId: string) => void;
}) {
  const version = data.benchmark.benchmark_version;
  const coverage = data.benchmark.coverage_counts;
  const automated = coverage["automated"] ?? 0;
  const partial = coverage["partial"] ?? 0;
  const manual = coverage["manual"] ?? 0;
  const unmapped = coverage["unmapped"] ?? 0;
  const policyRefs = data.benchmark.policy_profiles.reduce(
    (sum, profile) => sum + profile.policy_ref_count,
    0,
  );
  const assessed = data.assessment_summary !== null && data.assessment_summary.status !== "not_assessed";
  const columns: readonly Column<McsbControl>[] = useMemo(
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
        key: "domain",
        header: t("governance.rules.mcsb.column.domain"),
        cellClass: "control-column-secondary",
        headerClass: "control-column-secondary",
        render: (control) => displayValue("mcsbDomain", control.domain),
      },
      {
        key: "coverage",
        header: t("governance.rules.mcsb.column.coverage"),
        render: (control) => (
          <span class="mcsb-status-cell">
            <StatusPill
              kind={MCSB_COVERAGE_PILL[control.coverage]}
              label={displayValue("mcsbCoverage", control.coverage)}
            />
            {/* Narrow screens hide the assessment column and show its pill here instead. */}
            {assessed && control.assessment !== null ? (
              <span class="mcsb-assessment-inline">
                <StatusPill
                  kind={MCSB_SATISFACTION_PILL[control.assessment.satisfaction]}
                  label={displayValue("controlStatus", control.assessment.satisfaction)}
                />
              </span>
            ) : null}
          </span>
        ),
      },
      ...(assessed
        ? [
            {
              key: "assessment",
              header: t("governance.rules.mcsb.column.assessment"),
              headerClass: "mcsb-assessment-column",
              cellClass: "mcsb-assessment-column",
              render: (control: McsbControl) =>
                control.assessment === null ? (
                  <span class="muted">{t("governance.rules.mcsb.assessment.none")}</span>
                ) : (
                  <StatusPill
                    kind={MCSB_SATISFACTION_PILL[control.assessment.satisfaction]}
                    label={displayValue("controlStatus", control.assessment.satisfaction)}
                  />
                ),
            },
          ]
        : []),
      {
        key: "rules",
        header: t("governance.rules.mcsb.column.rules"),
        cellClass: "num control-column-secondary",
        headerClass: "num control-column-secondary",
        render: (control) => control.rule_count,
      },
      {
        key: "runtime",
        header: t("governance.rules.mcsb.column.runtime"),
        cellClass: "num control-column-secondary",
        headerClass: "num control-column-secondary",
        render: (control) => control.runtime_observation_count,
      },
      {
        key: "manual",
        header: t("governance.rules.mcsb.column.manual"),
        cellClass: "num control-column-secondary",
        headerClass: "num control-column-secondary",
        render: (control) => control.manual_evidence_count,
      },
      {
        key: "chevron",
        header: "",
        headerClass: "chevron-col",
        cellClass: "chevron-col",
        render: () => <span class="row-chevron" aria-hidden="true">›</span>,
      },
    ],
    [assessed],
  );

  usePublishViewContext(
    () => ({
      routeId: "rules",
      routeLabel: t("governance.rules.mcsb.context.routeLabel"),
      purpose: t("governance.rules.mcsb.context.purpose"),
      glossary: composeGlossary([]),
      headline: t("governance.rules.mcsb.context.headline", {
        version,
        total: data.total,
        unmapped,
      }),
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "benchmark_version", value: version, group: "catalog" },
        { key: "control_definition_count", value: data.total, group: "catalog" },
        { key: "automated_coverage_count", value: automated, group: "coverage" },
        { key: "partial_coverage_count", value: partial, group: "coverage" },
        { key: "manual_coverage_count", value: manual, group: "coverage" },
        { key: "unmapped_coverage_count", value: unmapped, group: "coverage" },
        { key: "azure_policy_reference_count", value: policyRefs, group: "catalog" },
        { key: "evaluation_source", value: data.evaluation_source, group: "evidence" },
        {
          key: "shadow_assessment_status",
          value: data.assessment_summary?.status ?? "unavailable",
          group: "evidence",
        },
      ],
      records: {
        controls: data.controls.map((control) => ({
          control_id: control.control_id,
          title: control.title,
          domain: control.domain,
          coverage: control.coverage,
          rule_count: control.rule_count,
          runtime_observation_count: control.runtime_observation_count,
          manual_evidence_count: control.manual_evidence_count,
          assessment_satisfaction: control.assessment?.satisfaction ?? null,
        })),
      },
    }),
    [automated, data, manual, partial, policyRefs, unmapped, version],
  );

  const metadataOnly = data.benchmark.control_import_status === "metadata_only";
  const previewDefinitions = data.benchmark.status === "preview" && !metadataOnly;
  const bannerTitle = metadataOnly
    ? "governance.rules.mcsb.banner.metadataTitle"
    : previewDefinitions
      ? "governance.rules.mcsb.banner.previewTitle"
      : "governance.rules.mcsb.banner.title";
  const bannerBody = metadataOnly
    ? "governance.rules.mcsb.banner.metadataBody"
    : previewDefinitions
      ? "governance.rules.mcsb.banner.previewBody"
      : "governance.rules.mcsb.banner.body";
  return (
    <div class="stack">
      <div class="governance-readonly-banner mcsb-coverage-banner">
        <strong>{t(bannerTitle)}</strong>
        <span>{t(bannerBody, { policyRefs, total: data.total })}</span>
        {assessed ? <span class="mcsb-assessment-summary">{mcsbAssessmentSummaryText(data.assessment_summary)}</span> : null}
      </div>
      <KpiGrid>
        <KpiCard href={mcsbControlsHref(version, EMPTY_FILTERS, null)} label={t("governance.rules.mcsb.kpi.total")} value={data.total} />
        <KpiCard href={mcsbControlsHref(version, { ...EMPTY_FILTERS, coverage: "automated" }, null)} label={t("governance.rules.mcsb.kpi.automated")} value={automated} />
        <KpiCard href={mcsbControlsHref(version, { ...EMPTY_FILTERS, coverage: "partial" }, null)} label={t("governance.rules.mcsb.kpi.partial")} value={partial} />
        <KpiCard href={mcsbControlsHref(version, { ...EMPTY_FILTERS, coverage: "manual" }, null)} label={t("governance.rules.mcsb.kpi.manual")} value={manual} />
        <KpiCard href={mcsbControlsHref(version, { ...EMPTY_FILTERS, coverage: "unmapped" }, null)} label={t("governance.rules.mcsb.kpi.unmapped")} value={unmapped} />
      </KpiGrid>
      <section class="stack-section">
        <div class="rule-facet-toolbar">
          <FacetSelect label={t("governance.rules.mcsb.filter.domain")} value={filters.domain} counts={data.facets.by_domain} onChange={(domain) => onFilter({ domain })} />
          <FacetChips label={t("governance.rules.mcsb.filter.coverage")} value={filters.coverage} counts={data.facets.by_coverage} displayGroup="mcsbCoverage" onChange={(coverageValue) => onFilter({ coverage: coverageValue })} />
          <label class="rule-facet-search">
            <span class="sr-only">{t("governance.rules.mcsb.filter.searchAria")}</span>
            <input type="search" value={searchInput} placeholder={t("governance.rules.mcsb.filter.searchPlaceholder")} onInput={(event) => onSearch((event.target as HTMLInputElement).value)} />
          </label>
        </div>
        <div class="table-toolbar">
          <p class="muted">{t("governance.rules.mcsb.result.showing", { filtered: data.filtered_total, total: data.total })}{loading ? t("governance.rules.result.updating") : ""}</p>
        </div>
        <div id="mcsb-control-table" class={loading ? "is-refreshing" : undefined} aria-busy={loading}>
          <DataTable<McsbControl>
            columns={columns}
            rows={data.controls}
            keyOf={(control) => control.control_id}
            empty={t(metadataOnly ? "governance.rules.mcsb.result.metadataOnly" : "governance.rules.mcsb.result.empty")}
            onRowClick={(control) => onSelect(control.control_id)}
            isRowActive={(control) => selected === control.control_id}
          />
        </div>
      </section>
    </div>
  );
}
