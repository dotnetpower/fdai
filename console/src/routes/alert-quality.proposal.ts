/** Typed form grammar for inert, evidence-bound, single-axis proposals. */
import {
  alertQualityFreshness, alertQualityRequestable, alertQualityTimestampMicros,
  alertTreatmentCandidates, isAlertQualityRef, isAlertQualityTimestamp,
  type AlertEvaluation, type AlertQualityPayload, type AlertQualityTreatment,
} from "./alert-quality.model";

export type AlertEvaluationParameter = "threshold" | "window_seconds" | "frequency_seconds";
export type AlertEvaluationDraft = {
  readonly metric_ref: string;
  readonly operator: AlertEvaluation["operator"] | "";
  readonly threshold: string;
  readonly window_seconds: string;
  readonly frequency_seconds: string;
  readonly aggregation: AlertEvaluation["aggregation"] | "";
};

/** Baseline input is user-supplied, not observed evidence; it is never added to the wire body. */
export type AlertProposalDraft =
  | { readonly kind: "routing"; readonly target_ref: string; readonly remove_group_ref: string; readonly replacement_group_ref: string }
  | { readonly kind: "suppression"; readonly target_ref: string; readonly processing_rule_ref: string;
      readonly starts_at: string; readonly ends_at: string; readonly preprovisioned: boolean }
  | { readonly kind: "evaluation"; readonly target_ref: string; readonly baseline: AlertEvaluationDraft;
      readonly parameter: AlertEvaluationParameter; readonly proposed_value: string };

export type AlertQualityProposal = {
  readonly scope_ref: string;
  readonly evidence_digest: string;
  readonly treatment: AlertQualityTreatment;
};
export type AlertProposalIssue = "reference" | "target" | "different" | "timestamp" | "future"
  | "positiveInterval" | "preprovisioned" | "number" | "seconds" | "choice" | "changed";
export type AlertProposalField = "target_ref" | "remove_group_ref" | "replacement_group_ref"
  | "processing_rule_ref" | "starts_at" | "ends_at" | "preprovisioned" | "parameter" | "proposed_value"
  | `baseline.${keyof AlertEvaluationDraft}`;
export type AlertProposalErrors = Partial<Record<AlertProposalField, AlertProposalIssue>>;

/** Changing treatment clears foreign-axis values and never seeds targets, dates or a baseline. */
export function initialAlertProposal(kind: AlertQualityTreatment["kind"] = "routing"): AlertProposalDraft {
  if (kind === "routing") return { kind, target_ref: "", remove_group_ref: "", replacement_group_ref: "" };
  if (kind === "suppression") return {
    kind, target_ref: "", processing_rule_ref: "", starts_at: "", ends_at: "", preprovisioned: false,
  };
  return {
    kind, target_ref: "", parameter: "threshold", proposed_value: "",
    baseline: { metric_ref: "", operator: "", threshold: "", window_seconds: "", frequency_seconds: "", aggregation: "" },
  };
}

/** Canonical finite decimal/scientific grammar: no trimming, hex, locale grouping or underflow. */
export function parseAlertThreshold(value: string): number | null {
  const match = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$/.exec(value);
  if (value.length > 128 || match?.[0] !== value) return null;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || (parsed === 0 && /[1-9]/.test(value.split(/[eE]/)[0]!))) return null;
  return parsed;
}

/** Seconds follow the shared Evaluation contract; provider-native restrictions remain server-owned. */
export function parseAlertSeconds(value: string): number | null {
  if (value.length > 5 || /^[1-9]\d*$/.exec(value)?.[0] !== value) return null;
  const parsed = Number(value);
  return parsed <= 86_400 ? parsed : null;
}

/** A current complete report narrows proposal input, but does not establish provider eligibility. */
export function alertProposalEvidenceReady(
  data: AlertQualityPayload, scope: string, kind: AlertQualityTreatment["kind"], now: number,
): boolean {
  const report = data.assessment;
  return isAlertQualityRef(scope) && alertQualityRequestable(data) && report !== null
    && report.scope_ref === scope && report.coverage === "complete" && report.reasons.length === 0
    && alertQualityFreshness(report.observed_at, report.valid_until, now) === "current"
    && alertTreatmentCandidates(report, kind).length > 0;
}

function parseBaseline(draft: AlertEvaluationDraft, errors: AlertProposalErrors): AlertEvaluation | null {
  if (!isAlertQualityRef(draft.metric_ref)) errors["baseline.metric_ref"] = "reference";
  const threshold = parseAlertThreshold(draft.threshold);
  const window = parseAlertSeconds(draft.window_seconds);
  const frequency = parseAlertSeconds(draft.frequency_seconds);
  if (threshold === null) errors["baseline.threshold"] = "number";
  if (window === null) errors["baseline.window_seconds"] = "seconds";
  if (frequency === null) errors["baseline.frequency_seconds"] = "seconds";
  if (draft.operator !== "above" && draft.operator !== "below") errors["baseline.operator"] = "choice";
  if (!["average", "maximum", "minimum"].includes(draft.aggregation)) errors["baseline.aggregation"] = "choice";
  if (!isAlertQualityRef(draft.metric_ref) || threshold === null || window === null || frequency === null
    || (draft.operator !== "above" && draft.operator !== "below")
    || (draft.aggregation !== "average" && draft.aggregation !== "maximum" && draft.aggregation !== "minimum")) return null;
  return {
    metric_ref: draft.metric_ref, operator: draft.operator, threshold,
    window_seconds: window, frequency_seconds: frequency, aggregation: draft.aggregation,
  };
}

function suppressionTreatment(
  draft: Extract<AlertProposalDraft, { kind: "suppression" }>, now: number, errors: AlertProposalErrors,
): AlertQualityTreatment | null {
  if (!isAlertQualityRef(draft.processing_rule_ref)) errors.processing_rule_ref = "reference";
  if (draft.preprovisioned !== true) errors.preprovisioned = "preprovisioned";
  const startValid = isAlertQualityTimestamp(draft.starts_at);
  const endValid = isAlertQualityTimestamp(draft.ends_at);
  if (!startValid) errors.starts_at = "timestamp";
  if (!endValid) errors.ends_at = "timestamp";
  if (startValid && Number.isSafeInteger(now)
    && alertQualityTimestampMicros(draft.starts_at) <= BigInt(now) * 1_000n) errors.starts_at = "future";
  if (startValid && endValid && alertQualityTimestampMicros(draft.ends_at) <= alertQualityTimestampMicros(draft.starts_at)) {
    errors.ends_at = "positiveInterval";
  }
  if (Object.keys(errors).length !== 0) return null;
  return {
    kind: "suppression", target_ref: draft.target_ref, processing_rule_ref: draft.processing_rule_ref,
    starts_at: draft.starts_at, ends_at: draft.ends_at,
  };
}

function evaluationTreatment(
  draft: Extract<AlertProposalDraft, { kind: "evaluation" }>, errors: AlertProposalErrors,
): AlertQualityTreatment | null {
  const baseline = parseBaseline(draft.baseline, errors);
  if (!["threshold", "window_seconds", "frequency_seconds"].includes(draft.parameter)) errors.parameter = "choice";
  const proposed = draft.parameter === "threshold"
    ? parseAlertThreshold(draft.proposed_value) : parseAlertSeconds(draft.proposed_value);
  if (proposed === null) errors.proposed_value = draft.parameter === "threshold" ? "number" : "seconds";
  if (baseline !== null && proposed === baseline[draft.parameter]) errors.proposed_value = "changed";
  if (baseline === null || proposed === null || Object.keys(errors).length !== 0) return null;
  return {
    kind: "evaluation", target_ref: draft.target_ref,
    evaluation: { ...baseline, [draft.parameter]: proposed },
  };
}

/** Build one exact treatment, excluding UI acknowledgements, baseline input and every authority field. */
export function validateAlertProposal(
  data: AlertQualityPayload, scope: string, draft: AlertProposalDraft, now: number,
): { readonly body: AlertQualityProposal | null; readonly errors: AlertProposalErrors } {
  const errors: AlertProposalErrors = {};
  const report = data.assessment;
  if (!isAlertQualityRef(draft.target_ref) || report === null
    || !alertTreatmentCandidates(report, draft.kind).includes(draft.target_ref)) errors.target_ref = "target";
  let treatment: AlertQualityTreatment | null = null;
  if (draft.kind === "routing") {
    if (!isAlertQualityRef(draft.remove_group_ref)) errors.remove_group_ref = "reference";
    if (!isAlertQualityRef(draft.replacement_group_ref)) errors.replacement_group_ref = "reference";
    else if (draft.remove_group_ref === draft.replacement_group_ref) errors.replacement_group_ref = "different";
    treatment = {
      kind: "routing", target_ref: draft.target_ref,
      remove_group_ref: draft.remove_group_ref, replacement_group_ref: draft.replacement_group_ref,
    };
  } else if (draft.kind === "suppression") treatment = suppressionTreatment(draft, now, errors);
  else treatment = evaluationTreatment(draft, errors);
  const body = report !== null && treatment !== null && Object.keys(errors).length === 0
    && alertProposalEvidenceReady(data, scope, draft.kind, now)
    ? { scope_ref: scope, evidence_digest: report.evidence_digest, treatment } : null;
  return { body, errors };
}
