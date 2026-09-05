import { useEffect, useRef, useState } from "preact/hooks";
import { readSseChunk } from "../hooks/sse-reader";

export type OntologyInvalidationStreamStatus =
  | "idle"
  | "connecting"
  | "open"
  | "reconnecting"
  | "unsupported";

export interface OntologyInvalidationEvent {
  readonly schema_version: "1.0.0";
  readonly watermark: number;
  readonly observation_count: number;
  readonly observed_at: string;
  readonly recorded_at: string;
  readonly complete: false;
  readonly execution_authority: false;
  readonly mutation_authority: false;
}

export interface UseOntologyInvalidationStreamOptions {
  readonly url: string;
  readonly enabled: boolean;
  readonly getAuthorizationHeader: () => Promise<string | null>;
  readonly onEvent: (event: OntologyInvalidationEvent) => void;
}

export interface UseOntologyInvalidationStreamResult {
  readonly status: OntologyInvalidationStreamStatus;
  readonly lastError: string | null;
}

const EVENT_NAME = "inventory.invalidated";
const MAX_OBSERVATIONS_PER_EVENT = 500;
const MAX_SSE_BUFFER_CHARS = 64 * 1024;
const RFC3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
const ALLOWED_EVENT_KEYS = new Set([
  "schema_version",
  "watermark",
  "observation_count",
  "observed_at",
  "recorded_at",
  "complete",
  "execution_authority",
  "mutation_authority",
]);

/** Decodes one sanitized invalidation without accepting provider or Resource payloads. */
export function decodeOntologyInvalidationEvent(data: string): OntologyInvalidationEvent | null {
  let value: unknown;
  try {
    value = JSON.parse(data);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const event = value as Record<string, unknown>;
  if (
    Object.keys(event).some((key) => !ALLOWED_EVENT_KEYS.has(key))
    || event.schema_version !== "1.0.0"
    || !Number.isSafeInteger(event.watermark)
    || (event.watermark as number) < 0
    || !Number.isSafeInteger(event.observation_count)
    || (event.observation_count as number) < 1
    || (event.observation_count as number) > MAX_OBSERVATIONS_PER_EVENT
    || typeof event.observed_at !== "string"
    || !RFC3339.test(event.observed_at)
    || Number.isNaN(Date.parse(event.observed_at))
    || typeof event.recorded_at !== "string"
    || !RFC3339.test(event.recorded_at)
    || Number.isNaN(Date.parse(event.recorded_at))
    || event.complete !== false
    || event.execution_authority !== false
    || event.mutation_authority !== false
  ) return null;
  return event as unknown as OntologyInvalidationEvent;
}

export function ontologyInvalidationHeaders(
  authorization: string | null,
  lastEventId: string | null,
): Headers {
  const headers = new Headers({ accept: "text/event-stream" });
  if (authorization) headers.set("authorization", authorization);
  if (lastEventId) headers.set("last-event-id", lastEventId);
  return headers;
}

export function ontologyInvalidationReconnectDelay(attempt: number): number {
  return Math.min(30_000, 1_000 * (2 ** Math.min(attempt, 5)));
}

export async function consumeOntologyInvalidationSse(
  response: Response,
  onEvent: (event: OntologyInvalidationEvent) => void,
): Promise<void> {
  if (!response.ok) {
    throw new Error(`ontology invalidation stream returned HTTP ${response.status}`);
  }
  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";
  if (!contentType.includes("text/event-stream")) {
    throw new Error("ontology invalidation stream returned an invalid content type");
  }
  if (!response.body) throw new Error("ontology invalidation stream response has no body");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const consumeBlock = (block: string): void => {
    const eventId = block.split("\n")
      .find((line) => line.startsWith("id:"))
      ?.slice(3).trim();
    const eventName = block.split("\n")
      .find((line) => line.startsWith("event:"))
      ?.slice(6).trim();
    if (eventName !== EVENT_NAME) return;
    const data = block.split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (!data) return;
    const event = decodeOntologyInvalidationEvent(data);
    if (event && eventId === String(event.watermark)) onEvent(event);
  };
  while (true) {
    const { value, done } = await readSseChunk(reader);
    buffer = (buffer + decoder.decode(value, { stream: !done })).replace(/\r\n/g, "\n");
    if (buffer.length > MAX_SSE_BUFFER_CHARS) {
      await reader.cancel("ontology invalidation SSE buffer exceeded its bound");
      throw new Error("ontology invalidation SSE buffer exceeded its bound");
    }
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

/** Keeps one authenticated invalidation stream connected only while its page is visible. */
export function useOntologyInvalidationStream(
  options: UseOntologyInvalidationStreamOptions,
): UseOntologyInvalidationStreamResult {
  const [status, setStatus] = useState<OntologyInvalidationStreamStatus>(
    typeof fetch === "undefined" ? "unsupported" : "idle",
  );
  const [lastError, setLastError] = useState<string | null>(null);
  const onEventRef = useRef(options.onEvent);
  const lastEventIdRef = useRef<string | null>(null);
  onEventRef.current = options.onEvent;

  useEffect(() => {
    if (typeof fetch === "undefined") return undefined;
    if (!options.enabled) {
      setStatus("idle");
      setLastError(null);
      return undefined;
    }
    let cancelled = false;
    let controller: AbortController | null = null;
    let reconnectTimer: number | null = null;
    let reconnectAttempt = 0;

    const isHidden = () => typeof document !== "undefined" && document.hidden;
    const scheduleReconnect = (): void => {
      if (cancelled || isHidden()) return;
      setStatus("reconnecting");
      const delay = ontologyInvalidationReconnectDelay(reconnectAttempt);
      reconnectAttempt += 1;
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        void connect();
      }, delay);
    };
    const connect = async (): Promise<void> => {
      if (cancelled || isHidden()) return;
      controller?.abort();
      controller = new AbortController();
      setStatus(reconnectAttempt === 0 ? "connecting" : "reconnecting");
      try {
        const authorization = await options.getAuthorizationHeader();
        const response = await fetch(options.url, {
          cache: "no-store",
          headers: ontologyInvalidationHeaders(authorization, lastEventIdRef.current),
          signal: controller.signal,
        });
        if (cancelled) return;
        setStatus("open");
        setLastError(null);
        reconnectAttempt = 0;
        await consumeOntologyInvalidationSse(response, (event) => {
          lastEventIdRef.current = String(event.watermark);
          onEventRef.current(event);
        });
        if (!cancelled) scheduleReconnect();
      } catch (error) {
        if (cancelled || controller.signal.aborted) return;
        setLastError(error instanceof Error ? error.message : String(error));
        scheduleReconnect();
      }
    };
    const onVisibility = (): void => {
      if (isHidden()) {
        controller?.abort();
        if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
        reconnectTimer = null;
        setStatus("idle");
        return;
      }
      reconnectAttempt = 0;
      void connect();
    };

    document.addEventListener("visibilitychange", onVisibility);
    void connect();
    return () => {
      cancelled = true;
      controller?.abort();
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [options.enabled, options.getAuthorizationHeader, options.url]);

  return { status, lastError };
}
