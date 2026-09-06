import { PANTHEON_NAME_SET, type PANTHEON_NAMES } from "../pantheon-names";

/** Goal-local advisory support; none of these fields grants execution authority. */
export interface AdaptiveGoalResult {
  readonly goal_id: string;
  readonly kind: "knowledge" | "operational" | "environment_example";
  readonly status: "answered" | "unavailable" | "held";
  readonly required: boolean;
  readonly evidence_refs: readonly string[];
  readonly limitation: string | null;
}

/** General advice is deliberately distinct from a verified operational answer. */
export interface AdaptiveAnswer {
  readonly answer: string;
  readonly goals: readonly AdaptiveGoalResult[];
  readonly role_agent: typeof PANTHEON_NAMES[number];
  readonly quality_status: "passed" | "limited";
  readonly refinements: 0 | 1;
  readonly execution_authority: false;
}

const SOURCE = "semantic-advisory-response";
const GOAL_ID = /^[a-z][a-z0-9_.-]{0,79}$/;

function hasWholeResponseSupport(value: Record<string, unknown>): boolean {
  return ["verification", "semantic_receipt", "action_draft", "presentation_artifact",
    "document_artifact", "chart_artifact", "intent_graph", "intent_graph_evidence",
    "ontology_release_digest", "principal_manifest_digest", "plan_digest",
    "execution_receipt_digest", "assurance_observation", "query_trajectory"].some(
    (key) => value[key] != null,
  ) || (value.evidence_refs != null &&
    (!Array.isArray(value.evidence_refs) || value.evidence_refs.length !== 0)) ||
    (value.checks_total != null && value.checks_total !== 0) ||
    (value.checks_completed != null && value.checks_completed !== 0) ||
    (value.checks_passed != null && value.checks_passed !== 0);
}

function record(raw: unknown): Record<string, unknown> | undefined {
  return typeof raw === "object" && raw !== null && !Array.isArray(raw)
    ? raw as Record<string, unknown>
    : undefined;
}

function boundedText(raw: unknown, maximum: number): raw is string {
  return typeof raw === "string" && raw.trim().length > 0 && raw.length <= maximum;
}

/** Validate persisted and live metadata without inferring support from prose. */
export function parseAdaptiveAnswer(raw: unknown, answer?: string): AdaptiveAnswer | undefined {
  const value = record(raw);
  if (!value || Object.keys(value).some((key) => ![
    "answer", "goals", "role_agent", "quality_status", "refinements", "execution_authority",
  ].includes(key)) ||
    !boundedText(value.answer, 16_000) ||
    (answer !== undefined && value.answer !== answer) ||
    typeof value.role_agent !== "string" || !PANTHEON_NAME_SET.has(value.role_agent) ||
    (value.quality_status !== "passed" && value.quality_status !== "limited") ||
    (value.refinements !== 0 && value.refinements !== 1) ||
    value.execution_authority !== false ||
    !Array.isArray(value.goals) || value.goals.length < 1 || value.goals.length > 8
  ) return undefined;
  const goals: AdaptiveGoalResult[] = [];
  for (const rawGoal of value.goals) {
    const goal = record(rawGoal);
    if (!goal || Object.keys(goal).some((key) => ![
      "goal_id", "kind", "status", "required", "evidence_refs", "limitation",
    ].includes(key)) ||
      typeof goal.goal_id !== "string" || !GOAL_ID.test(goal.goal_id) ||
      typeof goal.kind !== "string" ||
      !["knowledge", "operational", "environment_example"].includes(goal.kind) ||
      typeof goal.status !== "string" ||
      !["answered", "unavailable", "held"].includes(goal.status) ||
      typeof goal.required !== "boolean" ||
      !Array.isArray(goal.evidence_refs) || goal.evidence_refs.length > 12 ||
      goal.evidence_refs.some((ref) => !boundedText(ref, 256)) ||
      new Set(goal.evidence_refs).size !== goal.evidence_refs.length ||
      (goal.limitation != null && !boundedText(goal.limitation, 2_000)) ||
      (goal.kind === "knowledge" && goal.evidence_refs.length > 0) ||
      (goal.kind !== "knowledge" && goal.status === "answered" && goal.evidence_refs.length === 0) ||
      (goal.status !== "answered" && (
        goal.evidence_refs.length > 0 || !boundedText(goal.limitation, 2_000)
      ))
    ) return undefined;
    goals.push({
      goal_id: goal.goal_id,
      kind: goal.kind as AdaptiveGoalResult["kind"],
      status: goal.status as AdaptiveGoalResult["status"],
      required: goal.required,
      evidence_refs: goal.evidence_refs as string[],
      limitation: typeof goal.limitation === "string" ? goal.limitation : null,
    });
  }
  if (new Set(goals.map((goal) => goal.goal_id)).size !== goals.length ||
    (value.quality_status === "passed" &&
      goals.some((goal) => goal.required && goal.status !== "answered"))
  ) return undefined;
  return {
    answer: value.answer,
    goals,
    role_agent: value.role_agent as AdaptiveAnswer["role_agent"],
    quality_status: value.quality_status,
    refinements: value.refinements,
    execution_authority: false,
  };
}

/** Detect a claimed advisory terminal, including malformed metadata that must fail closed. */
export function hasAdvisoryResponse(raw: unknown): boolean {
  const value = record(raw);
  return value !== undefined && (
    value.status === "advisory_response" || value.source === SOURCE ||
    (value.adaptive_answer !== undefined && value.status !== "action_draft")
  );
}

/** Accept only a matching terminal without blanket verification or action artifacts. */
export function parseAdvisoryResponse(raw: unknown, requestId?: string): AdaptiveAnswer | undefined {
  const value = record(raw);
  if (!value || value.status !== "advisory_response" || value.source !== SOURCE ||
    value.execution_authority !== false ||
    (requestId !== undefined && value.request_id !== requestId) ||
    hasWholeResponseSupport(value)
  ) return undefined;
  const adaptive = typeof value.answer === "string"
    ? parseAdaptiveAnswer(value.adaptive_answer, value.answer)
    : undefined;
  if (!adaptive) return undefined;
  if (value.semantic_result != null) {
    const semantic = record(value.semantic_result);
    if (!semantic || semantic.disposition !== "advisory_response" ||
      hasWholeResponseSupport(semantic) ||
      semantic.semantic_route !== "semantic_advisory_response" ||
      semantic.answer !== adaptive.answer || semantic.execution_authority !== false ||
      JSON.stringify(parseAdaptiveAnswer(semantic.adaptive_answer, adaptive.answer)) !==
        JSON.stringify(adaptive)
    ) return undefined;
  }
  return adaptive;
}

/** An explanation supplements a governed draft; it never replaces its canonical fields. */
export function parseActionDraftExplanation(raw: unknown, requestId?: string): AdaptiveAnswer | undefined {
  const value = record(raw);
  if (!value || value.status !== "action_draft" || value.source === SOURCE ||
    value.execution_authority !== false
  ) return undefined;
  const receipt = record(value.semantic_receipt);
  if (requestId !== undefined && (value.request_id ?? receipt?.request_id) !== requestId) return undefined;
  const adaptive = parseAdaptiveAnswer(value.adaptive_answer);
  if (!adaptive) return undefined;
  if (value.semantic_result != null) {
    const semantic = record(value.semantic_result);
    if (!semantic || semantic.disposition !== "action_draft" ||
      semantic.execution_authority !== false || semantic.answer !== value.answer ||
      JSON.stringify(parseAdaptiveAnswer(semantic.adaptive_answer)) !== JSON.stringify(adaptive)
    ) return undefined;
  }
  return adaptive;
}
