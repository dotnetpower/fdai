import { useEffect, useRef, useState } from "preact/hooks";

import {
  decodeAgentOperationalActivity,
  type AgentOperationalActivityMessage,
} from "../agent-operational-activity";
import {
  mergeObservationSource,
  normalizeObservationSource,
  type FrameSource,
  type ObservationSource,
} from "./observation-source";
import {
  authenticatedSseHeaders,
  consumeSseFrames,
  isTransientSseStatus,
  sseReconnectDelay,
  useSharedAuthenticatedSse,
  type SseFrame,
} from "./sse-client";

export type LiveStageName =
  | "ingest"
  | "route"
  | "verify"
  | "gate"
  | "execute"
  | "audit";

export type LiveStagePhase = "begin" | "progress" | "done" | "failed";

export interface LiveStageEvent {
  readonly event_id: string;
  readonly correlation_id: string;
  readonly stage: LiveStageName;
  readonly phase: LiveStagePhase;
  readonly source?: FrameSource;
  readonly ts: string;
  readonly detail?: Record<string, unknown>;
  readonly error?: string;
}

export interface LiveSourceEvent {
  readonly status: "ready";
  readonly source: FrameSource;
  readonly ts: string;
}

export interface LiveActivityStatusEvent {
  readonly type: "live.activity-status";
  readonly status: "ready" | "unavailable";
  readonly reason: "durable_projection_unavailable" | null;
  readonly ts: string;
}

export type LiveConnectionStatus =
  | "idle"
  | "connecting"
  | "open"
  | "closed"
  | "unsupported";

export interface UseLiveStreamOptions {
  readonly url: string;
  readonly enabled?: boolean;
  readonly pauseWhenHidden?: boolean;
  readonly retryAuthenticationFailures?: boolean;
  readonly onEvent: (event: LiveStageEvent) => void;
  readonly onActivity?: (event: AgentOperationalActivityMessage) => void;
  readonly onActivityStatus?: (event: LiveActivityStatusEvent) => void;
  readonly onGap?: (droppedBefore: number) => void;
  readonly onCursorReset?: () => void;
  readonly onStatus?: (status: LiveConnectionStatus) => void;
  readonly getAuthorizationHeader?: () => Promise<string | null>;
}

export interface UseLiveStreamResult {
  readonly status: LiveConnectionStatus;
  readonly source: ObservationSource;
  readonly lastSignalAt: number | null;
  readonly lastError: string | null;
}

const LIVE_STAGES: ReadonlySet<string> = new Set([
  "ingest",
  "route",
  "verify",
  "gate",
  "execute",
  "audit",
]);
const LIVE_PHASES: ReadonlySet<string> = new Set([
  "begin",
  "progress",
  "done",
  "failed",
]);
const LIVE_SHARED_REPLAY_CAPACITY = 1_024;
export const LIVE_SOURCE_FRESHNESS_MS = 15_000;

export function decodeLiveStageEvent(data: string): LiveStageEvent | null {
  let value: unknown;
  try {
    value = JSON.parse(data);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  const event = value as Record<string, unknown>;
  if (
    typeof event.event_id !== "string" ||
    typeof event.correlation_id !== "string" ||
    typeof event.stage !== "string" ||
    !LIVE_STAGES.has(event.stage) ||
    typeof event.phase !== "string" ||
    !LIVE_PHASES.has(event.phase) ||
    typeof event.ts !== "string" ||
    !(
      event.detail === undefined ||
      (
        typeof event.detail === "object" &&
        event.detail !== null &&
        !Array.isArray(event.detail)
      )
    ) ||
    !(event.error === undefined || typeof event.error === "string")
  ) {
    return null;
  }
  return {
    ...event,
    source: normalizeObservationSource(event.source),
  } as unknown as LiveStageEvent;
}

export function decodeLiveSourceEvent(data: string): LiveSourceEvent | null {
  let value: unknown;
  try {
    value = JSON.parse(data);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  const event = value as Record<string, unknown>;
  const source = normalizeObservationSource(event.source);
  if (
    event.status !== "ready" ||
    source === "unknown" ||
    typeof event.ts !== "string"
  ) {
    return null;
  }
  return { status: "ready", source, ts: event.ts };
}

export function decodeLiveActivityStatusEvent(
  data: string,
): LiveActivityStatusEvent | null {
  let value: unknown;
  try {
    value = JSON.parse(data);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  const status = value as Record<string, unknown>;
  if (
    status.type !== "live.activity-status" ||
    (status.status !== "ready" && status.status !== "unavailable") ||
    !(
      status.reason === null ||
      status.reason === "durable_projection_unavailable"
    ) ||
    typeof status.ts !== "string" ||
    Number.isNaN(Date.parse(status.ts)) ||
    (status.status === "ready" && status.reason !== null) ||
    (
      status.status === "unavailable" &&
      status.reason !== "durable_projection_unavailable"
    )
  ) {
    return null;
  }
  return {
    type: "live.activity-status",
    status: status.status,
    reason: status.reason,
    ts: status.ts,
  };
}

export function isLiveSourceObservationFresh(
  timestamp: string,
  now = Date.now(),
): boolean {
  const observedAt = Date.parse(timestamp);
  return Number.isFinite(observedAt) &&
    observedAt <= now + LIVE_SOURCE_FRESHNESS_MS &&
    observedAt >= now - LIVE_SOURCE_FRESHNESS_MS;
}

export function liveStreamHeaders(authorization: string | null): Headers {
  return authenticatedSseHeaders(authorization);
}

export function liveReconnectDelay(attempt: number): number {
  return sseReconnectDelay(attempt);
}

export function isPermanentLiveStreamFailure(status: number): boolean {
  return status === 401 || status === 403;
}

export function shouldStopLiveStream(
  status: number,
  retryAuthenticationFailures: boolean,
): boolean {
  return isPermanentLiveStreamFailure(status) &&
    !retryAuthenticationFailures;
}

export function shouldPauseLiveStream(
  documentHidden: boolean,
  pauseWhenHidden: boolean,
): boolean {
  return documentHidden && pauseWhenHidden;
}

export async function consumeLiveSse(
  response: Response,
  onEvent: (event: LiveStageEvent) => void,
  onSource?: (event: LiveSourceEvent) => void,
  onActivity?: (event: AgentOperationalActivityMessage) => void,
  onGap?: (droppedBefore: number) => void,
  onActivityStatus?: (event: LiveActivityStatusEvent) => void,
  onCursorReset?: () => void,
): Promise<void> {
  await consumeSseFrames(response, (frame) => {
    consumeLiveFrame(
      frame,
      onEvent,
      (event) => onSource?.(event),
      onActivity,
      onGap,
      onActivityStatus,
      onCursorReset,
      () => undefined,
    );
  });
}

export function useLiveStream(
  options: UseLiveStreamOptions,
): UseLiveStreamResult {
  const [source, setSource] = useState<ObservationSource>("unknown");
  const [lastSignalAt, setLastSignalAt] = useState<number | null>(null);
  const sourceExpiryTimerRef = useRef<number | null>(null);
  const lastSignalValueRef = useRef<number | null>(null);
  const lastSignalFlushTimerRef = useRef<number | null>(null);
  const {
    url,
    getAuthorizationHeader = noAuthorization,
    enabled = true,
    pauseWhenHidden = true,
    retryAuthenticationFailures = false,
  } = options;

  const clearSourceObservation = (): void => {
    if (sourceExpiryTimerRef.current !== null) {
      window.clearTimeout(sourceExpiryTimerRef.current);
    }
    sourceExpiryTimerRef.current = null;
    setSource("unknown");
  };
  const observeSource = (incoming: FrameSource): void => {
    if (incoming === "unknown") return;
    setSource((current) => mergeObservationSource(current, incoming));
    if (sourceExpiryTimerRef.current !== null) {
      window.clearTimeout(sourceExpiryTimerRef.current);
    }
    sourceExpiryTimerRef.current = window.setTimeout(() => {
      sourceExpiryTimerRef.current = null;
      setSource("unknown");
    }, LIVE_SOURCE_FRESHNESS_MS);
  };
  const observeSignal = (): void => {
    lastSignalValueRef.current = Date.now();
    if (lastSignalFlushTimerRef.current !== null) return;
    lastSignalFlushTimerRef.current = window.setTimeout(() => {
      lastSignalFlushTimerRef.current = null;
      setLastSignalAt(lastSignalValueRef.current);
    }, 250);
  };
  const connection = useSharedAuthenticatedSse("live", {
    url,
    enabled,
    pauseWhenHidden,
    resumeFromLastEventId: true,
    getAuthorizationHeader,
    sharedFrameKey: liveSharedFrameKey,
    sharedReplayCapacity: LIVE_SHARED_REPLAY_CAPACITY,
    resetCursorOnFrame: isLiveEpochGapFrame,
    shouldRetryStatus: retryAuthenticationFailures
      ? retryLiveIncludingAuthentication
      : isTransientSseStatus,
    onStatus: (next) => {
      if (next === "closed" || next === "idle") clearSourceObservation();
      options.onStatus?.(next);
    },
    onFrame: (frame) => {
      const accepted = consumeLiveFrame(
        frame,
        options.onEvent,
        (event) => {
          if (isLiveSourceObservationFresh(event.ts)) {
            observeSource(event.source);
          }
        },
        options.onActivity,
        options.onGap,
        options.onActivityStatus,
        options.onCursorReset,
        (incoming, timestamp) => {
          if (isLiveSourceObservationFresh(timestamp)) observeSource(incoming);
        },
      );
      if (accepted) observeSignal();
    },
  });

  useEffect(() => {
    if (!enabled) {
      lastSignalValueRef.current = null;
      if (lastSignalFlushTimerRef.current !== null) {
        window.clearTimeout(lastSignalFlushTimerRef.current);
        lastSignalFlushTimerRef.current = null;
      }
      setLastSignalAt(null);
    }
  }, [enabled]);

  useEffect(() => () => {
    if (sourceExpiryTimerRef.current !== null) {
      window.clearTimeout(sourceExpiryTimerRef.current);
    }
    if (lastSignalFlushTimerRef.current !== null) {
      window.clearTimeout(lastSignalFlushTimerRef.current);
    }
  }, []);

  return {
    status: connection.status,
    lastError: connection.lastError,
    source,
    lastSignalAt,
  };
}

function consumeLiveFrame(
  frame: SseFrame,
  onEvent: (event: LiveStageEvent) => void,
  onSource: (event: LiveSourceEvent) => void,
  onActivity: ((event: AgentOperationalActivityMessage) => void) | undefined,
  onGap: ((droppedBefore: number) => void) | undefined,
  onActivityStatus: ((event: LiveActivityStatusEvent) => void) | undefined,
  onCursorReset: (() => void) | undefined,
  observeStageSource: (source: FrameSource, timestamp: string) => void,
): boolean {
  if (frame.droppedBefore > 0) onGap?.(frame.droppedBefore);
  if (frame.event === "hello") return false;
  if (frame.event === "gap") {
    const reset = decodeEpochGap(frame.data);
    if (reset) onCursorReset?.();
    return false;
  }
  if (frame.event === "source") {
    const source = decodeLiveSourceEvent(frame.data);
    if (source) onSource(source);
    return source !== null;
  }
  if (frame.event === "activity" || frame.event === "activity-snapshot") {
    const activity = decodeAgentOperationalActivityData(frame.data);
    if (activity) onActivity?.(activity);
    return activity !== null;
  }
  if (frame.event === "activity-status-snapshot") {
    const status = decodeLiveActivityStatusEvent(frame.data);
    if (status) onActivityStatus?.(status);
    return status !== null;
  }
  const event = decodeLiveStageEvent(frame.data);
  if (!event) return false;
  observeStageSource(
    normalizeObservationSource(event.source),
    event.ts,
  );
  onEvent(event);
  return true;
}

function decodeAgentOperationalActivityData(
  data: string,
): AgentOperationalActivityMessage | null {
  try {
    return decodeAgentOperationalActivity(JSON.parse(data));
  } catch {
    return null;
  }
}

function decodeEpochGap(data: string): boolean {
  try {
    const value: unknown = JSON.parse(data);
    return typeof value === "object" &&
      value !== null &&
      !Array.isArray(value) &&
      (value as Record<string, unknown>).reason === "stream_epoch_changed";
  } catch {
    return false;
  }
}

export function isLiveEpochGapFrame(frame: SseFrame): boolean {
  return frame.event === "gap" && decodeEpochGap(frame.data);
}

function liveSharedFrameKey(frame: SseFrame): string | null {
  if (frame.event === "source") return "source";
  if (frame.event === "gap" && decodeEpochGap(frame.data)) {
    return "cursor-gap";
  }
  if (frame.event === "activity-status-snapshot") return "activity-status";
  if (frame.event === "activity" || frame.event === "activity-snapshot") {
    const activity = decodeAgentOperationalActivityData(frame.data);
    return activity === null
      ? null
      : `activity:${activity.activity_instance_id ?? activity.activity_id}`;
  }

  const event = decodeLiveStageEvent(frame.data);
  if (event === null) return null;
  return frame.id === null
    ? `stage:${event.event_id}:${event.stage}:${event.phase}`
    : `delta:${frame.id}`;
}

function retryLiveIncludingAuthentication(status: number): boolean {
  return status === 401 || status === 403 || isTransientSseStatus(status);
}

async function noAuthorization(): Promise<null> {
  return null;
}
