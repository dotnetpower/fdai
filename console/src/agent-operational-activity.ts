export type OperationalActivityKind =
  | "inventory.scan"
  | "inventory.ontology-projection"
  | "current-state.read";

export type OperationalActivityStatus =
  | "started"
  | "completed"
  | "failed"
  | "superseded"
  | "degraded";

export type OperationalFreshness = "fresh" | "stale" | "unavailable" | "unknown";

export interface AgentOperationalActivityMessage {
  readonly type: "agent.operational-activity";
  readonly schema_version: "1.0.0";
  readonly activity_id: string;
  readonly idempotency_key: string;
  readonly kind: OperationalActivityKind;
  readonly status: OperationalActivityStatus;
  readonly owner_agent: "Huginn" | "Heimdall";
  readonly producer: "inventory-sync-job" | "core-control-plane";
  readonly observed_at: string;
  readonly source: string;
  readonly freshness: OperationalFreshness;
  readonly evidence_count: number;
  readonly duration_ms: number | null;
  readonly correlation_id: string | null;
  readonly reason_codes: readonly string[];
  readonly execution_authority: false;
}

export interface AgentOperationalActivityPage {
  readonly items: readonly AgentOperationalActivityMessage[];
  readonly snapshot_at: string;
  readonly source: string;
}

const KINDS = new Set<string>([
  "inventory.scan",
  "inventory.ontology-projection",
  "current-state.read",
]);
const STATUSES = new Set<string>([
  "started", "completed", "failed", "superseded", "degraded",
]);
const FRESHNESS = new Set<string>(["fresh", "stale", "unavailable", "unknown"]);
const OWNERS = new Set<string>(["Huginn", "Heimdall"]);
const PRODUCERS = new Set<string>(["inventory-sync-job", "core-control-plane"]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function boundedText(value: unknown, maximum: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maximum;
}

export function decodeAgentOperationalActivity(
  value: unknown,
): AgentOperationalActivityMessage | null {
  if (!isRecord(value)) return null;
  if (
    value.type !== "agent.operational-activity" || value.schema_version !== "1.0.0" ||
    !boundedText(value.activity_id, 512) || !boundedText(value.idempotency_key, 512) ||
    typeof value.kind !== "string" || !KINDS.has(value.kind) ||
    typeof value.status !== "string" || !STATUSES.has(value.status) ||
    typeof value.owner_agent !== "string" || !OWNERS.has(value.owner_agent) ||
    typeof value.producer !== "string" || !PRODUCERS.has(value.producer) ||
    !boundedText(value.observed_at, 64) || Number.isNaN(Date.parse(value.observed_at)) ||
    !boundedText(value.source, 128) ||
    typeof value.freshness !== "string" || !FRESHNESS.has(value.freshness) ||
    !Number.isInteger(value.evidence_count) || Number(value.evidence_count) < 0 ||
    Number(value.evidence_count) > 1_000_000 ||
    !(value.duration_ms === null || (
      Number.isInteger(value.duration_ms) && Number(value.duration_ms) >= 0 &&
      Number(value.duration_ms) <= 86_400_000
    )) ||
    !(value.correlation_id === null || boundedText(value.correlation_id, 512)) ||
    !Array.isArray(value.reason_codes) || value.reason_codes.length > 16 ||
    !value.reason_codes.every((reason) => boundedText(reason, 128)) ||
    new Set(value.reason_codes).size !== value.reason_codes.length ||
    value.execution_authority !== false
  ) return null;
  if (
    (value.kind === "inventory.scan" &&
      (value.owner_agent !== "Huginn" || value.producer !== "inventory-sync-job")) ||
    (value.kind === "current-state.read" &&
      (value.owner_agent !== "Heimdall" || value.producer !== "core-control-plane")) ||
    (value.kind === "inventory.ontology-projection" &&
      (value.owner_agent !== "Heimdall" || value.producer !== "inventory-sync-job"))
  ) return null;
  return value as unknown as AgentOperationalActivityMessage;
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
