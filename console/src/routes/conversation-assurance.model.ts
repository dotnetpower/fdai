import {
  panelArray,
  panelBoolean,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelNonNegativeNumber,
  panelRecord,
  panelString,
  panelStringArray,
} from "./panel-decode";

export type AssuranceVerdict = "pass" | "fail" | "inconclusive";

export interface AssuranceCriterionRow {
  readonly criterion: string;
  readonly score: number;
  readonly rationale: string;
  readonly evidence_refs: readonly string[];
}

export interface AssuranceAssessment {
  readonly assessment_id: string;
  readonly turn_id: string;
  readonly conversation_id: string;
  readonly state: "completed" | "deferred" | "disputed";
  readonly verdict: AssuranceVerdict;
  readonly content_score: number;
  readonly confidence: number;
  readonly criteria: readonly AssuranceCriterionRow[];
  readonly reasons: readonly string[];
  readonly evaluator_identities: readonly string[];
  readonly disagreement: boolean;
  readonly model_calls: number;
  readonly prompt_tokens: number;
  readonly completion_tokens: number;
  readonly cost_microusd: number;
  readonly rubric_version: string;
  readonly assessed_at: string;
}

export interface AssuranceDispute {
  readonly dispute_id: string;
  readonly assessment_id: string;
  readonly reason: string;
  readonly detail: string;
  readonly evidence_refs: readonly string[];
  readonly reported_at: string;
}

export interface ConversationAssurancePayload {
  readonly source: string;
  readonly read_only: true;
  readonly disputes_available: true;
  readonly policy_mutations_available: false;
  readonly summary: {
    readonly total: number;
    readonly pass: number;
    readonly fail: number;
    readonly inconclusive: number;
    readonly deferred: number;
    readonly disputes: number;
    readonly average_content_score: number | null;
    readonly model_calls: number;
    readonly cost_microusd: number;
  };
  readonly pantheon: PantheonAssuranceSummary;
  readonly assessments: readonly AssuranceAssessment[];
  readonly disputes: readonly AssuranceDispute[];
}

export interface PantheonAgentSummary {
  readonly agent: string;
  readonly turns: number;
  readonly average_score: number;
  readonly minimum_score: number;
  readonly pass: number;
  readonly review: number;
  readonly fail: number;
  readonly hard_zero_fail: number;
}

export interface PantheonAssuranceSummary {
  readonly available: boolean;
  readonly turns: number;
  readonly pass: number;
  readonly review: number;
  readonly fail: number;
  readonly hard_zero_fail: number;
  readonly average_score: number | null;
  readonly routing_accuracy: number | null;
  readonly missed_t2_rate: number | null;
  readonly unnecessary_t2_rate: number | null;
  readonly agents: readonly PantheonAgentSummary[];
}

export interface AssuranceDetailPayload {
  readonly assessment: AssuranceAssessment;
  readonly turn: {
    readonly available: boolean;
    readonly question: string | null;
    readonly answer: string | null;
  };
}

export function decodeConversationAssurance(value: unknown): ConversationAssurancePayload {
  const root = panelRecord(value, "conversation assurance");
  if (!panelBoolean(root, "read_only", "conversation assurance")) {
    throw new Error("invalid Operator API response: assurance projection MUST be read-only");
  }
  if (!panelBoolean(root, "disputes_available", "conversation assurance")) {
    throw new Error("invalid Operator API response: assurance disputes MUST be available");
  }
  if (panelBoolean(root, "policy_mutations_available", "conversation assurance")) {
    throw new Error("invalid Operator API response: assurance policy mutation is not allowed");
  }
  const summary = panelRecord(root["summary"], "conversation assurance.summary");
  const average = summary["average_content_score"] === null
    ? null
    : boundedScore(summary, "average_content_score", "conversation assurance.summary", 100);
  return {
    source: panelNonEmptyString(root, "source", "conversation assurance"),
    read_only: true,
    disputes_available: true,
    policy_mutations_available: false,
    summary: {
      total: panelNonNegativeInteger(summary, "total", "conversation assurance.summary"),
      pass: panelNonNegativeInteger(summary, "pass", "conversation assurance.summary"),
      fail: panelNonNegativeInteger(summary, "fail", "conversation assurance.summary"),
      inconclusive: panelNonNegativeInteger(summary, "inconclusive", "conversation assurance.summary"),
      deferred: panelNonNegativeInteger(summary, "deferred", "conversation assurance.summary"),
      disputes: panelNonNegativeInteger(summary, "disputes", "conversation assurance.summary"),
      average_content_score: average,
      model_calls: panelNonNegativeInteger(summary, "model_calls", "conversation assurance.summary"),
      cost_microusd: panelNonNegativeInteger(summary, "cost_microusd", "conversation assurance.summary"),
    },
    pantheon: decodePantheonSummary(root["pantheon"]),
    assessments: panelArray(root["assessments"], "conversation assurance.assessments")
      .map((item, index) => decodeAssessment(item, `conversation assurance.assessments[${index}]`)),
    disputes: panelArray(root["disputes"], "conversation assurance.disputes")
      .map((item, index) => decodeDispute(item, `conversation assurance.disputes[${index}]`)),
  };
}

function decodePantheonSummary(value: unknown): PantheonAssuranceSummary {
  const row = panelRecord(value, "conversation assurance.pantheon");
  const available = panelBoolean(row, "available", "conversation assurance.pantheon");
  const nullableMetric = (key: string) =>
    row[key] === null ? null : boundedScore(row, key, "conversation assurance.pantheon", 1);
  const average = row["average_score"] === null
    ? null
    : boundedScore(row, "average_score", "conversation assurance.pantheon", 30);
  const agents = panelArray(row["agents"], "conversation assurance.pantheon.agents")
    .map((item, index) => {
      const label = `conversation assurance.pantheon.agents[${index}]`;
      const agent = panelRecord(item, label);
      return {
        agent: panelNonEmptyString(agent, "agent", label),
        turns: panelNonNegativeInteger(agent, "turns", label),
        average_score: boundedScore(agent, "average_score", label, 30),
        minimum_score: boundedScore(agent, "minimum_score", label, 30),
        pass: panelNonNegativeInteger(agent, "pass", label),
        review: panelNonNegativeInteger(agent, "review", label),
        fail: panelNonNegativeInteger(agent, "fail", label),
        hard_zero_fail: panelNonNegativeInteger(agent, "hard_zero_fail", label),
      };
    });
  if (!available && (agents.length > 0 || average !== null)) {
    throw new Error("invalid Operator API response: unavailable Pantheon diagnostics contain measurements");
  }
  return {
    available,
    turns: panelNonNegativeInteger(row, "turns", "conversation assurance.pantheon"),
    pass: panelNonNegativeInteger(row, "pass", "conversation assurance.pantheon"),
    review: panelNonNegativeInteger(row, "review", "conversation assurance.pantheon"),
    fail: panelNonNegativeInteger(row, "fail", "conversation assurance.pantheon"),
    hard_zero_fail: panelNonNegativeInteger(row, "hard_zero_fail", "conversation assurance.pantheon"),
    average_score: average,
    routing_accuracy: nullableMetric("routing_accuracy"),
    missed_t2_rate: nullableMetric("missed_t2_rate"),
    unnecessary_t2_rate: nullableMetric("unnecessary_t2_rate"),
    agents,
  };
}

export function decodeAssuranceDetail(value: unknown): AssuranceDetailPayload {
  const root = panelRecord(value, "conversation assurance detail");
  const turn = panelRecord(root["turn"], "conversation assurance detail.turn");
  const available = panelBoolean(turn, "available", "conversation assurance detail.turn");
  const question = nullableString(turn, "question", "conversation assurance detail.turn");
  const answer = nullableString(turn, "answer", "conversation assurance detail.turn");
  if (available !== (answer !== null)) {
    throw new Error("invalid Operator API response: assurance turn availability is inconsistent");
  }
  return {
    assessment: decodeAssessment(root["assessment"], "conversation assurance detail.assessment"),
    turn: { available, question, answer },
  };
}

function decodeAssessment(value: unknown, label: string): AssuranceAssessment {
  const row = panelRecord(value, label);
  return {
    assessment_id: panelNonEmptyString(row, "assessment_id", label),
    turn_id: panelNonEmptyString(row, "turn_id", label),
    conversation_id: panelNonEmptyString(row, "conversation_id", label),
    state: enumValue(row, "state", label, ["completed", "deferred", "disputed"] as const),
    verdict: enumValue(row, "verdict", label, ["pass", "fail", "inconclusive"] as const),
    content_score: boundedScore(row, "content_score", label, 100),
    confidence: boundedScore(row, "confidence", label, 1),
    criteria: panelArray(row["criteria"], `${label}.criteria`).map((item, index) => {
      const criterion = panelRecord(item, `${label}.criteria[${index}]`);
      return {
        criterion: panelNonEmptyString(criterion, "criterion", `${label}.criteria[${index}]`),
        score: boundedScore(criterion, "score", `${label}.criteria[${index}]`, 4),
        rationale: panelNonEmptyString(criterion, "rationale", `${label}.criteria[${index}]`),
        evidence_refs: panelStringArray(criterion["evidence_refs"], `${label}.criteria[${index}].evidence_refs`),
      };
    }),
    reasons: panelStringArray(row["reasons"], `${label}.reasons`),
    evaluator_identities: panelStringArray(row["evaluator_identities"], `${label}.evaluator_identities`),
    disagreement: panelBoolean(row, "disagreement", label),
    model_calls: panelNonNegativeInteger(row, "model_calls", label),
    prompt_tokens: panelNonNegativeInteger(row, "prompt_tokens", label),
    completion_tokens: panelNonNegativeInteger(row, "completion_tokens", label),
    cost_microusd: panelNonNegativeInteger(row, "cost_microusd", label),
    rubric_version: panelNonEmptyString(row, "rubric_version", label),
    assessed_at: panelNonEmptyString(row, "assessed_at", label),
  };
}

function decodeDispute(value: unknown, label: string): AssuranceDispute {
  const row = panelRecord(value, label);
  return {
    dispute_id: panelNonEmptyString(row, "dispute_id", label),
    assessment_id: panelNonEmptyString(row, "assessment_id", label),
    reason: panelNonEmptyString(row, "reason", label),
    detail: panelNonEmptyString(row, "detail", label),
    evidence_refs: panelStringArray(row["evidence_refs"], `${label}.evidence_refs`),
    reported_at: panelNonEmptyString(row, "reported_at", label),
  };
}

function boundedScore(value: Readonly<Record<string, unknown>>, key: string, label: string, max: number): number {
  const item = panelNonNegativeNumber(value, key, label);
  if (item > max) throw new Error(`invalid Operator API response: ${label}.${key} MUST be <= ${max}`);
  return item;
}

function nullableString(value: Readonly<Record<string, unknown>>, key: string, label: string): string | null {
  return value[key] === null ? null : panelString(value, key, label);
}

function enumValue<const T extends readonly string[]>(value: Readonly<Record<string, unknown>>, key: string, label: string, allowed: T): T[number] {
  const item = panelString(value, key, label);
  if (!allowed.includes(item)) throw new Error(`invalid Operator API response: ${label}.${key} is unsupported`);
  return item as T[number];
}
