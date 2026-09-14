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
    if (event && frame.id === String(event.watermark)) onEvent(event);
  }, { maxBufferChars: MAX_SSE_BUFFER_CHARS });
}

/** Keeps one authenticated invalidation stream connected only while its page is visible. */
export function useOntologyInvalidationStream(
  options: UseOntologyInvalidationStreamOptions,
): UseOntologyInvalidationStreamResult {
  const connection = useAuthenticatedSse({
    url: options.url,
    enabled: options.enabled,
    getAuthorizationHeader: options.getAuthorizationHeader,
    pauseWhenHidden: true,
    resumeFromLastEventId: true,
    shouldRetryStatus: retryOntologyStatus,
    maxBufferChars: MAX_SSE_BUFFER_CHARS,
    onFrame: (frame) => {
      if (frame.event !== EVENT_NAME) return false;
      const event = decodeOntologyInvalidationEvent(frame.data);
      if (!event || frame.id !== String(event.watermark)) return false;
      options.onEvent(event);
      return true;
    },
  });
  return {
    status: connection.status,
    lastError: connection.lastError,
  };
}

function retryOntologyStatus(status: number): boolean {
  return status === 401 || isTransientSseStatus(status);
}
