import { useEffect, useRef, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import type { AuditItem, AuditPage } from "../types";
import {
  AsyncBoundary,
  DataTable,
  PageHeader,
  StatusPill,
  type AsyncState,
  type Column,
  type PillKind,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, agentTerm, composeGlossary } from "../deck/glossary";
import { currentRoute, routeHref } from "../router";
import { appendAuditPage, resolveAuditEntry, type AuditData as Data } from "./audit.model";
import { t } from "./i18n/evidence";

interface Props {
  readonly client: ReadApiClient;
}

const PAGE_SIZE = 25;

function correlationFromHash(): string | null {
  return new URLSearchParams(window.location.search).get("correlation");
}

interface AuditFilters {
  readonly mode: string | null;
  readonly tier: string | null;
  readonly action: string | null;
  readonly outcome: string | null;
  readonly vertical: string | null;
  readonly window: string | null;
  readonly fromSeq: number | null;
  readonly throughSeq: number | null;
  readonly invalid: readonly string[];
}

function auditSeq(
  search: URLSearchParams,
  key: "entry" | "from_seq" | "through_seq",
): number | null {
  const value = search.get(key);
  if (value === null || !/^[1-9][0-9]*$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

export function auditFiltersFromSearch(search: URLSearchParams): AuditFilters {
  const mode = search.get("mode");
  const tier = search.get("tier");
  const windowFilter = search.get("window");
  const rawFromSeq = search.get("from_seq");
  const rawThroughSeq = search.get("through_seq");
  const rawEntry = search.get("entry");
  const entrySeq = auditSeq(search, "entry");
  const fromSeq = entrySeq ?? auditSeq(search, "from_seq");
  const throughSeq = entrySeq ?? auditSeq(search, "through_seq");
  const invalid = [
    ...(mode !== null && mode !== "shadow" && mode !== "enforce" ? [`mode=${mode}`] : []),
    ...(tier !== null && tier !== "t0" && tier !== "t1" && tier !== "t2" ? [`tier=${tier}`] : []),
    ...(windowFilter !== null && !/^[1-9][0-9]{0,2}d$/.test(windowFilter) ? [`window=${windowFilter}`] : []),
    ...(rawFromSeq !== null && fromSeq === null ? [`from_seq=${rawFromSeq}`] : []),
    ...(rawThroughSeq !== null && throughSeq === null ? [`through_seq=${rawThroughSeq}`] : []),
    ...(rawEntry !== null && entrySeq === null ? [`entry=${rawEntry}`] : []),
    ...(fromSeq !== null && throughSeq !== null && fromSeq > throughSeq
      ? [`from_seq=${fromSeq}>through_seq=${throughSeq}`]
      : []),
  ];
  return {
    mode,
    tier,
    action: search.get("action"),
    outcome: search.get("outcome"),
    vertical: search.get("vertical"),
    window: windowFilter,
    fromSeq,
    throughSeq,
    invalid,
  };
}

function filtersFromSearch(): AuditFilters {
  return auditFiltersFromSearch(new URLSearchParams(window.location.search));
}

export function AuditRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<Data>>({ status: "loading" });
  const [loadingMore, setLoadingMore] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const [correlationId, setCorrelationId] = useState<string | null>(() => correlationFromHash());
  const [filters, setFilters] = useState<AuditFilters>(filtersFromSearch);
  const mountedRef = useRef(true);
  const requestGeneration = useRef(0);

  useEffect(() => () => {
    mountedRef.current = false;
  }, []);

  useEffect(() => {
    const sync = () => {
      setCorrelationId(correlationFromHash());
      setFilters(filtersFromSearch());
    };
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
    };
  }, []);

  useEffect(() => {
    const generation = requestGeneration.current + 1;
    requestGeneration.current = generation;
    if (filters.invalid.length > 0) {
      setState({
        status: "error",
        message: t("evidence.audit.invalidFilter", { filters: filters.invalid.join(", ") }),
      });
      return;
    }
    setState({ status: "loading" });
    setPageError(null);
    setLoadingMore(false);
    (async () => {
      try {
        const page = await client.listAudit(auditRequest(filters, correlationId));
        if (requestGeneration.current === generation) {
          setState({
            status: "ready",
            data: { items: page.items, nextCursor: page.next_cursor },
          });
        }
      } catch (err) {
        if (requestGeneration.current === generation) {
          setState({
            status: "error",
            message: err instanceof Error ? err.message : String(err),
          });
        }
      }
    })();
    return () => {
      if (requestGeneration.current === generation) requestGeneration.current += 1;
    };
  }, [client, correlationId, filters]);

  const loadMore = async (cursor: string): Promise<void> => {
    if (state.status !== "ready" || loadingMore || state.data.nextCursor !== cursor) return;
    const generation = requestGeneration.current;
    setLoadingMore(true);
    setPageError(null);
    try {
      const page: AuditPage = await client.listAudit({
        ...auditRequest(filters, correlationId),
        cursor,
      });
      if (!mountedRef.current || requestGeneration.current !== generation) return;
      setState((current) => current.status === "ready"
        ? { status: "ready", data: appendAuditPage(current.data, cursor, page) }
        : current);
    } catch (err) {
      if (!mountedRef.current || requestGeneration.current !== generation) return;
      setPageError(err instanceof Error ? err.message : String(err));
    } finally {
      if (mountedRef.current && requestGeneration.current === generation) setLoadingMore(false);
    }
  };

  return (
    <div class="stack">
      <PageHeader
        title={t("route.audit")}
        subtitle={t("evidence.audit.subtitle")}
      />
      {correlationId ? (
        <p class="muted footnote">
          {t("incidents.auditFilter", { correlation: correlationId })}
        </p>
      ) : null}
      {Object.entries(filters).some(([key, value]) => key !== "invalid" && value) ? (
        <div class="filter-summary" aria-label={t("evidence.audit.activeFilters")}>
          {Object.entries(filters).filter(([key, value]) => key !== "invalid" && value).map(([key, value]) => (
            <span key={key}>{t(`evidence.audit.filter.${key}`)}: <strong>{value}</strong></span>
          ))}
        </div>
      ) : null}
      <AsyncBoundary state={state} resourceLabel={t("evidence.audit.resource")}>
        {(data) => (
          <AuditBody
            data={data}
            loadingMore={loadingMore}
            pageError={pageError}
            onLoadMore={loadMore}
          />
        )}
      </AsyncBoundary>
    </div>
  );
}

function modePill(mode: string): PillKind {
  if (mode === "enforce") return "enforce";
  if (mode === "shadow") return "shadow";
  return "neutral";
}

/** Read a string field from an audit `entry` payload, or "-" when absent. The
 * causal fields (`detail`, `summary`, `reason`, `tier`, `outcome`) live in the
 * JSONB `entry`; surfacing them lets the deck answer "why did this happen". */
function entryStr(entry: Record<string, unknown>, key: string): string {
  const v = entry[key];
  return typeof v === "string" && v.trim() ? v : "-";
}

function auditRequest(filters: AuditFilters, correlationId: string | null) {
  return {
    limit: PAGE_SIZE,
    ...(correlationId ? { correlationId } : {}),
    ...(filters.mode ? { mode: filters.mode } : {}),
    ...(filters.tier ? { tier: filters.tier } : {}),
    ...(filters.action ? { action: filters.action } : {}),
    ...(filters.outcome ? { outcome: filters.outcome } : {}),
    ...(filters.vertical ? { vertical: filters.vertical } : {}),
    ...(filters.window ? { window: filters.window } : {}),
    ...(filters.fromSeq !== null ? { fromSeq: filters.fromSeq } : {}),
    ...(filters.throughSeq !== null ? { throughSeq: filters.throughSeq } : {}),
  };
}

interface BodyProps {
  readonly data: Data;
  readonly loadingMore: boolean;
  readonly pageError: string | null;
  readonly onLoadMore: (cursor: string) => Promise<void>;
}

function AuditBody({ data, loadingMore, pageError, onLoadMore }: BodyProps) {
  const entrySelection = resolveAuditEntry(data, currentRoute().search.get("entry"));
  const selectedSeq = entrySelection.status === "selected" ? entrySelection.seq : null;
  const entryHref = (seq: number): string => {
    const params = Object.fromEntries(currentRoute().search.entries());
    return routeHref("audit", { params: { ...params, entry: seq } });
  };
  usePublishViewContext(
    () => ({
      routeId: "audit",
      routeLabel: t("route.audit"),
      purpose: t("evidence.audit.viewPurpose"),
      glossary: composeGlossary([
        TERMS.correlationId,
        TERMS.actionKind,
        TERMS.mode,
        TERMS.tier,
        TERMS.outcome,
        agentTerm(),
      ]),
      headline: t(
        data.nextCursor === null ? "evidence.audit.headlineEnd" : "evidence.audit.headlineMore",
        { count: data.items.length },
      ),
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "loaded_rows", value: data.items.length, group: "page" },
        { key: "more_available", value: data.nextCursor !== null, group: "page" },
      ],
      records: {
        // Keep the causal fields (`summary`, `detail`, `reason`, `tier`,
        // `outcome`, `correlation_id`) - NOT projected away - so the narrator
        // can answer "why did this happen" by quoting the recorded narrative.
        items: data.items.map((r) => ({
          seq: r.seq,
          recorded_at: r.recorded_at,
          actor: r.actor,
          action_kind: r.action_kind,
          mode: r.mode,
          event_id: r.event_id,
          correlation_id: r.correlation_id ?? "-",
          tier: entryStr(r.entry, "tier"),
          outcome: entryStr(r.entry, "outcome"),
          summary: entryStr(r.entry, "summary"),
          detail: entryStr(r.entry, "detail"),
          reason: entryStr(r.entry, "reason"),
        })),
      },
    }),
    [data.items, data.nextCursor],
  );

  const columns: readonly Column<AuditItem>[] = [
    {
      key: "seq",
      header: "#",
      render: (r) => <a href={entryHref(r.seq)}>{r.seq}</a>,
      cellClass: "mono num",
      headerClass: "num",
    },
    { key: "at", header: t("evidence.audit.column.recordedAt"), render: (r) => r.recorded_at, cellClass: "mono" },
    { key: "actor", header: t("evidence.audit.column.actor"), render: (r) => r.actor },
    { key: "kind", header: t("evidence.audit.column.actionKind"), render: (r) => r.action_kind, cellClass: "mono" },
    {
      key: "mode",
      header: t("evidence.audit.column.mode"),
      render: (r) => <StatusPill kind={modePill(r.mode)} label={r.mode} />,
    },
    { key: "eid", header: t("evidence.audit.column.eventId"), render: (r) => r.event_id, cellClass: "mono" },
    {
      key: "evidence",
      header: t("evidence.audit.column.evidence"),
      render: (r) => r.correlation_id ? (
        <span class="table-action-links">
          <a href={routeHref("trace", { params: { correlation: r.correlation_id } })}>{t("evidence.audit.trace")}</a>
          <a href={routeHref("rca", { params: { correlation: r.correlation_id } })}>{t("evidence.audit.rca")}</a>
          <a href={routeHref("incidents", { params: { status: "all", correlation: r.correlation_id } })}>{t("evidence.audit.incident")}</a>
        </span>
      ) : <span class="muted">-</span>,
    },
    {
      key: "raw",
      header: t("evidence.audit.column.details"),
      render: (r) => (
        <details open={selectedSeq === r.seq}>
          <summary class="details-summary">{t("evidence.audit.viewJson")}</summary>
          <pre class="mono small entry-json">{JSON.stringify(r.entry, null, 2)}</pre>
        </details>
      ),
    },
  ];

  return (
    <div class="stack">
      {entrySelection.status === "invalid" ? (
        <p class="state-error-text" role="alert">{t("evidence.audit.invalidEntry", { value: entrySelection.value })}</p>
      ) : null}
      {entrySelection.status === "pending" ? (
        <p class="state-block state-unavailable" role="status">
          {t("evidence.audit.pendingEntry", { seq: entrySelection.seq })}
        </p>
      ) : null}
      {entrySelection.status === "unavailable" ? (
        <p class="state-block state-unavailable" role="alert">
          {t("evidence.audit.unavailableEntry", { seq: entrySelection.seq })}
        </p>
      ) : null}
      <DataTable
        columns={columns}
        rows={data.items}
        keyOf={(r) => r.seq}
        empty={t("evidence.audit.empty")}
      />
      {pageError ? <p class="state-error-text" role="alert">{t("evidence.audit.loadMoreError", { message: pageError })}</p> : null}
      {data.nextCursor !== null ? (
        <button
          type="button"
          class="primary"
          disabled={loadingMore}
          onClick={() => {
            void onLoadMore(data.nextCursor!);
          }}
        >
          {loadingMore ? t("evidence.audit.loadingMore") : t("evidence.audit.loadMore")}
        </button>
      ) : (
        <p class="muted footnote">{t("evidence.audit.end")}</p>
      )}
    </div>
  );
}
