import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "preact/hooks";
import {
  defaultRangeExtractor,
  elementScroll,
  observeElementOffset,
  observeElementRect,
  Virtualizer,
} from "@tanstack/virtual-core";
import { Tooltip } from "../components/tooltip";
import type { AuditItem } from "../types";
import type { OperationalActivityKind } from "../agent-operational-activity";
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
  AGENT_LOG_ROW_HIGHLIGHT_MS,
  appendedAgentLogRowIds,
  agentLogFullscreenAction,
  buildAgentLogRows,
  DEFAULT_AGENT_LOG_COLUMNS,
  filterAgentLogRows,
  fallbackAfterFullscreenFailure,
  hasAuditTrace,
  isNearLogTop,
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
  time: "156px",
  route: "150px",
  type: "96px",
  detail: "minmax(300px, 1fr)",
  correlation: "190px",
};
type OperationalLane = "all" | OperationalActivityKind;
const OPERATIONAL_LANES: readonly OperationalLane[] = [
  "all",
  "inventory.scan",
  "current-state.read",
  "inventory.ontology-projection",
  "observation",
  "assurance-twin.posture",
];


interface Props {
  readonly events: readonly LiveAgentActivityEvent[];
  readonly auditItems: readonly AuditItem[];
  readonly selectedAgent: string | null;
  readonly query: string;
  readonly streamStatus: AgentStreamStatus;
  readonly streamSource: ObservationSource;
  readonly lastEventAt: string | null;
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
  lastEventAt,
  onSelectedAgentChange,
  onQueryChange,
}: Props) {
  const [visibleColumns, setVisibleColumns] = useState<readonly AgentLogColumn[]>(
    DEFAULT_AGENT_LOG_COLUMNS,
  );
  const [heldRows, setHeldRows] = useState<readonly AgentLogRow[] | null>(null);
  const [focusedIndex, setFocusedIndex] = useState<number | null>(null);
  const [headerHeight, setHeaderHeight] = useState(32);
  const [, renderWindow] = useState(0);
  const [columnsOpen, setColumnsOpen] = useState(false);
  const [nativeFullscreen, setNativeFullscreen] = useState(false);
  const [fallbackFullscreen, setFallbackFullscreen] = useState(false);
  const [operationalLane, setOperationalLane] = useState<OperationalLane>("all");
  const panelRef = useRef<HTMLElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const headerRef = useRef<HTMLDivElement>(null);
  const columnsRef = useRef<HTMLDivElement>(null);
  const fullscreenButtonRef = useRef<HTMLButtonElement>(null);
  const fallbackFullscreenRef = useRef(false);
  const nativeFullscreenRef = useRef(false);
  const knownRowIdsRef = useRef<ReadonlySet<string> | null>(null);
  const highlightTimersRef = useRef<Set<number>>(new Set());
  const [highlightedRowIds, setHighlightedRowIds] = useState<ReadonlySet<string>>(new Set());
  const rows = useMemo(() => buildAgentLogRows(events, auditItems), [events, auditItems]);
  const filteredRows = useMemo(
    () => filterAgentLogRows(rows, selectedAgent, query, operationalLane),
    [rows, selectedAgent, query, operationalLane],
  );
  const visibleRows = heldRows ?? filteredRows;
  const heldRowIds = useMemo(
    () => heldRows === null ? null : new Set(heldRows.map((row) => row.id)),
    [heldRows],
  );
  const pendingCount = useMemo(
    () => heldRowIds === null ? 0 : filteredRows.filter((row) => !heldRowIds.has(row.id)).length,
    [filteredRows, heldRowIds],
  );
  const getItemKey = useMemo(() => (index: number) => visibleRows[index]!.id, [visibleRows]);
  const rangeExtractor = useMemo(() => (range: Parameters<typeof defaultRangeExtractor>[0]) => {
    const indexes = new Set(defaultRangeExtractor(range));
    if (focusedIndex !== null) {
      for (let index = focusedIndex - 1; index <= focusedIndex + 1; index += 1) {
        if (index >= 0 && index < range.count) indexes.add(index);
      }
    }
    return [...indexes].sort((left, right) => left - right);
  }, [focusedIndex]);
  const [virtualizer] = useState(() => new Virtualizer<HTMLDivElement, HTMLDivElement>({
    count: 0,
    getScrollElement: () => logRef.current,
    estimateSize: () => 64,
    observeElementRect,
    observeElementOffset,
    scrollToFn: elementScroll,
    overscan: 6,
    onChange: () => renderWindow((version) => version + 1),
  }));
  virtualizer.setOptions({
    ...virtualizer.options,
    count: visibleRows.length,
    getItemKey,
    rangeExtractor,
    paddingStart: headerHeight,
  });
  virtualizer.shouldAdjustScrollPositionOnItemSizeChange = () => heldRows !== null;
  useLayoutEffect(() => virtualizer._didMount(), [virtualizer]);
  useLayoutEffect(() => virtualizer._willUpdate());
  useLayoutEffect(() => {
    const retainedIds = new Set(visibleRows.map((row) => row.id));
    for (const key of virtualizer.itemSizeCache.keys()) {
      if (!retainedIds.has(String(key))) virtualizer.itemSizeCache.delete(key);
    }
    if (heldRows === null && logRef.current?.scrollTop !== 0) {
      virtualizer.scrollToOffset(0);
    }
  }, [visibleRows, heldRows]);
  useLayoutEffect(() => {
    const header = headerRef.current;
    if (header === null) return;
    const observer = new ResizeObserver(() => setHeaderHeight(header.getBoundingClientRect().height));
    observer.observe(header);
    return () => observer.disconnect();
  }, []);
  useLayoutEffect(() => {
    setHeldRows(null);
    setFocusedIndex(null);
    virtualizer.scrollToOffset(0);
  }, [selectedAgent, query, operationalLane]);
  useLayoutEffect(() => virtualizer.measure(), [visibleColumns]);
  const operationalLaneCounts = useMemo(() => Object.fromEntries(
    OPERATIONAL_LANES.map((lane) => [
      lane,
      lane === "all" ? rows.length : rows.filter((row) => row.operationalKind === lane).length,
    ]),
  ) as Record<OperationalLane, number>, [rows]);
  const agents = useMemo(() => {
    const names = new Set<string>();
    rows.forEach((row) => row.route.forEach((agent) => names.add(agent)));
    if (selectedAgent !== null) names.add(selectedAgent);
    return [...names].sort((left, right) => left.localeCompare(right));
  }, [rows, selectedAgent]);
  const fullscreen = nativeFullscreen || fallbackFullscreen;
  const clearHighlightedRows = (rowIds: readonly string[]): void => {
    setHighlightedRowIds((current) => {
      if (!rowIds.some((id) => current.has(id))) return current;
      const next = new Set(current);
      rowIds.forEach((id) => next.delete(id));
      return next;
    });
  };

  useEffect(() => {
    const appendedIds = appendedAgentLogRowIds(knownRowIdsRef.current, visibleRows);
    knownRowIdsRef.current = new Set(rows.map((row) => row.id));
    if (appendedIds.length === 0) return;

    setHighlightedRowIds((current) => new Set([...current, ...appendedIds]));
    const timer = window.setTimeout(() => {
      highlightTimersRef.current.delete(timer);
      clearHighlightedRows(appendedIds);
    }, AGENT_LOG_ROW_HIGHLIGHT_MS);
    highlightTimersRef.current.add(timer);
  }, [visibleRows]);

  useEffect(() => () => {
    highlightTimersRef.current.forEach((timer) => window.clearTimeout(timer));
    highlightTimersRef.current.clear();
  }, []);

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
            {lastEventAt ? (
              <> - {t("agentActivity.log.lastObserved")} <time dateTime={lastEventAt}>{formatConsoleTime(lastEventAt, undefined, "-", "milliseconds")}</time></>
            ) : null}
          </span>
          <h3 id="aa-live-journal-title">{t("agentActivity.log.title")}</h3>
        </div>
        <div class="aa-log-actions">
          <span class="aa-log-count" aria-live="polite">
            {t("agentActivity.log.rows", { count: visibleRows.length })}
          </span>
          {pendingCount > 0 ? (
            <button
              type="button"
              class="aa-log-control aa-log-new-events"
              onClick={() => {
                setHeldRows(null);
                setFocusedIndex(null);
                virtualizer.scrollToOffset(0);
                logRef.current?.focus({ preventScroll: true });
              }}
            >
              <span aria-hidden="true">↑</span>
              {t("agentActivity.log.newEvents", { count: pendingCount })}
            </button>
          ) : null}
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
              ref={fullscreenButtonRef}
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

      <div class="aa-log-lanes" role="group" aria-label={t("agentActivity.log.lanes")}>
        {OPERATIONAL_LANES.map((lane) => (
          <button
            key={lane}
            type="button"
            aria-pressed={operationalLane === lane}
            onClick={() => setOperationalLane(lane)}
          >
            <span>{t(`agentActivity.log.lane.${lane === "all" ? "all" : lane}`)}</span>
            <small>{operationalLaneCounts[lane]}</small>
          </button>
        ))}
      </div>

      <div
        ref={logRef}
        class="aa-log-scroll"
        role="log"
        tabIndex={0}
        aria-live="off"
        aria-label={t("agentActivity.log.title")}
        onScroll={(event) => {
          if (isNearLogTop(event.currentTarget.scrollTop)) {
            if (focusedIndex === null) setHeldRows(null);
          } else {
            setHeldRows((current) => current ?? filteredRows);
          }
        }}
        onFocusCapture={(event) => {
          const row = (event.target as HTMLElement).closest<HTMLElement>("[data-log-index]");
          if (row) {
            setHeldRows((current) => current ?? filteredRows);
            setFocusedIndex(Number(row.dataset.logIndex));
          }
        }}
        onBlurCapture={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
            setFocusedIndex(null);
            if (isNearLogTop(event.currentTarget.scrollTop)) setHeldRows(null);
          }
        }}
      >
        <div
          class="aa-log-grid"
          role="table"
          aria-label={t("agentActivity.log.title")}
          aria-rowcount={Math.max(visibleRows.length, 1) + 1}
          aria-colcount={visibleColumns.length}
          style={`--aa-log-template:${template};${visibleRows.length > 0 ? `height:${virtualizer.getTotalSize()}px` : ""}`}
        >
          <div ref={headerRef} class="aa-log-header" role="row" aria-rowindex={1}>
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
          ) : virtualizer.getVirtualItems().map((item) => (
            <AgentLogRowView
              key={item.key}
              row={visibleRows[item.index]!}
              index={item.index}
              offset={item.start}
              measureElement={virtualizer.measureElement}
              visibleColumns={visibleColumns}
              highlighted={highlightedRowIds.has(visibleRows[item.index]!.id)}
              onHighlightEnd={() => clearHighlightedRows([visibleRows[item.index]!.id])}
            />
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
  index,
  offset,
  measureElement,
  visibleColumns,
  highlighted,
  onHighlightEnd,
}: {
  readonly row: AgentLogRow;
  readonly index: number;
  readonly offset: number;
  readonly measureElement: (element: HTMLDivElement | null) => void;
  readonly visibleColumns: readonly AgentLogColumn[];
  readonly highlighted: boolean;
  readonly onHighlightEnd: () => void;
}) {
  return (
    <div
      ref={measureElement}
      class={`aa-log-row kind-${row.kind}${highlighted ? " is-new-activity" : ""}`}
      data-index={index}
      data-log-index={index}
      data-log-id={row.id}
      style={`transform:translateY(${offset}px)`}
      data-operational-kind={row.operationalKind ?? undefined}
      data-activity-id={row.activityId ?? undefined}
      role="row"
      aria-rowindex={index + 2}
      onAnimationEnd={(event) => {
        if (event.animationName === "aa-log-row-highlight") onHighlightEnd();
      }}
    >
      {visibleColumns.includes("time") ? (
        <Tooltip content={row.timestamp}>
          <time
            role="cell"
            data-column="time"
            dateTime={row.timestampValid ? row.timestamp : undefined}
            aria-invalid={row.timestampValid ? undefined : "true"}
          >
            {formatConsoleTime(row.timestamp, undefined, "-", "milliseconds")}
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
          {kindLabel(row)}
        </span>
      ) : null}
      {visibleColumns.includes("detail") ? (
        <span role="cell" data-column="detail" class="aa-log-detail">
          <strong>
            {row.resourceLabel ? (
              <>
                <Tooltip content={row.resourceRef ?? undefined}>
                  <code>{row.resourceLabel}</code>
                </Tooltip>
                {` - ${row.detail}`}
              </>
            ) : row.detail}
          </strong>
          <small>
            {row.observationDomain
              ? `${t(`agentActivity.observationDomain.${row.observationDomain}`)} - `
              : ""}
            {row.context ? `${row.context} - ` : ""}{sourceLabel(row.source)}
          </small>
        </span>
      ) : null}
      {visibleColumns.includes("correlation") ? (
        <span role="cell" data-column="correlation" class="aa-log-correlation">
          {row.correlationId ? (
            hasAuditTrace(row) ? (
              <a href={routeHref("trace", { params: { correlation: row.correlationId } })}>
                {row.correlationId}
              </a>
            ) : <code>{row.correlationId}</code>
          ) : <code>{row.eventId ?? t("agentActivity.live.noCorrelation")}</code>}
        </span>
      ) : null}
    </div>
  );
}

function kindLabel(row: AgentLogRow): string {
  if (row.operationalKind !== null) return t(`agentActivity.log.lane.${row.operationalKind}`);
  if (row.kind === "incident") return t("agentActivity.live.incident");
  if (row.kind === "handoff") return t("agentActivity.live.handoff");
  if (row.kind === "state") return t("agentActivity.live.state");
  if (row.kind === "activity") return t("agentActivity.log.activity");
  return t(`agentActivity.filter.${row.kind}`);
}

function sourceLabel(source: AgentLogSource): string {
  if (source === "audit-operational") return t("agentActivity.detail.operationalAudit");
  if (source === "audit-sample") return t("agentActivity.detail.localSample");
  return observationSourceLabel(source);
}
