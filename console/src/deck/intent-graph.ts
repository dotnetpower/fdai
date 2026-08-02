import type {
  IntentEvidenceMode,
  IntentGraphEvidence,
  IntentGraphMetadata,
} from "./backend-types";

const GOAL_ID = /^[a-z][a-z0-9_-]{0,63}$/;
const MAX_GOALS = 8;
const GRAPH_FIELDS = ["schema_version", "goals", "clarification", "confidence", "action_posture"];
const GOAL_FIELDS = [
  "goal_id", "intent", "capability", "arguments", "depends_on", "evidence_mode",
  "freshness_required", "confidence", "alternatives",
];
const RECEIPT_FIELDS = [
  "task_id", "goal_id", "intent", "capability", "evidence_mode", "status", "duration_ms",
  "depends_on", "reason", "blocked_by", "evidence_refs", "started_at", "completed_at",
];
const GOAL_EVIDENCE_MODES = ["screen", "catalog", "operational", "web", "model_knowledge", "mixed"];
const RECEIPT_STATUSES = ["completed", "unavailable", "failed", "timed_out", "skipped"];
const EVIDENCE_MODES: readonly IntentEvidenceMode[] = [
  "screen_grounded",
  "operational_grounded",
  "web_grounded",
  "mixed_grounded",
  "model_knowledge",
  "partial",
  "held_for_review",
];

export function parseIntentGraph(raw: unknown): IntentGraphMetadata | undefined {
  const record = objectRecord(raw);
  if (!record || !hasExactKeys(record, GRAPH_FIELDS) || record.schema_version !== 2 ||
      !Array.isArray(record.goals) ||
      record.goals.length < 1 || record.goals.length > MAX_GOALS ||
      typeof record.confidence !== "number" || record.confidence < 0 ||
      record.confidence > 1 ||
      !["advise_only", "draft_only"].includes(String(record.action_posture)) ||
      !(record.clarification === null || boundedString(record.clarification, 512))) {
    return undefined;
  }
  const goals = record.goals.map(parseGoal);
  if (goals.some((goal) => goal === undefined)) return undefined;
  return {
    schema_version: 2,
    goals: goals as IntentGraphMetadata["goals"],
    clarification: record.clarification as string | null,
    confidence: record.confidence,
    action_posture: record.action_posture as IntentGraphMetadata["action_posture"],
  };
}

export function parseIntentGraphEvidence(raw: unknown): IntentGraphEvidence | undefined {
  const record = objectRecord(raw);
  if (!record || !hasExactKeys(record, ["schema_version", "status", "evidence_mode", "goals"]) ||
      record.schema_version !== 1 ||
      !["completed", "partial", "unavailable", "failed"].includes(String(record.status)) ||
      !EVIDENCE_MODES.includes(record.evidence_mode as IntentEvidenceMode) ||
      !Array.isArray(record.goals) || record.goals.length > MAX_GOALS) {
    return undefined;
  }
  const goals = record.goals.map(parseReceipt);
  if (goals.some((goal) => goal === undefined)) return undefined;
  return {
    schema_version: 1,
    status: record.status as IntentGraphEvidence["status"],
    evidence_mode: record.evidence_mode as IntentEvidenceMode,
    goals: goals as IntentGraphEvidence["goals"],
  };
}

function parseGoal(raw: unknown): IntentGraphMetadata["goals"][number] | undefined {
  const record = objectRecord(raw);
  if (!record || !hasExactKeys(record, GOAL_FIELDS) ||
      typeof record.goal_id !== "string" || !GOAL_ID.test(record.goal_id) ||
      !boundedString(record.intent, 64) ||
      !(record.capability === null || boundedString(record.capability, 128)) ||
      !boundedJsonObject(record.arguments) || !stringArray(record.depends_on, 7) ||
      !GOAL_EVIDENCE_MODES.includes(String(record.evidence_mode)) ||
      typeof record.freshness_required !== "boolean" ||
      typeof record.confidence !== "number" || record.confidence < 0 || record.confidence > 1 ||
      !stringArray(record.alternatives, 4)) {
    return undefined;
  }
  return {
    goal_id: record.goal_id,
    intent: record.intent,
    capability: record.capability as string | null,
    arguments: record.arguments as Readonly<Record<string, unknown>>,
    depends_on: record.depends_on as readonly string[],
    evidence_mode: record.evidence_mode as string,
    freshness_required: record.freshness_required,
    confidence: record.confidence,
    alternatives: record.alternatives as readonly string[],
  };
}

function parseReceipt(raw: unknown): IntentGraphEvidence["goals"][number] | undefined {
  const record = objectRecord(raw);
  if (!record || !hasAllowedKeys(record, RECEIPT_FIELDS) ||
      !boundedString(record.task_id, 256) ||
      typeof record.goal_id !== "string" || !GOAL_ID.test(record.goal_id) ||
      !boundedString(record.intent, 64) ||
      !(record.capability === null || boundedString(record.capability, 128)) ||
      !GOAL_EVIDENCE_MODES.includes(String(record.evidence_mode)) ||
      !RECEIPT_STATUSES.includes(String(record.status)) ||
      !Number.isSafeInteger(record.duration_ms) || Number(record.duration_ms) < 0 ||
      Number(record.duration_ms) > 86_400_000 || !stringArray(record.depends_on, 7) ||
      !(record.reason === undefined || boundedString(record.reason, 128)) ||
      !(record.blocked_by === undefined || stringArray(record.blocked_by, 7)) ||
      !(record.evidence_refs === undefined || stringArray(record.evidence_refs, 12, 512)) ||
      !isoTimestamp(record.started_at) || !isoTimestamp(record.completed_at)) {
    return undefined;
  }
  return {
    task_id: record.task_id,
    goal_id: record.goal_id,
    intent: record.intent,
    capability: record.capability as string | null,
    evidence_mode: record.evidence_mode as string,
    status: record.status as IntentGraphEvidence["goals"][number]["status"],
    duration_ms: record.duration_ms as number,
    depends_on: record.depends_on as readonly string[],
    ...(record.reason === undefined ? {} : { reason: record.reason as string }),
    ...(record.blocked_by === undefined
      ? {}
      : { blocked_by: record.blocked_by as readonly string[] }),
    ...(record.evidence_refs === undefined
      ? {}
      : { evidence_refs: record.evidence_refs as readonly string[] }),
    started_at: record.started_at,
    completed_at: record.completed_at,
  };
}

function objectRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined;
}

function stringArray(value: unknown, maximum: number, maxItemLength = 128): boolean {
  return Array.isArray(value) && value.length <= maximum &&
    value.every((item) => boundedString(item, maxItemLength));
}

function boundedString(value: unknown, maximum: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maximum;
}

function isoTimestamp(value: unknown): value is string {
  return boundedString(value, 64) && Number.isFinite(Date.parse(value));
}

function hasExactKeys(record: Record<string, unknown>, expected: readonly string[]): boolean {
  return Object.keys(record).length === expected.length && hasAllowedKeys(record, expected);
}

function hasAllowedKeys(record: Record<string, unknown>, allowed: readonly string[]): boolean {
  const allowedSet = new Set(allowed);
  return Object.keys(record).every((key) => allowedSet.has(key));
}

function boundedJsonObject(value: unknown): value is Readonly<Record<string, unknown>> {
  const seen = new Set<object>();
  let nodes = 0;
  function visit(candidate: unknown, depth: number): boolean {
    nodes += 1;
    if (nodes > 128 || depth > 4) return false;
    if (candidate === null || typeof candidate === "boolean" ||
        (typeof candidate === "number" && Number.isFinite(candidate))) return true;
    if (typeof candidate === "string") return candidate.length <= 1024;
    if (typeof candidate !== "object" || seen.has(candidate)) return false;
    seen.add(candidate);
    if (Array.isArray(candidate)) {
      return candidate.length <= 32 && candidate.every((item) => visit(item, depth + 1));
    }
    const entries = Object.entries(candidate as Record<string, unknown>);
    return entries.length <= 32 && entries.every(([key, nested]) =>
      key.length > 0 && key.length <= 128 && visit(nested, depth + 1));
  }
  return objectRecord(value) !== undefined && visit(value, 0);
}
