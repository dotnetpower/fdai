import type {
  AnswerPlanMetadata,
  AnswerPlanningContributionMetadata,
  AnswerPlanningMetadata,
  GroundedCodeArtifact,
  ModelTrace,
  ModelTraceCall,
  TurnTiming,
  TurnTimingPhase,
} from "./backend-types";

const CODE_SHA256 = /^[0-9a-f]{64}$/;
const CODE_LANGUAGE = /^[A-Za-z0-9_+#.-]{1,32}$/;
const MAX_CODE_ARTIFACTS = 8;
const MAX_CODE_CHARS = 64 * 1024;
const MAX_CODE_VALIDATION_DETAIL_CHARS = 4 * 1024;
const MAX_ANSWER_PLAN_SECTION_CHARS = 64;
const MAX_ANSWER_PLAN_OVERRIDE_CHARS = 128;
const SHA256 = /^[0-9a-f]{64}$/;
const MAX_MODEL_TRACE_CALLS = 8;
const MAX_MODEL_TRACE_MESSAGES = 24;
const MAX_MODEL_TRACE_REQUEST_CHARS = 12_000;
const MAX_MODEL_TRACE_RESPONSE_CHARS = 6_000;
const MAX_MODEL_TRACE_REDACTIONS = 16;
const MAX_TURN_TIMING_PHASES = 8;
const MAX_TURN_DURATION_MS = 7_200_000;
const TURN_TIMING_PHASES = [
  "semantic_plan",
  "evidence",
  "generation",
  "quality_review",
  "verification",
] as const;
const TURN_TIMING_STATUSES = [
  "completed",
  "corrected",
  "degraded",
  "failed",
  "unverified",
] as const;

export function parseTurnTiming(raw: unknown): TurnTiming | undefined {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return undefined;
  const record = raw as Record<string, unknown>;
  if (record.schema_version !== 1 || !validTimestamp(record.started_at) ||
      !validTimestamp(record.completed_at) ||
      !boundedInteger(record.duration_ms, 0, MAX_TURN_DURATION_MS) ||
      !durationMatches(record.started_at, record.completed_at, record.duration_ms) ||
      !Array.isArray(record.phases) || record.phases.length > MAX_TURN_TIMING_PHASES) {
    return undefined;
  }
  const phases: TurnTimingPhase[] = [];
  for (const rawPhase of record.phases) {
    const phase = parseTurnTimingPhase(rawPhase, record.started_at, record.completed_at);
    if (!phase) return undefined;
    phases.push(phase);
  }
  if (new Set(phases.map((phase) => phase.phase)).size !== phases.length) return undefined;
  if (phases.some((phase, index) => index > 0 &&
    Date.parse(phase.started_at) < Date.parse(phases[index - 1]!.started_at))) return undefined;
  return {
    schema_version: 1,
    started_at: record.started_at,
    completed_at: record.completed_at,
    duration_ms: record.duration_ms,
    phases,
  };
}

function parseTurnTimingPhase(
  raw: unknown,
  envelopeStart: string,
  envelopeEnd: string,
): TurnTimingPhase | undefined {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return undefined;
  const record = raw as Record<string, unknown>;
  if (!TURN_TIMING_PHASES.includes(record.phase as TurnTimingPhase["phase"]) ||
      !TURN_TIMING_STATUSES.includes(record.status as TurnTimingPhase["status"]) ||
      !validTimestamp(record.started_at) || !validTimestamp(record.completed_at) ||
      !boundedInteger(record.duration_ms, 0, MAX_TURN_DURATION_MS) ||
      !durationMatches(record.started_at, record.completed_at, record.duration_ms)) {
    return undefined;
  }
  if (Date.parse(record.started_at) < Date.parse(envelopeStart) ||
      Date.parse(record.completed_at) > Date.parse(envelopeEnd)) return undefined;
  if ((record.status === "corrected" || record.status === "unverified") &&
      record.phase !== "verification") return undefined;
  return {
    phase: record.phase as TurnTimingPhase["phase"],
    status: record.status as TurnTimingPhase["status"],
    started_at: record.started_at,
    completed_at: record.completed_at,
    duration_ms: record.duration_ms,
  };
}

function durationMatches(startedAt: string, completedAt: string, durationMs: number): boolean {
  const observed = Date.parse(completedAt) - Date.parse(startedAt);
  return observed >= 0 && Math.abs(observed - durationMs) <= 1;
}

export function parseModelTrace(raw: unknown): ModelTrace | undefined {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return undefined;
  const record = raw as Record<string, unknown>;
  if (record.schema_version !== 1 || record.redacted !== true) return undefined;
  if (!Array.isArray(record.calls) || record.calls.length > MAX_MODEL_TRACE_CALLS) return undefined;
  if (!boundedInteger(record.omitted_calls, 0, 10_000)) return undefined;
  const calls: ModelTraceCall[] = [];
  for (const rawCall of record.calls) {
    const call = parseModelTraceCall(rawCall);
    if (!call) return undefined;
    calls.push(call);
  }
  if (new Set(calls.map((call) => call.call_id)).size !== calls.length) return undefined;
  return {
    schema_version: 1,
    redacted: true,
    calls,
    omitted_calls: record.omitted_calls,
  };
}

function parseModelTraceCall(raw: unknown): ModelTraceCall | undefined {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return undefined;
  const call = raw as Record<string, unknown>;
  if (!boundedString(call.call_id, 128) || !boundedString(call.kind, 128) ||
      !boundedString(call.model, 128) || (call.status !== "completed" && call.status !== "incomplete") ||
      !validTimestamp(call.started_at)) return undefined;
  const completedAt = call.completed_at === null ? null
    : validTimestamp(call.completed_at) ? call.completed_at : undefined;
  const durationMs = call.duration_ms === null ? null
    : boundedInteger(call.duration_ms, 0, 7_200_000) ? call.duration_ms : undefined;
  if (completedAt === undefined || durationMs === undefined) return undefined;
  if (completedAt !== null && Date.parse(completedAt) < Date.parse(call.started_at)) return undefined;
  const request = parseModelTraceRequest(call.request);
  const response = call.response === null ? null : parseModelTraceResponse(call.response);
  const usage = call.usage === null ? null : parseModelTraceUsage(call.usage);
  const redactions = parseModelTraceRedactions(call.redactions);
  if (!request || response === undefined || usage === undefined || !redactions) return undefined;
  if (call.status === "completed" && (completedAt === null || durationMs === null || response === null)) {
    return undefined;
  }
  if (call.status === "incomplete" && (completedAt !== null || durationMs !== null || response !== null)) {
    return undefined;
  }
  return {
    call_id: call.call_id,
    kind: call.kind,
    model: call.model,
    status: call.status,
    started_at: call.started_at,
    completed_at: completedAt,
    duration_ms: durationMs,
    request,
    response,
    usage,
    redactions,
  };
}

function parseModelTraceRequest(raw: unknown): ModelTraceCall["request"] | undefined {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return undefined;
  const request = raw as Record<string, unknown>;
  if (!Array.isArray(request.messages) || request.messages.length > MAX_MODEL_TRACE_MESSAGES ||
      typeof request.sha256 !== "string" || !SHA256.test(request.sha256)) return undefined;
  let totalChars = 0;
  const messages: ModelTraceCall["request"]["messages"][number][] = [];
  for (const rawMessage of request.messages) {
    if (typeof rawMessage !== "object" || rawMessage === null || Array.isArray(rawMessage)) {
      return undefined;
    }
    const message = rawMessage as Record<string, unknown>;
    if (!(["system", "user", "assistant", "tool"] as const).includes(
      message.role as "system" | "user" | "assistant" | "tool",
    ) || typeof message.content !== "string") return undefined;
    totalChars += message.content.length;
    if (totalChars > MAX_MODEL_TRACE_REQUEST_CHARS) return undefined;
    messages.push({
      role: message.role as "system" | "user" | "assistant" | "tool",
      content: message.content,
    });
  }
  return { messages, sha256: request.sha256 };
}

function parseModelTraceResponse(raw: unknown): NonNullable<ModelTraceCall["response"]> | undefined {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return undefined;
  const response = raw as Record<string, unknown>;
  if (response.role !== "assistant" || typeof response.content !== "string" ||
      response.content.length > MAX_MODEL_TRACE_RESPONSE_CHARS ||
      typeof response.sha256 !== "string" || !SHA256.test(response.sha256)) return undefined;
  return { role: "assistant", content: response.content, sha256: response.sha256 };
}

function parseModelTraceUsage(raw: unknown): Readonly<Record<string, number>> | undefined {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return undefined;
  const usage = raw as Record<string, unknown>;
  const output: Record<string, number> = {};
  for (const key of ["prompt_tokens", "completion_tokens", "total_tokens"] as const) {
    const value = usage[key];
    if (value !== undefined) {
      if (!boundedInteger(value, 0, Number.MAX_SAFE_INTEGER)) return undefined;
      output[key] = value;
    }
  }
  return Object.keys(output).length > 0 ? output : undefined;
}

function parseModelTraceRedactions(raw: unknown): ModelTraceCall["redactions"] | undefined {
  if (!Array.isArray(raw) || raw.length > MAX_MODEL_TRACE_REDACTIONS) return undefined;
  const redactions: Array<{ readonly rule: string; readonly replacements: number }> = [];
  for (const item of raw) {
    if (typeof item !== "object" || item === null || Array.isArray(item)) return undefined;
    const redaction = item as Record<string, unknown>;
    if (!boundedString(redaction.rule, 64) || !boundedInteger(redaction.replacements, 1, 100_000)) {
      return undefined;
    }
    redactions.push({ rule: redaction.rule, replacements: redaction.replacements });
  }
  return redactions;
}

function validTimestamp(value: unknown): value is string {
  return typeof value === "string" && value.length <= 64 && Number.isFinite(Date.parse(value));
}

export function parseGroundedCodeArtifacts(raw: unknown): GroundedCodeArtifact[] {
  if (!Array.isArray(raw)) return [];
  const artifacts: GroundedCodeArtifact[] = [];
  for (const item of raw.slice(0, MAX_CODE_ARTIFACTS)) {
    if (typeof item !== "object" || item === null || Array.isArray(item)) continue;
    const record = item as Record<string, unknown>;
    const sha256 = record.sha256;
    const artifactRef = record.artifact_ref;
    const language = record.language;
    const content = record.content;
    const status = record.validation_status;
    const detail = record.validation_detail;
    if (typeof sha256 !== "string" || !CODE_SHA256.test(sha256)) continue;
    if (artifactRef !== `code:sha256:${sha256}`) continue;
    if (typeof language !== "string" || !CODE_LANGUAGE.test(language)) continue;
    if (typeof content !== "string" || content.length > MAX_CODE_CHARS) continue;
    if (status !== "valid" && status !== "invalid" && status !== "not_checked") continue;
    if (
      detail !== null &&
      (typeof detail !== "string" || detail.length > MAX_CODE_VALIDATION_DETAIL_CHARS)
    ) continue;
    artifacts.push({
      artifact_ref: artifactRef,
      language,
      content,
      sha256,
      validation_status: status,
      validation_detail: detail,
    });
  }
  return artifacts;
}

export function parseAnswerPlan(raw: unknown): AnswerPlanMetadata | undefined {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return undefined;
  const record = raw as Record<string, unknown>;
  const intents = ["definition", "why", "procedure", "comparison", "diagnosis", "status", "list", "summary", "proposal", "open_question", "greeting"] as const;
  const details = ["brief", "standard", "deep"] as const;
  const formats = ["prose", "bullets", "numbered_steps", "table", "chart", "checklist", "mixed"] as const;
  const evidence = ["none", "screen", "catalog", "server_read_model", "agent_owned"] as const;
  const discuss = ["skip", "shadow", "selective"] as const;
  if (!intents.includes(record.intent as typeof intents[number])) return undefined;
  if (!details.includes(record.detail_level as typeof details[number])) return undefined;
  if (!formats.includes(record.format as typeof formats[number])) return undefined;
  if (!evidence.includes(record.evidence_requirement as typeof evidence[number])) return undefined;
  if (!discuss.includes(record.discuss as typeof discuss[number])) return undefined;
  if (record.preference_applied !== undefined && typeof record.preference_applied !== "boolean") {
    return undefined;
  }
  if (typeof record.max_words !== "number" || !Number.isInteger(record.max_words) || record.max_words < 1 || record.max_words > 2000) return undefined;
  const sections = boundedStringArray(record.sections, 12, MAX_ANSWER_PLAN_SECTION_CHARS);
  const overrides = boundedStringArray(
    record.explicit_overrides ?? [],
    8,
    MAX_ANSWER_PLAN_OVERRIDE_CHARS,
  );
  if (sections === undefined || overrides === undefined) return undefined;
  return {
    intent: record.intent as AnswerPlanMetadata["intent"],
    detail_level: record.detail_level as AnswerPlanMetadata["detail_level"],
    format: record.format as AnswerPlanMetadata["format"],
    sections,
    evidence_requirement: record.evidence_requirement as AnswerPlanMetadata["evidence_requirement"],
    max_words: record.max_words,
    discuss: record.discuss as AnswerPlanMetadata["discuss"],
    explicit_overrides: overrides,
    preference_applied: record.preference_applied === true,
  };
}

export function parseAnswerPlanning(raw: unknown): AnswerPlanningMetadata | undefined {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return undefined;
  const record = raw as Record<string, unknown>;
  const statuses = ["skipped", "completed", "degraded", "timed_out"] as const;
  if (record.mode !== "shadow") return undefined;
  if (!statuses.includes(record.status as typeof statuses[number])) return undefined;
  if (record.primary_agent !== null && !boundedString(record.primary_agent, 64)) return undefined;
  const consulted = boundedStringArray(record.consulted_agents, 2, 64);
  const covered = boundedStringArray(record.covered_sections, 12, 64);
  const conflicts = boundedStringArray(record.conflicting_evidence_refs, 32, 512);
  if (consulted === undefined || covered === undefined || conflicts === undefined) return undefined;
  if (!Array.isArray(record.contributions) || record.contributions.length > 2) return undefined;
  const contributions: AnswerPlanningContributionMetadata[] = [];
  for (const rawContribution of record.contributions) {
    if (typeof rawContribution !== "object" || rawContribution === null) return undefined;
    const contribution = rawContribution as Record<string, unknown>;
    const evidenceRefs = boundedStringArray(contribution.evidence_refs, 32, 512);
    const sections = boundedStringArray(contribution.suggested_sections, 12, 64);
    if (!boundedString(contribution.agent, 64) || evidenceRefs === undefined || sections === undefined) {
      return undefined;
    }
    if (typeof contribution.confidence !== "number" || !Number.isFinite(contribution.confidence)
      || contribution.confidence < 0 || contribution.confidence > 1) return undefined;
    contributions.push({
      agent: contribution.agent,
      evidence_refs: evidenceRefs,
      confidence: contribution.confidence,
      suggested_sections: sections,
    });
  }
  if (!Array.isArray(record.failures) || record.failures.length > 3) return undefined;
  const failures: { readonly agent: string; readonly kind: string }[] = [];
  for (const rawFailure of record.failures) {
    if (typeof rawFailure !== "object" || rawFailure === null) return undefined;
    const failure = rawFailure as Record<string, unknown>;
    if (!boundedString(failure.agent, 64) || !boundedString(failure.kind, 64)) return undefined;
    failures.push({ agent: failure.agent, kind: failure.kind });
  }
  if (!boundedInteger(record.elapsed_ms, 0, 5_000)) return undefined;
  if (!boundedInteger(record.unique_evidence_count, 0, 64)) return undefined;
  if (!boundedInteger(record.duplicate_evidence_count, 0, 64)) return undefined;
  if (!boundedInteger(record.estimated_added_tokens, 0, 800)) return undefined;
  if (typeof record.budget !== "object" || record.budget === null || Array.isArray(record.budget)) {
    return undefined;
  }
  const budget = record.budget as Record<string, unknown>;
  if (!boundedInteger(budget.max_contributors, 1, 2) || budget.max_rounds !== 1
    || !boundedInteger(budget.max_wall_ms, 1, 1_200)
    || !boundedInteger(budget.max_added_tokens, 1, 800)
    || budget.nested_rounds !== false) return undefined;
  if (record.reason !== null && !boundedString(record.reason, 64)) return undefined;
  return {
    mode: "shadow",
    status: record.status as AnswerPlanningMetadata["status"],
    primary_agent: record.primary_agent,
    consulted_agents: consulted,
    contributions,
    failures,
    elapsed_ms: record.elapsed_ms,
    unique_evidence_count: record.unique_evidence_count,
    duplicate_evidence_count: record.duplicate_evidence_count,
    conflicting_evidence_refs: conflicts,
    covered_sections: covered,
    estimated_added_tokens: record.estimated_added_tokens,
    budget: {
      max_contributors: budget.max_contributors,
      max_rounds: 1,
      max_wall_ms: budget.max_wall_ms,
      max_added_tokens: budget.max_added_tokens,
      nested_rounds: false,
    },
    reason: record.reason,
  };
}

function boundedString(value: unknown, maxLength: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maxLength;
}

function boundedStringArray(
  value: unknown,
  maxItems: number,
  maxLength: number,
): readonly string[] | undefined {
  if (!Array.isArray(value) || value.length > maxItems) return undefined;
  return value.every((item) => boundedString(item, maxLength)) ? value : undefined;
}

function boundedInteger(value: unknown, minimum: number, maximum: number): value is number {
  return typeof value === "number" && Number.isInteger(value)
    && value >= minimum && value <= maximum;
}
