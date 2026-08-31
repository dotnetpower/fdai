/**
 * Provisioning progress stream hook (surface B consumer).
 *
 * Subscribes to the Operator API's `GET /provision/stream` SSE endpoint via
 * authenticated fetch and decodes the `provision.*` events documented in
 * {@link fdai.delivery.operator_api.provision_stream}. It mirrors
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
import { readSseChunk, SSE_INACTIVITY_TIMEOUT_MS } from "./sse-reader";

/** Provisioning phase carried by the durable status projection. */
export type ProvisionPhase =
  | "snapshot"
  | "progress"
  | "waiting"
  | "resumed"
  | "done"
  | "failed";

export type ProvisionStageStatus =
  | "pending"
  | "active"
  | "waiting"
  | "completed"
  | "blocked"
  | "failed"
  | "cancelled"
  | "incomplete";

export interface ProvisionStage {
  readonly id: string;
  readonly status: ProvisionStageStatus;
}

export interface ProvisionReadiness {
  readonly database: boolean;
  readonly semantic: boolean;
  readonly models: boolean;
  readonly runtime: boolean;
  readonly inventory: boolean;
  readonly system: boolean;
}

export interface ProvisionInventoryProgress {
  readonly resources_observed: number | null;
  readonly resources_expected: number | null;
  readonly pages_completed: number | null;
  readonly pages_expected: number | null;
}

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
  readonly run_id?: string;
  readonly sequence?: number;
  readonly attempt?: number;
  readonly state?: string;
  readonly current_stage?: string;
  readonly stages_completed?: number;
  readonly stages_total?: number;
  readonly checkpoints_completed?: number;
  readonly checkpoints_total?: number;
  readonly last_progress_at?: string;
  readonly reason_code?: string | null;
  readonly ready?: boolean;
  readonly readiness?: ProvisionReadiness;
  readonly stages?: readonly ProvisionStage[];
  readonly inventory?: ProvisionInventoryProgress;
  /** Durable SSE replay cursor from the frame `id` field. */
  readonly stream_id?: number;
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
  /** Connect only after the read-source manifest declares an authoritative relay. */
  readonly enabled?: boolean;
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
  "snapshot",
  "waiting",
  "resumed",
  "done",
  "failed",
]);

const _STAGE_STATUSES: ReadonlySet<string> = new Set([
  "pending",
  "active",
  "waiting",
  "completed",
  "blocked",
  "failed",
  "cancelled",
  "incomplete",
]);

const _RUN_STATES: ReadonlySet<string> = new Set([
  "planning",
  "waiting",
  "applying",
  "verifying",
  "completed",
  "ready",
  "blocked",
  "failed",
  "cancelled",
  "incomplete",
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
    run_id?: string;
    sequence?: number;
    attempt?: number;
    state?: string;
    current_stage?: string;
    stages_completed?: number;
    stages_total?: number;
    checkpoints_completed?: number;
    checkpoints_total?: number;
    last_progress_at?: string;
    reason_code?: string | null;
    ready?: boolean;
    readiness?: ProvisionReadiness;
    stages?: readonly ProvisionStage[];
    inventory?: ProvisionInventoryProgress;
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
  if (phase === "snapshot") {
    const snapshot = decodeProvisionSnapshot(raw);
    if (snapshot === null) return null;
    Object.assign(event, snapshot);
  }
  return event;
}

function decodeProvisionSnapshot(
  raw: Readonly<Record<string, unknown>>,
): Omit<ProvisionEvent, "type" | "phase"> | null {
  const runId = boundedText(raw.run_id);
  const state = boundedText(raw.state);
  const currentStage = boundedText(raw.current_stage);
  const lastProgressAt = boundedText(raw.last_progress_at);
  const sequence = nonNegativeInteger(raw.sequence);
  const attempt = nonNegativeInteger(raw.attempt);
  const stagesCompleted = nonNegativeInteger(raw.stages_completed);
  const stagesTotal = positiveInteger(raw.stages_total);
  if (
    runId === null ||
    state === null ||
    currentStage === null ||
    lastProgressAt === null ||
    sequence === null ||
    sequence < 1 ||
    attempt === null ||
    attempt < 1 ||
    stagesCompleted === null ||
    stagesTotal === null ||
    stagesCompleted > stagesTotal ||
    typeof raw.ready !== "boolean"
  ) return null;
  const readiness = decodeReadiness(raw.readiness);
  const stages = decodeStages(raw.stages, stagesTotal);
  const completedStageIds =
    stages === null
      ? new Set<string>()
      : new Set(stages.filter((stage) => stage.status === "completed").map((stage) => stage.id));
  const currentStatus = stages?.find((stage) => stage.id === currentStage)?.status;
  const expectedCurrentStatus: ProvisionStageStatus | undefined = {
    planning: "active",
    applying: "active",
    verifying: "active",
    waiting: "waiting",
    completed: "completed",
    ready: "completed",
    blocked: "blocked",
    failed: "failed",
    cancelled: "cancelled",
    incomplete: "incomplete",
  }[state] as ProvisionStageStatus | undefined;
  if (
    readiness === null ||
    stages === null ||
    !_RUN_STATES.has(state) ||
    !stages.some((stage) => stage.id === currentStage) ||
    currentStatus !== expectedCurrentStatus ||
    stages.filter((stage) => stage.status === "completed").length !== stagesCompleted ||
    readiness.database !== completedStageIds.has("database") ||
    readiness.semantic !== completedStageIds.has("semantic-defaults") ||
    readiness.models !== completedStageIds.has("model-deployments") ||
    readiness.runtime !== completedStageIds.has("console") ||
    readiness.inventory !== completedStageIds.has("initial-inventory") ||
    (raw.ready && (
      state !== "ready" ||
      !Object.values(readiness).every(Boolean) ||
      stagesCompleted !== stagesTotal
    )) ||
    (!raw.ready && (state === "ready" || readiness.system))
  ) return null;
  const snapshot: {
    run_id: string;
    sequence: number;
    attempt: number;
    state: string;
    current_stage: string;
    stages_completed: number;
    stages_total: number;
    last_progress_at: string;
    ready: boolean;
    readiness: ProvisionReadiness;
    stages: readonly ProvisionStage[];
    checkpoints_completed?: number;
    checkpoints_total?: number;
    reason_code?: string | null;
    inventory?: ProvisionInventoryProgress;
  } = {
    run_id: runId,
    sequence,
    attempt,
    state,
    current_stage: currentStage,
    stages_completed: stagesCompleted,
    stages_total: stagesTotal,
    last_progress_at: lastProgressAt,
    ready: raw.ready,
    readiness,
    stages,
  };
  const checkpointsCompleted = optionalNonNegativeInteger(raw.checkpoints_completed);
  const checkpointsTotal = optionalNonNegativeInteger(raw.checkpoints_total);
  if (checkpointsCompleted === false || checkpointsTotal === false) return null;
  if ((checkpointsCompleted === null) !== (checkpointsTotal === null)) return null;
  if (
    typeof checkpointsCompleted === "number" &&
    typeof checkpointsTotal === "number" &&
    checkpointsCompleted > checkpointsTotal
  ) return null;
  if (typeof checkpointsCompleted === "number") {
    snapshot.checkpoints_completed = checkpointsCompleted;
    snapshot.checkpoints_total = checkpointsTotal as number;
  }
  if (raw.reason_code === null || typeof raw.reason_code === "string") {
    snapshot.reason_code = raw.reason_code;
  } else if (raw.reason_code !== undefined) {
    return null;
  }
  if (raw.inventory !== undefined) {
    const inventory = decodeInventory(raw.inventory);
    if (inventory === null) return null;
    snapshot.inventory = inventory;
  }
  return snapshot;
}

function decodeReadiness(value: unknown): ProvisionReadiness | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const raw = value as Record<string, unknown>;
  const keys = ["database", "semantic", "models", "runtime", "inventory", "system"] as const;
  if (keys.some((key) => typeof raw[key] !== "boolean")) return null;
  return {
    database: raw.database as boolean,
    semantic: raw.semantic as boolean,
    models: raw.models as boolean,
    runtime: raw.runtime as boolean,
    inventory: raw.inventory as boolean,
    system: raw.system as boolean,
  };
}

function decodeStages(value: unknown, expectedTotal: number): readonly ProvisionStage[] | null {
  if (!Array.isArray(value) || value.length !== expectedTotal || value.length > 100) return null;
  const stages: ProvisionStage[] = [];
  const ids = new Set<string>();
  for (const item of value) {
    if (typeof item !== "object" || item === null || Array.isArray(item)) return null;
    const raw = item as Record<string, unknown>;
    const id = boundedText(raw.id);
    const status = raw.status;
    if (id === null || ids.has(id) || typeof status !== "string" || !_STAGE_STATUSES.has(status)) {
      return null;
    }
    ids.add(id);
    stages.push({ id, status: status as ProvisionStageStatus });
  }
  return stages;
}

function decodeInventory(value: unknown): ProvisionInventoryProgress | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const raw = value as Record<string, unknown>;
  const resourcesObserved = nullableNonNegativeInteger(raw.resources_observed);
  const resourcesExpected = nullableNonNegativeInteger(raw.resources_expected);
  const pagesCompleted = nullableNonNegativeInteger(raw.pages_completed);
  const pagesExpected = nullableNonNegativeInteger(raw.pages_expected);
  if (
    resourcesObserved === false ||
    resourcesExpected === false ||
    pagesCompleted === false ||
    pagesExpected === false ||
    (resourcesObserved === null) !== (resourcesExpected === null) ||
    (pagesCompleted === null) !== (pagesExpected === null)
  ) return null;
  return {
    resources_observed: resourcesObserved,
    resources_expected: resourcesExpected,
    pages_completed: pagesCompleted,
    pages_expected: pagesExpected,
  };
}

function boundedText(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 && value.length <= 256 ? value : null;
}

function nonNegativeInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

function positiveInteger(value: unknown): number | null {
  const result = nonNegativeInteger(value);
  return result !== null && result > 0 ? result : null;
}

function optionalNonNegativeInteger(value: unknown): number | null | false {
  return value === undefined ? null : nonNegativeInteger(value) ?? false;
}

function nullableNonNegativeInteger(value: unknown): number | null | false {
  return value === null ? null : nonNegativeInteger(value) ?? false;
}

export function provisionStreamHeaders(
  authorization: string | null,
  lastEventId: number | null = null,
): Headers {
  const headers = new Headers({ accept: "text/event-stream" });
  if (authorization) headers.set("authorization", authorization);
  if (lastEventId !== null) headers.set("last-event-id", String(lastEventId));
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
  inactivityTimeoutMs = SSE_INACTIVITY_TIMEOUT_MS,
  onCursor?: (sequence: number) => void,
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
    const lines = block.split("\n");
    const idLine = lines.find((line) => line.startsWith("id:"));
    const rawId = idLine?.slice(3).trim();
    const streamId = rawId && /^[0-9]+$/.test(rawId) ? Number(rawId) : null;
    if (streamId !== null && Number.isSafeInteger(streamId)) onCursor?.(streamId);
    const data = lines
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (!data) return;
    const event = decodeProvisionEvent(data);
    if (!event) return;
    onEvent(
      streamId !== null && Number.isSafeInteger(streamId)
        ? { ...event, stream_id: streamId }
        : event,
    );
  };

  try {
    while (true) {
      const { value, done } = await readSseChunk(reader, inactivityTimeoutMs);
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
  } catch (error) {
    await reader.cancel(error).catch(() => undefined);
    throw error;
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
  const enabled = options.enabled ?? true;
  const getAuthorizationHeader = options.getAuthorizationHeader;

  useEffect(() => {
    if (!enabled || typeof fetch === "undefined") {
      setStatus(enabled ? "unsupported" : "idle");
      setLastError(null);
      return undefined;
    }

    let cancelled = false;
    let controller: AbortController | null = null;
    let reconnectTimer: number | null = null;
    let reconnectAttempt = 0;
    let permanentFailure = false;
    let lastEventId: number | null = null;

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
          headers: provisionStreamHeaders(authorization, lastEventId),
          credentials: "omit",
          signal: active.signal,
        });
        if (!response.ok) {
          permanentFailure = isPermanentProvisionFailure(response.status);
          throw new Error(`provisioning stream returned HTTP ${response.status}`);
        }
        publishStatus("open");
        setLastError(null);
        await consumeProvisionSse(
          response,
          (event) => {
            if (!cancelled && controller === active) {
              reconnectAttempt = 0;
              onEventRef.current(event);
            }
          },
          SSE_INACTIVITY_TIMEOUT_MS,
          (sequence) => {
            if (lastEventId === null || sequence > lastEventId) lastEventId = sequence;
          },
        );
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
  }, [enabled, url, getAuthorizationHeader]);

  return { status, lastError };
}
