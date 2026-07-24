import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "preact/hooks";
import { Tooltip } from "../components/tooltip";
import type { AuditItem } from "../types";
import type { AgentStreamStatus } from "../hooks/use-agent-stream";
import {
  observationSourceLabel,
  type ObservationSource,
} from "../hooks/observation-source";
import { t } from "../i18n";
import { routeHref } from "../router";
import { formatConsoleTime } from "../time-format";
import {
  AGENT_LOG_LIMIT,
  agentLogFullscreenAction,
  buildAgentLogRows,
  DEFAULT_AGENT_LOG_COLUMNS,
  filterAgentLogRows,
  fallbackAfterFullscreenFailure,
  isNearLogBottom,
  toggleAgentLogColumn,
  type AgentLogColumn,
  type AgentLogRow,
  type AgentLogSource,
} from "./agent-activity-log-model";
import type { LiveAgentActivityEvent } from "./agents.model";

const COLUMN_ORDER: readonly AgentLogColumn[] = [
  "time",
  "route",
  "type",
  "detail",
  "correlation",
];
const COLUMN_WIDTH: Readonly<Record<AgentLogColumn, string>> = {
  time: "112px",
  route: "150px",
  type: "96px",
  detail: "minmax(300px, 1fr)",
  correlation: "190px",
};


interface Props {
  readonly events: readonly LiveAgentActivityEvent[];
  readonly auditItems: readonly AuditItem[];
  readonly selectedAgent: string | null;
  readonly query: string;
  readonly streamStatus: AgentStreamStatus;
  readonly streamSource: ObservationSource;
  readonly onSelectedAgentChange: (agent: string | null) => void;
  readonly onQueryChange: (query: string) => void;
}

export function LiveActivityJournal({
  events,
  auditItems,
  selectedAgent,
  query,
  streamStatus,
  streamSource,
  onSelectedAgentChange,
  onQueryChange,
}: Props) {
  const [visibleColumns, setVisibleColumns] = useState<readonly AgentLogColumn[]>(
    DEFAULT_AGENT_LOG_COLUMNS,
  );
  const [tailing, setTailing] = useState(true);
  const [columnsOpen, setColumnsOpen] = useState(false);
  const [nativeFullscreen, setNativeFullscreen] = useState(false);
  const [fallbackFullscreen, setFallbackFullscreen] = useState(false);
  const panelRef = useRef<HTMLElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const columnsRef = useRef<HTMLDivElement>(null);
  const fullscreenButtonRef = useRef<HTMLButtonElement>(null);
  const fallbackFullscreenRef = useRef(false);
  const nativeFullscreenRef = useRef(false);
  const rows = useMemo(() => buildAgentLogRows(events, auditItems), [events, auditItems]);
  const visibleRows = useMemo(
    () => filterAgentLogRows(rows, selectedAgent, query),
    [rows, selectedAgent, query],
  );
  const agents = useMemo(() => {
    const names = new Set<string>();
    rows.forEach((row) => row.route.forEach((agent) => names.add(agent)));
    if (selectedAgent !== null) names.add(selectedAgent);
    return [...names].sort((left, right) => left.localeCompare(right));
  }, [rows, selectedAgent]);
  const latestRowId = visibleRows.at(-1)?.id ?? null;
  const fullscreen = nativeFullscreen || fallbackFullscreen;

  useLayoutEffect(() => {
    if (!tailing || logRef.current === null) return;
    logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [tailing, latestRowId, selectedAgent, query]);

  useEffect(() => {
    const restoreFocus = () => {
      window.requestAnimationFrame(() => fullscreenButtonRef.current?.focus());
    };
    const sync = () => {
      const active = document.fullscreenElement === panelRef.current;
      const wasActive = nativeFullscreenRef.current;
      nativeFullscreenRef.current = active;
      setNativeFullscreen(active);
      if (wasActive && !active) restoreFocus();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && fallbackFullscreenRef.current) {
        setFallbackFullscreen(false);
      }
    };
    document.addEventListener("fullscreenchange", sync);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("fullscreenchange", sync);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  useEffect(() => {
    const wasActive = fallbackFullscreenRef.current;
    fallbackFullscreenRef.current = fallbackFullscreen;
    document.body.classList.toggle("aa-log-fullscreen-fallback", fallbackFullscreen);
    if (wasActive && !fallbackFullscreen) {
      window.requestAnimationFrame(() => fullscreenButtonRef.current?.focus());
    }
    return () => {
      document.body.classList.remove("aa-log-fullscreen-fallback");
    };
  }, [fallbackFullscreen]);

  useEffect(() => {
    if (!columnsOpen) return;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (!columnsRef.current?.contains(event.target as Node | null)) setColumnsOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setColumnsOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [columnsOpen]);

  const toggleFullscreen = async (): Promise<void> => {
    const panel = panelRef.current;
    if (panel === null) return;
    if (fallbackFullscreen) {
      setFallbackFullscreen(false);
      return;
    }
    const action = agentLogFullscreenAction(
      document.fullscreenElement !== null,
      panel.requestFullscreen !== undefined,
    );
    if (action === "exit-native") {
      try {
        await document.exitFullscreen();
      } catch {
        return;
      }
      return;
    }
    if (action === "enter-fallback") {
      setFallbackFullscreen(true);
      return;
    }
    try {
      await panel.requestFullscreen({ navigationUI: "hide" });
      setNativeFullscreen(true);
    } catch {
      if (fallbackAfterFullscreenFailure(action)) setFallbackFullscreen(true);
    }
  };

  const template = COLUMN_ORDER
    .filter((column) => visibleColumns.includes(column))
    .map((column) => COLUMN_WIDTH[column])
    .join(" ");

  return (
    <section
      ref={panelRef}
      class={`aa-live-journal aa-agent-log ${fallbackFullscreen ? "is-fullscreen-fallback" : ""}`}
      aria-labelledby="aa-live-journal-title"
    >
      <header>
        <div>
          <span>
            {t("agentActivity.live.session")} - {t(`agents.connection.${streamStatus}`)} - {observationSourceLabel(streamSource)}
          </span>
          <h3 id="aa-live-journal-title">{t("agentActivity.log.title")}</h3>
        </div>
        <div class="aa-log-actions">
          <span class="aa-log-count" aria-live="polite">
            {t("agentActivity.log.rows", { count: visibleRows.length })}
          </span>
          <button
            ref={fullscreenButtonRef}
            type="button"
            class="aa-log-control aa-log-tail"
            aria-pressed={tailing}
            aria-label={t(tailing ? "agentActivity.log.disableTail" : "agentActivity.log.resumeTail")}
            onClick={() => setTailing((current) => !current)}
          >
            <span class="aa-log-live-dot" aria-hidden="true" />
            {t(tailing ? "agentActivity.log.tailOn" : "agentActivity.log.resumeTail")}
          </button>
          <div ref={columnsRef} class="aa-log-columns">
            <Tooltip content={t("agentActivity.log.columns")}>
              <button
                type="button"
                class="aa-log-control"
                aria-haspopup="menu"
                aria-expanded={columnsOpen}
                onClick={() => setColumnsOpen((current) => !current)}
              >
                <span aria-hidden="true">☷</span>
                <span>{t("agentActivity.log.columns")}</span>
              </button>
            </Tooltip>
            {columnsOpen ? <div class="aa-log-column-menu" role="menu">
              {COLUMN_ORDER.map((column) => (
                <label key={column}>
                  <input
                    type="checkbox"
                    checked={visibleColumns.includes(column)}
                    onChange={() => setVisibleColumns((current) => toggleAgentLogColumn(current, column))}
                  />
                  <span>{t(`agentActivity.log.column.${column}`)}</span>
                </label>
              ))}
            </div> : null}
          </div>
          <Tooltip content={t(fullscreen ? "agentActivity.log.exitFullscreen" : "agentActivity.log.fullscreen")}>
            <button
              type="button"
              class="aa-log-control"
              aria-pressed={fullscreen}
              onClick={() => void toggleFullscreen()}
            >
              <span aria-hidden="true">{fullscreen ? "×" : "⛶"}</span>
              <span>{t(fullscreen ? "agentActivity.log.exitFullscreen" : "agentActivity.log.fullscreen")}</span>
            </button>
          </Tooltip>
        </div>
      </header>

      <div class="aa-log-filters">
        <label>
          <span>{t("agentActivity.log.agent")}</span>
          <select
            value={selectedAgent ?? ""}
            onChange={(event) => onSelectedAgentChange(event.currentTarget.value || null)}
          >
            <option value="">{t("agentActivity.log.allAgents")}</option>
            {agents.map((agent) => <option key={agent} value={agent}>{agent}</option>)}
          </select>
        </label>
        <label>
          <span>{t("agentActivity.log.find")}</span>
          <input
            type="search"
            value={query}
            placeholder={t("agentActivity.log.searchPlaceholder")}
            onInput={(event) => onQueryChange(event.currentTarget.value)}
          />
        </label>
      </div>

      <div
        ref={logRef}
        class="aa-log-scroll"
        role="log"
        aria-live="off"
        aria-label={t("agentActivity.log.title")}
        onScroll={(event) => {
          if (tailing && !isNearLogBottom(
            event.currentTarget.scrollHeight,
            event.currentTarget.scrollTop,
            event.currentTarget.clientHeight,
          )) setTailing(false);
        }}
      >
        <div
          class="aa-log-grid"
          role="table"
          aria-label={t("agentActivity.log.title")}
          aria-rowcount={Math.max(visibleRows.length, 1) + 1}
          aria-colcount={visibleColumns.length}
          style={`--aa-log-template:${template}`}
        >
          <div class="aa-log-header" role="row">
            {COLUMN_ORDER.filter((column) => visibleColumns.includes(column)).map((column) => (
              <span key={column} role="columnheader" data-column={column}>
                {t(`agentActivity.log.column.${column}`)}
              </span>
            ))}
          </div>
          {visibleRows.length === 0 ? (
            <div class="aa-log-empty" role="row">
              <span role="cell">{t("agentActivity.log.noRows")}</span>
            </div>
          ) : visibleRows.map((row) => (
            <AgentLogRowView key={row.id} row={row} visibleColumns={visibleColumns} />
          ))}
        </div>
      </div>
      <footer class="aa-log-footer">
        <span>{t("agentActivity.log.retention", { count: AGENT_LOG_LIMIT })}</span>
        <a href={routeHref("audit")}>{t("agentActivity.log.openAudit")}</a>
      </footer>
    </section>
  );
}

function AgentLogRowView({
  row,
  visibleColumns,
}: {
  readonly row: AgentLogRow;
  readonly visibleColumns: readonly AgentLogColumn[];
}) {
  return (
    <div class={`aa-log-row kind-${row.kind}`} role="row">
      {visibleColumns.includes("time") ? (
        <Tooltip content={row.timestampValid ? undefined : row.timestamp}>
          <time
            role="cell"
            data-column="time"
            dateTime={row.timestampValid ? row.timestamp : undefined}
            aria-invalid={row.timestampValid ? undefined : "true"}
          >
            {formatConsoleTime(row.timestamp)}
          </time>
        </Tooltip>
      ) : null}
      {visibleColumns.includes("route") ? (
        <span role="cell" data-column="route" class="aa-log-route">
          {row.route.join(" -> ")}
        </span>
      ) : null}
      {visibleColumns.includes("type") ? (
        <span role="cell" data-column="type" class="aa-log-kind">
          {kindLabel(row.kind)}
        </span>
      ) : null}
      {visibleColumns.includes("detail") ? (
        <span role="cell" data-column="detail" class="aa-log-detail">
          <strong>{row.detail}</strong>
          <small>{row.context ? `${row.context} - ` : ""}{sourceLabel(row.source)}</small>
        </span>
      ) : null}
      {visibleColumns.includes("correlation") ? (
        <span role="cell" data-column="correlation" class="aa-log-correlation">
          {row.correlationId ? (
            <a href={routeHref("trace", { params: { correlation: row.correlationId } })}>
              {row.correlationId}
            </a>
          ) : <code>{row.eventId ?? t("agentActivity.live.noCorrelation")}</code>}
        </span>
      ) : null}
    </div>
  );
}

function kindLabel(kind: AgentLogRow["kind"]): string {
  if (kind === "incident") return t("agentActivity.live.incident");
  if (kind === "handoff") return t("agentActivity.live.handoff");
  if (kind === "state") return t("agentActivity.live.state");
  if (kind === "activity") return t("agentActivity.log.activity");
  return t(`agentActivity.filter.${kind}`);
}

function sourceLabel(source: AgentLogSource): string {
  if (source === "audit-operational") return t("agentActivity.detail.operationalAudit");
  if (source === "audit-sample") return t("agentActivity.detail.localSample");
  return observationSourceLabel(source);
}
