import { useEffect, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import type { AuditPage } from "../types";
import {
  AsyncBoundary,
  PageHeader,
  type AsyncState,
} from "../components/ui";
import { currentRoute } from "../router";
import { appendAuditPage, resolveAuditEntry, type AuditData as Data } from "./audit.model";
import { AuditQueryControls } from "./audit.filters";
import { AuditWorkspace } from "./audit.workspace";
import { t } from "./i18n/evidence";
import "./audit.workspace.css";

interface Props {
  readonly client: OperatorApiClient;
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
            data: {
              items: page.items,
              nextCursor: page.next_cursor,
              summary: page.summary ?? null,
            },
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
    <div class="audit-route">
      <PageHeader
        title={t("route.audit")}
        subtitle={t("evidence.audit.workspace.subtitle")}
        actions={<div class="audit-header-meta">
          <span>{t("evidence.audit.workspace.ledgerWindow")}</span>
          <strong>{state.status === "ready"
            ? state.data.summary
              ? t("evidence.audit.workspace.loadedAndMatchingCount", {
                  loaded: state.data.items.length,
                  matching: state.data.summary.matching_record_count,
                })
              : t("evidence.audit.workspace.loadedCount", { count: state.data.items.length })
            : t("evidence.audit.workspace.source")}</strong>
        </div>}
      />
      <aside class="audit-boundary" role="note">
        <strong>{t("evidence.audit.workspace.boundaryTitle")}</strong>
        <span>{t("evidence.audit.workspace.boundaryBody")}</span>
      </aside>
      {state.status !== "ready" ? <AuditQueryControls search={currentRoute().search.toString()} /> : null}
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

function auditRequest(filters: AuditFilters, correlationId: string | null) {
  return {
    limit: PAGE_SIZE,
    includeSummary: true,
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
  return (
    <div class="audit-body">
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
      <AuditWorkspace data={data} selection={entrySelection} />
      <footer class="audit-pagination">
      <div><strong>{t("evidence.audit.workspace.cursorBoundary")}</strong>
        <p>{t("evidence.audit.workspace.cursorHint")}</p></div>
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
      </footer>
    </div>
  );
}
