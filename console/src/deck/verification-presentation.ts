import { t } from "../i18n";
import type { AnswerVerification, SemanticProjectionReceipt } from "./backend";

export type VerificationIssueKind =
  | "contextRequired"
  | "modelIdentityUnavailable"
  | "plannerUnavailable"
  | "sourceUnavailable"
  | "invalidQuery"
  | "visionUnverified"
  | "unsupportedClaim"
  | "requestUnsupported"
  | "staleEvidence"
  | "partialEvidence"
  | "conflictingEvidence"
  | "evidenceUnavailable";

export type EvidencePostureIssueKind =
  | "staleEvidence"
  | "partialEvidence"
  | "conflictingEvidence"
  | "evidenceUnavailable";

const CONTEXT_REQUIRED_REASONS = new Set([
  "ambiguous_candidate_identity_conflict",
  "ordinal_requery_not_unique",
  "semantic_clarification_required",
  "semantic_judgment_review_conflict",
  "semantic_reading_ambiguous",
]);

// A question held on its reading needs a narrower or restated question, not another source.
const READING_HOLD_REASONS = new Set([
  "semantic_constraint_uncovered",
  "semantic_reading_continuation_required",
  "semantic_reading_limited",
  "semantic_reading_unverified",
]);

const SOURCE_UNAVAILABLE_REASONS = new Set([
  "ordinal_query_invalid_result",
  "ordinal_requery_truncated",
  "ordinal_resource_no_longer_observed",
  "semantic_deadline_exceeded",
  "semantic_evidence_held",
  "semantic_evidence_incomplete",
  "semantic_result_store_unavailable",
  "semantic_runtime_unavailable",
  "semantic_transport_unavailable",
]);

const EVIDENCE_POSTURE_ISSUES: Readonly<Record<string, EvidencePostureIssueKind>> = {
  stale: "staleEvidence",
  incomplete: "partialEvidence",
  conflicting: "conflictingEvidence",
  unavailable: "evidenceUnavailable",
};

export function verificationIssueKind(reasonCode: string | null): VerificationIssueKind {
  const reason = reasonCode?.toLowerCase() ?? "";
  if (reason === "semantic_model_identity_unavailable") {
    return "modelIdentityUnavailable";
  }
  if (
    reason === "conversation_preflight_malformed" ||
    reason === "semantic_frame_unavailable" ||
    reason === "semantic_judgment_review_unavailable" ||
    reason === "semantic_planning_failed" ||
    reason === "semantic_runtime_unavailable"
  ) {
    return "plannerUnavailable";
  }
  if (reason === "vision_interpretation_unverified") {
    return "visionUnverified";
  }
  if (
    reason === "semantic_request_unsupported" ||
    reason === "semantic_stated_constraint_unsupported"
  ) {
    return "requestUnsupported";
  }
  if (READING_HOLD_REASONS.has(reason)) {
    return "invalidQuery";
  }
  if (
    CONTEXT_REQUIRED_REASONS.has(reason) ||
    reason === "prior_context_required" ||
    reason.startsWith("exact_prior_") ||
    reason.startsWith("prior_result_set_") ||
    reason.includes("selector_required") ||
    reason.includes("context_required") ||
    reason.includes("context_missing")
  ) {
    return "contextRequired";
  }
  if (
    reason === "capability_invalid_arguments" ||
    reason.includes("query_rejected") ||
    reason.includes("query_not_compiled") ||
    reason.includes("query_unrecognized")
  ) {
    return "invalidQuery";
  }
  if (
    SOURCE_UNAVAILABLE_REASONS.has(reason) ||
    reason.includes("unavailable") ||
    reason.includes("provider_") ||
    reason.includes("source_")
  ) {
    return "sourceUnavailable";
  }
  return "unsupportedClaim";
}

export function evidencePostureIssueKind(
  semanticReceipt: SemanticProjectionReceipt | undefined,
): EvidencePostureIssueKind | null {
  if (semanticReceipt?.schema_version !== "2.0.0") return null;
  const posture = semanticReceipt.assurance_observation?.evidence_posture;
  if (!posture || posture === "fresh") return null;
  return EVIDENCE_POSTURE_ISSUES[posture] ?? null;
}

export function secondaryEvidencePostureIssueKind(
  semanticReceipt: SemanticProjectionReceipt | undefined,
): EvidencePostureIssueKind | null {
  const observation = semanticReceipt?.assurance_observation;
  if (
    observation?.evidence_posture === "incomplete" &&
    observation.fact_kinds.includes("evidence.conflicts")
  ) {
    return "conflictingEvidence";
  }
  return null;
}

export function verificationAttentionKind(
  verification: AnswerVerification,
  semanticReceipt?: SemanticProjectionReceipt,
): VerificationIssueKind | null {
  if (verification.status === "unverified") {
    return verificationIssueKind(verification.reason_code);
  }
  return evidencePostureIssueKind(semanticReceipt);
}

export function verificationIssueDetailLabel(
  issue: VerificationIssueKind,
  claims: string,
): string {
  return t(`deck.grounded.verificationLabel.${issue}`, { claims });
}

export function verificationPrimaryLabel(
  verification: AnswerVerification,
  semanticReceipt?: SemanticProjectionReceipt,
): string {
  if (verification.status !== "unverified") {
    const evidenceIssue = evidencePostureIssueKind(semanticReceipt);
    if (evidenceIssue) {
      return t(`deck.grounded.verificationStatus.${evidenceIssue}`);
    }
    return t(`deck.grounded.verificationStatus.${verification.status}`);
  }
  return t(`deck.grounded.verificationStatus.${verificationIssueKind(verification.reason_code)}`);
}

export function unverifiedDetailLabel(
  verification: AnswerVerification,
  claims: string,
): string {
  return verificationIssueDetailLabel(verificationIssueKind(verification.reason_code), claims);
}
