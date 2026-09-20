import { useEffect, useRef, useState } from "preact/hooks";
import {
  authenticatedSseHeaders,
  consumeSseFrames,
  isTransientSseStatus,
  sseReconnectDelay,
  useAuthenticatedSse,
} from "../hooks/sse-client";

export type OntologyInvalidationStreamStatus =
  | "idle"
  | "connecting"
  | "open"
  | "closed"
  | "reconnecting"
  | "unsupported";

export interface OntologyInvalidationEvent {
  readonly schema_version: "1.0.0" | "2.0.0";
  readonly epoch?: string;
  readonly reset_required?: boolean;
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
  readonly initialLastEventId?: string | null;
  readonly getAuthorizationHeader: () => Promise<string | null>;
  readonly onEvent: (event: OntologyInvalidationEvent) => void;
  readonly reloadSnapshot: (isCurrent: () => boolean) => Promise<void>;
}

export interface UseOntologyInvalidationStreamResult {
  readonly status: OntologyInvalidationStreamStatus;
  readonly lastError: string | null;
}

const EVENT_NAME = "inventory.invalidated";
const MAX_OBSERVATIONS_PER_EVENT = 500;
const MAX_SSE_BUFFER_CHARS = 64 * 1024;
const RFC3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
const EPOCH = /^[a-f0-9]{32}$/;
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
  const epochMode = event.schema_version === "2.0.0";
  if (
    Object.keys(event).some((key) => !ALLOWED_EVENT_KEYS.has(key) && !(epochMode && (key === "epoch" || key === "reset_required")))
    || (!epochMode && event.schema_version !== "1.0.0")
    || (epochMode && (typeof event.epoch !== "string" || !EPOCH.test(event.epoch) || typeof event.reset_required !== "boolean"))
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

export function ontologyInvalidationCursor(event: OntologyInvalidationEvent): string {
  return event.schema_version === "2.0.0" ? `${event.epoch}:${event.watermark}` : String(event.watermark);
}

export async function recoverOntologyInvalidationCursor(
  event: OntologyInvalidationEvent,
  reloadSnapshot: (isCurrent: () => boolean) => Promise<void>,
  isCurrent: () => boolean = () => true,
): Promise<string> {
  if (event.schema_version !== "2.0.0" || event.reset_required !== true) {
    throw new Error("Ontology cursor recovery requires an epoch reset");
  }
  let timeout: ReturnType<typeof setTimeout> | undefined;
  let active = true;
  try {
    await Promise.race([
      reloadSnapshot(() => active && isCurrent()),
      new Promise<never>((_, reject) => {
        timeout = setTimeout(() => reject(new Error("Ontology snapshot recovery timed out")), 10_000);
      }),
    ]);
    if (!isCurrent()) throw new Error("Ontology snapshot recovery was cancelled");
    return ontologyInvalidationCursor(event);
  } finally {
    active = false;
    clearTimeout(timeout);
  }
}

export function ontologyInvalidationHeaders(
  authorization: string | null,
  lastEventId: string | null,
): Headers {
  return authenticatedSseHeaders(authorization, lastEventId);
}

export function ontologyInvalidationReconnectDelay(attempt: number): number {
  return sseReconnectDelay(attempt);
}

export async function consumeOntologyInvalidationSse(
  response: Response,
  onEvent: (event: OntologyInvalidationEvent) => void,
): Promise<void> {
  await consumeSseFrames(response, (frame) => {
    if (frame.event !== EVENT_NAME) return;
    const event = decodeOntologyInvalidationEvent(frame.data);
    if (event && frame.id === ontologyInvalidationCursor(event)) onEvent(event);
  }, { maxBufferChars: MAX_SSE_BUFFER_CHARS });
}

/** Keeps one authenticated invalidation stream connected only while its page is visible. */
export function useOntologyInvalidationStream(
  options: UseOntologyInvalidationStreamOptions,
): UseOntologyInvalidationStreamResult {
  const [recoveredCursor, setRecoveredCursor] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);
  const resetPending = useRef(false);
  const lifetime = useRef(0);
  useEffect(() => {
    lifetime.current += 1;
    setRecoveredCursor(null);
    setResetting(false);
    setResetError(null);
    resetPending.current = false;
    return () => { lifetime.current += 1; };
  }, [options.url, options.getAuthorizationHeader]);
  const connection = useAuthenticatedSse({
    url: `${options.url}${options.url.includes("?") ? "&" : "?"}cursor_version=2`,
    enabled: options.enabled && !resetting && resetError === null,
    getAuthorizationHeader: options.getAuthorizationHeader,
    pauseWhenHidden: true,
    resumeFromLastEventId: true,
    initialLastEventId: recoveredCursor ?? options.initialLastEventId ?? null,
    shouldRetryStatus: retryOntologyStatus,
    maxBufferChars: MAX_SSE_BUFFER_CHARS,
    onFrame: (frame) => {
      if (frame.event !== EVENT_NAME) return false;
      const event = decodeOntologyInvalidationEvent(frame.data);
      if (!event || frame.id !== ontologyInvalidationCursor(event) || resetPending.current) return false;
      if (event.reset_required === true) {
        resetPending.current = true;
        setResetting(true);
        const current = lifetime.current;
        void recoverOntologyInvalidationCursor(event, options.reloadSnapshot, () => current === lifetime.current).then((cursor) => {
          if (current !== lifetime.current) return;
          setRecoveredCursor(cursor);
          options.onEvent(event);
          resetPending.current = false;
          setResetting(false);
        }).catch((error: unknown) => {
          if (current !== lifetime.current) return;
          setResetError(error instanceof Error ? error.message : "Ontology snapshot recovery failed");
          setResetting(false);
        });
        return false;
      }
      options.onEvent(event);
      return true;
    },
  });
  return {
    status: resetError ? "closed" : resetting ? "reconnecting" : connection.status,
    lastError: resetError ?? connection.lastError,
  };
}

function retryOntologyStatus(status: number): boolean {
  return status === 401 || isTransientSseStatus(status);
}
