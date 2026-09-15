export type OperationalActivityKind =
  | "inventory.scan"
  | "inventory.ontology-projection"
  | "current-state.read"
  | "observation"
  | "assurance-twin.posture";

export type ObservationDomain =
  | "inventory"
  | "activity-log"
  | "resource-health"
  | "service-health"
  | "metrics"
  | "logs"
  | "guest-logs"
  | "network-config"
  | "cost"
  | "recovery";

export type OperationalActivityStatus =
  | "started"
  | "completed"
  | "failed"
  | "superseded"
  | "degraded";

export type OperationalFreshness = "fresh" | "stale" | "unavailable" | "unknown";

export type OperationalActivitySummaryKey =
  | "inventory_collection"
  | "ontology_projection"
  | "current_state_observation"
  | "source_observation"
  | "assurance_posture";

export type OperationalActivityScopeClass =
  | "configured-estate"
  | "source-domain"
  | "investigation"
  | "change-review";

export type OperationalActivityResultState =
  | "measured"
  | "not-recorded"
  | "unavailable";

export type OperationalActivityResultUnit =
  | "evidence-items"
  | "resources"
  | "records"
  | "signals"
  | "receipts";

interface AgentOperationalActivityBase {
  readonly type: "agent.operational-activity";
  readonly activity_id: string;
  readonly idempotency_key: string;
  readonly kind: OperationalActivityKind;
  readonly status: OperationalActivityStatus;
  readonly owner_agent: "Huginn" | "Heimdall" | "Njord" | "Freyr" | "Vidar";
  readonly producer:
    | "inventory-sync-job"
    | "core-control-plane"
    | "observation-campaign-job"
    | "assurance-twin";
  readonly observation_domain: ObservationDomain | null;
  readonly observed_at: string;
  readonly source: string;
  readonly freshness: OperationalFreshness;
  readonly evidence_count: number;
  readonly duration_ms: number | null;
  readonly correlation_id: string | null;
  readonly reason_codes: readonly string[];
  readonly execution_authority: false;
}

export interface LegacyAgentOperationalActivityMessage
  extends AgentOperationalActivityBase {
  readonly schema_version: "1.0.0" | "1.1.0" | "1.2.0";
  readonly activity_instance_id?: never;
  readonly summary_key?: never;
  readonly scope_class?: never;
  readonly target_count?: never;
  readonly result_state?: never;
  readonly result_count?: never;
  readonly result_unit?: never;
  readonly source_cutoff?: never;
  readonly started_at?: never;
  readonly completed_at?: never;
}

interface AgentOperationalActivityV13Base extends AgentOperationalActivityBase {
  readonly schema_version: "1.3.0";
  readonly activity_instance_id: string;
  readonly summary_key: OperationalActivitySummaryKey;
  readonly scope_class: OperationalActivityScopeClass;
  readonly target_count: number | null;
  readonly source_cutoff: string | null;
  readonly started_at: string | null;
  readonly completed_at: string | null;
}

export type AgentOperationalActivityV13Message =
  AgentOperationalActivityV13Base & (
    | {
        readonly result_state: "measured";
        readonly result_count: number;
        readonly result_unit: OperationalActivityResultUnit;
      }
    | {
        readonly result_state: Exclude<OperationalActivityResultState, "measured">;
        readonly result_count: null;
        readonly result_unit: null;
      }
  );

export type AgentOperationalActivityMessage =
  | LegacyAgentOperationalActivityMessage
  | AgentOperationalActivityV13Message;

export interface AgentOperationalActivityPage {
  readonly items: readonly AgentOperationalActivityMessage[];
  readonly snapshot_at: string;
  readonly source: string;
}

const KINDS = new Set<string>([
  "inventory.scan",
  "inventory.ontology-projection",
  "current-state.read",
  "observation",
  "assurance-twin.posture",
]);
const SCHEMA_VERSIONS = new Set<string>(["1.0.0", "1.1.0", "1.2.0", "1.3.0"]);
const STATUSES = new Set<string>([
  "started", "completed", "failed", "superseded", "degraded",
]);
const FRESHNESS = new Set<string>(["fresh", "stale", "unavailable", "unknown"]);
const OWNERS = new Set<string>(["Huginn", "Heimdall", "Njord", "Freyr", "Vidar"]);
const PRODUCERS = new Set<string>([
  "inventory-sync-job", "core-control-plane", "observation-campaign-job", "assurance-twin",
]);
const OBSERVATION_DOMAINS = new Set<string>([
  "inventory", "activity-log", "resource-health", "service-health", "metrics", "logs",
  "guest-logs", "network-config", "cost", "recovery",
]);
const OBSERVATION_REASON_CODE = /^[a-z][a-z0-9_]{0,127}$/;
const SUMMARY_KEYS = new Set<string>([
  "inventory_collection", "ontology_projection", "current_state_observation",
  "source_observation", "assurance_posture",
]);
const SCOPE_CLASSES = new Set<string>([
  "configured-estate", "source-domain", "investigation", "change-review",
]);
const RESULT_STATES = new Set<string>(["measured", "not-recorded", "unavailable"]);
const RESULT_UNITS = new Set<string>([
  "evidence-items", "resources", "records", "signals", "receipts",
]);
const V13_FIELDS = [
  "activity_instance_id", "summary_key", "scope_class", "target_count",
  "result_state", "result_count", "result_unit", "source_cutoff", "started_at",
  "completed_at",
] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function boundedText(value: unknown, maximum: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maximum;
}

function boundedCount(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0 && Number(value) <= 1_000_000;
}

function optionalTimestamp(value: unknown): value is string | null {
  return value === null || (
    boundedText(value, 64) && !Number.isNaN(Date.parse(value))
  );
}

export function decodeAgentOperationalActivity(
  value: unknown,
): AgentOperationalActivityMessage | null {
  if (!isRecord(value)) return null;
  if (
    value.type !== "agent.operational-activity" ||
    typeof value.schema_version !== "string" || !SCHEMA_VERSIONS.has(value.schema_version) ||
    !boundedText(value.activity_id, 512) || !boundedText(value.idempotency_key, 512) ||
    typeof value.kind !== "string" || !KINDS.has(value.kind) ||
    typeof value.status !== "string" || !STATUSES.has(value.status) ||
    typeof value.owner_agent !== "string" || !OWNERS.has(value.owner_agent) ||
    typeof value.producer !== "string" || !PRODUCERS.has(value.producer) ||
    !boundedText(value.observed_at, 64) || Number.isNaN(Date.parse(value.observed_at)) ||
    !boundedText(value.source, 128) ||
    typeof value.freshness !== "string" || !FRESHNESS.has(value.freshness) ||
    !boundedCount(value.evidence_count) ||
    !(value.duration_ms === null || (
      Number.isInteger(value.duration_ms) && Number(value.duration_ms) >= 0 &&
      Number(value.duration_ms) <= 86_400_000
    )) ||
    !(value.correlation_id === null || boundedText(value.correlation_id, 512)) ||
    !Array.isArray(value.reason_codes) || value.reason_codes.length > 16 ||
    !value.reason_codes.every((reason) =>
      boundedText(reason, 128) && OBSERVATION_REASON_CODE.test(reason)
    ) ||
    new Set(value.reason_codes).size !== value.reason_codes.length ||
    value.execution_authority !== false
  ) return null;
  const observationDomain = value.observation_domain;
  const isV13 = value.schema_version === "1.3.0";
  if (isV13) {
    if (
      !V13_FIELDS.every((field) => field in value) ||
      !boundedText(value.activity_instance_id, 512) ||
      typeof value.summary_key !== "string" || !SUMMARY_KEYS.has(value.summary_key) ||
      typeof value.scope_class !== "string" || !SCOPE_CLASSES.has(value.scope_class) ||
      !(value.target_count === null || boundedCount(value.target_count)) ||
      typeof value.result_state !== "string" || !RESULT_STATES.has(value.result_state) ||
      !(value.result_count === null || boundedCount(value.result_count)) ||
      !(value.result_unit === null || (
        typeof value.result_unit === "string" && RESULT_UNITS.has(value.result_unit)
      )) ||
      !optionalTimestamp(value.source_cutoff) ||
      !optionalTimestamp(value.started_at) ||
      !optionalTimestamp(value.completed_at) ||
      !presentationMatches(value.kind, value.summary_key, value.scope_class) ||
      (value.result_state === "measured" && (
        value.result_count === null ||
        value.result_unit === null ||
        value.result_count !== value.evidence_count
      )) ||
      (value.result_state !== "measured" && (
        value.result_count !== null ||
        value.result_unit !== null ||
        value.evidence_count !== 0
      )) ||
      (value.status === "started" && value.result_state !== "not-recorded") ||
      (value.status === "failed" && value.result_state !== "unavailable") ||
      (
        (value.status === "completed" || value.status === "superseded") &&
        value.result_state === "unavailable"
      ) ||
      (value.status === "started" && value.completed_at !== null) ||
      (
        typeof value.started_at === "string" &&
        typeof value.completed_at === "string" &&
        Date.parse(value.completed_at) < Date.parse(value.started_at)
      )
    ) return null;
  } else if (V13_FIELDS.some((field) => field in value)) {
    return null;
  }
  if (
    (value.kind === "inventory.scan" &&
      (value.owner_agent !== "Huginn" || value.producer !== "inventory-sync-job")) ||
    (value.kind === "current-state.read" &&
      (value.owner_agent !== "Heimdall" || value.producer !== "core-control-plane")) ||
    (value.kind === "inventory.ontology-projection" &&
      (value.owner_agent !== "Heimdall" || value.producer !== "inventory-sync-job")) ||
    (value.kind === "assurance-twin.posture" && (
      (value.schema_version !== "1.2.0" && value.schema_version !== "1.3.0") ||
      value.owner_agent !== "Heimdall" || value.producer !== "assurance-twin" ||
      !value.reason_codes.every((reason) => OBSERVATION_REASON_CODE.test(String(reason)))
    )) ||
    (value.kind !== "assurance-twin.posture" && value.producer === "assurance-twin") ||
    (value.kind === "observation" && (
      (value.schema_version !== "1.1.0" && value.schema_version !== "1.3.0") ||
      typeof observationDomain !== "string" || !OBSERVATION_DOMAINS.has(observationDomain) ||
      value.producer !== "observation-campaign-job" ||
      !observationOwnerMatches(observationDomain, value.owner_agent) ||
      !value.reason_codes.every((reason) => OBSERVATION_REASON_CODE.test(String(reason)))
    )) ||
    (value.kind !== "observation" && observationDomain !== undefined && observationDomain !== null)
  ) return null;
  const normalized = {
    ...value,
    observation_domain: typeof observationDomain === "string" ? observationDomain : null,
  };
  return isV13
    ? normalized as unknown as AgentOperationalActivityV13Message
    : normalized as unknown as LegacyAgentOperationalActivityMessage;
}

function presentationMatches(
  kind: unknown,
  summaryKey: unknown,
  scopeClass: unknown,
): boolean {
  if (kind === "inventory.scan") {
    return summaryKey === "inventory_collection" && scopeClass === "configured-estate";
  }
  if (kind === "inventory.ontology-projection") {
    return summaryKey === "ontology_projection" && scopeClass === "configured-estate";
  }
  if (kind === "current-state.read") {
    return summaryKey === "current_state_observation" && scopeClass === "investigation";
  }
  if (kind === "observation") {
    return summaryKey === "source_observation" && scopeClass === "source-domain";
  }
  return summaryKey === "assurance_posture" && scopeClass === "change-review";
}

function observationOwnerMatches(domain: string, owner: unknown): boolean {
  if (domain === "inventory" || domain === "activity-log") return owner === "Huginn";
  if (domain === "cost") return owner === "Njord";
  if (domain === "recovery") return owner === "Vidar";
  if (domain === "metrics") return owner === "Heimdall" || owner === "Freyr";
  return owner === "Heimdall";
}

export function decodeAgentOperationalActivityPage(value: unknown): AgentOperationalActivityPage {
  if (!isRecord(value) || !Array.isArray(value.items) ||
    typeof value.snapshot_at !== "string" || typeof value.source !== "string") {
    throw new Error("agent activity response is malformed");
  }
  const items = value.items.map(decodeAgentOperationalActivity);
  if (items.some((item) => item === null)) throw new Error("agent activity item is malformed");
  return {
    items: items as AgentOperationalActivityMessage[],
    snapshot_at: value.snapshot_at,
    source: value.source,
  };
}
