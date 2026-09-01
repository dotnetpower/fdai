import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, type OperatorApiClient } from "../api";
import {
  DataTable,
  ErrorState,
  KpiCard,
  KpiGrid,
  LoadingState,
  StatusPill,
  UnavailableState,
  type Column,
  type PillKind,
} from "../components/ui";
import { currentRoute, navigate, replaceRouteState } from "../router";
import { displayValue, t } from "./i18n/governance";
import { DetailRow, DetailSection, FacetSelect } from "./rule-catalog-components";
import {
  decodeWaraDetail,
  decodeWaraResponse,
  waraHref,
  waraStateFromSearch,
  type WaraControl,
  type WaraFilters,
  type WaraResponse,
  type WaraSatisfaction,
} from "./wara-controls.model";

const PAGE_SIZE = 50;
const EMPTY_FILTERS: WaraFilters = {
  resource_type: "",
  recommendation_control: "",
  impact: "",
  lifecycle: "",
  product_group_verified: "",
  automation_available: "",
  mapping_disposition: "",
  applicability: "",
  evaluation_status: "",
  satisfaction: "",
  q: "",
};
const SATISFACTION_PILL: Readonly<Record<WaraSatisfaction, PillKind>> = {
  satisfied: "success",
  failed: "danger",
  not_applicable: "info",
  unknown: "neutral",
};

type DetailState =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly data: WaraControl }
  | { readonly status: "error"; readonly message: string };

export function WaraControlsRoute({ client }: { readonly client: OperatorApiClient }) {
  const initial = waraStateFromSearch(currentRoute().search);
  const [filters, setFilters] = useState(initial.filters);
  const [searchInput, setSearchInput] = useState(initial.filters.q);
  const [selected, setSelected] = useState(initial.selected);
  const [offset, setOffset] = useState(initial.offset);
  const [data, setData] = useState<WaraResponse | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error" | "unavailable">("loading");
  const [message, setMessage] = useState("");
  const [detail, setDetail] = useState<DetailState>({ status: "loading" });
  const debounceRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      if (searchInput === filters.q) return;
      const next = { ...filters, q: searchInput };
      setFilters(next);
      setOffset(0);
      replaceRouteState(waraHref(next, selected));
    }, 250);
    return () => window.clearTimeout(debounceRef.current);
  }, [filters, searchInput, selected]);

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    (async () => {
      try {
        const params = Object.fromEntries(
          Object.entries(filters).filter(([, value]) => value),
        );
        const response = decodeWaraResponse(
          await client.panel<unknown>("/wara-controls", {
            ...params,
            limit: String(PAGE_SIZE),
            offset: String(offset),
          }),
        );
        if (!cancelled) {
          setData(response);
          setStatus("ready");
        }
      } catch (error) {
        if (!cancelled) {
          setMessage(error instanceof Error ? error.message : String(error));
          setStatus(isOptionalOperatorApiUnavailable(error) ? "unavailable" : "error");
        }
      }
    })();
    return () => { cancelled = true; };
  }, [client, filters, offset]);

  useEffect(() => {
    const onRouteChange = () => {
      const next = waraStateFromSearch(currentRoute().search);
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
    let cancelled = false;
    setDetail({ status: "loading" });
    (async () => {
      try {
        const value = decodeWaraDetail(
          await client.panel<unknown>(`/wara-controls/${encodeURIComponent(selected)}`),
        );
        if (!cancelled) setDetail({ status: "ready", data: value });
      } catch (error) {
        if (!cancelled) {
          setDetail({
            status: "error",
            message: error instanceof Error ? error.message : String(error),
          });
        }
      }
    })();
    return () => { cancelled = true; };
  }, [client, selected]);

  useEffect(() => {
    if (selected === null) return;
    document.body.classList.add("scroll-locked");
    return () => document.body.classList.remove("scroll-locked");
  }, [selected]);

  function updateFilter(patch: Partial<WaraFilters>): void {
    setOffset(0);
    navigate(waraHref({ ...filters, ...patch }, selected));
  }

  if (data === null) {
    return status === "error" ? (
      <ErrorState message={t("governance.rules.wara.loadFailed", { message })} />
    ) : status === "unavailable" ? (
      <UnavailableState evidenceState="not-connected" message={t("governance.rules.wara.routeUnavailable")} />
    ) : (
      <LoadingState label={t("governance.rules.wara.loading")} />
    );
  }

  return (
    <div class="stack wara-controls-view">
      {status === "error" ? <ErrorState message={t("governance.rules.wara.loadFailed", { message })} /> : null}
      <WaraControlsBody
        data={data}
        filters={filters}
        searchInput={searchInput}
        loading={status === "loading" || searchInput !== filters.q}
        selected={selected}
        onFilter={updateFilter}
        onSearch={setSearchInput}
        onSelect={(id) => navigate(waraHref(filters, id, offset))}
        onPage={(nextOffset) => navigate(waraHref(filters, selected, nextOffset))}
      />
      {selected !== null ? (
        <WaraDrawer detail={detail} onClose={() => navigate(waraHref(filters, null, offset))} />
      ) : null}
    </div>
  );
}

function WaraControlsBody({
  data,
  filters,
  searchInput,
  loading,
  selected,
  onFilter,
  onSearch,
  onSelect,
  onPage,
}: {
  readonly data: WaraResponse;
  readonly filters: WaraFilters;
  readonly searchInput: string;
  readonly loading: boolean;
  readonly selected: string | null;
  readonly onFilter: (patch: Partial<WaraFilters>) => void;
  readonly onSearch: (value: string) => void;
  readonly onSelect: (id: string) => void;
  readonly onPage: (offset: number) => void;
}) {
  const columns: readonly Column<WaraControl>[] = useMemo(
    () => [
      {
        key: "recommendation",
        header: t("governance.rules.wara.column.recommendation"),
        render: (item) => (
          <span style={{ display: "grid", gridTemplateColumns: "74px minmax(0, 1fr)", alignItems: "baseline", gap: 8, minWidth: 0 }}>
            <code title={item.id}>{item.id.slice(0, 8)}...</code>
            <span class="muted" style={{ minWidth: 0, overflowWrap: "anywhere" }}>
              {item.title}
              <small class="muted" style={{ display: "block", overflowWrap: "anywhere" }}>{item.resource_type}</small>
            </span>
          </span>
        ),
      },
      {
        key: "assessment",
        header: t("governance.rules.wara.column.state"),
        render: (item) => (
          <span style={{ display: "grid", gap: 2, minWidth: 0 }}>
            <span>{displayValue("waraMapping", item.mapping_disposition)}</span>
            <small class="muted">{displayValue("controlEvaluation", item.evaluation_status)}</small>
            <StatusPill kind={SATISFACTION_PILL[item.satisfaction]} label={displayValue("controlStatus", item.satisfaction)} />
          </span>
        ),
      },
    ],
    [],
  );
  const facets = data.facets;
  const active = data.inventory.active_recommendations;
  const automated = data.inventory.automated_recommendations;
  const unknown = facets["by_satisfaction"]?.["unknown"] ?? 0;
  const facet = (name: string) => facets[name] ?? {};
  const pageStart = data.filtered_total === 0 ? 0 : data.offset + 1;
  const pageEnd = Math.min(data.offset + data.limit, data.filtered_total);
  const hasPrevious = data.offset > 0;
  const hasNext = data.offset + data.limit < data.filtered_total;
  return (
    <div class="stack">
      <div class="governance-readonly-banner control-evidence-banner" data-evidence-state="not-connected">
        <strong>{t("governance.rules.wara.banner.title")}</strong>
        <span>{t("governance.rules.wara.banner.body")}</span>
      </div>
      <KpiGrid>
        <KpiCard href={waraHref(EMPTY_FILTERS, null)} label={t("governance.rules.wara.kpi.total")} value={data.inventory.active_recommendations + data.inventory.disabled_recommendations} />
        <KpiCard href={waraHref({ ...EMPTY_FILTERS, lifecycle: "active" }, null)} label={t("governance.rules.wara.kpi.active")} value={active} />
        <KpiCard href={waraHref({ ...EMPTY_FILTERS, lifecycle: "active", automation_available: "true" }, null)} label={t("governance.rules.wara.kpi.automated")} value={automated} />
        <KpiCard evidenceState="not-connected" href={waraHref({ ...EMPTY_FILTERS, satisfaction: "unknown" }, null)} label={t("governance.rules.wara.kpi.unknown")} value={unknown} />
      </KpiGrid>
      <section class="stack-section">
        <div class="rule-facet-toolbar">
          <FacetSelect label={t("governance.rules.wara.filter.resourceType")} value={filters.resource_type} counts={facet("by_resource_type")} onChange={(value) => onFilter({ resource_type: value })} />
          <FacetSelect label={t("governance.rules.wara.filter.control")} value={filters.recommendation_control} counts={facet("by_recommendation_control")} onChange={(value) => onFilter({ recommendation_control: value })} />
          <FacetSelect label={t("governance.rules.wara.filter.impact")} value={filters.impact} counts={facet("by_impact")} onChange={(value) => onFilter({ impact: value })} />
          <FacetSelect label={t("governance.rules.wara.filter.lifecycle")} value={filters.lifecycle} counts={facet("by_lifecycle")} displayGroup="waraLifecycle" onChange={(value) => onFilter({ lifecycle: value })} />
          <FacetSelect label={t("governance.rules.wara.filter.productVerified")} value={filters.product_group_verified} counts={facet("by_product_group_verified")} displayGroup="boolean" onChange={(value) => onFilter({ product_group_verified: value })} />
          <FacetSelect label={t("governance.rules.wara.filter.automation")} value={filters.automation_available} counts={facet("by_automation_available")} displayGroup="boolean" onChange={(value) => onFilter({ automation_available: value })} />
          <FacetSelect label={t("governance.rules.wara.filter.mapping")} value={filters.mapping_disposition} counts={facet("by_mapping_disposition")} displayGroup="waraMapping" onChange={(value) => onFilter({ mapping_disposition: value })} />
          <FacetSelect label={t("governance.rules.wara.filter.applicability")} value={filters.applicability} counts={facet("by_applicability")} displayGroup="controlStatus" onChange={(value) => onFilter({ applicability: value })} />
          <FacetSelect label={t("governance.rules.wara.filter.evaluation")} value={filters.evaluation_status} counts={facet("by_evaluation")} displayGroup="controlEvaluation" onChange={(value) => onFilter({ evaluation_status: value })} />
          <FacetSelect label={t("governance.rules.wara.filter.satisfaction")} value={filters.satisfaction} counts={facet("by_satisfaction")} displayGroup="controlStatus" onChange={(value) => onFilter({ satisfaction: value })} />
          <label class="rule-facet-search">
            <span class="sr-only">{t("governance.rules.wara.filter.searchAria")}</span>
            <input type="search" value={searchInput} placeholder={t("governance.rules.wara.filter.searchPlaceholder")} onInput={(event) => onSearch((event.target as HTMLInputElement).value)} />
          </label>
        </div>
        <div class="table-toolbar">
          <p class="muted">{t("governance.rules.wara.result.showing", { start: pageStart, end: pageEnd, filtered: data.filtered_total, total: data.total })}{loading ? t("governance.rules.result.updating") : ""}</p>
          <div class="pager">
            <button type="button" class="btn" style={{ minHeight: 44 }} disabled={loading || !hasPrevious} onClick={() => onPage(Math.max(0, data.offset - data.limit))}>{t("governance.rules.result.previous")}</button>
            <button type="button" class="btn" style={{ minHeight: 44 }} disabled={loading || !hasNext} onClick={() => onPage(data.offset + data.limit)}>{t("governance.rules.result.next")}</button>
          </div>
        </div>
        <div class={loading ? "is-refreshing" : undefined} aria-busy={loading}>
          <DataTable<WaraControl>
            columns={columns}
            rows={data.controls}
            keyOf={(item) => item.id}
            empty={t("governance.rules.wara.result.empty")}
            onRowClick={(item) => onSelect(item.id)}
            isRowActive={(item) => item.id === selected}
            rowActionLabel={(item) => t("governance.rules.wara.openRow", { title: item.title })}
            rowActionControls="wara-control-detail"
          />
        </div>
      </section>
    </div>
  );
}

function WaraDrawer({ detail, onClose }: { readonly detail: DetailState; readonly onClose: () => void }) {
  const panelRef = useRef<HTMLElement>(null);
  useEffect(() => {
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
    const focusables = panelRef.current.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
    );
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (!first || !last) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div class="drawer-overlay" onClick={onClose}>
      <aside id="wara-control-detail" ref={panelRef} tabIndex={-1} class="rule-drawer" role="dialog" aria-modal="true" aria-label={t("governance.rules.wara.detail.aria")} onClick={(event) => event.stopPropagation()} onKeyDown={trapFocus}>
        <header class="rule-drawer-head">
          <h3 class="mono">{detail.status === "ready" ? detail.data.id : t("governance.rules.wara.detail.title")}</h3>
          <button type="button" class="btn" onClick={onClose}>{t("governance.common.close")}</button>
        </header>
        <div class="rule-drawer-body">
          {detail.status === "loading" ? (
            <LoadingState label={t("governance.rules.wara.detail.loading")} />
          ) : detail.status === "error" ? (
            <ErrorState message={t("governance.rules.wara.detail.loadFailed", { message: detail.message })} />
          ) : (
            <div class="stack">
              <div class="pill-row">
                <StatusPill kind={SATISFACTION_PILL[detail.data.satisfaction]} label={displayValue("controlStatus", detail.data.satisfaction)} />
                <StatusPill kind="info" label={displayValue("waraMapping", detail.data.mapping_disposition)} />
                <StatusPill kind="neutral" label={displayValue("controlEvaluation", detail.data.evaluation_status)} />
              </div>
              <section class="rule-overview">
                <h4 class="rule-overview-title">{detail.data.title}</h4>
                <p class="rule-overview-desc">{t("governance.rules.wara.detail.boundary")}</p>
              </section>
              <dl class="detail-grid">
                <dt>{t("governance.rules.wara.column.resourceType")}</dt><dd><code>{detail.data.resource_type}</code></dd>
                <dt>{t("governance.rules.wara.column.control")}</dt><dd>{detail.data.recommendation_control}</dd>
                <dt>{t("governance.rules.wara.column.impact")}</dt><dd>{detail.data.impact}</dd>
                <dt>{t("governance.rules.wara.detail.evaluationScope")}</dt><dd><code>{detail.data.evaluation_scope ?? "-"}</code></dd>
                <dt>{t("governance.rules.wara.detail.evaluatedAt")}</dt><dd><code>{detail.data.evaluated_at ?? "-"}</code></dd>
                <dt>{t("governance.rules.wara.detail.evidenceComplete")}</dt><dd>{displayValue("boolean", String(detail.data.evidence_complete))}</dd>
                <dt>{t("governance.rules.wara.detail.evidenceRefs")}</dt><dd>{detail.data.evidence_refs.join(", ") || "-"}</dd>
                <dt>{t("governance.rules.wara.detail.limitations")}</dt><dd>{detail.data.limitations.join(", ") || "-"}</dd>
              </dl>
              <DetailSection title={t("governance.rules.wara.detail.source")}>
                <dl class="detail-grid">
                  <DetailRow
                    label={t("governance.rules.wara.detail.aprlSource")}
                    value={<a href={detail.data.source_url} target="_blank" rel="noreferrer">{detail.data.source_path}</a>}
                  />
                  <DetailRow label={t("governance.rules.wara.detail.sourceVersion")} value={detail.data.source_version} mono />
                  <DetailRow label={t("governance.rules.wara.detail.sourceRevision")} value={detail.data.source_revision} mono />
                  <DetailRow label={t("governance.rules.wara.detail.sourceDigest")} value={detail.data.source_digest} mono />
                  <DetailRow label={t("governance.rules.wara.detail.retrievedAt")} value={detail.data.retrieved_at} mono />
                  <DetailRow label={t("governance.rules.wara.detail.license")} value={detail.data.source_license} />
                  <DetailRow
                    label={t("governance.rules.wara.detail.learnMore")}
                    value={detail.data.learn_more_url === null ? "-" : <a href={detail.data.learn_more_url} target="_blank" rel="noreferrer">{detail.data.learn_more_name}</a>}
                  />
                  <DetailRow label={t("governance.rules.wara.detail.queryDigest")} value={detail.data.query_digest ?? "-"} mono />
                </dl>
              </DetailSection>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
