import { useEffect, useMemo, useReducer, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { loadConfig } from "../config";
import type { LiveStageEvent } from "../hooks/use-live-stream";
import { useLiveStream } from "../hooks/use-live-stream";
import { currentRoute, replaceRouteState, routeHref } from "../router";
import {
  liveSelectionState,
  makeInitialState,
  reducer,
  type FilterKind,
} from "./live.model";
import {
  LivePanels,
  type LiveRouteUpdate,
  type LiveViewMode,
} from "./live.panels";
import { useLiveViewModel } from "./live.view-model";

export { liveTraceHref } from "./live.ticker";

interface Props {
  readonly client: OperatorApiClient;
}

export const LIVE_BACKLOG_CAP = 1_000;
export const LIVE_FLUSH_CAP = 200;

export function appendLiveBacklog(
  backlog: readonly LiveStageEvent[],
  event: LiveStageEvent,
  cap = LIVE_BACKLOG_CAP,
): { readonly backlog: readonly LiveStageEvent[]; readonly dropped: number } {
  if (cap <= 0) return { backlog: [], dropped: 1 };
  const appended = [...backlog, event];
  const dropped = Math.max(0, appended.length - cap);
  return { backlog: dropped > 0 ? appended.slice(dropped) : appended, dropped };
}

export function drainLiveBacklog(
  backlog: readonly LiveStageEvent[],
  cap = LIVE_FLUSH_CAP,
): { readonly drained: readonly LiveStageEvent[]; readonly remaining: readonly LiveStageEvent[] } {
  const count = Math.max(0, cap);
  return { drained: backlog.slice(0, count), remaining: backlog.slice(count) };
}

export function LiveRoute({ client }: Props) {
  const initialRoute = currentRoute();
  const [state, dispatch] = useReducer(reducer, undefined, makeInitialState);
  const [tickerPaused, setTickerPaused] = useState(false);
  const [tickerCollapsed, setTickerCollapsed] = useState(false);
  const [viewMode, setViewMode] = useState<LiveViewMode>(
    initialRoute.search.get("view") === "flow" ? "flow" : "queue",
  );
  const [frozenObserved, setFrozenObserved] = useState(0);
  const [droppedFrames, setDroppedFrames] = useState(0);
  const pausedSnapshotRef = useRef<readonly LiveStageEvent[]>([]);
  const pausedRef = useRef(false);
  const frozenObservedRef = useRef(0);
  const pendingEventsRef = useRef<LiveStageEvent[]>([]);

  const updateRoute = ({
    eventId = state.selectedEventId,
    filter = state.filter,
    view = viewMode,
  }: LiveRouteUpdate): void => {
    dispatch({ kind: "filter", value: filter });
    setViewMode(view);
    replaceRouteState(routeHref("live", {
      params: {
        event: eventId,
        filter: filter === "all" ? null : filter,
        view: view === "queue" ? null : view,
      },
    }));
  };

  const selectEvent = (eventId: string | null): void => {
    dispatch({ kind: "select", event_id: eventId });
    replaceRouteState(routeHref("live", {
      params: {
        event: eventId,
        filter: state.filter === "all" ? null : state.filter,
        view: viewMode === "queue" ? null : viewMode,
      },
    }));
  };

  useEffect(() => {
    const sync = () => {
      const route = currentRoute();
      const filter = route.search.get("filter");
      dispatch({
        kind: "filter",
        value: filter === "hil" || filter === "deny" || filter === "failed" || filter === "stuck"
          ? filter
          : "all",
      });
      dispatch({ kind: "select", event_id: route.search.get("event") });
      setViewMode(route.search.get("view") === "flow" ? "flow" : "queue");
    };
    sync();
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
    };
  }, []);

  const url = useMemo(() => {
    const config = loadConfig();
    const base = config.operatorApiBaseUrl || (typeof window !== "undefined" ? window.location.origin : "");
    return `${base.replace(/\/$/, "")}/live/stream`;
  }, []);

  const { status, lastError, source: streamSource } = useLiveStream({
    url,
    getAuthorizationHeader: client.authorizationHeader,
    onEvent: (event) => {
      const next = appendLiveBacklog(pendingEventsRef.current, event);
      pendingEventsRef.current = [...next.backlog];
      if (next.dropped > 0) setDroppedFrames((current) => current + next.dropped);
      if (pausedRef.current) {
        frozenObservedRef.current += 1;
      }
    },
  });

  useEffect(() => {
    const handle = window.setInterval(() => {
      if (pausedRef.current) {
        setFrozenObserved(frozenObservedRef.current);
        return;
      }
      const buffer = pendingEventsRef.current;
      if (buffer.length === 0) return;
      const { drained, remaining } = drainLiveBacklog(buffer);
      pendingEventsRef.current = [...remaining];
      dispatch({ kind: "batch", events: drained });
    }, 250);
    return () => {
      window.clearInterval(handle);
      pendingEventsRef.current = [];
    };
  }, []);

  useEffect(() => {
    const handle = window.setInterval(() => {
      if (pausedRef.current) return;
      dispatch({ kind: "tick", now: Date.now() });
    }, 250);
    return () => window.clearInterval(handle);
  }, []);

  const displayedTicker = tickerPaused ? pausedSnapshotRef.current : state.ticker;
  const togglePause = () => {
    if (tickerPaused) {
      pausedRef.current = false;
      setTickerPaused(false);
      pausedSnapshotRef.current = [];
    } else {
      pausedRef.current = true;
      frozenObservedRef.current = 0;
      setFrozenObserved(0);
      pausedSnapshotRef.current = state.ticker;
      setTickerPaused(true);
    }
  };
  const toggleCollapse = () => setTickerCollapsed((value) => !value);

  const selectedTile = state.selectedEventId
    ? state.tiles.find((tile) => tile?.event_id === state.selectedEventId) ?? null
    : null;
  const selectionState = liveSelectionState(
    state.selectedEventId,
    selectedTile,
    state.session_total,
  );
  const view = useLiveViewModel(state, status, selectedTile, droppedFrames);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || target?.isContentEditable) return;
      if (target?.closest('[role="dialog"]')) return;
      if (event.key === "Escape" && state.selectedEventId) {
        selectEvent(null);
        event.preventDefault();
        return;
      }
      if (event.key === "p" || event.key === "P") {
        togglePause();
        event.preventDefault();
        return;
      }
      const index = ["1", "2", "3", "4", "5"].indexOf(event.key);
      if (index >= 0) {
        const filters: readonly FilterKind[] = ["all", "hil", "deny", "failed", "stuck"];
        const value = filters[index];
        if (value !== undefined) {
          updateRoute({ filter: value });
          event.preventDefault();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [state.selectedEventId, state.filter, tickerPaused, state.session_total, state.ticker, viewMode]);

  return (
    <LivePanels
      state={state}
      view={view}
      status={status}
      lastError={lastError}
      streamSource={streamSource}
      tickerPaused={tickerPaused}
      tickerCollapsed={tickerCollapsed}
      frozenObserved={frozenObserved}
      droppedFrames={droppedFrames}
      displayedTicker={displayedTicker}
      viewMode={viewMode}
      selectionState={selectionState}
      selectedTile={selectedTile}
      togglePause={togglePause}
      toggleCollapse={toggleCollapse}
      updateRoute={updateRoute}
      selectEvent={selectEvent}
    />
  );
}
