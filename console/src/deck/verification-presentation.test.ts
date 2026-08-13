import { describe, expect, it } from "vitest";
import type { AnswerVerification } from "./backend";
import {
  unverifiedDetailLabel,
  verificationIssueKind,
  verificationPrimaryLabel,
} from "./verification-presentation";

function verification(reasonCode: string | null): AnswerVerification {
  return {
    status: "unverified",
    authority: "server_conversation_context",
    checks_completed: 0,
    checks_total: 1,
    evidence_refs: [],
    failed_claim_ids: [],
    reason_code: reasonCode,
    claims: [],
  };
}

describe("verification presentation", () => {
  it.each([
    ["prior_context_required", "contextRequired", "Context required"],
    ["semantic_clarification_required", "contextRequired", "Context required"],
    ["capability_invalid_arguments", "invalidQuery", "Invalid query"],
    ["provider_unavailable", "sourceUnavailable", "Source unavailable"],
    ["screen_claim_mismatch", "unsupportedClaim", "Unsupported claim"],
    [
      "vision_interpretation_unverified",
      "visionUnverified",
      "Image interpretation",
    ],
  ] as const)("maps %s to %s", (reason, kind, label) => {
    const value = verification(reason);
    expect(verificationIssueKind(reason)).toBe(kind);
    expect(verificationPrimaryLabel(value)).toBe(label);
  });

  it.each([
    ["ordinal_requery_not_unique", "contextRequired"],
    ["ambiguous_candidate_identity_conflict", "contextRequired"],
    ["ordinal_resource_no_longer_observed", "sourceUnavailable"],
    ["ordinal_requery_truncated", "sourceUnavailable"],
    ["ordinal_query_invalid_result", "sourceUnavailable"],
  ] as const)("maps conversation hold %s to %s", (reason, kind) => {
    expect(verificationIssueKind(reason)).toBe(kind);
  });

  it("keeps a reason-specific detail while preserving unverified machine state", () => {
    const value = verification("prior_result_set_truncated");
    expect(value.status).toBe("unverified");
    expect(unverifiedDetailLabel(value, "")).toBe("Required conversation context is missing");
  });
});
