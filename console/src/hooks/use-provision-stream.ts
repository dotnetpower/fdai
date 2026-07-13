/**
 * Provisioning progress stream hook (surface B consumer).
 *
 * Subscribes to the read-API's `GET /provision/stream` SSE endpoint via
 * authenticated fetch and decodes the `provision.*` events documented in
 * {@link fdai.delivery.read_api.provision_stream}. It mirrors
 * {@link useLiveStream}: pure read consumer, browser-managed reconnect,
 * visibility-gated so a backgrounded tab does not hammer the server.
 *
 * The provisioning source emits every event as an unnamed (`message`) SSE
 * event whose JSON payload carries the semantic `type`, so a bare
 * `EventSource.onmessage` receives them (the server also emits a named
 * `hello` frame on connect and `: keepalive` comments, both ignored here).
 *
 * The hook never issues privileged calls - the console renders provisioning
 * progress, it never executes provisioning (app-shape.instructions.md §
 * Operator console).
 */

import { useEffect, useRef, useState } from "preact/hooks";

/** Provisioning phase - mirrors {@link ProvisionPhase}. */
export type ProvisionPhase = "progress" | "waiting" | "resumed" | "done" | "failed";

/** One decoded `provision.*` frame from the SSE wire. */
export interface ProvisionEvent {
  /** Semantic type, e.g. `"provision.done"`. */
  readonly type: string;
  /** The phase parsed out of {@link type}. */
  readonly phase: ProvisionPhase;
  /** 0..1 completion (present on `progress` / `done`). */
  readonly fraction?: number;
  /** Resource address (present on `waiting` / `resumed` / `failed`). */
  readonly node?: string;
  /** Human-readable reason (present on `waiting` / `failed`). */
  readonly reason?: string;
  /** Operator-console URL (present on `done` when known). */
  readonly console_url?: string;
  /** ISO-8601 timestamp. */
  readonly ts?: string;
}

/** Status of the underlying EventSource. */
export type ProvisionConnectionStatus =
  | "idle"
  | "connecting"
  | "open"
  | "closed"
  | "unsupported";

export interface UseProvisionStreamOptions {
  /** Absolute or relative URL to the SSE endpoint. */
  readonly url: string;
  /** Called for every decoded provision event. */
  readonly onEvent: (event: ProvisionEvent) => void;
  /** Optional connection-status observer. */
  readonly onStatus?: (status: ProvisionConnectionStatus) => void;
  /** Acquire the current bearer header. Dev mode returns null. */
  readonly getAuthorizationHeader?: () => Promise<string | null>;
}

export interface UseProvisionStreamResult {
  readonly status: ProvisionConnectionStatus;
  readonly lastError: string | null;
}

const _PHASES: ReadonlySet<string> = new Set([
  "progress",
  "waiting",
  "resumed",
  "done",
  "failed",
]);

/** Parse a raw wire payload into a typed {@link ProvisionEvent}, or `null`
 *  when the payload is not a recognisable `provision.*` event. Exported for
 *  unit testing the decode boundary. */
export function decodeProvisionEvent(data: string): ProvisionEvent | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null) return null;
  const raw = parsed as Record<string, unknown>;
  const type = raw.type;
  if (typeof type !== "string" || !type.startsWith("provision.")) return null;
  const phase = type.slice("provision.".length);
  if (!_PHASES.has(phase)) return null;
  // Build with only the keys that are present. `exactOptionalPropertyTypes`
  // forbids assigning an explicit `undefined` to an optional property, so the
  // optional fields are attached conditionally rather than defaulted.
  const event: {
    type: string;
    phase: ProvisionPhase;
    fraction?: number;
    node?: string;
    reason?: string;
    console_url?: string;
    ts?: string;
  } = { type, phase: phase as ProvisionPhase };
  // `fraction` comes off an untrusted wire: only accept a finite value in
  // [0, 1]. A NaN / Infinity / out-of-range number is ignored (the previous
  // fraction stands) so a buggy or hostile producer cannot pin the meter.
  if (typeof raw.fraction === "number" && raw.fraction >= 0 && raw.fraction <= 1) {
    event.fraction = raw.fraction;
  }
  if (typeof raw.node === "string") event.node = raw.node;
  if (typeof raw.reason === "string") event.reason = raw.reason;
  if (typeof raw.console_url === "string") event.console_url = raw.console_url;
  if (typeof raw.ts === "string") event.ts = raw.ts;
  return event;
}

export function provisionStreamHeaders(authorization: string | null): Headers {
  const headers = new Headers({ accept: "text/event-stream" });
  if (authorization) headers.set("authorization", authorization);
  return headers;
}

export function provisionReconnectDelay(attempt: number): number {
  return Math.min(30000, 1000 * (2 ** Math.min(attempt, 5)));
}

export function isPermanentProvisionFailure(status: number): boolean {
  return status === 401 || status === 403;
}

/** Consume one fetch SSE response until EOF or abort. */
export async function consumeProvisionSse(
  response: Response,
  onEvent: (event: ProvisionEvent) => void,
): Promise<void> {
  if (!response.ok) throw new Error(`provisioning stream returned HTTP ${response.status}`);
  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";
  if (!contentType.includes("text/event-stream")) {
    throw new Error("provisioning stream returned an invalid content type");
  }
  if (!response.body) throw new Error("provisioning stream response has no body");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const consumeBlock = (block: string) => {
    const data = block
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (!data) return;
    const event = decodeProvisionEvent(data);
    if (event) onEvent(event);
  };

  while (true) {
    const { value, done } = await reader.read();
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

/**
 * Attach an authenticated fetch stream to the provisioning SSE endpoint.
 * Every decoded frame is passed to `onEvent`; the hook aborts on unmount.
 */
export function useProvisionStream(
  options: UseProvisionStreamOptions,
): UseProvisionStreamResult {
  const [status, setStatus] = useState<ProvisionConnectionStatus>(
    typeof fetch === "undefined" ? "unsupported" : "idle",
  );
  const [lastError, setLastError] = useState<string | null>(null);

  const onEventRef = useRef(options.onEvent);
  const onStatusRef = useRef(options.onStatus);
  onEventRef.current = options.onEvent;
  onStatusRef.current = options.onStatus;

  const url = options.url;
  const getAuthorizationHeader = options.getAuthorizationHeader;

  useEffect(() => {
    if (typeof fetch === "undefined") return undefined;

    let cancelled = false;
    let controller: AbortController | null = null;
    let reconnectTimer: number | null = null;
    let reconnectAttempt = 0;
    let permanentFailure = false;

    const publishStatus = (next: ProvisionConnectionStatus) => {
      setStatus(next);
      onStatusRef.current?.(next);
    };

    const scheduleReconnect = () => {
      if (cancelled || permanentFailure || (typeof document !== "undefined" && document.hidden)) return;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      const delay = provisionReconnectDelay(reconnectAttempt);
      reconnectAttempt += 1;
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        void connect();
      }, delay);
    };

    const connect = async () => {
      if (cancelled || controller) return;
      setStatus("connecting");
      onStatusRef.current?.("connecting");
      const active = new AbortController();
      controller = active;
      try {
        const authorization = await getAuthorizationHeader?.() ?? null;
        if (cancelled || controller !== active) return;
        const response = await fetch(url, {
          method: "GET",
          headers: provisionStreamHeaders(authorization),
          credentials: "omit",
          signal: active.signal,
        });
        if (!response.ok) {
          permanentFailure = isPermanentProvisionFailure(response.status);
          throw new Error(`provisioning stream returned HTTP ${response.status}`);
        }
        publishStatus("open");
        setLastError(null);
        await consumeProvisionSse(response, (event) => {
          if (!cancelled && controller === active) {
            reconnectAttempt = 0;
            onEventRef.current(event);
          }
        });
        if (!cancelled && controller === active) {
          setLastError("connection to provisioning stream closed");
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

    const disconnect = (nextStatus: ProvisionConnectionStatus) => {
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
      controller?.abort();
      controller = null;
      publishStatus(nextStatus);
    };

    const isHidden = () => typeof document !== "undefined" && document.hidden;

    const handleVisibility = () => {
      if (cancelled) return;
      if (isHidden()) {
        disconnect("idle");
      } else {
        void connect();
      }
    };

    if (isHidden()) {
      setStatus("idle");
      onStatusRef.current?.("idle");
    } else {
      void connect();
    }

    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", handleVisibility);
    }

    return () => {
      cancelled = true;
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", handleVisibility);
      }
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      controller?.abort();
    };
  }, [url, getAuthorizationHeader]);

  return { status, lastError };
}
