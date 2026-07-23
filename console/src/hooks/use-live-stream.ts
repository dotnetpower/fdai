/**
 * Live stage-event stream hook.
 *
 * Subscribes to the read-API's `GET /live/stream` SSE endpoint via
 * authenticated fetch streaming, honours the connection lifecycle (open / closed /
 * reconnecting), and hands raw {@link LiveStageEvent} records to a
 * consumer via a mutable ring buffer.
 *
 * The hook never issues privileged calls - it is a pure read consumer.
 * Reconnection uses bounded exponential backoff. Upstream today has no
 * replay (the audit page has full history), and the frontend keeps rendering
 * when reconnection lands.
 *
 * Visibility gating: while the page is hidden (backgrounded tab) the
 * hook closes the `EventSource` and reports `idle`. This stops a
 * background tab from hammering the server with EventSource's built-in
 * 3s reconnect loop when the backend is down or slow. The connection
 * is re-established when the page becomes visible again.
 */

import { useEffect, useRef, useState } from "preact/hooks";
import {
  mergeObservationSource,
  normalizeObservationSource,
  type FrameSource,
  type ObservationSource,
} from "./observation-source";
import { readSseChunk } from "./sse-reader";

/** Stage identifier - mirrors {@link fdai.shared.providers.stage_publisher.StageName}. */
export type LiveStageName =
  | "ingest"
  | "route"
  | "verify"
  | "gate"
  | "execute"
  | "audit";

/** Stage phase - mirrors {@link StagePhase}. */
export type LiveStagePhase = "begin" | "progress" | "done" | "failed";

/** One decoded stage frame from the SSE wire. */
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

/** Status of the underlying EventSource. */
export type LiveConnectionStatus =
  | "idle"
  | "connecting"
  | "open"
  | "closed"
  | "unsupported";

export interface UseLiveStreamOptions {
  /** Absolute or relative URL to the SSE endpoint. */
  readonly url: string;
  /** Do not connect until the owning feature is explicitly enabled. */
  readonly enabled?: boolean;
  /** Disconnect while hidden. Browser notifications set this to false. */
  readonly pauseWhenHidden?: boolean;
  /** Retry 401/403 responses so a later token acquisition can recover. */
  readonly retryAuthenticationFailures?: boolean;
  /** Called for every decoded stage event. */
  readonly onEvent: (event: LiveStageEvent) => void;
  /** Optional connection-status observer. */
  readonly onStatus?: (status: LiveConnectionStatus) => void;
  /** Acquire the current bearer header. Dev mode returns null. */
  readonly getAuthorizationHeader?: () => Promise<string | null>;
}

export interface UseLiveStreamResult {
  readonly status: LiveConnectionStatus;
  readonly source: ObservationSource;
  /** Best-effort last error the browser reported. */
  readonly lastError: string | null;
}

/**
 * Attach an `EventSource` to the SSE endpoint. Every decoded frame is
 * passed to `onEvent` (in a `useRef` so re-renders do not tear the
 * subscription). The hook cleans up on unmount.
 */
const LIVE_STAGES: ReadonlySet<string> = new Set(["ingest", "route", "verify", "gate", "execute", "audit"]);
const LIVE_PHASES: ReadonlySet<string> = new Set(["begin", "progress", "done", "failed"]);

export function decodeLiveStageEvent(data: string): LiveStageEvent | null {
  let value: unknown;
  try {
    value = JSON.parse(data);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const event = value as Record<string, unknown>;
  if (
    typeof event.event_id !== "string" || typeof event.correlation_id !== "string" ||
    typeof event.stage !== "string" || !LIVE_STAGES.has(event.stage) ||
    typeof event.phase !== "string" || !LIVE_PHASES.has(event.phase) ||
    typeof event.ts !== "string" ||
    !(event.detail === undefined || (typeof event.detail === "object" && event.detail !== null && !Array.isArray(event.detail))) ||
    !(event.error === undefined || typeof event.error === "string")
  ) return null;
  return { ...event, source: normalizeObservationSource(event.source) } as unknown as LiveStageEvent;
}

export function liveStreamHeaders(authorization: string | null): Headers {
  const headers = new Headers({ accept: "text/event-stream" });
  if (authorization) headers.set("authorization", authorization);
  return headers;
}

export function liveReconnectDelay(attempt: number): number {
  return Math.min(30000, 1000 * (2 ** Math.min(attempt, 5)));
}

export function isPermanentLiveStreamFailure(status: number): boolean {
  return status === 401 || status === 403;
}

export function shouldStopLiveStream(status: number, retryAuthenticationFailures: boolean): boolean {
  return isPermanentLiveStreamFailure(status) && !retryAuthenticationFailures;
}

export function shouldPauseLiveStream(documentHidden: boolean, pauseWhenHidden: boolean): boolean {
  return documentHidden && pauseWhenHidden;
}

export async function consumeLiveSse(
  response: Response,
  onEvent: (event: LiveStageEvent) => void,
): Promise<void> {
  if (!response.ok) throw new Error(`live stream returned HTTP ${response.status}`);
  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";
  if (!contentType.includes("text/event-stream")) throw new Error("live stream returned an invalid content type");
  if (!response.body) throw new Error("live stream response has no body");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const consumeBlock = (block: string): void => {
    const data = block.split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (!data) return;
    const event = decodeLiveStageEvent(data);
    if (event) onEvent(event);
  };
  while (true) {
    const { value, done } = await readSseChunk(reader);
    buffer = (buffer + decoder.decode(value, { stream: !done })).replace(/\r\n/g, "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      consumeBlock(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");
    }
    if (done) {
      if (buffer.trim()) consumeBlock(buffer);
      return;
    }
  }
}

export function useLiveStream(options: UseLiveStreamOptions): UseLiveStreamResult {
  const [status, setStatus] = useState<LiveConnectionStatus>(typeof fetch === "undefined" ? "unsupported" : "idle");
  const [lastError, setLastError] = useState<string | null>(null);
  const [source, setSource] = useState<ObservationSource>("unknown");
  const onEventRef = useRef(options.onEvent);
  const onStatusRef = useRef(options.onStatus);
  onEventRef.current = options.onEvent;
  onStatusRef.current = options.onStatus;
  const {
    url,
    getAuthorizationHeader,
    enabled = true,
    pauseWhenHidden = true,
    retryAuthenticationFailures = false,
  } = options;

  useEffect(() => {
    if (typeof fetch === "undefined") return undefined;
    if (!enabled) {
      setStatus("idle");
      setLastError(null);
      return undefined;
    }
    let cancelled = false;
    let controller: AbortController | null = null;
    let reconnectTimer: number | null = null;
    let reconnectAttempt = 0;
    let permanentFailure = false;
    const publishStatus = (next: LiveConnectionStatus): void => {
      setStatus(next);
      onStatusRef.current?.(next);
    };
    const isHidden = (): boolean => shouldPauseLiveStream(
      typeof document !== "undefined" && document.hidden,
      pauseWhenHidden,
    );
    const scheduleReconnect = (): void => {
      if (cancelled || permanentFailure || isHidden()) return;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      const delay = liveReconnectDelay(reconnectAttempt);
      reconnectAttempt += 1;
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        void connect();
      }, delay);
    };
    const connect = async (): Promise<void> => {
      if (cancelled || controller) return;
      publishStatus("connecting");
      const active = new AbortController();
      controller = active;
      try {
        const authorization = await getAuthorizationHeader?.() ?? null;
        if (cancelled || controller !== active) return;
        const response = await fetch(url, {
          method: "GET",
          headers: liveStreamHeaders(authorization),
          credentials: "omit",
          signal: active.signal,
        });
        if (!response.ok) {
          permanentFailure = shouldStopLiveStream(
            response.status,
            retryAuthenticationFailures,
          );
          throw new Error(`live stream returned HTTP ${response.status}`);
        }
        publishStatus("open");
        setLastError(null);
        await consumeLiveSse(response, (event) => {
          if (!cancelled && controller === active) {
            reconnectAttempt = 0;
            setSource((current) => mergeObservationSource(
              current,
              normalizeObservationSource(event.source),
            ));
            onEventRef.current(event);
          }
        });
        if (!cancelled && controller === active) {
          setLastError("connection to live stream closed");
          publishStatus("closed");
        }
      } catch (error) {
        if (!cancelled && !active.signal.aborted) {
          setLastError(error instanceof Error ? error.message : String(error));
          publishStatus("closed");
        }
      } finally {
        if (controller === active) controller = null;
        scheduleReconnect();
      }
    };
    const disconnect = (next: LiveConnectionStatus): void => {
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
      controller?.abort();
      controller = null;
      publishStatus(next);
    };
    const handleVisibility = (): void => {
      if (cancelled) return;
      if (isHidden()) disconnect("idle");
      else void connect();
    };
    if (isHidden()) publishStatus("idle");
    else void connect();
    if (pauseWhenHidden) document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      cancelled = true;
      if (pauseWhenHidden) document.removeEventListener("visibilitychange", handleVisibility);
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      controller?.abort();
    };
  }, [url, getAuthorizationHeader, enabled, pauseWhenHidden, retryAuthenticationFailures]);
  return { status, lastError, source };
}
