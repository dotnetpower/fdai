import { describe, expect, it } from "vitest";
import type { AnswerVerification, SemanticProjectionReceipt } from "./backend";
import {
  evidencePostureIssueKind,
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

function semanticReceipt(
  evidence_posture: "fresh" | "stale" | "incomplete" | "conflicting" | "unavailable",
): SemanticProjectionReceipt {
  return {
    schema_version: "2.0.0",
    projection_id: "projection-1",
    request_id: "request-1",
    disposition: "answered",
    reason_code: "query_completed",
    execution_authority: false,
    assurance_observation: {
      schema_version: "1.0.0",
      frame: null,
      capabilities: [],
      object_types: [],
      link_types: [],
      function_types: [],
      ontology_paths: [],
      fact_kinds: [],
      limitation_kinds: [],
      claim_kinds: [],
      evidence_posture,
      authority_posture: "read_only",
      read_performed: true,
      observation_digest: "sha256:obs",
      execution_authority: false,
    },
  };
}

describe("verification presentation", () => {
  it.each([
    ["prior_context_required", "contextRequired", "Context required"],
    ["operational_case_context_missing", "contextRequired", "Context required"],
    ["semantic_clarification_required", "contextRequired", "Context required"],
    [
      "semantic_model_identity_unavailable",
      "modelIdentityUnavailable",
      "Model authentication unavailable",
    ],
    ["semantic_frame_unavailable", "plannerUnavailable", "Semantic planning unavailable"],
    ["capability_invalid_arguments", "invalidQuery", "Invalid query"],
    ["provider_unavailable", "sourceUnavailable", "Source unavailable"],
    ["screen_claim_mismatch", "unsupportedClaim", "Unsupported claim"],
    ["semantic_request_unsupported", "requestUnsupported", "Unsupported request"],
    [
      "vision_interpretation_unverified",
      "visionUnverified",
      "Image interpretation",
    ],
    ["conversation_preflight_malformed", "plannerUnavailable", "Semantic planning unavailable"],
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
    ["semantic_evidence_held", "sourceUnavailable"],
    ["semantic_evidence_incomplete", "sourceUnavailable"],
    ["semantic_deadline_exceeded", "sourceUnavailable"],
    ["semantic_result_store_unavailable", "sourceUnavailable"],
    ["semantic_runtime_unavailable", "plannerUnavailable"],
    ["semantic_transport_unavailable", "sourceUnavailable"],
  ] as const)("maps conversation hold %s to %s", (reason, kind) => {
    expect(verificationIssueKind(reason)).toBe(kind);
  });

  it("keeps a reason-specific detail while preserving unverified machine state", () => {
    const value = verification("prior_result_set_truncated");
    expect(value.status).toBe("unverified");
    expect(unverifiedDetailLabel(value, "")).toBe("Required conversation context is missing");
  });

  it("surfaces stale evidence posture on verified replies", () => {
    const value: AnswerVerification = {
      ...verification(null),
      status: "consistent",
      reason_code: null,
    };

    expect(evidencePostureIssueKind(semanticReceipt("stale"))).toBe("staleEvidence");
    expect(verificationPrimaryLabel(value, semanticReceipt("stale"))).toBe("Stale evidence");
    expect(verificationPrimaryLabel(value, semanticReceipt("fresh"))).toBe("Consistent");
  });
});
