import { t } from "../i18n";
import type { AnswerVerification } from "./backend";

export type VerificationIssueKind =
  | "contextRequired"
  | "sourceUnavailable"
  | "invalidQuery"
  | "unsupportedClaim";

const CONTEXT_REQUIRED_REASONS = new Set([
  "ambiguous_candidate_identity_conflict",
  "ordinal_requery_not_unique",
]);

const SOURCE_UNAVAILABLE_REASONS = new Set([
  "ordinal_query_invalid_result",
  "ordinal_requery_truncated",
  "ordinal_resource_no_longer_observed",
]);

export function verificationIssueKind(reasonCode: string | null): VerificationIssueKind {
  const reason = reasonCode?.toLowerCase() ?? "";
  if (
    CONTEXT_REQUIRED_REASONS.has(reason) ||
    reason === "prior_context_required" ||
    reason.startsWith("exact_prior_") ||
    reason.startsWith("prior_result_set_") ||
    reason.includes("selector_required") ||
    reason.includes("context_required")
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

export function verificationPrimaryLabel(verification: AnswerVerification): string {
  if (verification.status !== "unverified") {
    return t(`deck.grounded.verificationStatus.${verification.status}`);
  }
  return t(`deck.grounded.verificationStatus.${verificationIssueKind(verification.reason_code)}`);
}

export function unverifiedDetailLabel(
  verification: AnswerVerification,
  claims: string,
): string {
  return t(`deck.grounded.verificationLabel.${verificationIssueKind(verification.reason_code)}`, {
    claims,
  });
}
