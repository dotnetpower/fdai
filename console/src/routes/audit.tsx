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
import { t } from "../i18n";
import { appendAuditPage, type AuditData as Data } from "./audit.model";

interface Props {
  readonly client: ReadApiClient;
}

const PAGE_SIZE = 25;

export function AuditRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<Data>>({ status: "loading" });
  const [loadingMore, setLoadingMore] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => () => {
    mountedRef.current = false;
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const page = await client.listAudit({ limit: PAGE_SIZE });
        if (!cancelled) {
          setState({
            status: "ready",
            data: { items: page.items, nextCursor: page.next_cursor },
          });
        }
      } catch (err) {
        if (!cancelled) {
          setState({
            status: "error",
            message: err instanceof Error ? err.message : String(err),
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client]);

  const loadMore = async (cursor: string): Promise<void> => {
    if (state.status !== "ready" || loadingMore || state.data.nextCursor !== cursor) return;
    setLoadingMore(true);
    setPageError(null);
    try {
      const page: AuditPage = await client.listAudit({
        limit: PAGE_SIZE,
        cursor,
      });
      if (!mountedRef.current) return;
      setState((current) => current.status === "ready"
        ? { status: "ready", data: appendAuditPage(current.data, cursor, page) }
        : current);
    } catch (err) {
      if (!mountedRef.current) return;
      setPageError(err instanceof Error ? err.message : String(err));
    } finally {
      if (mountedRef.current) setLoadingMore(false);
    }
  };

  return (
    <div class="stack">
      <PageHeader
        title={t("route.audit")}
        subtitle="Append-only record of every terminal control-plane decision. Read-only; entries are never edited or deleted."
      />
      <AsyncBoundary state={state} resourceLabel="audit log">
        {(data) => <AuditBody data={data} loadingMore={loadingMore} pageError={pageError} onLoadMore={loadMore} />}
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

interface BodyProps {
  readonly data: Data;
  readonly loadingMore: boolean;
  readonly pageError: string | null;
  readonly onLoadMore: (cursor: string) => Promise<void>;
}

function AuditBody({ data, loadingMore, pageError, onLoadMore }: BodyProps) {
  usePublishViewContext(
    () => ({
      routeId: "audit",
      routeLabel: "Audit log",
      purpose:
        "The append-only record of every terminal control-plane decision - one " +
        "row per event that reached a verdict. Read-only: entries are never " +
        "edited or deleted, and each carries the recorded reason it happened.",
      glossary: composeGlossary([
        TERMS.correlationId,
        TERMS.actionKind,
        TERMS.mode,
        TERMS.tier,
        TERMS.outcome,
        agentTerm(),
      ]),
      headline: `${data.items.length} row(s) loaded${data.nextCursor === null ? " (end of log)" : " (more available)"}`,
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
    { key: "seq", header: "#", render: (r) => r.seq, cellClass: "mono num", headerClass: "num" },
    { key: "at", header: "Recorded at", render: (r) => r.recorded_at, cellClass: "mono" },
    { key: "actor", header: "Actor", render: (r) => r.actor },
    { key: "kind", header: "Action kind", render: (r) => r.action_kind, cellClass: "mono" },
    {
      key: "mode",
      header: "Mode",
      render: (r) => <StatusPill kind={modePill(r.mode)} label={r.mode} />,
    },
    { key: "eid", header: "Event id", render: (r) => r.event_id, cellClass: "mono" },
    {
      key: "raw",
      header: "Details",
      render: (r) => (
        <details>
          <summary class="details-summary">view JSON</summary>
          <pre class="mono small entry-json">{JSON.stringify(r.entry, null, 2)}</pre>
        </details>
      ),
    },
  ];

  return (
    <div class="stack">
      <DataTable
        columns={columns}
        rows={data.items}
        keyOf={(r) => r.seq}
        empty="Audit log is empty."
      />
      {pageError ? <p class="state-error-text" role="alert">Failed to load more audit rows: {pageError}</p> : null}
      {data.nextCursor !== null ? (
        <button
          type="button"
          class="primary"
          disabled={loadingMore}
          onClick={() => {
            void onLoadMore(data.nextCursor!);
          }}
        >
          {loadingMore ? "Loading..." : "Load more"}
        </button>
      ) : (
        <p class="muted footnote">End of log.</p>
      )}
    </div>
  );
}
