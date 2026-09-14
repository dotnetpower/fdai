import { useEffect, useRef, useState } from "preact/hooks";

import { readSseChunk, SSE_INACTIVITY_TIMEOUT_MS } from "./sse-reader";

export const SSE_MAX_BUFFER_CHARS = 256 * 1024;
const SSE_EVENT_NAME = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/;
const SSE_CURSOR = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$/;

export type SseConnectionStatus =
  | "idle"
  | "connecting"
  | "open"
  | "closed"
  | "unsupported";

export interface SseFrame {
  readonly event: string;
  readonly data: string;
  readonly id: string | null;
  readonly retryMs: number | null;
  readonly droppedBefore: number;
}

export interface UseAuthenticatedSseOptions {
  readonly url: string;
  readonly onFrame: (frame: SseFrame) => boolean | void;
  readonly onStatus?: (status: SseConnectionStatus) => void;
  readonly getAuthorizationHeader?: () => Promise<string | null>;
  readonly enabled?: boolean;
  readonly pauseWhenHidden?: boolean;
  readonly resumeFromLastEventId?: boolean;
  readonly shouldRetryStatus?: (status: number) => boolean;
  readonly inactivityTimeoutMs?: number;
  readonly maxBufferChars?: number;
  readonly initialLastEventId?: string | null;
  readonly onLastEventId?: (lastEventId: string | null) => void;
  readonly strictEventId?: boolean;
  readonly resetCursorOnFrame?: (frame: SseFrame) => boolean;
  readonly sharedFrameKey?: (frame: SseFrame) => string | null;
  readonly sharedReplayCapacity?: number;
}

export interface UseAuthenticatedSseResult {
  readonly status: SseConnectionStatus;
  readonly lastError: string | null;
  readonly lastEventId: string | null;
}

export class SseResponseError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(`SSE endpoint returned HTTP ${status}`);
    this.name = "SseResponseError";
    this.status = status;
  }
}

export function authenticatedSseHeaders(
  authorization: string | null,
  lastEventId: string | null = null,
): Headers {
  const headers = new Headers({ accept: "text/event-stream" });
  if (authorization) headers.set("authorization", authorization);
  if (lastEventId) headers.set("last-event-id", lastEventId);
  return headers;
}

export function sseReconnectDelay(
  attempt: number,
  serverRetryMs: number | null = null,
): number {
  if (serverRetryMs !== null) return serverRetryMs;
  return Math.min(30_000, 1_000 * (2 ** Math.min(attempt, 5)));
}

export function shouldResetRejectedSseCursor(
  status: number,
  cursorAttached: boolean,
  resetAttempted: boolean,
): boolean {
  return cursorAttached &&
    !resetAttempted &&
    (status === 400 || status === 416);
}

export function shouldAdvanceSseCursor(
  frame: SseFrame,
  accepted: boolean | void,
): boolean {
  return accepted !== false && frame.id !== null;
}

export function isTransientSseStatus(status: number): boolean {
  return status === 408 || status === 425 || status === 429 || status >= 500;
}

export async function consumeSseFrames(
  response: Response,
  onFrame: (frame: SseFrame) => void | Promise<void>,
  options: {
    readonly inactivityTimeoutMs?: number;
    readonly maxBufferChars?: number;
    readonly strictEventId?: boolean;
  } = {},
): Promise<void> {
  if (!response.ok) throw new SseResponseError(response.status);
  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";
  if (!contentType.includes("text/event-stream")) {
    throw new Error("SSE endpoint returned an invalid content type");
  }
  if (!response.body) throw new Error("SSE endpoint response has no body");
  const inactivityTimeoutMs =
    options.inactivityTimeoutMs ?? SSE_INACTIVITY_TIMEOUT_MS;
  const maxBufferChars = options.maxBufferChars ?? SSE_MAX_BUFFER_CHARS;
  const strictEventId = options.strictEventId ?? true;
  if (maxBufferChars < 1) throw new Error("SSE buffer bound MUST be positive");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let pendingCarriageReturn = false;
  try {
    while (true) {
      const { value, done } = await readSseChunk(reader, inactivityTimeoutMs);
      let decoded = decoder.decode(value, { stream: !done });
      if (pendingCarriageReturn) {
        decoded = `\r${decoded}`;
        pendingCarriageReturn = false;
      }
      if (!done && decoded.endsWith("\r")) {
        decoded = decoded.slice(0, -1);
        pendingCarriageReturn = true;
      }
      buffer += decoded.replace(/\r\n|\r/g, "\n");
      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        const frame = parseSseBlock(
          buffer.slice(0, boundary),
          maxBufferChars,
          strictEventId,
        );
        buffer = buffer.slice(boundary + 2);
        if (frame !== null) await onFrame(frame);
        boundary = buffer.indexOf("\n\n");
      }
      if (buffer.length > maxBufferChars) {
        throw new Error("SSE stream buffer exceeded its bound");
      }
      if (done) {
        if (buffer.trim()) {
          const frame = parseSseBlock(buffer, maxBufferChars, strictEventId);
          if (frame !== null) await onFrame(frame);
        }
        return;
      }
    }
  } catch (error) {
    await reader.cancel(error).catch(() => undefined);
    throw error;
  }
}

export function useAuthenticatedSse(
  options: UseAuthenticatedSseOptions,
): UseAuthenticatedSseResult {
  const [status, setStatus] = useState<SseConnectionStatus>(
    typeof fetch === "undefined" ? "unsupported" : "idle",
  );
  const [lastError, setLastError] = useState<string | null>(null);
  const [lastEventId, setLastEventId] = useState<string | null>(null);
  const onFrameRef = useRef(options.onFrame);
  const onStatusRef = useRef(options.onStatus);
  const onLastEventIdRef = useRef(options.onLastEventId);
  const resetCursorOnFrameRef = useRef(options.resetCursorOnFrame);
  const lastEventIdRef = useRef<string | null>(null);
  const serverRetryRef = useRef<number | null>(null);
  onFrameRef.current = options.onFrame;
  onStatusRef.current = options.onStatus;
  onLastEventIdRef.current = options.onLastEventId;
  resetCursorOnFrameRef.current = options.resetCursorOnFrame;

  const {
    url,
    getAuthorizationHeader,
    enabled = true,
    pauseWhenHidden = true,
    resumeFromLastEventId = false,
    shouldRetryStatus = isTransientSseStatus,
    inactivityTimeoutMs = SSE_INACTIVITY_TIMEOUT_MS,
    maxBufferChars = SSE_MAX_BUFFER_CHARS,
    initialLastEventId = null,
    strictEventId = true,
  } = options;

  useEffect(() => {
    lastEventIdRef.current = resumeFromLastEventId
      ? initialLastEventId
      : null;
    serverRetryRef.current = null;
    setLastEventId(lastEventIdRef.current);
    if (typeof fetch === "undefined") return undefined;
    if (!enabled) {
      setStatus("idle");
      setLastError(null);
      return undefined;
    }

    let cancelled = false;
    let controller: AbortController | null = null;
    let reconnectTimer: ReturnType<typeof globalThis.setTimeout> | null = null;
    let reconnectAttempt = 0;
    let permanentFailure = false;

    const publishStatus = (next: SseConnectionStatus): void => {
      setStatus(next);
      onStatusRef.current?.(next);
    };
    const isHidden = (): boolean =>
      pauseWhenHidden &&
      typeof document !== "undefined" &&
      document.hidden;
    const scheduleReconnect = (): void => {
      if (cancelled || permanentFailure || isHidden()) return;
      if (reconnectTimer !== null) globalThis.clearTimeout(reconnectTimer);
      const delay = sseReconnectDelay(
        reconnectAttempt,
        serverRetryRef.current,
      );
      reconnectAttempt += 1;
      reconnectTimer = globalThis.setTimeout(() => {
        reconnectTimer = null;
        void connect();
      }, delay);
    };
    const connect = async (): Promise<void> => {
      if (cancelled || controller || isHidden()) return;
      publishStatus("connecting");
      const active = new AbortController();
      controller = active;
      try {
        const authorization = await getAuthorizationHeader?.() ?? null;
        if (cancelled || controller !== active) return;
        let cursor = resumeFromLastEventId
          ? lastEventIdRef.current
          : null;
        let resetAttempted = false;
        let response: Response;
        while (true) {
          response = await fetch(url, {
            method: "GET",
            cache: "no-store",
            headers: authenticatedSseHeaders(authorization, cursor),
            credentials: "omit",
            signal: active.signal,
          });
          if (response.ok) break;
          if (
            shouldResetRejectedSseCursor(
              response.status,
              cursor !== null,
              resetAttempted,
            )
          ) {
            cursor = null;
            lastEventIdRef.current = null;
            setLastEventId(null);
            onLastEventIdRef.current?.(null);
            resetAttempted = true;
            continue;
          }
          permanentFailure = !shouldRetryStatus(response.status);
          throw new SseResponseError(response.status);
        }
        publishStatus("open");
        setLastError(null);
        await consumeSseFrames(
          response,
          (frame) => {
            if (frame.retryMs !== null) serverRetryRef.current = frame.retryMs;
            if (
              resumeFromLastEventId &&
              resetCursorOnFrameRef.current?.(frame) === true
            ) {
              lastEventIdRef.current = null;
              setLastEventId(null);
              onLastEventIdRef.current?.(null);
            }
            const accepted = onFrameRef.current(frame);
            if (accepted !== false) reconnectAttempt = 0;
            if (
              resumeFromLastEventId &&
              shouldAdvanceSseCursor(frame, accepted)
            ) {
              lastEventIdRef.current = frame.id;
              setLastEventId(frame.id);
              onLastEventIdRef.current?.(frame.id);
            }
          },
          { inactivityTimeoutMs, maxBufferChars, strictEventId },
        );
        if (!cancelled && controller === active) {
          setLastError("SSE connection closed");
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
    const disconnect = (next: SseConnectionStatus): void => {
      if (reconnectTimer !== null) globalThis.clearTimeout(reconnectTimer);
      reconnectTimer = null;
      controller?.abort();
      controller = null;
      publishStatus(next);
    };
    const onVisibility = (): void => {
      if (cancelled) return;
      if (isHidden()) disconnect("idle");
      else void connect();
    };

    if (isHidden()) publishStatus("idle");
    else void connect();
    if (pauseWhenHidden && typeof document !== "undefined") {
      document.addEventListener("visibilitychange", onVisibility);
    }
    return () => {
      cancelled = true;
      if (pauseWhenHidden && typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", onVisibility);
      }
      if (reconnectTimer !== null) globalThis.clearTimeout(reconnectTimer);
      controller?.abort();
    };
  }, [
    enabled,
    getAuthorizationHeader,
    inactivityTimeoutMs,
    initialLastEventId,
    maxBufferChars,
    pauseWhenHidden,
    resumeFromLastEventId,
    shouldRetryStatus,
    strictEventId,
    url,
  ]);

  return { status, lastError, lastEventId };
}

interface SharedSseSubscriber {
  readonly token: symbol;
  readonly pauseWhenHidden: boolean;
  readonly onFrameRef: { current: (frame: SseFrame) => boolean | void };
  readonly onStatusRef: {
    current: ((status: SseConnectionStatus) => void) | undefined;
  };
  readonly setLeader: (leader: boolean) => void;
  readonly setStatus: (status: SseConnectionStatus) => void;
  readonly setLastError: (error: string | null) => void;
  readonly sharedFrameKey: ((frame: SseFrame) => string | null) | undefined;
  readonly sharedReplayCapacity: number;
}

interface SharedSseEntry {
  readonly subscribers: Map<symbol, SharedSseSubscriber>;
  readonly latestFrames: Map<string, SseFrame>;
  leader: symbol | null;
  status: SseConnectionStatus;
  lastError: string | null;
  lastEventId: string | null;
}

const SHARED_SSE = new Map<string, SharedSseEntry>();
const AUTHORIZATION_IDENTITIES = new WeakMap<
  () => Promise<string | null>,
  number
>();
let nextAuthorizationIdentity = 1;

export function useSharedAuthenticatedSse(
  scope: string,
  options: UseAuthenticatedSseOptions,
): UseAuthenticatedSseResult {
  const enabled = options.enabled ?? true;
  const pauseWhenHidden = options.pauseWhenHidden ?? true;
  const replayCapacity = options.sharedReplayCapacity ?? 0;
  if (!Number.isInteger(replayCapacity) || replayCapacity < 0) {
    throw new Error("shared SSE replay capacity MUST be a non-negative integer");
  }
  const authorizationIdentity = sharedAuthorizationIdentity(
    options.getAuthorizationHeader,
  );
  const shareKey = [
    scope,
    normalizedSharedSseUrl(options.url),
    authorizationIdentity,
  ].join("\u0000");
  const tokenRef = useRef(Symbol(scope));
  const onFrameRef = useRef(options.onFrame);
  const onStatusRef = useRef(options.onStatus);
  const [leader, setLeader] = useState(false);
  const [status, setStatus] = useState<SseConnectionStatus>(
    typeof fetch === "undefined" ? "unsupported" : "idle",
  );
  const [lastError, setLastError] = useState<string | null>(null);
  const priorLeaderRef = useRef(false);
  const leaderCursorRef = useRef<string | null>(null);
  onFrameRef.current = options.onFrame;
  onStatusRef.current = options.onStatus;

  useEffect(() => {
    if (!enabled || typeof fetch === "undefined") {
      setLeader(false);
      setStatus(typeof fetch === "undefined" ? "unsupported" : "idle");
      setLastError(null);
      return undefined;
    }
    const entry = sharedSseEntry(shareKey);
    const subscriber: SharedSseSubscriber = {
      token: tokenRef.current,
      pauseWhenHidden,
      onFrameRef,
      onStatusRef,
      setLeader,
      setStatus,
      setLastError,
      sharedFrameKey: options.sharedFrameKey,
      sharedReplayCapacity: replayCapacity,
    };
    entry.subscribers.set(subscriber.token, subscriber);
    electSharedSseLeader(entry);
    publishSharedSseStateToSubscriber(entry, subscriber);
    entry.latestFrames.forEach((frame) => {
      subscriber.onFrameRef.current(frame);
    });
    const onVisibility = (): void => {
      publishSharedSseStateToSubscriber(entry, subscriber);
    };
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", onVisibility);
    }
    return () => {
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", onVisibility);
      }
      entry.subscribers.delete(subscriber.token);
      electSharedSseLeader(entry);
      if (entry.subscribers.size === 0) SHARED_SSE.delete(shareKey);
    };
  }, [
    enabled,
    options.sharedFrameKey,
    pauseWhenHidden,
    replayCapacity,
    shareKey,
  ]);

  const entryCursor = SHARED_SSE.get(shareKey)?.lastEventId ?? null;
  if (leader && !priorLeaderRef.current) leaderCursorRef.current = entryCursor;
  priorLeaderRef.current = leader;
  const physical = useAuthenticatedSse({
    ...options,
    enabled: enabled && leader,
    initialLastEventId: leaderCursorRef.current,
    onLastEventId: (cursor) => {
      const entry = SHARED_SSE.get(shareKey);
      if (entry !== undefined) entry.lastEventId = cursor;
    },
    onFrame: (frame) => publishSharedSseFrame(shareKey, frame),
    onStatus: (next) => {
      publishSharedSseState(
        shareKey,
        next,
        next === "open" ? null : undefined,
      );
    },
  });

  useEffect(() => {
    if (!leader) return;
    publishSharedSseState(shareKey, physical.status, physical.lastError);
  }, [leader, physical.lastError, physical.status, shareKey]);

  return {
    status,
    lastError,
    lastEventId: physical.lastEventId ?? entryCursor,
  };
}

function sharedAuthorizationIdentity(
  authorization: (() => Promise<string | null>) | undefined,
): string {
  if (authorization === undefined) return "anonymous";
  let identity = AUTHORIZATION_IDENTITIES.get(authorization);
  if (identity === undefined) {
    identity = nextAuthorizationIdentity;
    nextAuthorizationIdentity += 1;
    AUTHORIZATION_IDENTITIES.set(authorization, identity);
  }
  return String(identity);
}

function sharedSseEntry(key: string): SharedSseEntry {
  const existing = SHARED_SSE.get(key);
  if (existing !== undefined) return existing;
  const created: SharedSseEntry = {
    subscribers: new Map(),
    latestFrames: new Map(),
    leader: null,
    status: "idle",
    lastError: null,
    lastEventId: null,
  };
  SHARED_SSE.set(key, created);
  return created;
}

function electSharedSseLeader(entry: SharedSseEntry): void {
  const subscribers = [...entry.subscribers.values()];
  const preferred = subscribers.filter(
    (subscriber) => !subscriber.pauseWhenHidden,
  );
  const candidates = preferred.length > 0 ? preferred : subscribers;
  const current = candidates.find(
    (subscriber) => subscriber.token === entry.leader,
  );
  const leader = current ?? candidates[0] ?? null;
  entry.leader = leader?.token ?? null;
  subscribers.forEach((subscriber) => {
    subscriber.setLeader(subscriber.token === entry.leader);
  });
}

function publishSharedSseFrame(key: string, frame: SseFrame): boolean {
  const entry = SHARED_SSE.get(key);
  if (entry === undefined) return false;
  rememberSharedSseFrame(entry, frame);
  let accepted = false;
  for (const subscriber of entry.subscribers.values()) {
    if (subscriber.onFrameRef.current(frame) !== false) accepted = true;
  }
  if (accepted && frame.id !== null) entry.lastEventId = frame.id;
  return accepted;
}

function rememberSharedSseFrame(
  entry: SharedSseEntry,
  frame: SseFrame,
): void {
  let key: string | null = null;
  let capacity = 0;
  for (const subscriber of entry.subscribers.values()) {
    capacity = Math.max(capacity, subscriber.sharedReplayCapacity);
    key ??= subscriber.sharedFrameKey?.(frame) ?? null;
  }
  if (key === null || capacity < 1) return;
  entry.latestFrames.delete(key);
  entry.latestFrames.set(key, frame);
  while (entry.latestFrames.size > capacity) {
    const oldest = entry.latestFrames.keys().next().value;
    if (typeof oldest !== "string") break;
    entry.latestFrames.delete(oldest);
  }
}

function publishSharedSseState(
  key: string,
  status: SseConnectionStatus,
  error: string | null | undefined,
): void {
  const entry = SHARED_SSE.get(key);
  if (entry === undefined) return;
  entry.status = status;
  if (error !== undefined) entry.lastError = error;
  entry.subscribers.forEach((subscriber) => {
    publishSharedSseStateToSubscriber(entry, subscriber);
  });
}

function publishSharedSseStateToSubscriber(
  entry: SharedSseEntry,
  subscriber: SharedSseSubscriber,
): void {
  const hidden = subscriber.pauseWhenHidden && documentIsHidden();
  const status = hidden ? "idle" : entry.status;
  subscriber.setStatus(status);
  subscriber.setLastError(hidden ? null : entry.lastError);
  subscriber.onStatusRef.current?.(status);
}

function documentIsHidden(): boolean {
  return typeof document !== "undefined" && document.hidden;
}

function normalizedSharedSseUrl(url: string): string {
  try {
    const base =
      typeof window === "undefined"
        ? "http://localhost/"
        : window.location.href;
    return new URL(url, base).toString();
  } catch {
    return url;
  }
}

function parseSseBlock(
  block: string,
  maxDataChars: number,
  strictEventId: boolean,
): SseFrame | null {
  let event = "message";
  let id: string | null = null;
  let retryMs: number | null = null;
  let droppedBefore = 0;
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue;
    const separator = line.indexOf(":");
    const field = separator < 0 ? line : line.slice(0, separator);
    const raw = separator < 0 ? "" : line.slice(separator + 1);
    const value = raw.startsWith(" ") ? raw.slice(1) : raw;
    if (field === "data") data.push(value);
    else if (field === "event" && SSE_EVENT_NAME.test(value)) event = value;
    else if (field === "id") {
      if (SSE_CURSOR.test(value)) id = value;
      else if (strictEventId) throw new Error("SSE event id is malformed");
    } else if (field === "retry" && /^\d{3,5}$/.test(value)) {
      const parsed = Number(value);
      if (parsed >= 100 && parsed <= 60_000) retryMs = parsed;
    } else if (field === "dropped" && /^\d{1,7}$/.test(value)) {
      const parsed = Number(value);
      if (parsed <= 1_000_000) droppedBefore = parsed;
    }
  }
  if (data.length === 0) return null;
  const payload = data.join("\n");
  if (payload.length > maxDataChars) {
    throw new Error("SSE frame data exceeded its bound");
  }
  return { event, data: payload, id, retryMs, droppedBefore };
}
