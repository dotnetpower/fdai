import {
  decodeOutcomeAssuranceProjection,
  type OutcomeAssuranceMetric,
  type OutcomeAssuranceProjection,
  type OutcomeAssuranceReadState,
  type OutcomeAssuranceUnavailableReason,
} from "../api-outcome-assurance";
import {
  panelArray,
  panelBoolean,
  panelContractError,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelNullableString,
  panelRatio,
  panelRecord,
  panelString,
  panelStringArray,
} from "./panel-decode";

export type OutcomeAssuranceLocale = "en" | "ko";
export type OutcomeAssuranceSummaryCardId =
  | "operational_readiness"
  | "objective_alignment"
  | "control_assurance";

export interface OutcomeAssuranceSummaryCard {
  readonly card_id: OutcomeAssuranceSummaryCardId;
  readonly state: string;
  readonly available: boolean;
  readonly headline_metric: number | null;
  readonly unit: string | null;
  readonly reason: OutcomeAssuranceUnavailableReason | null;
  readonly evidence_refs: readonly string[];
}

export interface ObjectiveAttributionDrilldown {
  readonly objective_ref: string;
  readonly state: "unattributed" | "partial" | "attributed" | "unavailable";
  readonly workflow_refs: readonly string[];
  readonly action_type_ids: readonly string[];
  readonly finalized_events: number;
  readonly attributed_events: number;
  readonly unattributed_events: number;
  readonly coverage: number | null;
  readonly metrics: readonly OutcomeAssuranceMetric[];
  readonly evidence_refs: readonly string[];
  readonly reason: OutcomeAssuranceUnavailableReason | null;
}

export interface OutcomeAssuranceGuardEvaluation {
  readonly guard_id: string;
  readonly threshold: number;
  readonly observed_value: number;
  readonly passed: boolean;
  readonly evidence_ref: string;
}

export interface OutcomeAssuranceOperatorProjectionPayload {
  readonly type: "outcome-assurance.operator-projection";
  readonly schema_version: "1.0.0";
  readonly read_only: true;
  readonly authority: "none";
  readonly principal_id: string;
  readonly state: OutcomeAssuranceReadState;
  readonly reason: OutcomeAssuranceUnavailableReason | null;
  readonly summary_cards: readonly OutcomeAssuranceSummaryCard[];
  readonly objective_drilldowns: readonly ObjectiveAttributionDrilldown[];
  readonly guard_status: {
    readonly state: string;
    readonly reason: OutcomeAssuranceUnavailableReason | null;
    readonly policy_escape_count: number;
    readonly guard_evaluations: readonly OutcomeAssuranceGuardEvaluation[];
    readonly evidence_refs: readonly string[];
  };
  readonly projection: OutcomeAssuranceProjection;
}

export interface FormattedSummaryCard {
  readonly cardId: OutcomeAssuranceSummaryCardId;
  readonly title: string;
  readonly stateLabel: string;
  readonly available: boolean;
  readonly headlineDisplay: string;
  readonly evidenceRefs: readonly string[];
}

export interface FormattedObjectiveDrilldown {
  readonly objectiveRef: string;
  readonly stateLabel: string;
  readonly coverageDisplay: string;
  readonly attributionCountDisplay: string;
  readonly workflowRefs: readonly string[];
  readonly actionTypeIds: readonly string[];
  readonly metrics: readonly {
    readonly metric: string;
    readonly stateLabel: string;
    readonly currentDisplay: string;
    readonly sampleDisplay: string;
    readonly evidenceRefs: readonly string[];
  }[];
  readonly evidenceRefs: readonly string[];
}

export interface OutcomeAssuranceViewModel {
  readonly locale: OutcomeAssuranceLocale;
  readonly readOnly: true;
  readonly authority: "none";
  readonly state: OutcomeAssuranceReadState;
  readonly unavailableBanner: string | null;
  readonly summaryCards: readonly FormattedSummaryCard[];
  readonly objectiveDrilldowns: readonly FormattedObjectiveDrilldown[];
  readonly guardSummary: {
    readonly stateLabel: string;
    readonly policyEscapeDisplay: string;
    readonly evaluations: readonly OutcomeAssuranceGuardEvaluation[];
    readonly evidenceRefs: readonly string[];
  };
}

const CARD_IDS = new Set<OutcomeAssuranceSummaryCardId>(["operational_readiness", "objective_alignment", "control_assurance"]);
const REASONS = new Set<OutcomeAssuranceUnavailableReason>(["source_not_connected", "source_missing", "source_stale", "projection_missing", "projection_malformed", "principal_scope_empty", "insufficient_sample"]);
const ATTRIBUTION_STATES = new Set<ObjectiveAttributionDrilldown["state"]>(["unattributed", "partial", "attributed", "unavailable"]);

const CARD_TITLES: Record<OutcomeAssuranceLocale, Record<OutcomeAssuranceSummaryCardId, string>> = {
  en: { operational_readiness: "Operational readiness", objective_alignment: "Objective alignment", control_assurance: "Control assurance" },
  ko: { operational_readiness: "운영 준비도", objective_alignment: "목표 정합성", control_assurance: "제어 보증" },
};

const STATE_LABELS: Record<OutcomeAssuranceLocale, Readonly<Record<string, string>>> = {
  en: {
    complete: "Complete", stale: "Stale", unavailable: "Unavailable",
    ready: "Ready", observed: "Observed", blocked: "Blocked", unknown: "Unknown",
    attributed: "Attributed", partial: "Partial", unattributed: "Unattributed",
    healthy: "Healthy", attention: "Attention", measured: "Measured",
    insufficient_sample: "Insufficient sample", regressed: "Regressed",
  },
  ko: {
    complete: "완료", stale: "만료됨", unavailable: "사용 불가",
    ready: "준비 완료", observed: "관찰됨", blocked: "차단됨", unknown: "알 수 없음",
    attributed: "귀속 완료", partial: "부분 귀속", unattributed: "미귀속",
    healthy: "정상", attention: "주의 필요", measured: "측정됨",
    insufficient_sample: "표본 부족", regressed: "회귀 발생",
  },
};

const REASON_LABELS: Record<OutcomeAssuranceLocale, Record<OutcomeAssuranceUnavailableReason, string>> = {
  en: {
    source_not_connected: "Authoritative source is not connected",
    source_missing: "Authoritative source is missing",
    source_stale: "Authoritative source is stale",
    projection_missing: "Projection record is missing",
    projection_malformed: "Projection record is malformed",
    principal_scope_empty: "Principal scope has no mapped resources",
    insufficient_sample: "Insufficient sample size",
  },
  ko: {
    source_not_connected: "권위 있는 소스가 연결되지 않았습니다",
    source_missing: "권위 있는 소스가 누락되었습니다",
    source_stale: "권위 있는 소스가 만료되었습니다",
    projection_missing: "프로젝션 레코드가 없습니다",
    projection_malformed: "프로젝션 레코드 형식이 올바르지 않습니다",
    principal_scope_empty: "주체 범위에 매핑된 리소스가 없습니다",
    insufficient_sample: "표본 크기가 부족합니다",
  },
};

export function decodeOutcomeAssuranceOperatorProjection(value: unknown): OutcomeAssuranceOperatorProjectionPayload {
  const root = panelRecord(value, "OutcomeAssuranceOperatorProjection");
  if (panelString(root, "type", "OutcomeAssuranceOperatorProjection") !== "outcome-assurance.operator-projection") {
    throw panelContractError("OutcomeAssuranceOperatorProjection.type is invalid");
  }
  if (panelString(root, "schema_version", "OutcomeAssuranceOperatorProjection") !== "1.0.0") {
    throw panelContractError("OutcomeAssuranceOperatorProjection.schema_version is invalid");
  }
  if (!panelBoolean(root, "read_only", "OutcomeAssuranceOperatorProjection")) {
    throw panelContractError("OutcomeAssuranceOperatorProjection.read_only MUST be true");
  }
  if (panelString(root, "authority", "OutcomeAssuranceOperatorProjection") !== "none") {
    throw panelContractError("OutcomeAssuranceOperatorProjection.authority MUST be none");
  }
  const projection = decodeOutcomeAssuranceProjection(root["projection"]);
  const state = panelString(root, "state", "OutcomeAssuranceOperatorProjection");
  if (state !== "complete" && state !== "stale" && state !== "unavailable") {
    throw panelContractError("OutcomeAssuranceOperatorProjection.state is invalid");
  }
  return {
    type: "outcome-assurance.operator-projection",
    schema_version: "1.0.0",
    read_only: true,
    authority: "none",
    principal_id: panelNonEmptyString(root, "principal_id", "OutcomeAssuranceOperatorProjection"),
    state,
    reason: decodeNullableReason(root, "reason", "OutcomeAssuranceOperatorProjection"),
    summary_cards: panelArray(root["summary_cards"], "summary_cards").map(decodeSummaryCard),
    objective_drilldowns: panelArray(root["objective_drilldowns"], "objective_drilldowns").map(
      (item, idx) => decodeObjectiveDrilldown(item, idx, projection.outcomes),
    ),
    guard_status: decodeGuardStatus(root["guard_status"]),
    projection,
  };
}

export function formatOutcomeAssuranceViewModel(
  payload: OutcomeAssuranceOperatorProjectionPayload | null,
  locale: OutcomeAssuranceLocale = "en",
): OutcomeAssuranceViewModel {
  const unavailLabel = STATE_LABELS[locale]["unavailable"] ?? "Unavailable";
  if (payload === null) {
    return {
      locale, readOnly: true, authority: "none", state: "unavailable",
      unavailableBanner: locale === "ko"
        ? "결과 보증 소스가 연결되지 않았습니다 (합성 값 생성 안 함)."
        : "Outcome Assurance source is not connected (no synthetic values).",
      summaryCards: (["operational_readiness", "objective_alignment", "control_assurance"] as const).map((cardId) => ({
        cardId, title: CARD_TITLES[locale][cardId], stateLabel: unavailLabel,
        available: false, headlineDisplay: unavailLabel, evidenceRefs: [],
      })),
      objectiveDrilldowns: [],
      guardSummary: { stateLabel: unavailLabel, policyEscapeDisplay: unavailLabel, evaluations: [], evidenceRefs: [] },
    };
  }
  return {
    locale, readOnly: true, authority: "none", state: payload.state,
    unavailableBanner: formatUnavailableBanner(payload.state, payload.reason, locale),
    summaryCards: payload.summary_cards.map((card) => ({
      cardId: card.card_id,
      title: CARD_TITLES[locale][card.card_id],
      stateLabel: STATE_LABELS[locale][card.state] ?? card.state,
      available: card.available,
      headlineDisplay: !card.available || card.headline_metric === null
        ? unavailLabel
        : card.unit === "ratio" ? `${Math.round(card.headline_metric * 100)}%` : String(card.headline_metric),
      evidenceRefs: card.evidence_refs,
    })),
    objectiveDrilldowns: payload.objective_drilldowns.map((d) => ({
      objectiveRef: d.objective_ref,
      stateLabel: STATE_LABELS[locale][d.state] ?? d.state,
      coverageDisplay: d.coverage === null ? unavailLabel : `${Math.round(d.coverage * 100)}%`,
      attributionCountDisplay: locale === "ko"
        ? `${d.attributed_events}/${d.finalized_events} 귀속됨 (미귀속 ${d.unattributed_events})`
        : `${d.attributed_events}/${d.finalized_events} attributed (${d.unattributed_events} unattributed)`,
      workflowRefs: d.workflow_refs,
      actionTypeIds: d.action_type_ids,
      metrics: d.metrics.map((m) => ({
        metric: m.metric,
        stateLabel: STATE_LABELS[locale][m.state] ?? m.state,
        currentDisplay: m.current_value === null
          ? unavailLabel
          : m.unit === "ratio" ? `${Math.round(m.current_value * 100)}%` : String(m.current_value),
        sampleDisplay: m.sample_size === null ? unavailLabel : String(m.sample_size),
        evidenceRefs: m.evidence_refs,
      })),
      evidenceRefs: d.evidence_refs,
    })),
    guardSummary: {
      stateLabel: STATE_LABELS[locale][payload.guard_status.state] ?? payload.guard_status.state,
      policyEscapeDisplay: payload.guard_status.state === "unavailable" || payload.guard_status.state === "stale"
        ? unavailLabel
        : String(payload.guard_status.policy_escape_count),
      evaluations: payload.guard_status.guard_evaluations,
      evidenceRefs: payload.guard_status.evidence_refs,
    },
  };
}

function formatUnavailableBanner(
  state: OutcomeAssuranceReadState,
  reason: OutcomeAssuranceUnavailableReason | null,
  locale: OutcomeAssuranceLocale,
): string | null {
  if (state === "complete") return null;
  const detail = reason !== null ? REASON_LABELS[locale][reason] : STATE_LABELS[locale][state];
  return locale === "ko"
    ? state === "stale"
      ? `결과 보증 증거가 만료되어 사용 불가 처리되었습니다: ${detail}`
      : `결과 보증을 사용할 수 없습니다: ${detail}`
    : state === "stale"
      ? `Outcome Assurance evidence is stale and rendered unavailable: ${detail}`
      : `Outcome Assurance is unavailable: ${detail}`;
}

function decodeSummaryCard(value: unknown, index: number): OutcomeAssuranceSummaryCard {
  const label = `summary_cards[${index}]`;
  const row = panelRecord(value, label);
  const cardId = panelString(row, "card_id", label) as OutcomeAssuranceSummaryCardId;
  if (!CARD_IDS.has(cardId)) throw panelContractError(`${label}.card_id is invalid`);
  const available = panelBoolean(row, "available", label);
  const headline = row["headline_metric"] === null || row["headline_metric"] === undefined
    ? null
    : panelRatio(row, "headline_metric", label);
  if (!available && headline !== null) {
    throw panelContractError(`${label} cannot carry synthetic headline_metric when unavailable`);
  }
  return {
    card_id: cardId, state: panelNonEmptyString(row, "state", label), available,
    headline_metric: headline, unit: panelNullableString(row, "unit", label),
    reason: decodeNullableReason(row, "reason", label),
    evidence_refs: panelStringArray(row["evidence_refs"] ?? [], `${label}.evidence_refs`),
  };
}

function decodeObjectiveDrilldown(
  value: unknown,
  index: number,
  projectionMetrics: readonly OutcomeAssuranceMetric[],
): ObjectiveAttributionDrilldown {
  const label = `objective_drilldowns[${index}]`;
  const row = panelRecord(value, label);
  const objectiveRef = panelNonEmptyString(row, "objective_ref", label);
  const state = panelString(row, "state", label) as ObjectiveAttributionDrilldown["state"];
  if (!ATTRIBUTION_STATES.has(state)) throw panelContractError(`${label}.state is invalid`);
  const coverage = row["coverage"] === null || row["coverage"] === undefined ? null : panelRatio(row, "coverage", label);
  if (state === "unavailable" && coverage !== null) {
    throw panelContractError(`${label} cannot carry synthetic coverage when unavailable`);
  }
  return {
    objective_ref: objectiveRef, state,
    workflow_refs: panelStringArray(row["workflow_refs"] ?? [], `${label}.workflow_refs`),
    action_type_ids: panelStringArray(row["action_type_ids"] ?? [], `${label}.action_type_ids`),
    finalized_events: panelNonNegativeInteger(row, "finalized_events", label),
    attributed_events: panelNonNegativeInteger(row, "attributed_events", label),
    unattributed_events: panelNonNegativeInteger(row, "unattributed_events", label),
    coverage, metrics: projectionMetrics.filter((m) => m.objective_ref === objectiveRef),
    evidence_refs: panelStringArray(row["evidence_refs"] ?? [], `${label}.evidence_refs`),
    reason: decodeNullableReason(row, "reason", label),
  };
}

function decodeGuardStatus(value: unknown): OutcomeAssuranceOperatorProjectionPayload["guard_status"] {
  const row = panelRecord(value, "guard_status");
  const evals = panelArray(row["guard_evaluations"] ?? [], "guard_status.guard_evaluations").map((item, idx) => {
    const g = panelRecord(item, `guard_evaluations[${idx}]`);
    return {
      guard_id: panelNonEmptyString(g, "guard_id", `guard_evaluations[${idx}]`),
      threshold: Number(g["threshold"]),
      observed_value: Number(g["observed_value"]),
      passed: panelBoolean(g, "passed", `guard_evaluations[${idx}]`),
      evidence_ref: panelNonEmptyString(g, "evidence_ref", `guard_evaluations[${idx}]`),
    };
  });
  return {
    state: panelNonEmptyString(row, "state", "guard_status"),
    reason: decodeNullableReason(row, "reason", "guard_status"),
    policy_escape_count: panelNonNegativeInteger(row, "policy_escape_count", "guard_status"),
    guard_evaluations: evals,
    evidence_refs: panelStringArray(row["evidence_refs"] ?? [], "guard_status.evidence_refs"),
  };
}

function decodeNullableReason(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): OutcomeAssuranceUnavailableReason | null {
  const raw = record[key];
  if (raw === null || raw === undefined) return null;
  const text = panelString(record, key, label) as OutcomeAssuranceUnavailableReason;
  if (!REASONS.has(text)) throw panelContractError(`${label}.${key} is not a valid reason code`);
  return text;
}
