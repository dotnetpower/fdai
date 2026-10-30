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
import {
  cafHref,
  cafStateFromSearch,
  decodeCafDetail,
  decodeCafResponse,
  type CafControl,
  type CafControlDetail,
  type CafFilters,
  type CafResponse,
  type CafSatisfaction,
} from "./caf-controls.model";
import { displayValue, t } from "./i18n/governance";
import { DetailRow, DetailSection, FacetSelect } from "./rule-catalog-components";
import { verifyFrameworkGuidanceDigest } from "./framework-guidance.model";
import { FrameworkGuidanceContent } from "./framework-guidance";
import { ControlEnablementBadge, ControlEnablementSection } from "./control-enablement";
import { ControlRemediationSection } from "./control-remediation";

const PAGE_SIZE = 100;
const EMPTY_FILTERS: CafFilters = {
  area: "",
  mapping_state: "",
  applicability: "",
  evaluation_status: "",
  satisfaction: "",
  owner_slot: "",
  q: "",
};
const SATISFACTION_PILL: Readonly<Record<CafSatisfaction, PillKind>> = {
  satisfied: "success",
  failed: "danger",
  not_applicable: "info",
  unknown: "neutral",
};

type DetailState =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly data: CafControlDetail }
  | { readonly status: "error"; readonly message: string };

export function CafControlsRoute({ client }: { readonly client: OperatorApiClient }) {
  const initial = cafStateFromSearch(currentRoute().search);
  const [filters, setFilters] = useState(initial.filters);
  const [searchInput, setSearchInput] = useState(initial.filters.q);
  const [selected, setSelected] = useState(initial.selected);
  const [data, setData] = useState<CafResponse | null>(null);
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
      replaceRouteState(cafHref(next, selected));
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
        const response = decodeCafResponse(
          await client.panel<unknown>("/caf-controls", {
            ...params,
            limit: String(PAGE_SIZE),
            offset: "0",
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
  }, [client, filters]);

  useEffect(() => {
    const onRouteChange = () => {
      const next = cafStateFromSearch(currentRoute().search);
      setFilters(next.filters);
      setSearchInput(next.filters.q);
      setSelected(next.selected);
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
        const value = decodeCafDetail(
          await client.panel<unknown>(`/caf-controls/${encodeURIComponent(selected)}`),
          selected,
        );
        await verifyFrameworkGuidanceDigest(value.guidance);
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

  function updateFilter(patch: Partial<CafFilters>): void {
    navigate(cafHref({ ...filters, ...patch }, selected));
  }

  if (data === null) {
    return status === "error" ? (
      <ErrorState message={t("governance.rules.caf.loadFailed", { message })} />
    ) : status === "unavailable" ? (
      <UnavailableState evidenceState="not-connected" message={t("governance.rules.caf.routeUnavailable")} />
    ) : (
      <LoadingState label={t("governance.rules.caf.loading")} />
    );
  }

  return (
    <div class="stack caf-controls-view">
      {status === "error" ? <ErrorState message={t("governance.rules.caf.loadFailed", { message })} /> : null}
      <CafControlsBody
        data={data}
        filters={filters}
        searchInput={searchInput}
        loading={status === "loading" || searchInput !== filters.q}
        onFilter={updateFilter}
        onSearch={setSearchInput}
        onSelect={(controlId) => navigate(cafHref(filters, controlId))}
      />
      {selected !== null ? (
        <CafDrawer detail={detail} onClose={() => navigate(cafHref(filters, null))} />
      ) : null}
    </div>
  );
}

function CafControlsBody({
  data,
  filters,
  searchInput,
  loading,
  onFilter,
  onSearch,
  onSelect,
}: {
  readonly data: CafResponse;
  readonly filters: CafFilters;
  readonly searchInput: string;
  readonly loading: boolean;
  readonly onFilter: (patch: Partial<CafFilters>) => void;
  readonly onSearch: (value: string) => void;
  readonly onSelect: (controlId: string) => void;
}) {
  const columns: readonly Column<CafControl>[] = useMemo(
    () => [
      {
        key: "control",
        header: t("governance.rules.caf.column.control"),
        render: (item) => (
          <span class="control-table-identity">
            <code>{item.control_id}</code>
            <span>{item.title}</span>
          </span>
        ),
      },
      {
        key: "area",
        header: t("governance.rules.caf.column.area"),
        render: (item) => item.area,
      },
      {
        key: "enablement",
        header: t("governance.rules.enablement.column"),
        render: (control) => <ControlEnablementBadge value={control.enablement} />,
      },
      {
        key: "owner",
        header: t("governance.rules.caf.column.owner"),
        render: (item) => <code>{item.owner_slot}</code>,
      },
      {
        key: "state",
        header: t("governance.rules.caf.column.state"),
        render: (item) => (
          <span style={{ display: "grid", gap: 2 }}>
            <span>{displayValue("controlEvaluation", item.evaluation_status)}</span>
            <StatusPill kind={SATISFACTION_PILL[item.satisfaction]} label={displayValue("controlStatus", item.satisfaction)} />
          </span>
        ),
      },
    ],
    [],
  );
  const facet = (name: string) => data.facets[name] ?? {};
  const applicable = facet("by_applicability")["applicable"] ?? 0;
  const unknown = facet("by_satisfaction")["unknown"] ?? 0;
  const evidenceReady = data.controls.filter((item) => item.evidence_complete).length;

  return (
    <div class="stack">
      <div class="governance-readonly-banner control-evidence-banner" data-evidence-state="not-connected">
        <strong>{t("governance.rules.caf.banner.title")}</strong>
        <span>{t("governance.rules.caf.banner.body")}</span>
      </div>
      <KpiGrid>
        <KpiCard href="#caf-control-table" label={t("governance.rules.caf.kpi.total")} value={data.total} />
        <KpiCard href={cafHref({ ...EMPTY_FILTERS, applicability: "applicable" }, null)} label={t("governance.rules.caf.kpi.applicable")} value={applicable} />
        <KpiCard href={cafHref({ ...EMPTY_FILTERS, satisfaction: "unknown" }, null)} label={t("governance.rules.caf.kpi.unknown")} value={unknown} evidenceState={unknown > 0 ? "not-measured" : "measured"} />
        <KpiCard href="#caf-control-table" label={t("governance.rules.caf.kpi.evidenceReady")} value={evidenceReady} />
      </KpiGrid>
      <section class="stack-section">
        <div class="rule-facet-toolbar">
          <FacetSelect label={t("governance.rules.caf.filter.area")} value={filters.area} counts={facet("by_area")} onChange={(area) => onFilter({ area })} />
          <FacetSelect label={t("governance.rules.caf.filter.applicability")} value={filters.applicability} counts={facet("by_applicability")} displayGroup="controlStatus" onChange={(applicability) => onFilter({ applicability })} />
          <FacetSelect label={t("governance.rules.caf.filter.satisfaction")} value={filters.satisfaction} counts={facet("by_satisfaction")} displayGroup="controlStatus" onChange={(satisfaction) => onFilter({ satisfaction })} />
          <label class="rule-facet-search">
            <span class="sr-only">{t("governance.rules.caf.filter.searchAria")}</span>
            <input type="search" value={searchInput} placeholder={t("governance.rules.caf.filter.searchPlaceholder")} onInput={(event) => onSearch((event.target as HTMLInputElement).value)} />
          </label>
        </div>
        <div class="table-toolbar">
          <p class="muted">{t("governance.rules.caf.result.showing", { filtered: data.filtered_total, total: data.total })}{loading ? t("governance.rules.result.updating") : ""}</p>
        </div>
        <div id="caf-control-table">
        <DataTable<CafControl>
          columns={columns}
          rows={data.controls}
          keyOf={(item) => item.control_id}
          onRowClick={(item) => onSelect(item.control_id)}
          rowActionLabel={(item) => t("governance.rules.caf.openRow", { title: item.title })}
          rowActionControls="caf-control-detail"
          empty={t("governance.rules.caf.result.empty")}
        />
        </div>
      </section>
    </div>
  );
}

function CafDrawer({
  detail,
  onClose,
}: {
  readonly detail: DetailState;
  readonly onClose: () => void;
}) {
  const panelRef = useRef<HTMLElement>(null);
  const [expanded, setExpanded] = useState(false);
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
      <aside id="caf-control-detail" ref={panelRef} tabIndex={-1} class={`rule-drawer wara-drawer${expanded ? " is-expanded" : ""}`} role="dialog" aria-modal="true" aria-label={t("governance.rules.caf.detail.aria")} onClick={(event) => event.stopPropagation()} onKeyDown={trapFocus}>
        <header class="rule-drawer-head">
          <h3 class="mono">{detail.status === "ready" ? detail.data.control_id : t("governance.rules.caf.detail.title")}</h3>
          <button type="button" class="btn" onClick={onClose} aria-label={t("governance.common.close")}>{t("governance.common.close")}</button>
        </header>
        <div class="rule-drawer-body">
          {detail.status === "loading" ? (
            <LoadingState label={t("governance.rules.caf.detail.loading")} />
          ) : detail.status === "error" ? (
            <ErrorState message={t("governance.rules.caf.detail.loadFailed", { message: detail.message })} />
          ) : (
            <CafDetailContent data={detail.data} expanded={expanded} onExpand={() => setExpanded((value) => !value)} />
          )}
        </div>
      </aside>
    </div>
  );
}

function CafDetailContent({ data, expanded, onExpand }: { readonly data: CafControlDetail; readonly expanded: boolean; readonly onExpand: () => void }) {
  return (
    <div class="stack">
      <FrameworkGuidanceContent guidance={data.guidance} controlId={data.control_id} title={data.title} description={data.description} expanded={expanded} onExpand={onExpand} unavailableReason={data.guidance_unavailable_reason} />
      <h3 id="framework-runtime" tabIndex={-1}>{t("governance.rules.wara.guidance.runtime")}</h3>
      <ControlEnablementSection value={data.enablement} severitySource={data.severity_source} />
      <ControlRemediationSection value={data.remediation} />
      <div class="pill-row">
        <StatusPill kind={SATISFACTION_PILL[data.satisfaction]} label={displayValue("controlStatus", data.satisfaction)} />
        <StatusPill kind="info" label={data.area} />
      </div>
      <dl class="detail-grid">
        <DetailRow label={t("governance.rules.caf.detail.reference")} value={data.reference_state} />
        <DetailRow label={t("governance.rules.controls.column.mapping")} value={data.mapping_state} />
        <DetailRow label={t("governance.rules.controls.column.applicability")} value={displayValue("controlStatus", data.applicability)} />
        <DetailRow label={t("governance.rules.controls.column.evaluation")} value={displayValue("controlEvaluation", data.evaluation_status)} />
        <DetailRow label={t("governance.rules.controls.column.satisfaction")} value={displayValue("controlStatus", data.satisfaction)} />
        <DetailRow label={t("governance.rules.caf.detail.owner")} value={data.owner_slot} mono />
        <DetailRow label={t("governance.rules.caf.detail.cadence")} value={`${data.cadence_days} days`} />
        <DetailRow label={t("governance.rules.caf.detail.scope")} value={data.evaluation_scope ?? "-"} mono />
        <DetailRow label={t("governance.rules.caf.detail.evaluatedAt")} value={data.evaluated_at ?? "-"} mono />
        <DetailRow label={t("governance.rules.caf.detail.profile")} value={data.profile_id ?? "-"} mono />
      </dl>
      {data.approved_exception ? (
        <DetailSection title={t("governance.rules.caf.detail.exception")}>
          <DetailRow label={t("governance.rules.caf.detail.justification")} value={data.approved_exception.justification} />
          <DetailRow label={t("governance.rules.caf.detail.expiresAt")} value={data.approved_exception.expires_at} mono />
        </DetailSection>
      ) : null}
      <DetailSection title={t("governance.rules.caf.detail.evidence")}>
        <dl class="detail-grid">
          <DetailRow label={t("governance.rules.caf.detail.evidenceRefs")} value={data.evidence_refs.join(", ") || "-"} mono />
          <DetailRow label={t("governance.rules.caf.detail.evidenceDigests")} value={data.evidence_digests.join(", ") || "-"} mono />
          <DetailRow label={t("governance.rules.caf.detail.limitations")} value={data.limitations.join(", ") || "-"} />
        </dl>
      </DetailSection>
      <DetailSection title={t("governance.rules.caf.detail.specifications")}>
        <div class="control-requirement-list">
          {data.evidence_specifications.map((item) => (
            <article key={item.requirement_id} class="control-requirement-row">
              <div><span class="muted small">{item.kind} - {item.process_phase}</span><code>{item.source_ref}</code></div>
              <span>{item.authoritative_producer ?? item.blocked_dependency}</span>
            </article>
          ))}
        </div>
      </DetailSection>
      <DetailSection title={t("governance.rules.caf.detail.crosswalk")}>
        <div class="control-requirement-list">
          {data.crosswalk.map((item) => (
            <article key={`${item.target_kind}:${item.target_ref}`} class="control-requirement-row">
              <div><span class="muted small">{item.target_kind}</span><code>{item.target_ref ?? "unmapped"}</code></div>
              <span>{item.relationship}</span>
            </article>
          ))}
        </div>
      </DetailSection>
    </div>
  );
}
