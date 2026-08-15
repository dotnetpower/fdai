import { useEffect, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import type {
  AuditItem,
  IncidentPage,
  IncidentOutcomeMetrics,
  IncidentStatusFilter,
  IncidentSummary,
} from "../types";
import {
  AsyncBoundary,
  PageHeader,
  StatusPill,
  type AsyncState,
  type PillKind,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { currentRoute, navigate, routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import { t } from "./i18n/evidence";
import "./incident-clarity.css";
import {
  IncidentMilestones,
  IncidentOutcomeAnalytics,
  IncidentSourceContext,
} from "./incidents.detail-sections";
import {
  incidentAgentStatus,
  incidentOperationalOverview,
  type IncidentOperationalOverview,
} from "./incidents.overview";
import { incidentTimelinePresentation } from "./incidents.timeline";

const INCIDENT_DETAIL_ID = "incident-detail";

interface Props {
  readonly client: OperatorApiClient;
}

interface IncidentData {
  readonly items: readonly IncidentSummary[];
  readonly nextCursor: string | null;
  readonly metrics: IncidentOutcomeMetrics;
}

const PAGE_SIZE = 25;
const FILTERS: readonly IncidentStatusFilter[] = ["active", "resolved", "all"];
const INCIDENT_VERTICALS = ["resilience", "change_safety", "cost_governance", "unknown"] as const;
type IncidentVertical = typeof INCIDENT_VERTICALS[number];
const INCIDENT_SEVERITIES = ["critical", "high", "medium", "low", "unknown"] as const;
type IncidentSeverity = typeof INCIDENT_SEVERITIES[number];

export function parseIncidentVertical(value: string | null): IncidentVertical | null {
  if (value === null) return null;
  const normalized = value.trim().toLowerCase().replaceAll("-", "_");
  return INCIDENT_VERTICALS.includes(normalized as IncidentVertical)
    ? normalized as IncidentVertical
    : null;
}

export function parseIncidentSeverity(value: string | null): IncidentSeverity | null {
  if (value === null) return null;
  const normalized = value.trim().toLowerCase();
  return INCIDENT_SEVERITIES.includes(normalized as IncidentSeverity)
    ? normalized as IncidentSeverity
    : null;
}

export function mergeIncidentItems(
  current: readonly IncidentSummary[],
  incoming: readonly IncidentSummary[],
): readonly IncidentSummary[] {
  const seen = new Set(current.map((item) => item.correlation_id));
  return [...current, ...incoming.filter((item) => !seen.has(item.correlation_id))];
}

export function resolveIncidentSelection(
  items: readonly Pick<IncidentSummary, "correlation_id">[],
  requested: string | null,
): string | null {
  return requested ?? items[0]?.correlation_id ?? null;
}

export function incidentDisplayTitle(
  incident: Pick<IncidentSummary, "title" | "title_source">,
  unavailable: string,
): string {
  return incident.title_source === "identifier_fallback" ? unavailable : incident.title;
}

/** The identifier an operator can carry into Audit, Trace, RCA, and the dossier. */
export function incidentRosterIdentifier(
  incident: Pick<IncidentSummary, "correlation_id">,
): string {
  return incident.correlation_id;
}

export function incidentVerticalDisplayLabel(vertical: IncidentVertical): string {
  return localized("vertical", vertical);
}

export function incidentPageMatchesSnapshot(
  current: Pick<IncidentOutcomeMetrics, "snapshot_seq">,
  incoming: Pick<IncidentOutcomeMetrics, "snapshot_seq">,
): boolean {
  return current.snapshot_seq === incoming.snapshot_seq;
}

export function IncidentsRoute({ client }: Props) {
  const initialRoute = currentRoute();
  const initialStatus = initialRoute.search.get("status");
  const [verticalFilter, setVerticalFilter] = useState<IncidentVertical | null>(
    parseIncidentVertical(initialRoute.search.get("vertical")),
  );
  const [severityFilter, setSeverityFilter] = useState<IncidentSeverity | null>(
    parseIncidentSeverity(initialRoute.search.get("severity")),
  );
  const [filter, setFilter] = useState<IncidentStatusFilter>(
    initialStatus === "resolved" || initialStatus === "all" ? initialStatus : "active",
  );
  const [state, setState] = useState<AsyncState<IncidentData>>({ status: "loading" });
  const [selectedId, setSelectedId] = useState<string | null>(
    initialRoute.search.get("correlation"),
  );
  const [history, setHistory] = useState<AsyncState<readonly AuditItem[]>>({ status: "idle" });
  const [loadingMore, setLoadingMore] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const rosterGeneration = useRef(0);
  const historyGeneration = useRef(0);
  const exactLookup = useRef<string | null>(null);

  useEffect(() => {
    const sync = () => {
      const route = currentRoute();
      const status = route.search.get("status");
      setFilter(status === "resolved" || status === "all" ? status : "active");
      setVerticalFilter(parseIncidentVertical(route.search.get("vertical")));
      setSeverityFilter(parseIncidentSeverity(route.search.get("severity")));
      setSelectedId(route.search.get("correlation"));
    };
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
    };
  }, []);

  const openRoute = (status: IncidentStatusFilter, correlation: string | null): void => {
    navigate(routeHref("incidents", {
      params: {
        status: status === "active" ? null : status,
        vertical: verticalFilter,
        severity: severityFilter,
        correlation,
      },
    }));
  };

  const openFilters = (
    vertical: IncidentVertical | null,
    severity: IncidentSeverity | null,
  ): void => {
    navigate(routeHref("incidents", {
      params: {
        status: filter === "active" ? null : filter,
        vertical,
        severity,
        correlation: null,
      },
    }));
  };

  useEffect(() => {
    const generation = rosterGeneration.current + 1;
    rosterGeneration.current = generation;
    setState({ status: "loading" });
    setPageError(null);
    setLoadingMore(false);
    const filters = {
      status: filter,
      limit: PAGE_SIZE,
      ...(verticalFilter ? { vertical: verticalFilter } : {}),
      ...(severityFilter ? { severity: severityFilter } : {}),
    } as const;
    exactLookup.current = null;
    void client.listIncidents(filters).then(
      (page) => {
        if (rosterGeneration.current !== generation) return;
        setState({
          status: "ready",
          data: { items: page.items, nextCursor: page.next_cursor, metrics: page.metrics },
        });
        setSelectedId((current) => resolveIncidentSelection(page.items, current));
      },
      (error: unknown) => {
        if (rosterGeneration.current === generation) {
          setState({
            status: "error",
            message: error instanceof Error ? error.message : String(error),
          });
        }
      },
    );
    return () => {
      if (rosterGeneration.current === generation) rosterGeneration.current += 1;
    };
  }, [client, filter, verticalFilter, severityFilter]);

  useEffect(() => {
    if (selectedId === null || state.status !== "ready") return;
    if (state.data.items.some((item) => item.correlation_id === selectedId)) return;
    const lookupKey = `${filter}:${verticalFilter ?? "all"}:${severityFilter ?? "all"}:${selectedId}`;
    if (exactLookup.current === lookupKey) return;
    exactLookup.current = lookupKey;
    const generation = rosterGeneration.current;
    void client.listIncidents({
      status: filter,
      limit: 1,
      correlationId: selectedId,
      ...(verticalFilter ? { vertical: verticalFilter } : {}),
      ...(severityFilter ? { severity: severityFilter } : {}),
    }).then(
      (page) => {
        if (
          rosterGeneration.current !== generation
          || exactLookup.current !== lookupKey
        ) return;
        if (!incidentPageMatchesSnapshot(state.data.metrics, page.metrics)) {
          exactLookup.current = null;
          setPageError("Incident exact lookup snapshot changed");
          return;
        }
        setState((current) => current.status === "ready"
          ? {
              status: "ready",
              data: {
                ...current.data,
                items: mergeIncidentItems(page.items, current.data.items),
                metrics: page.metrics,
              },
            }
          : current);
      },
      (error: unknown) => {
        if (
          rosterGeneration.current !== generation
          || exactLookup.current !== lookupKey
        ) return;
        exactLookup.current = null;
        setPageError(error instanceof Error ? error.message : String(error));
      },
    );
  }, [client, filter, selectedId, state, verticalFilter]);

  useEffect(() => {
    const generation = historyGeneration.current + 1;
    historyGeneration.current = generation;
    if (selectedId === null) {
      setHistory({ status: "idle" });
      return;
    }
    setHistory({ status: "loading" });
    void client.listAudit({ limit: 100, correlationId: selectedId }).then(
      (page) => {
        if (historyGeneration.current === generation) {
          setHistory({ status: "ready", data: [...page.items].reverse() });
        }
      },
      (error: unknown) => {
        if (historyGeneration.current === generation) {
          setHistory({
            status: "error",
            message: error instanceof Error ? error.message : String(error),
          });
        }
      },
    );
    return () => {
      if (historyGeneration.current === generation) historyGeneration.current += 1;
    };
  }, [client, selectedId]);

  async function loadMore(cursor: string): Promise<void> {
    if (state.status !== "ready" || loadingMore || state.data.nextCursor !== cursor) return;
    const generation = rosterGeneration.current;
    const requestedFilter = filter;
    const requestedVertical = verticalFilter;
    const requestedSeverity = severityFilter;
    setLoadingMore(true);
    setPageError(null);
    try {
      const page: IncidentPage = await client.listIncidents({
        status: requestedFilter,
        limit: PAGE_SIZE,
        cursor,
        ...(requestedVertical ? { vertical: requestedVertical } : {}),
        ...(requestedSeverity ? { severity: requestedSeverity } : {}),
      });
      if (
        rosterGeneration.current !== generation
        || filter !== requestedFilter
        || verticalFilter !== requestedVertical
        || severityFilter !== requestedSeverity
      ) return;
      if (!incidentPageMatchesSnapshot(state.data.metrics, page.metrics)) {
        throw new Error("Incident page snapshot changed during pagination");
      }
      setState((current) => current.status === "ready"
        ? {
            status: "ready",
            data: {
              items: [
                ...mergeIncidentItems(current.data.items, page.items),
              ],
              nextCursor: page.next_cursor,
              metrics: page.metrics,
            },
          }
        : current);
    } catch (error) {
      if (
        rosterGeneration.current !== generation
        || filter !== requestedFilter
        || verticalFilter !== requestedVertical
        || severityFilter !== requestedSeverity
      ) return;
      setPageError(error instanceof Error ? error.message : String(error));
    } finally {
      if (
        rosterGeneration.current === generation
        && filter === requestedFilter
        && verticalFilter === requestedVertical
        && severityFilter === requestedSeverity
      ) {
        setLoadingMore(false);
      }
    }
  }

  return (
    <div class="stack incidents-route">
      <PageHeader title={t("route.incidents")} subtitle={t("incidents.subtitle")} />
      <aside class="incident-readonly-banner" aria-label={t("incidents.bannerTitle")}>
        <strong>{t("incidents.bannerTitle")}</strong>
        <span>{t("incidents.bannerBody")}</span>
      </aside>
      {verticalFilter ? (
        <div class="filter-summary"><span>{t("evidence.incidents.verticalFilter")}: <strong>{incidentVerticalDisplayLabel(verticalFilter)}</strong></span></div>
      ) : null}
      <div class="segmented-control" role="group" aria-label={t("incidents.filterLabel")}>
        {FILTERS.map((value) => (
          <button
            key={value}
            type="button"
            class={filter === value ? "active" : undefined}
            aria-pressed={filter === value}
            onClick={() => openRoute(value, null)}
          >
            {t(`incidents.filter.${value}`)}
          </button>
        ))}
      </div>
      <div class="incident-scope-filters">
        <label>
          <span>{t("incidents.verticalLabel")}</span>
          <select
            value={verticalFilter ?? ""}
            onChange={(event) => openFilters(
              parseIncidentVertical((event.currentTarget as HTMLSelectElement).value),
              severityFilter,
            )}
          >
            <option value="">{t("incidents.filter.anyVertical")}</option>
            {INCIDENT_VERTICALS.map((value) => (
              <option key={value} value={value}>{localized("vertical", value)}</option>
            ))}
          </select>
        </label>
        <label>
          <span>{t("incidents.overview.severity")}</span>
          <select
            value={severityFilter ?? ""}
            onChange={(event) => openFilters(
              verticalFilter,
              parseIncidentSeverity((event.currentTarget as HTMLSelectElement).value),
            )}
          >
            <option value="">{t("incidents.filter.anySeverity")}</option>
            {INCIDENT_SEVERITIES.map((value) => (
              <option key={value} value={value}>{localized("severity", value)}</option>
            ))}
          </select>
        </label>
        {verticalFilter || severityFilter ? (
          <button type="button" onClick={() => openFilters(null, null)}>
            {t("incidents.filter.clearScope")}
          </button>
        ) : null}
      </div>
      <AsyncBoundary state={state} resourceLabel={t("route.incidents")}>
        {(data) => (
          <IncidentBody
            data={data}
            selectedId={selectedId}
            history={history}
            loadingMore={loadingMore}
            pageError={pageError}
            onSelect={(correlationId) => openRoute(filter, correlationId)}
            onLoadMore={loadMore}
          />
        )}
      </AsyncBoundary>
    </div>
  );
}

interface BodyProps {
  readonly data: IncidentData;
  readonly selectedId: string | null;
  readonly history: AsyncState<readonly AuditItem[]>;
  readonly loadingMore: boolean;
  readonly pageError: string | null;
  readonly onSelect: (correlationId: string) => void;
  readonly onLoadMore: (cursor: string) => Promise<void>;
}

function IncidentBody({
  data,
  selectedId,
  history,
  loadingMore,
  pageError,
  onSelect,
  onLoadMore,
}: BodyProps) {
  const selected = data.items.find((item) => item.correlation_id === selectedId) ?? null;
  const selectedHistory = history.status === "ready" ? history.data : [];

  usePublishViewContext(
    () => ({
      routeId: "incidents",
      routeLabel: t("route.incidents"),
      purpose:
        t("incidents.viewPurpose"),
      glossary: composeGlossary([TERMS.correlationId, TERMS.mode, TERMS.outcome]),
      headline: t("incidents.viewHeadline", { count: data.items.length }),
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "loaded_incidents", value: data.items.length, group: "incidents" },
        { key: "selected_correlation_id", value: selectedId, group: "incidents" },
      ],
      records: {
        incidents: data.items.map((item) => ({ ...item })),
        selected_incident: selected ? [{ ...selected }] : [],
        selected_history: selectedHistory.map((item) => ({
          seq: item.seq,
          correlation_id: item.correlation_id,
          actor: item.actor,
          action_kind: item.action_kind,
          mode: item.mode,
          recorded_at: item.recorded_at,
          ...item.entry,
        })),
      },
    }),
    [data.items, selected, selectedHistory],
  );

  return (
    <>
      <IncidentOutcomeAnalytics metrics={data.metrics} />
      <div class="incidents-workspace">
      <section class="incidents-roster" aria-labelledby="incident-roster-title">
        <header class="incidents-roster-head">
          <h2 id="incident-roster-title">{t("incidents.roster")}</h2>
          <span>{t("incidents.loadedCount", { count: data.items.length })}</span>
        </header>
        {data.items.length > 0 ? (
          <ul class="incidents-roster-list">
            {data.items.map((item) => (
              <li key={item.correlation_id}>
                <button
                  type="button"
                  class={`incident-roster-item${item.correlation_id === selectedId ? " is-selected" : ""}`}
                  aria-pressed={item.correlation_id === selectedId}
                  aria-controls={INCIDENT_DETAIL_ID}
                  onClick={() => onSelect(item.correlation_id)}
                >
                  <span class="incident-roster-title">
                    {incidentDisplayTitle(item, t("incidents.titleUnavailable"))}
                  </span>
                  {item.title_source === "identifier_fallback" ? (
                    <span class="incident-roster-identifier mono">
                      {incidentRosterIdentifier(item)}
                    </span>
                  ) : null}
                  <span class="incident-roster-meta">
                    <StatusPill kind={severityPill(item.severity)} label={localized("severity", item.severity)} />
                    <span class={`incident-status-dot status-${item.status}`} aria-hidden="true" />
                    <span>{localized("status", item.status)}</span>
                    <span aria-hidden="true">/</span>
                    <span>{localized("vertical", item.vertical)}</span>
                  </span>
                  <span class="incident-roster-updated mono">
                    {formatConsoleTimestamp(item.last_updated_at)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p class="incidents-roster-empty">{t("incidents.empty")}</p>
        )}
        <footer class="incidents-roster-foot">
          {pageError ? (
            <p class="state-error-text" role="alert">
              {t("incidents.loadMoreError", { message: pageError })}
            </p>
          ) : null}
          {data.nextCursor !== null ? (
            <button
              type="button"
              class="primary"
              disabled={loadingMore}
              onClick={() => void onLoadMore(data.nextCursor!)}
            >
              {loadingMore ? t("incidents.loadingMore") : t("incidents.loadMore")}
            </button>
          ) : (
            <p class="muted footnote">{t("incidents.end")}</p>
          )}
        </footer>
      </section>
      <div class="incident-selection">
        {selected ? <IncidentDetail incident={selected} history={history} /> : (
          selectedId ? (
            <div class="state-block state-unavailable" role={data.nextCursor ? "status" : "alert"}>
              <span class="state-icon" aria-hidden="true">?</span>
              <span>
                {t("evidence.incidents.notLoaded", { id: selectedId })}
                {data.nextCursor
                  ? ` ${t("evidence.incidents.continueSearch")}`
                  : ` ${t("evidence.incidents.filteredUnavailable")}`}
              </span>
            </div>
          ) : <p class="muted">{t("incidents.select")}</p>
        )}
      </div>
      </div>
    </>
  );
}

function IncidentDetail({
  incident,
  history,
}: {
  readonly incident: IncidentSummary;
  readonly history: AsyncState<readonly AuditItem[]>;
}) {
  const auditHref = routeHref("audit", { params: { correlation: incident.correlation_id } });
  const traceHref = routeHref("trace", { params: { correlation: incident.correlation_id } });
  const reportHref = routeHref("reports", {
    segments: ["incident-rca-dossier"],
    params: { correlation_id: incident.correlation_id },
  });
  return (
    <section id={INCIDENT_DETAIL_ID} class="incident-detail" aria-labelledby={`${INCIDENT_DETAIL_ID}-title`}>
      <header class="incident-detail-head">
        <div class="incident-detail-title-row">
          <h2 id={`${INCIDENT_DETAIL_ID}-title`}>
            {incidentDisplayTitle(incident, t("incidents.titleUnavailable"))}
          </h2>
          <StatusPill kind={severityPill(incident.severity)} label={localized("severity", incident.severity)} />
          <StatusPill kind={statusPill(incident.status)} label={localized("status", incident.status)} />
        </div>
        <dl class="incident-detail-meta">
          <div><dt>{t("incidents.opened")}</dt><dd>{formatConsoleTimestamp(incident.opened_at)}</dd></div>
          <div><dt>{t("incidents.lastUpdated")}</dt><dd>{formatConsoleTimestamp(incident.last_updated_at)}</dd></div>
          <div><dt>{t("incidents.history")}</dt><dd>{t("incidents.recordCount", { count: incident.history_count })}</dd></div>
          <div><dt>{t("incidents.latestMode")}</dt><dd>{localized("modeMeaning", incident.latest_mode)}</dd></div>
        </dl>
        <details class="incident-additional-evidence">
          <summary>{t("incidents.additionalEvidence")}</summary>
          <dl>
            <div><dt>{t("incidents.correlation")}</dt><dd class="mono">{incident.correlation_id}</dd></div>
            <div><dt>{t("incidents.incidentId")}</dt><dd class="mono">{incident.incident_id ?? t("incidents.none")}</dd></div>
            <div><dt>{t("incidents.ticketId")}</dt><dd class="mono">{incident.ticket_id ?? t("incidents.none")}</dd></div>
            <div><dt>{t("incidents.currentDisposition")}</dt><dd>{localized("disposition", incident.disposition)}</dd></div>
            <div><dt>{t("incidents.currentVerdict")}</dt><dd><StatusPill kind={verdictPill(incident.verdict)} label={localized("verdict", incident.verdict)} /></dd></div>
            <div><dt>{t("incidents.verticalLabel")}</dt><dd>{localized("vertical", incident.vertical)}</dd></div>
            <div><dt>{t("incidents.statusSource")}</dt><dd class="mono">{incident.status_source}</dd></div>
            <div><dt>{t("incidents.titleSource")}</dt><dd class="mono">{incident.title_source}</dd></div>
            <div><dt>{t("incidents.involvedAgents")}</dt><dd>{incident.involved_agents.length > 0 ? incident.involved_agents.join(", ") : t("incidents.none")}</dd></div>
          </dl>
        </details>
      </header>
      <IncidentSourceContext incident={incident} />
      <AsyncBoundary state={history} resourceLabel={t("incidents.timeline")}>
        {(items) => (
          <>
            <IncidentCurrentState incident={incident} items={items} />
            <IncidentMilestones items={items} />
            <IncidentEvidenceViews
              incident={incident}
              overview={incidentOperationalOverview(incident, items)}
              auditHref={auditHref}
              traceHref={traceHref}
              rcaHref={routeHref("rca", { params: { correlation: incident.correlation_id } })}
              reportHref={reportHref}
            />
            <div class="incident-history">
              <header class="incident-history-head">
                <h3>{t("incidents.timeline")}</h3>
                <span>{t("incidents.historyShown", {
                  shown: items.length,
                  total: incident.history_count,
                })}</span>
              </header>
              <IncidentTimeline items={items} />
            </div>
          </>
        )}
      </AsyncBoundary>
    </section>
  );
}

function IncidentCurrentState({
  incident,
  items,
}: {
  readonly incident: IncidentSummary;
  readonly items: readonly AuditItem[];
}) {
  const overview = incidentOperationalOverview(incident, items);
  const agentStatus = incidentAgentStatus(overview.phase);
  return (
    <section class="incident-current-state" aria-labelledby="incident-current-state-title">
      <header class="incident-current-state-head">
        <div>
          <span class="incident-section-label">{t("incidents.overview.label")}</span>
          <h3 id="incident-current-state-title">{t(`incidents.overview.headline.${overview.phase}`)}</h3>
        </div>
        <StatusPill kind={phasePill(overview.phase)} label={t(`incidents.overview.badge.${overview.phase}`)} />
      </header>
      <p>{t(`incidents.overview.body.${overview.phase}`)}</p>
      <dl class="incident-current-facts">
        <div><dt>{t("incidents.overview.alertStatus")}</dt><dd>{localized("status", incident.status)}</dd></div>
        <div><dt>{t("incidents.overview.agentStatus")}</dt><dd>{t(`incidents.overview.agentState.${agentStatus}`)}</dd></div>
        <div><dt>{t("incidents.overview.userInput")}</dt><dd>{t(agentStatus === "pending_user_input" ? "incidents.overview.required" : "incidents.overview.notRequired")}</dd></div>
        <div><dt>{t("incidents.overview.decision")}</dt><dd>{overview.decisionRecorded ? localized("verdict", incident.verdict) : t("incidents.overview.noDecision")}</dd></div>
        <div><dt>{t("incidents.overview.authority")}</dt><dd>{localized("modeMeaning", incident.latest_mode)}</dd></div>
      </dl>
      <section class="incident-response-routing" aria-label={t("incidents.overview.routingTitle")}>
        <h4>{t("incidents.overview.routingTitle")}</h4>
        <dl>
          <div><dt>{t("incidents.overview.severity")}</dt><dd>{localized("severity", incident.severity)}</dd></div>
          <div><dt>{t("incidents.overview.accountableAgents")}</dt><dd>{incident.involved_agents.length > 0 ? <a href={routeHref("agents", { params: { incident: incident.correlation_id } })}>{incident.involved_agents.join(", ")}</a> : t("incidents.none")}</dd></div>
          <div><dt>{t("incidents.overview.humanOwnership")}</dt><dd><a href={routeHref("handover")}>{t("incidents.overview.openOwnership")}</a></dd></div>
          <div><dt>{t("incidents.overview.autonomy")}</dt><dd>{localized("modeMeaning", incident.latest_mode)}</dd></div>
        </dl>
      </section>
      <div class="incident-next-step">
        <strong>{t("incidents.overview.nextStep")}</strong>
        <span>{t(`incidents.overview.next.${overview.phase}`)}</span>
        {overview.blockingReason !== null ? (
          <span class="incident-next-step-blocker">
            {t("incidents.overview.recordedBlocker", { reason: overview.blockingReason })}
          </span>
        ) : null}
      </div>
    </section>
  );
}

function IncidentEvidenceViews({
  incident,
  overview,
  auditHref,
  traceHref,
  rcaHref,
  reportHref,
}: {
  readonly incident: IncidentSummary;
  readonly overview: IncidentOperationalOverview;
  readonly auditHref: string;
  readonly traceHref: string;
  readonly rcaHref: string;
  readonly reportHref: string;
}) {
  return (
    <section class="incident-related-views" aria-labelledby="incident-related-views-title">
      <h3 id="incident-related-views-title">{t("incidents.evidence.title")}</h3>
      <p>{t("incidents.evidence.body")}</p>
      <div class="incident-view-list">
        <IncidentViewRow
          available={overview.auditAvailable}
          href={auditHref}
          label={t("incidents.evidence.auditTitle")}
          description={t("incidents.evidence.auditBody", { count: overview.activityCount })}
        />
        <IncidentViewRow
          available={overview.traceAvailable}
          href={traceHref}
          label={t("incidents.evidence.traceTitle")}
          description={t("incidents.evidence.traceBody", { count: overview.activityCount })}
        />
        <IncidentViewRow
          available={overview.rcaAvailable}
          href={rcaHref}
          label={t("incidents.evidence.rcaTitle")}
          description={overview.rcaAvailable
            ? t("incidents.evidence.rcaBody")
            : t("incidents.evidence.rcaUnavailable")}
        />
        <IncidentViewRow
          available={overview.reportAvailable}
          href={reportHref}
          label={t("incidents.evidence.reportTitle")}
          description={overview.reportAvailable
            ? t("incidents.evidence.reportBody")
            : t("incidents.evidence.reportUnavailable")}
        />
      </div>
      <span class="muted footnote">{t("incidents.evidence.correlation", { correlation: incident.correlation_id })}</span>
    </section>
  );
}

function IncidentViewRow({
  available,
  href,
  label,
  description,
}: {
  readonly available: boolean;
  readonly href: string;
  readonly label: string;
  readonly description: string;
}) {
  const content = (
    <>
      <strong>{label}</strong>
      <span>{description}</span>
      <em>{available ? t("incidents.evidence.open") : t("incidents.evidence.unavailable")}</em>
    </>
  );
  return available
    ? <a class="incident-view-row" href={href}>{content}</a>
    : <div class="incident-view-row is-unavailable" aria-disabled="true">{content}</div>;
}

function IncidentTimeline({ items }: { readonly items: readonly AuditItem[] }) {
  if (items.length === 0) return <p class="incidents-history-empty">{t("incidents.emptyHistory")}</p>;
  return (
    <ol class="incident-timeline">
      {items.map((item) => {
        const presentation = incidentTimelinePresentation(item);
        return (
          <li key={item.seq} class={`incident-timeline-event mode-${item.mode}`}>
            <div class="incident-timeline-row">
              <div class="incident-timeline-heading">
                <strong class="incident-timeline-title">{presentation.title}</strong>
                <code class="incident-timeline-kind">{presentation.actionKind}</code>
              </div>
              <span class={`incident-owner owner-${presentation.ownerKind}`}>
                <span>{t("incidents.ownerLabel", {
                  kind: t(`incidents.ownerKind.${presentation.ownerKind}`),
                })}</span>
                <strong>{presentation.owner}</strong>
              </span>
              <time dateTime={item.recorded_at}>{formatConsoleTimestamp(item.recorded_at)}</time>
            </div>
            <p class="incident-timeline-description">{presentation.description}</p>
            <div class="incident-timeline-facts">
              {presentation.facts.map((fact) => (
                <span key={`${fact.label}:${fact.value}`}>
                  {fact.label} <strong>{fact.value}</strong>
                </span>
              ))}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function localized(group: string, value: string): string {
  const key = `incidents.${group}.${value}`;
  const translated = t(key);
  return translated === key ? humanizeIncidentToken(value) : translated;
}

/** Keep an unmapped server value readable instead of rendering its catalog key. */
function humanizeIncidentToken(value: string): string {
  const words = value.replace(/[._-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function statusPill(status: IncidentSummary["status"]): PillKind {
  if (status === "resolved") return "success";
  if (status === "in_progress") return "info";
  return "hil";
}

function severityPill(severity: string): PillKind {
  if (severity === "critical" || severity === "high") return "danger";
  if (severity === "medium") return "hil";
  if (severity === "low" || severity === "info") return "info";
  return "neutral";
}

function verdictPill(verdict: string): PillKind {
  if (verdict === "auto") return "auto";
  if (verdict === "hil") return "hil";
  if (verdict === "deny") return "danger";
  return "neutral";
}

function phasePill(phase: IncidentOperationalOverview["phase"]): PillKind {
  if (phase === "resolved") return "success";
  if (phase === "notification_failed" || phase === "response_failed") return "danger";
  if (phase === "approval_required") return "hil";
  return "info";
}
