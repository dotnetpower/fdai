import { t } from "../i18n";
import type { AnswerVerification } from "./backend";

export type VerificationIssueKind =
  | "contextRequired"
  | "sourceUnavailable"
  | "invalidQuery"
  | "unsupportedClaim";

export function verificationIssueKind(reasonCode: string | null): VerificationIssueKind {
  const reason = reasonCode?.toLowerCase() ?? "";
  if (
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
