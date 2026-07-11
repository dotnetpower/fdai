/**
 * Provisioning progress stream hook (surface B consumer).
 *
 * Subscribes to the read-API's `GET /provision/stream` SSE endpoint via
 * `EventSource` and decodes the `provision.*` events documented in
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
  /** Send credentials (cookies) with the request. Same-origin production
   *  deployments need this; cross-origin dev does not. */
  readonly withCredentials?: boolean;
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

/**
 * Attach an `EventSource` to the provisioning SSE endpoint. Every decoded
 * frame is passed to `onEvent` (in a `useRef` so re-renders do not tear the
 * subscription). The hook cleans up on unmount.
 */
export function useProvisionStream(
  options: UseProvisionStreamOptions,
): UseProvisionStreamResult {
  const [status, setStatus] = useState<ProvisionConnectionStatus>(
    typeof EventSource === "undefined" ? "unsupported" : "idle",
  );
  const [lastError, setLastError] = useState<string | null>(null);

  const onEventRef = useRef(options.onEvent);
  const onStatusRef = useRef(options.onStatus);
  onEventRef.current = options.onEvent;
  onStatusRef.current = options.onStatus;

  const url = options.url;
  const withCredentials = options.withCredentials ?? false;

  useEffect(() => {
    if (typeof EventSource === "undefined") return undefined;

    let cancelled = false;
    let source: EventSource | null = null;

    const connect = () => {
      if (cancelled || source) return;
      setStatus("connecting");
      onStatusRef.current?.("connecting");

      const es = new EventSource(url, { withCredentials });
      source = es;

      // provision.* events arrive as unnamed `message` events; the named
      // `hello` frame and `: keepalive` comments are ignored by onmessage.
      es.onmessage = (raw) => {
        if (cancelled || source !== es) return;
        const decoded = decodeProvisionEvent((raw as MessageEvent).data);
        if (decoded) {
          onEventRef.current(decoded);
        }
      };

      es.onopen = () => {
        if (cancelled || source !== es) return;
        setStatus("open");
        setLastError(null);
        onStatusRef.current?.("open");
      };

      es.onerror = () => {
        if (cancelled || source !== es) return;
        const nextStatus: ProvisionConnectionStatus =
          es.readyState === EventSource.CLOSED ? "closed" : "connecting";
        setStatus(nextStatus);
        onStatusRef.current?.(nextStatus);
      };
    };

    const disconnect = (nextStatus: ProvisionConnectionStatus) => {
      if (source) {
        source.close();
        source = null;
      }
      setStatus(nextStatus);
      onStatusRef.current?.(nextStatus);
    };

    const isHidden = () => typeof document !== "undefined" && document.hidden;

    const handleVisibility = () => {
      if (cancelled) return;
      if (isHidden()) {
        disconnect("idle");
      } else {
        connect();
      }
    };

    if (isHidden()) {
      setStatus("idle");
      onStatusRef.current?.("idle");
    } else {
      connect();
    }

    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", handleVisibility);
    }

    return () => {
      cancelled = true;
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", handleVisibility);
      }
      if (source) source.close();
      setStatus("closed");
      onStatusRef.current?.("closed");
    };
  }, [url, withCredentials]);

  return { status, lastError };
}
