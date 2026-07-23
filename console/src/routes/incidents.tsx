import { useEffect, useRef, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import type {
  AuditItem,
  IncidentPage,
  IncidentStatusFilter,
  IncidentSummary,
} from "../types";
import {
  AsyncBoundary,
  DataTable,
  KpiCard,
  KpiGrid,
  PageHeader,
  StatusPill,
  type AsyncState,
  type Column,
  type PillKind,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { currentRoute, navigate, routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import { t } from "./i18n/evidence";

const INCIDENT_DETAIL_ID = "incident-detail";

interface Props {
  readonly client: ReadApiClient;
}

interface IncidentData {
  readonly items: readonly IncidentSummary[];
  readonly nextCursor: string | null;
}

const PAGE_SIZE = 25;
const FILTERS: readonly IncidentStatusFilter[] = ["active", "resolved", "all"];
const INCIDENT_VERTICALS = ["resilience", "change_safety", "cost_governance", "unknown"] as const;
type IncidentVertical = typeof INCIDENT_VERTICALS[number];

export function parseIncidentVertical(value: string | null): IncidentVertical | null {
  if (value === null) return null;
  const normalized = value.trim().toLowerCase().replaceAll("-", "_");
  return INCIDENT_VERTICALS.includes(normalized as IncidentVertical)
    ? normalized as IncidentVertical
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

export function IncidentsRoute({ client }: Props) {
  const initialRoute = currentRoute();
  const initialStatus = initialRoute.search.get("status");
  const [verticalFilter, setVerticalFilter] = useState<IncidentVertical | null>(
    parseIncidentVertical(initialRoute.search.get("vertical")),
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
        correlation,
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
    } as const;
    exactLookup.current = null;
    void client.listIncidents(filters).then(
      (page) => {
        if (rosterGeneration.current !== generation) return;
        setState({
          status: "ready",
          data: { items: page.items, nextCursor: page.next_cursor },
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
  }, [client, filter, verticalFilter]);

  useEffect(() => {
    if (selectedId === null || state.status !== "ready") return;
    if (state.data.items.some((item) => item.correlation_id === selectedId)) return;
    const lookupKey = `${filter}:${verticalFilter ?? "all"}:${selectedId}`;
    if (exactLookup.current === lookupKey) return;
    exactLookup.current = lookupKey;
    const generation = rosterGeneration.current;
    void client.listIncidents({
      status: filter,
      limit: 1,
      correlationId: selectedId,
      ...(verticalFilter ? { vertical: verticalFilter } : {}),
    }).then(
      (page) => {
        if (rosterGeneration.current !== generation) return;
        setState((current) => current.status === "ready"
          ? {
              status: "ready",
              data: {
                ...current.data,
                items: mergeIncidentItems(page.items, current.data.items),
              },
            }
          : current);
      },
      () => undefined,
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
    setLoadingMore(true);
    setPageError(null);
    try {
      const page: IncidentPage = await client.listIncidents({
        status: requestedFilter,
        limit: PAGE_SIZE,
        cursor,
        ...(verticalFilter ? { vertical: verticalFilter } : {}),
      });
      if (rosterGeneration.current !== generation || filter !== requestedFilter) return;
      setState((current) => current.status === "ready"
        ? {
            status: "ready",
            data: {
              items: [
                ...mergeIncidentItems(current.data.items, page.items),
              ],
              nextCursor: page.next_cursor,
            },
          }
        : current);
    } catch (error) {
      if (rosterGeneration.current !== generation || filter !== requestedFilter) return;
      setPageError(error instanceof Error ? error.message : String(error));
    } finally {
      if (rosterGeneration.current === generation && filter === requestedFilter) {
        setLoadingMore(false);
      }
    }
  }

  return (
    <div class="stack">
      <PageHeader title={t("route.incidents")} subtitle={t("incidents.subtitle")} />
      {verticalFilter ? (
        <div class="filter-summary"><span>{t("evidence.incidents.verticalFilter")}: <strong>{verticalFilter}</strong></span></div>
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

  const columns: readonly Column<IncidentSummary>[] = [
    { key: "title", header: t("incidents.column.title"), render: (item) => item.title },
    {
      key: "severity",
      header: t("incidents.column.severity"),
      render: (item) => (
        <StatusPill kind={severityPill(item.severity)} label={localized("severity", item.severity)} />
      ),
    },
    {
      key: "status",
      header: t("incidents.column.status"),
      render: (item) => (
        <StatusPill kind={statusPill(item.status)} label={localized("status", item.status)} />
      ),
    },
    {
      key: "disposition",
      header: t("incidents.column.disposition"),
      render: (item) => localized("disposition", item.disposition),
    },
    {
      key: "vertical",
      header: t("incidents.column.vertical"),
      render: (item) => localized("vertical", item.vertical),
    },
    {
      key: "updated",
      header: t("incidents.column.updated"),
      render: (item) => formatConsoleTimestamp(item.last_updated_at),
      cellClass: "mono",
    },
  ];

  return (
    <div class="stack">
      <DataTable
        columns={columns}
        rows={data.items}
        keyOf={(item) => item.correlation_id}
        empty={t("incidents.empty")}
        onRowClick={(item) => onSelect(item.correlation_id)}
        isRowActive={(item) => item.correlation_id === selectedId}
        rowActionLabel={(item) => t("incidents.selectNamed", { title: item.title })}
        rowActionControls={INCIDENT_DETAIL_ID}
      />
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
  );
}

function IncidentDetail({
  incident,
  history,
}: {
  readonly incident: IncidentSummary;
  readonly history: AsyncState<readonly AuditItem[]>;
}) {
  const route = currentRoute();
  const currentStatus = route.search.get("status");
  const incidentHref = routeHref("incidents", {
    params: {
      status: currentStatus === "resolved" || currentStatus === "all" ? currentStatus : null,
      vertical: route.search.get("vertical") ?? incident.vertical,
      correlation: incident.correlation_id,
    },
  });
  const auditHref = routeHref("audit", { params: { correlation: incident.correlation_id } });
  const traceHref = routeHref("trace", { params: { correlation: incident.correlation_id } });
  const reportHref = routeHref("reports", {
    segments: ["incident-rca-dossier"],
    params: { correlation_id: incident.correlation_id },
  });
  return (
    <section id={INCIDENT_DETAIL_ID} class="stack-section" aria-labelledby={`${INCIDENT_DETAIL_ID}-title`}>
      <h3 id={`${INCIDENT_DETAIL_ID}-title`} class="section-title">{t("incidents.detail")}</h3>
      <KpiGrid>
        <KpiCard href={auditHref} label={t("incidents.correlation")} value={<span class="mono small">{incident.correlation_id}</span>} />
        <KpiCard href={reportHref} label={t("incidents.incidentId")} value={<span class="mono small">{incident.incident_id ?? t("incidents.none")}</span>} />
        <KpiCard href={reportHref} label={t("incidents.ticketId")} value={<span class="mono small">{incident.ticket_id ?? t("incidents.none")}</span>} />
        <KpiCard href={auditHref} label={t("incidents.opened")} value={<span class="mono small">{formatConsoleTimestamp(incident.opened_at)}</span>} />
        <KpiCard href={auditHref} label={t("incidents.lastUpdated")} value={<span class="mono small">{formatConsoleTimestamp(incident.last_updated_at)}</span>} />
        <KpiCard href={incidentHref} label={t("incidents.currentStatus")} value={<StatusPill kind={statusPill(incident.status)} label={localized("status", incident.status)} />} />
        <KpiCard href={incidentHref} label={t("incidents.currentDisposition")} value={localized("disposition", incident.disposition)} />
        <KpiCard href={traceHref} label={t("incidents.currentVerdict")} value={<StatusPill kind={verdictPill(incident.verdict)} label={incident.verdict} />} />
        <KpiCard href={incidentHref} label={t("incidents.verticalLabel")} value={localized("vertical", incident.vertical)} />
        <KpiCard href={routeHref("audit", { params: { correlation: incident.correlation_id, mode: incident.latest_mode } })} label={t("incidents.latestMode")} value={<StatusPill kind={incident.latest_mode} label={incident.latest_mode} />} />
        <KpiCard href={auditHref} label={t("incidents.statusSource")} value={<span class="mono small">{incident.status_source}</span>} />
        <KpiCard href={auditHref} label={t("incidents.history")} value={incident.history_count} />
        <KpiCard
          href={traceHref}
          label={t("incidents.involvedAgents")}
          value={incident.involved_agents.length > 0
            ? incident.involved_agents.join(", ")
            : t("incidents.none")}
        />
      </KpiGrid>
      <nav class="incident-evidence-links" aria-label={t("evidence.incidents.evidence")}>
        <a href={reportHref}>{t("incidents.report")}</a>
        <a href={auditHref}>{t("incidents.audit")}</a>
        <a href={traceHref}>{t("incidents.trace")}</a>
        <a href={routeHref("rca", { params: { correlation: incident.correlation_id } })}>{t("incidents.rca")}</a>
      </nav>
      <AsyncBoundary state={history} resourceLabel={t("incidents.timeline")}>
        {(items) => (
          <div class="stack">
            <p class="muted footnote">
              {t("incidents.historyShown", {
                shown: items.length,
                total: incident.history_count,
              })}
            </p>
            <IncidentTimeline items={items} />
          </div>
        )}
      </AsyncBoundary>
    </section>
  );
}

function IncidentTimeline({ items }: { readonly items: readonly AuditItem[] }) {
  const columns: readonly Column<AuditItem>[] = [
    { key: "at", header: t("incidents.column.updated"), render: (item) => formatConsoleTimestamp(item.recorded_at), cellClass: "mono" },
    { key: "actor", header: t("incidents.actor"), render: (item) => item.actor },
    { key: "action", header: t("incidents.action"), render: (item) => item.action_kind, cellClass: "mono" },
    { key: "decision", header: t("incidents.decision"), render: (item) => entryString(item, "decision") },
    { key: "mode", header: t("incidents.mode"), render: (item) => <StatusPill kind={item.mode} label={item.mode} /> },
    { key: "rollback", header: t("incidents.rollback"), render: (item) => entryString(item, "rollback_reference", "rollback_ref") },
    {
      key: "details",
      header: t("incidents.details"),
      render: (item) => (
        <details>
          <summary class="details-summary">{t("incidents.viewJson")}</summary>
          <pre class="mono small entry-json">{JSON.stringify(item.entry, null, 2)}</pre>
        </details>
      ),
    },
  ];
  return (
    <div class="stack">
      <h4 class="section-title">{t("incidents.timeline")}</h4>
      <DataTable columns={columns} rows={items} keyOf={(item) => item.seq} empty={t("incidents.emptyHistory")} />
    </div>
  );
}

function entryString(item: AuditItem, ...keys: string[]): string {
  for (const key of keys) {
    const value = item.entry[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return t("incidents.none");
}

function localized(group: string, value: string): string {
  return t(`incidents.${group}.${value}`);
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
