import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, type OperatorApiClient } from "../api";
import { Tooltip } from "../components/tooltip";
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
import { getLocale } from "../i18n";
import { currentRoute, navigate, pushRouteState, replaceRouteState } from "../router";
import { displayValue, t } from "./i18n/governance";
import {
  EMPTY_MSRC_CSAF_FILTERS,
  PINNED_MSRC_CSAF_CATALOG,
  buildMsrcCsafFacets,
  filterMsrcCsafRows,
  mergeMsrcCsafProjection,
  msrcCsafHref,
  msrcCsafStateFromSearch,
  type MsrcCsafCatalog,
  type MsrcCsafControlRow,
  type MsrcCsafExploitStatus,
  type MsrcCsafExposure,
  type MsrcCsafFilters,
} from "./msrc-csaf-controls.model";
import {
  buildMsrcCsafGuidance,
  msrcCsafDisplayTitle,
  parseCvssVector,
} from "./msrc-csaf-guidance";
import { DetailRow, DetailSection, FacetSelect } from "./rule-catalog-components";
import { ruleCatalogHref, type RuleFilters } from "./rule-catalog-state";
import { SEVERITY_PILL } from "./rule-catalog-types";
import { IllustratedGuidanceContent } from "./wara-guidance";
import { guidanceText } from "./wara-guidance.model";

const EMPTY_RULE_FILTERS: RuleFilters = { origin: "", category: "", severity: "", source: "", q: "" };

const EXPLOIT_PILL: Readonly<Record<MsrcCsafExploitStatus, PillKind>> = {
  exploited: "danger",
  exploitation_more_likely: "warning",
  publicly_disclosed: "warning",
  exploitation_less_likely: "info",
  exploitation_unlikely: "neutral",
  unproven: "neutral",
};

const EXPOSURE_PILL: Readonly<Record<MsrcCsafExposure, PillKind>> = {
  affected: "danger",
  mitigated: "warning",
  fixed: "success",
  not_applicable: "info",
  unknown: "neutral",
};

const PAGE_SIZE = 50;

export function MsrcCsafControlsRoute({ client }: { readonly client?: OperatorApiClient } = {}) {
  const initial = msrcCsafStateFromSearch(currentRoute().search);
  const [catalog, setCatalog] = useState<MsrcCsafCatalog>(PINNED_MSRC_CSAF_CATALOG);
  const [filters, setFilters] = useState<MsrcCsafFilters>(initial.filters);
  const [searchInput, setSearchInput] = useState(initial.filters.q);
  const [selected, setSelected] = useState<string | null>(initial.selected);
  const [offset, setOffset] = useState<number>(initial.offset);
  const debounceRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (!client) return;
    let active = true;
    void client
      .panel<unknown>("/msrc-csaf-controls", { limit: "500" })
      .then((raw: unknown) => {
        if (!active) return;
        setCatalog(mergeMsrcCsafProjection(PINNED_MSRC_CSAF_CATALOG, raw));
      })
      .catch((err: unknown) => {
        if (isOptionalOperatorApiUnavailable(err)) {
          return;
        }
      });
    return () => {
      active = false;
    };
  }, [client]);

  useEffect(() => {
    window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      if (searchInput === filters.q) return;
      const next = { ...filters, q: searchInput };
      setFilters(next);
      setOffset(0);
      replaceRouteState(msrcCsafHref(next, selected, 0));
    }, 250);
    return () => window.clearTimeout(debounceRef.current);
  }, [filters, searchInput, selected]);

  useEffect(() => {
    const onRouteChange = () => {
      const next = msrcCsafStateFromSearch(currentRoute().search);
      setFilters(next.filters);
      setSearchInput(next.filters.q);
      setSelected(next.selected);
      setOffset(next.offset);
    };
    window.addEventListener("popstate", onRouteChange);
    window.addEventListener("fdai:route-changed", onRouteChange);
    return () => {
      window.removeEventListener("popstate", onRouteChange);
      window.removeEventListener("fdai:route-changed", onRouteChange);
    };
  }, []);

  useEffect(() => {
    if (selected === null) return;
    document.body.classList.add("scroll-locked");
    return () => document.body.classList.remove("scroll-locked");
  }, [selected]);

  function updateFilter(patch: Partial<MsrcCsafFilters>): void {
    const next = { ...filters, ...patch };
    setFilters(next);
    setOffset(0);
    navigate(msrcCsafHref(next, selected, 0));
  }

  const facets = useMemo(() => buildMsrcCsafFacets(catalog.rows), [catalog.rows]);
  const filteredRows = useMemo(
    () => filterMsrcCsafRows(catalog.rows, filters),
    [catalog.rows, filters],
  );
  const safeOffset = offset < filteredRows.length ? offset : 0;
  const pagedRows = useMemo(
    () => filteredRows.slice(safeOffset, safeOffset + PAGE_SIZE),
    [filteredRows, safeOffset],
  );
  const pageStart = filteredRows.length === 0 ? 0 : safeOffset + 1;
  const pageEnd = Math.min(safeOffset + PAGE_SIZE, filteredRows.length);
  const hasPrevious = safeOffset > 0;
  const hasNext = safeOffset + PAGE_SIZE < filteredRows.length;
  const selectedRow = useMemo(
    () => (selected === null ? null : catalog.rows.find((row) => row.cve_id === selected) ?? null),
    [catalog.rows, selected],
  );

  const exploitedCount = catalog.rows.filter((r) => r.exploit_status === "exploited").length;
  const mappedCount = catalog.rows.filter((r) => r.mapping_state === "full").length;
  const blockedCount = catalog.rows.filter((r) => r.evaluation_status === "blocked").length;
  const evaluatedCount = catalog.rows.filter((r) => r.evaluation_status === "evaluated").length;
  const hasActiveFilters = Boolean(
    filters.year
    || filters.severity
    || filters.exploit_status
    || filters.disposition
    || filters.mapping_state
    || filters.resource_type
    || filters.exposure
    || filters.q,
  );
  const facet = (name: string) => facets[name] ?? {};

  usePublishViewContext(
    () => {
      const selectedGuidance = selectedRow ? buildMsrcCsafGuidance(selectedRow, catalog.source_revision) : null;
      const locale = getLocale();
      return {
        routeId: "rules",
        routeLabel: "MSRC CSAF 2.0",
        purpose: t("governance.rules.msrcCsaf.banner.body", { revision: catalog.source_revision }),
        glossary: composeGlossary([]),
        headline: selectedRow
          ? `${selectedRow.cve_id}: ${msrcCsafDisplayTitle(selectedRow, locale)} (CVSS ${selectedRow.cvss_base_score.toFixed(1)})`
          : `MSRC CSAF 2.0: ${catalog.rows.length} CVEs (${exploitedCount} exploited)`,
        capturedAt: new Date().toISOString(),
        facts: [
          { key: "total_cves", value: catalog.rows.length, group: "catalog" },
          { key: "exploited_cves", value: exploitedCount, group: "catalog" },
          { key: "mapped_cves", value: mappedCount, group: "catalog" },
          { key: "blocked_cves", value: blockedCount, group: "catalog" },
          { key: "filtered_cves", value: filteredRows.length, group: "filter" },
          // C40: Publish selected_year and selected_exposure facts to Deck context
          ...(selectedRow && selectedGuidance
            ? [
                { key: "selected_cve", value: selectedRow.cve_id, group: "selection" },
                { key: "selected_year", value: selectedRow.year, group: "selection" },
                { key: "selected_title", value: msrcCsafDisplayTitle(selectedRow, locale), group: "selection" },
                { key: "selected_cvss", value: selectedRow.cvss_base_score, group: "selection" },
                { key: "selected_exploit_status", value: selectedRow.exploit_status, group: "selection" },
                { key: "selected_exposure", value: selectedRow.exposure, group: "selection" },
                { key: "selected_resource_type", value: selectedRow.primary_resource_type, group: "selection" },
                { key: "selected_version_window", value: selectedRow.version_window, group: "selection" },
                { key: "selected_summary", value: guidanceText(selectedGuidance.summary, locale), group: "selection" },
                { key: "selected_remediation", value: guidanceText(selectedGuidance.configuration.after[0]!, locale), group: "selection" },
              ]
            : []),
        ],
        records: {
          cves: pagedRows.slice(0, 25).map((row) => ({
            cve_id: row.cve_id,
            title: msrcCsafDisplayTitle(row, locale),
            severity: row.severity,
            cvss: row.cvss_base_score,
            exploit_status: row.exploit_status,
            resource_type: row.primary_resource_type,
            version_window: row.version_window,
            disposition: row.disposition,
          })),
        },
      };
    },
    [blockedCount, catalog.rows.length, catalog.source_revision, exploitedCount, filteredRows.length, mappedCount, pagedRows, selectedRow],
  );

  const columns: readonly Column<MsrcCsafControlRow>[] = useMemo(
    () => [
      {
        key: "cve",
        header: t("governance.rules.msrcCsaf.column.cve"),
        render: (item) => {
          const displayTitle = msrcCsafDisplayTitle(item, getLocale());
          return (
            <span class="wara-recommendation-identity" data-cve-id={item.cve_id}>
              <span class="wara-recommendation-title">
                {displayTitle === item.title ? (
                  item.title
                ) : (
                  <Tooltip content={t("governance.rules.wara.detail.sourceTitle", { title: item.title })} placement="top">
                    <span>{displayTitle}</span>
                  </Tooltip>
                )}
              </span>
              <small class="muted">
                <code>{item.cve_id}</code>
                <span>{item.advisory_tracking_id}</span>
                <span>{item.primary_resource_type}</span>
              </small>
            </span>
          );
        },
      },
      {
        key: "severity",
        header: t("governance.rules.msrcCsaf.column.severity"),
        cellClass: "control-column-secondary",
        headerClass: "control-column-secondary",
        render: (item) => (
          <StatusPill
            kind={SEVERITY_PILL[item.severity] ?? "neutral"}
            label={`${displayValue("severity", item.severity)} (${item.cvss_base_score.toFixed(1)})`}
          />
        ),
      },
      {
        key: "exploit",
        header: t("governance.rules.msrcCsaf.column.exploitStatus"),
        cellClass: "control-column-secondary",
        headerClass: "control-column-secondary",
        render: (item) => (
          <StatusPill
            kind={EXPLOIT_PILL[item.exploit_status]}
            label={displayValue("msrcCsafExploit", item.exploit_status)}
          />
        ),
      },
      {
        key: "disposition",
        header: t("governance.rules.controls.column.mapping"),
        cellClass: "control-column-secondary",
        headerClass: "control-column-secondary",
        render: (item) => displayValue("waraMapping", item.disposition),
      },
      {
        key: "window",
        header: t("governance.rules.msrcCsaf.column.versionWindow"),
        cellClass: "control-column-secondary",
        headerClass: "control-column-secondary",
        render: (item) => <code>{item.version_window}</code>,
      },
      {
        key: "exposure",
        header: t("governance.rules.msrcCsaf.column.exposure"),
        render: (item) => (
          <StatusPill
            kind={EXPOSURE_PILL[item.exposure]}
            label={displayValue("msrcCsafExposure", item.exposure)}
          />
        ),
      },
    ],
    [],
  );

  return (
    <div class="stack wara-controls-view msrc-csaf-controls-view">
      <div
        class="governance-readonly-banner control-evidence-banner"
        data-evidence-state={evaluatedCount > 0 ? "connected" : "not-connected"}
      >
        <strong>{t("governance.rules.msrcCsaf.banner.title")}</strong>
        <span>{t("governance.rules.msrcCsaf.banner.body", { revision: catalog.source_revision })}</span>
      </div>
      <KpiGrid>
        <KpiCard
          href={msrcCsafHref(EMPTY_MSRC_CSAF_FILTERS, null)}
          label={t("governance.rules.msrcCsaf.kpi.total")}
          value={catalog.rows.length}
        />
        <KpiCard
          href={msrcCsafHref({ ...EMPTY_MSRC_CSAF_FILTERS, exploit_status: "exploited" }, null)}
          label={t("governance.rules.msrcCsaf.kpi.exploited")}
          value={exploitedCount}
        />
        <KpiCard
          href={msrcCsafHref({ ...EMPTY_MSRC_CSAF_FILTERS, mapping_state: "full" }, null)}
          label={t("governance.rules.msrcCsaf.kpi.mapped")}
          value={mappedCount}
        />
        <KpiCard
          evidenceState="not-connected"
          href={msrcCsafHref({ ...EMPTY_MSRC_CSAF_FILTERS, disposition: "ambiguous_or_blocked" }, null)}
          label={t("governance.rules.msrcCsaf.kpi.blocked")}
          value={blockedCount}
        />
      </KpiGrid>
      <section class="stack-section">
        <div class="rule-facet-toolbar">
          <FacetSelect
            label={t("governance.rules.msrcCsaf.filter.year")}
            value={filters.year}
            counts={facet("by_year")}
            onChange={(value) => updateFilter({ year: value })}
          />
          <FacetSelect
            label={t("governance.rules.msrcCsaf.filter.severity")}
            value={filters.severity}
            counts={facet("by_severity")}
            displayGroup="severity"
            onChange={(value) => updateFilter({ severity: value })}
          />
          <FacetSelect
            label={t("governance.rules.msrcCsaf.filter.exploitStatus")}
            value={filters.exploit_status}
            counts={facet("by_exploit_status")}
            displayGroup="msrcCsafExploit"
            onChange={(value) => updateFilter({ exploit_status: value })}
          />
          <FacetSelect
            label={t("governance.rules.msrcCsaf.filter.disposition")}
            value={filters.disposition}
            counts={facet("by_disposition")}
            displayGroup="waraMapping"
            onChange={(value) => updateFilter({ disposition: value })}
          />
          <FacetSelect
            label={t("governance.rules.msrcCsaf.filter.mappingState")}
            value={filters.mapping_state}
            counts={facet("by_mapping_state")}
            onChange={(value) => updateFilter({ mapping_state: value })}
          />
          <FacetSelect
            label={t("governance.rules.msrcCsaf.filter.resourceType")}
            value={filters.resource_type}
            counts={facet("by_resource_type")}
            onChange={(value) => updateFilter({ resource_type: value })}
          />
          <FacetSelect
            label={t("governance.rules.msrcCsaf.column.exposure")}
            value={filters.exposure}
            counts={facet("by_exposure")}
            displayGroup="msrcCsafExposure"
            onChange={(value) => updateFilter({ exposure: value })}
          />
          <label class="rule-facet-search">
            <span class="sr-only">{t("governance.rules.msrcCsaf.filter.searchAria")}</span>
            <input
              type="search"
              maxLength={256}
              value={searchInput}
              placeholder={t("governance.rules.msrcCsaf.filter.searchPlaceholder")}
              onInput={(event) => setSearchInput((event.target as HTMLInputElement).value)}
            />
          </label>
          {hasActiveFilters ? (
            <button
              type="button"
              class="btn"
              onClick={() => {
                setFilters(EMPTY_MSRC_CSAF_FILTERS);
                setSearchInput("");
                setOffset(0);
                navigate(msrcCsafHref(EMPTY_MSRC_CSAF_FILTERS, selected, 0));
              }}
            >
              {t("governance.common.clearFilter")}
            </button>
          ) : null}
        </div>
        <div class="table-toolbar">
          <p class="muted">
            {t("governance.rules.msrcCsaf.result.showing", {
              start: pageStart,
              end: pageEnd,
              filtered: filteredRows.length,
              total: catalog.rows.length,
            })}
          </p>
          <div class="pager">
            <button
              type="button"
              class="btn"
              style={{ minHeight: 44 }}
              disabled={!hasPrevious}
              onClick={() => navigate(msrcCsafHref(filters, selected, Math.max(0, safeOffset - PAGE_SIZE)))}
            >
              {t("governance.rules.result.previous")}
            </button>
            <button
              type="button"
              class="btn"
              style={{ minHeight: 44 }}
              disabled={!hasNext}
              onClick={() => navigate(msrcCsafHref(filters, selected, safeOffset + PAGE_SIZE))}
            >
              {t("governance.rules.result.next")}
            </button>
          </div>
        </div>
        <DataTable<MsrcCsafControlRow>
          columns={columns}
          rows={pagedRows}
          keyOf={(item) => item.cve_id}
          empty={t("governance.rules.msrcCsaf.result.empty")}
          onRowClick={(item) => {
            pushRouteState(msrcCsafHref(filters, item.cve_id, safeOffset));
            setSelected(item.cve_id);
          }}
          isRowActive={(item) => item.cve_id === selected}
          rowActionLabel={(item) => t("governance.rules.msrcCsaf.openRow", { cve: item.cve_id, title: msrcCsafDisplayTitle(item, getLocale()) })}
          rowActionControls="msrc-csaf-control-detail"
        />
      </section>
      {selectedRow !== null ? (
        <MsrcCsafDrawer
          row={selectedRow}
          sourceRevision={catalog.source_revision}
          crosswalkDigest={catalog.crosswalk_digest}
          onClose={() => {
            pushRouteState(msrcCsafHref(filters, null, safeOffset));
            setSelected(null);
          }}
        />
      ) : null}
    </div>
  );
}

function MsrcCsafDrawer({
  row,
  sourceRevision,
  crosswalkDigest,
  onClose,
}: {
  readonly row: MsrcCsafControlRow;
  readonly sourceRevision: string;
  readonly crosswalkDigest: string;
  readonly onClose: () => void;
}) {
  const panelRef = useRef<HTMLElement>(null);
  const [expanded, setExpanded] = useState(false);
  const locale = getLocale();
  const guidance = useMemo(() => buildMsrcCsafGuidance(row, sourceRevision), [row, sourceRevision]);
  const cvssDimensions = useMemo(() => parseCvssVector(row.cvss_vector), [row.cvss_vector]);
  useLayoutEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();
    return () => previous?.focus?.();
  }, []);

  function trapFocus(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== "Tab" || panelRef.current === null) return;
    const focusables = Array.from(
      panelRef.current.querySelectorAll<HTMLElement>(
        'summary, a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ),
    ).filter((el) => {
      const closed = el.closest("details:not([open])");
      return el.getClientRects().length > 0 && (closed === null || el === closed.querySelector(":scope > summary"));
    });
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (!first || !last) return;
    if (event.shiftKey && (document.activeElement === first || document.activeElement === panelRef.current)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div class="drawer-overlay" onClick={onClose}>
      <aside
        id="msrc-csaf-control-detail"
        ref={panelRef}
        tabIndex={-1}
        class={`rule-drawer wara-drawer${expanded ? " is-expanded" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={t("governance.rules.msrcCsaf.detail.aria")}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={trapFocus}
      >
        <header class="rule-drawer-head">
          <p class="wara-drawer-label">{t("governance.rules.msrcCsaf.detail.title")}</p>
          <button type="button" class="btn" onClick={onClose}>{t("governance.common.close")}</button>
        </header>
        <div class="rule-drawer-body">
          <div class="stack">
            <IllustratedGuidanceContent
              control={{
                id: row.cve_id,
                title: `${row.cve_id} - ${msrcCsafDisplayTitle(row, locale)}`,
                description: row.advisory_title,
                guidance,
                source_url: row.source_url,
                source_version: sourceRevision,
              }}
              expanded={expanded}
              onExpand={() => setExpanded((value) => !value)}
              prefix="framework"
            />

            <section id="framework-runtime" tabIndex={-1} class="stack-section">
              <h3>{t("governance.rules.wara.guidance.runtime")}</h3>
              <p class="muted">{row.advisory_title}</p>
              <div class="pill-row">
                <StatusPill
                  kind={SEVERITY_PILL[row.severity] ?? "neutral"}
                  label={`${displayValue("severity", row.severity)} (CVSS ${row.cvss_base_score.toFixed(1)})`}
                />
                <StatusPill
                  kind={EXPLOIT_PILL[row.exploit_status]}
                  label={displayValue("msrcCsafExploit", row.exploit_status)}
                />
                <StatusPill
                  kind="info"
                  label={displayValue("waraMapping", row.disposition)}
                />
                <StatusPill
                  kind={EXPOSURE_PILL[row.exposure]}
                  label={displayValue("msrcCsafExposure", row.exposure)}
                />
              </div>
              <p>{t("governance.rules.msrcCsaf.detail.boundary")}</p>
              {cvssDimensions.length > 0 ? (
                <div class="control-requirement-list" aria-label="CVSS v3.1 vector breakdown">
                  {cvssDimensions.map((dim) => (
                    <div key={dim.code} class="control-requirement-row">
                      <div>
                        <span class="muted small">{guidanceText(dim.label, locale)}</span>
                        <code>{dim.code}</code>
                      </div>
                      <StatusPill kind={dim.tone} label={guidanceText(dim.value, locale)} />
                    </div>
                  ))}
                </div>
              ) : null}
            </section>

            <DetailSection title={t("governance.rules.msrcCsaf.detail.advisorySection")}>
              <dl class="detail-grid">
                <DetailRow label={t("governance.rules.msrcCsaf.detail.trackingId")} value={row.advisory_tracking_id} mono />
                <DetailRow label={t("governance.rules.msrcCsaf.filter.year")} value={row.year} mono />
                <DetailRow label={t("governance.rules.msrcCsaf.detail.sourceRevision")} value={sourceRevision} mono />
                <DetailRow
                  label={t("governance.rules.msrcCsaf.detail.cvssVector")}
                  value={
                    row.cvss_temporal_score !== null
                      ? `${row.cvss_vector} (temporal ${row.cvss_temporal_score.toFixed(1)})`
                      : row.cvss_vector
                  }
                  mono
                />
                <DetailRow label={t("governance.rules.msrcCsaf.detail.initialRelease")} value={row.initial_release_date} mono />
                <DetailRow label={t("governance.rules.msrcCsaf.detail.currentRelease")} value={row.current_release_date} mono />
                <DetailRow label={t("governance.rules.msrcCsaf.detail.signatureVerified")} value={displayValue("boolean", String(row.signature_verified))} />
                <DetailRow label={t("governance.rules.msrcCsaf.detail.documentDigest")} value={row.document_digest} mono />
                <DetailRow label={t("governance.rules.msrcCsaf.detail.crosswalkDigest")} value={crosswalkDigest} mono />
                <dt>{t("governance.rules.msrcCsaf.detail.sourceUrl")}</dt>
                <dd>
                  <a href={row.source_url} target="_blank" rel="noopener noreferrer">{row.source_url}</a>
                </dd>
              </dl>
            </DetailSection>

            <DetailSection title={t("governance.rules.msrcCsaf.detail.crosswalkSection")}>
              <dl class="detail-grid">
                <DetailRow label={t("governance.rules.msrcCsaf.detail.productIds")} value={row.product_ids.join(", ")} mono />
                <DetailRow label={t("governance.rules.msrcCsaf.detail.canonicalResourceType")} value={row.primary_resource_type} mono />
                <DetailRow label={t("governance.rules.msrcCsaf.detail.versionWindow")} value={row.version_window} mono />
                <DetailRow
                  label={t("governance.rules.msrcCsaf.detail.existingRule")}
                  value={
                    row.existing_rule_id ? (
                      <a
                        href={ruleCatalogHref(EMPTY_RULE_FILTERS, 0, { id: row.existing_rule_id, origin: "active" })}
                        aria-label={t("governance.rules.controls.detail.openRule", { id: row.existing_rule_id })}
                      >
                        <code>{row.existing_rule_id}</code>
                      </a>
                    ) : (
                      "-"
                    )
                  }
                  mono
                />
                <DetailRow label={t("governance.rules.msrcCsaf.detail.candidateActionType")} value={row.candidate_action_type ?? "-"} mono />
                <DetailRow
                  label={t("governance.rules.msrcCsaf.detail.workaroundCheck")}
                  value={
                    row.workaround_property !== null
                      ? `${row.workaround_property} === ${String(row.workaround_expected_value)}`
                      : "-"
                  }
                  mono
                />
                <DetailRow label={t("governance.rules.msrcCsaf.detail.blockedReasons")} value={row.blocked_reasons.map((reason) => displayValue("msrcBlockedReason", reason)).join(", ") || "-"} />
              </dl>
            </DetailSection>

            <DetailSection title={t("governance.rules.msrcCsaf.detail.remediationSection")}>
              {row.remediations.length === 0 ? (
                <p class="muted">{t("governance.rules.msrcCsaf.detail.noRemediations")}</p>
              ) : (
                <div class="control-requirement-list">
                  {row.remediations.map((rem, idx) => (
                    <div key={`${rem.category}-${idx}`} class="control-requirement-row">
                      <div>
                        <strong>{displayValue("msrcRemediationCategory", rem.category)}</strong>
                        <span>{rem.details}</span>
                        {rem.fixed_version ? <code>fixed_version &gt;= {rem.fixed_version}</code> : null}
                        {rem.workaround_property ? (
                          <code>{rem.workaround_property} = {String(rem.workaround_expected_value)}</code>
                        ) : null}
                      </div>
                      <StatusPill kind="neutral" label={rem.recommended_action_type ?? "manual"} />
                    </div>
                  ))}
                </div>
              )}
            </DetailSection>

            <DetailSection title={t("governance.rules.msrcCsaf.detail.pantheonSection")}>
              <dl class="detail-grid">
                <DetailRow label="Heimdall" value="object.drift (msrc_csaf.vulnerability_drift) + read_drift_status" mono />
                <DetailRow label="Forseti" value="object.verdict (risk_verdict=hil, autonomy=shadow_only)" mono />
                <DetailRow label="Saga" value="object.audit-entry (append-only chain)" mono />
                <DetailRow
                  label="Norns"
                  value={
                    row.disposition === "new_rule_candidate"
                      ? `object.rule-candidate (msrc-csaf.${row.cve_id.toLowerCase()})`
                      : "inert"
                  }
                  mono
                />
              </dl>
            </DetailSection>
          </div>
        </div>
      </aside>
    </div>
  );
}
