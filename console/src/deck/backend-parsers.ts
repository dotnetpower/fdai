import type {
  AnswerPlanMetadata,
  AnswerPlanningContributionMetadata,
  AnswerPlanningMetadata,
  GroundedCodeArtifact,
} from "./backend-types";

const CODE_SHA256 = /^[0-9a-f]{64}$/;
const CODE_LANGUAGE = /^[A-Za-z0-9_+#.-]{1,32}$/;
const MAX_CODE_ARTIFACTS = 8;
const MAX_CODE_CHARS = 64 * 1024;

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
    if (detail !== null && typeof detail !== "string") continue;
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
  const formats = ["prose", "bullets", "numbered_steps", "table", "checklist", "mixed"] as const;
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
  if (!Array.isArray(record.sections) || !record.sections.every((item) => typeof item === "string") || record.sections.length > 12) return undefined;
  const overrides = Array.isArray(record.explicit_overrides)
    ? record.explicit_overrides.filter((item): item is string => typeof item === "string").slice(0, 8)
    : [];
  return {
    intent: record.intent as AnswerPlanMetadata["intent"],
    detail_level: record.detail_level as AnswerPlanMetadata["detail_level"],
    format: record.format as AnswerPlanMetadata["format"],
    sections: record.sections,
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
  if (consulted === undefined || covered === undefined) return undefined;
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
