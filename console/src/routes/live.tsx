import { useEffect, useMemo, useReducer, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { loadConfig } from "../config";
import type { ConsoleDataMode } from "../console-data-mode";
import type { AgentOperationalActivityMessage } from "../agent-operational-activity";
import type { LiveStageEvent } from "../hooks/use-live-stream";
import { useLiveStream } from "../hooks/use-live-stream";
import { currentRoute, replaceRouteState, routeHref } from "../router";
import {
  liveSelectionState,
  makeInitialState,
  POOL_SIZE,
  reducer,
  type FilterKind,
} from "./live.model";
import {
  LivePanels,
  type LiveRouteUpdate,
  type LiveViewMode,
} from "./live.panels";
import {
  LIVE_OBSERVATION_LIMIT,
  mergeLiveObservations,
  type LiveObservationLoadState,
} from "./live.observations";
import { useLiveViewModel } from "./live.view-model";
import {
  OPERATIONS_SAMPLE_LIVE_EVENTS,
  OPERATIONS_SAMPLE_LIVE_EVENTS_PER_LOOP,
  OPERATIONS_SAMPLE_LIVE_HISTORY_COUNT,
  OPERATIONS_SAMPLE_LIVE_LOOP_INTERVAL_MS,
  sampleLiveStageDelay,
  sampleLivePreviewEvents,
  OPERATIONS_SAMPLE_LIVE_VISIBLE_COUNT,
  sampleLiveObservations,
  sampleLiveEvents,
} from "./operations.sample";
import { useLiveCoverage } from "./live.coverage";
import {
  createLiveMetrics,
  LIVE_METRIC_WINDOW_MS,
  observeLiveControl,
  observeLiveSource,
  summarizeLiveMetrics,
} from "./live.metrics";
import "./live.css";

export { liveTraceHref } from "./live.ticker";

interface Props {
  readonly client: OperatorApiClient;
  readonly dataMode: ConsoleDataMode;
}

export const LIVE_BACKLOG_CAP = 1_000;
export const LIVE_FLUSH_CAP = 200;
const LIVE_FILTER_SHORTCUTS: readonly FilterKind[] = [
  "all",
  "control",
  "source",
  "hil",
  "deny",
  "failed",
  "stuck",
];

function liveFilter(value: string | null): FilterKind {
  if (
    value === "control" ||
    value === "source" ||
    value === "hil" ||
    value === "deny" ||
    value === "failed" ||
    value === "stuck"
  ) {
    return value;
  }
  return "all";
}

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

export function LiveRoute({ client, dataMode }: Props) {
  const initialRoute = currentRoute();
  const [state, dispatch] = useReducer(
    reducer,
    undefined,
    () => makeInitialState(
      dataMode === "sample" ? OPERATIONS_SAMPLE_LIVE_VISIBLE_COUNT : POOL_SIZE,
    ),
  );
  const [tickerPaused, setTickerPaused] = useState(false);
  const [sampleEpoch, setSampleEpoch] = useState(0);
  const metricsRef = useRef(createLiveMetrics());
  const metrics = useMemo(
    () => summarizeLiveMetrics(metricsRef.current, state.now),
    [state.now, sampleEpoch],
  );
  const [viewMode, setViewMode] = useState<LiveViewMode>(
    initialRoute.search.get("view") === "queue" ? "queue" : "flow",
  );
  const [frozenObserved, setFrozenObserved] = useState(0);
  const [droppedFrames, setDroppedFrames] = useState(0);
  const [cursorReset, setCursorReset] = useState(false);
  const [observations, setObservations] = useState<
    readonly AgentOperationalActivityMessage[]
  >([]);
  const [observationLoadState, setObservationLoadState] =
    useState<LiveObservationLoadState>("loading");
  const [observationError, setObservationError] = useState<string | null>(null);
  const [selectedObservationId, setSelectedObservationId] = useState<
    string | null
  >(dataMode === "live" ? initialRoute.search.get("activity") : null);
  const selectedObservationIdRef = useRef(selectedObservationId);
  const observationAvailabilityRef = useRef<"ready" | "unavailable" | null>(null);
  const pausedRef = useRef(false);
  const frozenObservedRef = useRef(0);
  const pendingEventsRef = useRef<LiveStageEvent[]>([]);
  const sampleCleanupRef = useRef<(() => void) | null>(null);
  const pendingObservationsRef = useRef<AgentOperationalActivityMessage[]>([]);
  const coverage = useLiveCoverage(client, dataMode);

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
        activity: eventId ? null : selectedObservationId,
        filter: filter === "all" ? null : filter,
        view: view === "flow" ? null : view,
        data: dataMode === "sample" ? "sample" : null,
      },
    }));
  };

  const selectEvent = (eventId: string | null): void => {
    dispatch({ kind: "select", event_id: eventId });
    selectedObservationIdRef.current = null;
    setSelectedObservationId(null);
    replaceRouteState(routeHref("live", {
      params: {
        event: eventId,
        activity: null,
        filter: state.filter === "all" ? null : state.filter,
        view: viewMode === "flow" ? null : viewMode,
        data: dataMode === "sample" ? "sample" : null,
      },
    }));
  };

  const selectObservation = (activityId: string | null): void => {
    dispatch({ kind: "select", event_id: null });
    selectedObservationIdRef.current = activityId;
    setSelectedObservationId(activityId);
    replaceRouteState(routeHref("live", {
      params: {
        event: null,
        activity: activityId,
        filter: state.filter === "all" ? null : state.filter,
        view: viewMode === "flow" ? null : viewMode,
        data: dataMode === "sample" ? "sample" : null,
      },
    }));
  };

  useEffect(() => {
    const sync = () => {
      const route = currentRoute();
      dispatch({
        kind: "filter",
        value: liveFilter(route.search.get("filter")),
      });
      const eventId = route.search.get("event");
      dispatch({ kind: "select", event_id: eventId });
      const activityId = dataMode === "live" && eventId === null
        ? route.search.get("activity")
        : null;
      selectedObservationIdRef.current = activityId;
      setSelectedObservationId(activityId);
      setViewMode(route.search.get("view") === "queue" ? "queue" : "flow");
    };
    sync();
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
    };
  }, [dataMode]);

  const url = useMemo(() => {
    const config = loadConfig();
    const base = config.operatorApiBaseUrl || (typeof window !== "undefined" ? window.location.origin : "");
    return `${base.replace(/\/$/, "")}/live/stream`;
  }, []);

  const stream = useLiveStream({
    url,
    enabled: dataMode === "live",
    getAuthorizationHeader: client.authorizationHeader,
    onEvent: (event) => {
      observeLiveControl(metricsRef.current, event, Date.now());
      const next = appendLiveBacklog(pendingEventsRef.current, event);
      pendingEventsRef.current = [...next.backlog];
      if (next.dropped > 0) setDroppedFrames((current) => current + next.dropped);
      if (pausedRef.current) {
        frozenObservedRef.current += 1;
      }
    },
    onActivity: (event) => {
      observeLiveSource(metricsRef.current, event, Date.now());
      observationAvailabilityRef.current = "ready";
      if (pausedRef.current) {
        pendingObservationsRef.current = [
          ...mergeLiveObservations(
            pendingObservationsRef.current,
            [event],
            LIVE_OBSERVATION_LIMIT,
          ),
        ];
        frozenObservedRef.current += 1;
        return;
      }
      setObservationLoadState("ready");
      setObservationError(null);
      setObservations((current) => mergeLiveObservations(
        current,
        [event],
        LIVE_OBSERVATION_LIMIT,
        selectedObservationIdRef.current,
      ));
    },
    onActivityStatus: (event) => {
      observationAvailabilityRef.current = event.status;
      setObservationLoadState(event.status);
      setObservationError(
        event.status === "unavailable" ? event.reason : null,
      );
    },
    onGap: (dropped) => {
      metricsRef.current.partialUntil = Date.now() + LIVE_METRIC_WINDOW_MS;
      setDroppedFrames((current) => current + dropped);
    },
    onCursorReset: () => {
      metricsRef.current.partialUntil = Date.now() + LIVE_METRIC_WINDOW_MS;
      setCursorReset(true);
    },
  });
  const status = dataMode === "sample" ? "open" : stream.status;
  const lastError = dataMode === "sample" ? null : stream.lastError;
  const streamSource = dataMode === "sample" ? "synthetic-dev" : stream.source;

  useEffect(() => {
    if (dataMode !== "live") {
      observationAvailabilityRef.current = null;
      const sampleObservations = sampleLiveObservations();
      sampleObservations.forEach((event) => observeLiveSource(metricsRef.current, event, Date.now()));
      setObservations(sampleObservations);
      setObservationLoadState("ready");
      setObservationError(null);
      return undefined;
    }
    if (stream.status === "connecting" || stream.status === "idle") {
      setObservationLoadState("loading");
      setObservationError(null);
    } else if (stream.status === "open") {
      setObservationLoadState(
        observationAvailabilityRef.current ?? "loading",
      );
    } else {
      setObservationLoadState("unavailable");
      setObservationError(stream.lastError);
    }
    return undefined;
  }, [dataMode, stream.lastError, stream.status, sampleEpoch]);

  useEffect(() => {
    if (dataMode !== "sample") return undefined;
    const sampleNow = Date.now();
    const lastSampleAt = Math.max(...OPERATIONS_SAMPLE_LIVE_EVENTS.map(event => Date.parse(event.ts)));
    OPERATIONS_SAMPLE_LIVE_EVENTS.forEach((event) => observeLiveControl(
      metricsRef.current,
      { ...event, ts: new Date(sampleNow - (lastSampleAt - Date.parse(event.ts)) / 100).toISOString() },
      sampleNow,
    ));
    dispatch({ kind: "batch", events: sampleLivePreviewEvents() });
    dispatch({ kind: "seed-rate", now: Date.now(), per_tier_per_second: 1 });
    let nextEvent = OPERATIONS_SAMPLE_LIVE_HISTORY_COUNT;
    const stageHandles = new Set<number>();
    const enqueue = (event: LiveStageEvent) => {
      observeLiveControl(metricsRef.current, event, Date.now());
      const next = appendLiveBacklog(pendingEventsRef.current, event);
      pendingEventsRef.current = [...next.backlog];
      if (next.dropped > 0) setDroppedFrames((current) => current + next.dropped);
      if (pausedRef.current) frozenObservedRef.current += 1;
    };
    const scheduleLoop = () => {
      const startedAt = Date.now();
      for (let eventOffset = 0; eventOffset < OPERATIONS_SAMPLE_LIVE_EVENTS_PER_LOOP; eventOffset += 1) {
        const events = sampleLiveEvents(nextEvent + eventOffset, 1);
        events.forEach((event, stageIndex) => {
          const delay = eventOffset * (OPERATIONS_SAMPLE_LIVE_LOOP_INTERVAL_MS / OPERATIONS_SAMPLE_LIVE_EVENTS_PER_LOOP)
            + sampleLiveStageDelay(nextEvent + eventOffset, stageIndex, events.length);
          const stageHandle = window.setTimeout(() => {
            stageHandles.delete(stageHandle);
            enqueue({ ...event, ts: new Date(startedAt + delay).toISOString() });
          }, delay);
          stageHandles.add(stageHandle);
        });
      }
      nextEvent += OPERATIONS_SAMPLE_LIVE_EVENTS_PER_LOOP;
    };
    scheduleLoop();
    const loopHandle = window.setInterval(
      scheduleLoop,
      OPERATIONS_SAMPLE_LIVE_LOOP_INTERVAL_MS,
    );
    const cleanup = () => {
      window.clearInterval(loopHandle);
      stageHandles.forEach((handle) => window.clearTimeout(handle));
    };
    sampleCleanupRef.current = cleanup;
    return cleanup;
  }, [dataMode, sampleEpoch]);

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

  const togglePause = () => {
    if (tickerPaused) {
      pausedRef.current = false;
      setObservations((current) =>
        mergeLiveObservations(
          current,
          pendingObservationsRef.current,
          LIVE_OBSERVATION_LIMIT,
          selectedObservationIdRef.current,
        ));
      pendingObservationsRef.current = [];
      setTickerPaused(false);
    } else {
      pausedRef.current = true;
      frozenObservedRef.current = 0;
      setFrozenObserved(0);
      setTickerPaused(true);
    }
  };

  const restartSample = () => {
    if (dataMode !== "sample") throw new Error("Sample replay is unavailable in Live mode");
    sampleCleanupRef.current?.();
    pendingEventsRef.current = [];
    pendingObservationsRef.current = [];
    metricsRef.current = createLiveMetrics();
    pausedRef.current = false;
    frozenObservedRef.current = 0;
    setTickerPaused(false);
    setFrozenObserved(0);
    setDroppedFrames(0);
    selectObservation(null);
    dispatch({ kind: "reset" });
    setSampleEpoch(epoch => epoch + 1);
  };

  const selectedTile = state.selectedEventId
    ? state.tiles.find((tile) => tile?.event_id === state.selectedEventId) ?? null
    : null;
  const selectedObservation = selectedObservationId
    ? observations.find(
      (item) =>
        (item.activity_instance_id ?? item.activity_id) ===
          selectedObservationId ||
        item.activity_id === selectedObservationId,
    ) ?? null
    : null;
  const selectionState = liveSelectionState(
    state.selectedEventId,
    selectedTile,
    state.session_total,
  );
  const view = useLiveViewModel(
    state,
    metrics,
    status,
    streamSource,
    selectedTile,
    droppedFrames,
    observations,
  );

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || target?.isContentEditable) return;
      if (target?.closest('[role="dialog"]:not(.live-workspace)')) return;
      if (
        event.key === "Escape" &&
        (state.selectedEventId || selectedObservationId)
      ) {
        if (selectedObservationId) selectObservation(null);
        else selectEvent(null);
        event.preventDefault();
        return;
      }
      if (event.key === "p" || event.key === "P") {
        togglePause();
        event.preventDefault();
        return;
      }
      const index = ["1", "2", "3", "4", "5", "6", "7"].indexOf(event.key);
      if (index >= 0) {
        const value = LIVE_FILTER_SHORTCUTS[index];
        if (value !== undefined) {
          updateRoute({ filter: value });
          event.preventDefault();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [
    state.selectedEventId,
    selectedObservationId,
    state.filter,
    tickerPaused,
    state.session_total,
    viewMode,
  ]);

  return (
    <LivePanels
      state={state}
      view={view}
      status={status}
      lastSignalAt={stream.lastSignalAt}
      lastError={lastError}
      streamSource={streamSource}
      tickerPaused={tickerPaused}
      restartSample={dataMode === "sample" ? restartSample : undefined}
      frozenObserved={frozenObserved}
      droppedFrames={droppedFrames}
      cursorReset={cursorReset}
      observations={observations}
      observationLoadState={observationLoadState}
      observationStreamStatus={status}
      observationStreamSource={streamSource}
      observationError={observationError}
      coverage={coverage}
      viewMode={viewMode}
      selectionState={selectionState}
      selectedTile={selectedTile}
      selectedObservationId={selectedObservationId}
      selectedObservation={selectedObservation}
      togglePause={togglePause}
      updateRoute={updateRoute}
      selectEvent={selectEvent}
      selectObservation={selectObservation}
    />
  );
}
