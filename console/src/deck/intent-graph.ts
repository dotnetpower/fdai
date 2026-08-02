import type {
  IntentEvidenceMode,
  IntentGraphEvidence,
  IntentGraphMetadata,
} from "./backend-types";

const GOAL_ID = /^[a-z][a-z0-9_-]{0,63}$/;
const MAX_GOALS = 8;
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
  if (!record || record.schema_version !== 2 || !Array.isArray(record.goals) ||
      record.goals.length < 1 || record.goals.length > MAX_GOALS ||
      typeof record.confidence !== "number" || record.confidence < 0 ||
      record.confidence > 1 ||
      !["advise_only", "draft_only"].includes(String(record.action_posture)) ||
      !(record.clarification === null || typeof record.clarification === "string")) {
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
  if (!record || record.schema_version !== 1 ||
      !["completed", "partial", "unavailable", "failed"].includes(String(record.status)) ||
      !EVIDENCE_MODES.includes(record.evidence_mode as IntentEvidenceMode) ||
      !Array.isArray(record.goals) || record.goals.length > MAX_GOALS) {
    return undefined;
  }
  const goals = record.goals.map(objectRecord);
  if (goals.some((goal) => goal === undefined)) return undefined;
  return {
    schema_version: 1,
    status: record.status as IntentGraphEvidence["status"],
    evidence_mode: record.evidence_mode as IntentEvidenceMode,
    goals: goals as readonly Readonly<Record<string, unknown>>[],
  };
}

function parseGoal(raw: unknown): IntentGraphMetadata["goals"][number] | undefined {
  const record = objectRecord(raw);
  if (!record || typeof record.goal_id !== "string" || !GOAL_ID.test(record.goal_id) ||
      typeof record.intent !== "string" ||
      !(record.capability === null || typeof record.capability === "string") ||
      !objectRecord(record.arguments) || !stringArray(record.depends_on, 7) ||
      typeof record.evidence_mode !== "string" ||
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
    evidence_mode: record.evidence_mode,
    freshness_required: record.freshness_required,
    confidence: record.confidence,
    alternatives: record.alternatives as readonly string[],
  };
}

function objectRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined;
}

function stringArray(value: unknown, maximum: number): boolean {
  return Array.isArray(value) && value.length <= maximum &&
    value.every((item) => typeof item === "string" && item.length <= 128);
}
