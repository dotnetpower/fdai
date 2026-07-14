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
import { t } from "../i18n";

interface Props {
  readonly client: ReadApiClient;
}

interface IncidentData {
  readonly items: readonly IncidentSummary[];
  readonly nextCursor: string | null;
}

const PAGE_SIZE = 25;
const FILTERS: readonly IncidentStatusFilter[] = ["active", "resolved", "all"];

export function IncidentsRoute({ client }: Props) {
  const [filter, setFilter] = useState<IncidentStatusFilter>("active");
  const [state, setState] = useState<AsyncState<IncidentData>>({ status: "loading" });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [history, setHistory] = useState<AsyncState<readonly AuditItem[]>>({ status: "idle" });
  const [loadingMore, setLoadingMore] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const rosterGeneration = useRef(0);
  const historyGeneration = useRef(0);

  useEffect(() => {
    const generation = rosterGeneration.current + 1;
    rosterGeneration.current = generation;
    setState({ status: "loading" });
    setPageError(null);
    setLoadingMore(false);
    void client.listIncidents({ status: filter, limit: PAGE_SIZE }).then(
      (page) => {
        if (rosterGeneration.current !== generation) return;
        const first = page.items[0]?.correlation_id ?? null;
        setState({
          status: "ready",
          data: { items: page.items, nextCursor: page.next_cursor },
        });
        setSelectedId((current) =>
          page.items.some((item) => item.correlation_id === current) ? current : first,
        );
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
  }, [client, filter]);

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
      });
      if (rosterGeneration.current !== generation || filter !== requestedFilter) return;
      setState((current) => current.status === "ready"
        ? {
            status: "ready",
            data: {
              items: [...current.data.items, ...page.items],
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
      <div class="segmented-control" role="group" aria-label={t("incidents.filterLabel")}>
        {FILTERS.map((value) => (
          <button
            key={value}
            type="button"
            class={filter === value ? "active" : undefined}
            aria-pressed={filter === value}
            onClick={() => setFilter(value)}
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
            onSelect={setSelectedId}
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
      records: { incidents: data.items.map((item) => ({ ...item })) },
    }),
    [data.items, selectedId],
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
      render: (item) => item.last_updated_at,
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
        <p class="muted">{t("incidents.select")}</p>
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
  return (
    <section class="stack-section">
      <h3 class="section-title">{t("incidents.detail")}</h3>
      <KpiGrid>
        <KpiCard label={t("incidents.correlation")} value={<span class="mono small">{incident.correlation_id}</span>} />
        <KpiCard label={t("incidents.opened")} value={<span class="mono small">{incident.opened_at}</span>} />
        <KpiCard label={t("incidents.history")} value={incident.history_count} />
      </KpiGrid>
      <p>
        <a href={`#/audit?correlation=${encodeURIComponent(incident.correlation_id)}`}>{t("incidents.audit")}</a>
        {" | "}
        <a href={`#/trace?correlation=${encodeURIComponent(incident.correlation_id)}`}>{t("incidents.trace")}</a>
      </p>
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
    { key: "at", header: t("incidents.column.updated"), render: (item) => item.recorded_at, cellClass: "mono" },
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
