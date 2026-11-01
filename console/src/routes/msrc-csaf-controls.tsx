import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "preact/hooks";
import {
  DataTable,
  KpiCard,
  KpiGrid,
  StatusPill,
  type Column,
  type PillKind,
} from "../components/ui";
import { currentRoute, navigate, pushRouteState, replaceRouteState } from "../router";
import { displayValue, t } from "./i18n/governance";
import {
  EMPTY_MSRC_CSAF_FILTERS,
  PINNED_MSRC_CSAF_CATALOG,
  buildMsrcCsafFacets,
  filterMsrcCsafRows,
  msrcCsafHref,
  msrcCsafStateFromSearch,
  type MsrcCsafControlRow,
  type MsrcCsafExploitStatus,
  type MsrcCsafExposure,
  type MsrcCsafFilters,
} from "./msrc-csaf-controls.model";
import { DetailRow, DetailSection, FacetSelect } from "./rule-catalog-components";
import { SEVERITY_PILL } from "./rule-catalog-types";

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

export function MsrcCsafControlsRoute() {
  const initial = msrcCsafStateFromSearch(currentRoute().search);
  const [filters, setFilters] = useState<MsrcCsafFilters>(initial.filters);
  const [searchInput, setSearchInput] = useState(initial.filters.q);
  const [selected, setSelected] = useState<string | null>(initial.selected);
  const [offset, setOffset] = useState<number>(initial.offset);
  const debounceRef = useRef<number | undefined>(undefined);

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

  const catalog = PINNED_MSRC_CSAF_CATALOG;
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
  const facet = (name: string) => facets[name] ?? {};

  const columns: readonly Column<MsrcCsafControlRow>[] = useMemo(
    () => [
      {
        key: "cve",
        header: t("governance.rules.msrcCsaf.column.cve"),
        render: (item) => (
          <span class="wara-recommendation-identity" data-cve-id={item.cve_id}>
            <span class="wara-recommendation-title">{item.title}</span>
            <small class="muted">
              <code>{item.cve_id}</code>
              <span>{item.advisory_tracking_id}</span>
              <span>{item.primary_resource_type}</span>
            </small>
          </span>
        ),
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
      <div class="governance-readonly-banner control-evidence-banner" data-evidence-state="not-connected">
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
          <label class="rule-facet-search">
            <span class="sr-only">{t("governance.rules.msrcCsaf.filter.searchAria")}</span>
            <input
              type="search"
              value={searchInput}
              placeholder={t("governance.rules.msrcCsaf.filter.searchPlaceholder")}
              onInput={(event) => setSearchInput((event.target as HTMLInputElement).value)}
            />
          </label>
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
          rowActionLabel={(item) => t("governance.rules.msrcCsaf.openRow", { cve: item.cve_id, title: item.title })}
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
    ).filter((el) => el.getClientRects().length > 0);
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
        class="rule-drawer wara-drawer"
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
            <section class="stack-section">
              <h3>{row.cve_id} - {row.title}</h3>
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
            </section>

            <DetailSection title={t("governance.rules.msrcCsaf.detail.advisorySection")}>
              <dl class="detail-grid">
                <DetailRow label={t("governance.rules.msrcCsaf.detail.trackingId")} value={row.advisory_tracking_id} mono />
                <DetailRow label={t("governance.rules.msrcCsaf.detail.sourceRevision")} value={sourceRevision} mono />
                <DetailRow label={t("governance.rules.msrcCsaf.detail.cvssVector")} value={row.cvss_vector} mono />
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
                <DetailRow label={t("governance.rules.msrcCsaf.detail.existingRule")} value={row.existing_rule_id ?? "-"} mono />
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
                <DetailRow label={t("governance.rules.msrcCsaf.detail.blockedReasons")} value={row.blocked_reasons.join(", ") || "-"} mono />
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
                        <strong>{rem.category}</strong>
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
