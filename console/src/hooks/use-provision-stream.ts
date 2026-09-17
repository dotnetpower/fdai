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

import {
  authenticatedSseHeaders,
  consumeSseFrames,
  isTransientSseStatus,
  sseReconnectDelay,
  useAuthenticatedSse,
} from "./sse-client";
import { SSE_INACTIVITY_TIMEOUT_MS } from "./sse-reader";

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
  readonly provider_types_completed: number;
  readonly provider_types_total: number;
  readonly links_observed: number;
  readonly unmapped_objects: number;
  readonly coverage_gaps: number;
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
  readonly attempt_id?: string;
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
    attempt_id?: string;
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
  if (phase === "progress" && (raw.run_id !== undefined || raw.inventory !== undefined)) {
    const runId = boundedText(raw.run_id);
    const attemptId = boundedText(raw.attempt_id);
    const sequence = positiveInteger(raw.sequence);
    const state = boundedText(raw.state);
    const currentStage = boundedText(raw.current_stage);
    const inventory = decodeInventory(raw.inventory);
    if (
      runId === null || attemptId === null || sequence === null || state === null ||
      currentStage === null || inventory === null
    ) return null;
    event.run_id = runId;
    event.attempt_id = attemptId;
    event.sequence = sequence;
    event.state = state;
    event.current_stage = currentStage;
    event.inventory = inventory;
    if (raw.reason_code === null || typeof raw.reason_code === "string") {
      event.reason_code = raw.reason_code;
    } else if (raw.reason_code !== undefined) {
      return null;
    }
  }
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
  const providerTypesCompleted = nonNegativeInteger(raw.provider_types_completed);
  const providerTypesTotal = nonNegativeInteger(raw.provider_types_total);
  const linksObserved = nonNegativeInteger(raw.links_observed);
  const unmappedObjects = nonNegativeInteger(raw.unmapped_objects);
  const coverageGaps = nonNegativeInteger(raw.coverage_gaps);
  if (
    resourcesObserved === false ||
    resourcesExpected === false ||
    pagesCompleted === false ||
    pagesExpected === false ||
    (pagesCompleted === null) !== (pagesExpected === null) ||
    providerTypesCompleted === null || providerTypesTotal === null ||
    providerTypesCompleted > providerTypesTotal || linksObserved === null ||
    unmappedObjects === null || coverageGaps === null
  ) return null;
  return {
    resources_observed: resourcesObserved,
    resources_expected: resourcesExpected,
    pages_completed: pagesCompleted,
    pages_expected: pagesExpected,
    provider_types_completed: providerTypesCompleted,
    provider_types_total: providerTypesTotal,
    links_observed: linksObserved,
    unmapped_objects: unmappedObjects,
    coverage_gaps: coverageGaps,
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
  return authenticatedSseHeaders(
    authorization,
    lastEventId === null ? null : String(lastEventId),
  );
}

export function provisionReconnectDelay(attempt: number): number {
  return sseReconnectDelay(attempt);
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
  await consumeSseFrames(response, (frame) => {
    const streamId = frame.id && /^[0-9]+$/.test(frame.id)
      ? Number(frame.id)
      : null;
    if (streamId !== null && Number.isSafeInteger(streamId)) onCursor?.(streamId);
    const event = decodeProvisionEvent(frame.data);
    if (!event) return;
    onEvent(
      streamId !== null && Number.isSafeInteger(streamId)
        ? { ...event, stream_id: streamId }
        : event,
    );
  }, { inactivityTimeoutMs });
}

/**
 * Attach an authenticated fetch stream to the provisioning SSE endpoint.
 * Every decoded frame is passed to `onEvent`; the hook aborts on unmount.
 */
export function useProvisionStream(
  options: UseProvisionStreamOptions,
): UseProvisionStreamResult {
  const url = options.url;
  const enabled = options.enabled ?? true;
  const connection = useAuthenticatedSse({
    url,
    enabled,
    getAuthorizationHeader: options.getAuthorizationHeader ?? noAuthorization,
    pauseWhenHidden: true,
    resumeFromLastEventId: true,
    shouldRetryStatus: isTransientSseStatus,
    onStatus: (next) => options.onStatus?.(next),
    onFrame: (frame) => {
      const event = decodeProvisionEvent(frame.data);
      if (!event) return false;
      const streamId = frame.id && /^[0-9]+$/.test(frame.id)
        ? Number(frame.id)
        : null;
      options.onEvent(
        streamId !== null && Number.isSafeInteger(streamId)
          ? { ...event, stream_id: streamId }
          : event,
      );
      return true;
    },
  });
  return {
    status: connection.status,
    lastError: connection.lastError,
  };
}

async function noAuthorization(): Promise<null> {
  return null;
}
