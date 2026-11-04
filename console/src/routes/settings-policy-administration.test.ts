import { describe, expect, test } from "vitest";
import {
  buildPolicyRevisionRequestBody,
  decodePolicyRevisionReceipt,
  initialPolicyRevisionDraft,
  validatePolicyRevisionDraft,
} from "./settings-policy-administration.model";

describe("policy administration revision model", () => {
  test("builds canonical approval policy revision payload with original and effective quorum", () => {
    const draft = initialPolicyRevisionDraft();
    expect(validatePolicyRevisionDraft(draft)).toBeNull();
    const body = buildPolicyRevisionRequestBody(draft);
    expect(body).toEqual({
      policy_kind: "approval",
      parent_revision_id: "rev-12",
      reason: "Adopt reviewed single-operator production approval profile within Release maximums.",
      content: {
        document: {
          revision_id: "rev-13",
          approval_profile: "single-operator-production",
          operator_principal: "owner@example.com",
          executor_principal: "thor-executor-uami",
          effective_from: "2026-11-01T00:00:00Z",
          original_quorum: 2,
          effective_quorum: 1,
        },
        action_type_modes: {
          "aks.nodepool.scale": "shadow",
        },
      },
    });
  });

  test("rejects identical approval and executor principals and short reasons", () => {
    const base = initialPolicyRevisionDraft();
    expect(
      validatePolicyRevisionDraft({
        ...base,
        operatorPrincipal: "same-principal",
        executorPrincipal: "SAME-PRINCIPAL",
      }),
    ).toMatch(/distinct/);
    expect(validatePolicyRevisionDraft({ ...base, reason: "too short" })).toMatch(/20/);
  });

  test("builds admission OPA/Rego policy revision payload and decodes receipt", () => {
    const draft = {
      ...initialPolicyRevisionDraft(),
      policyKind: "admission" as const,
      actionTypeMode: "enforce" as const,
    };
    expect(validatePolicyRevisionDraft(draft)).toBeNull();
    expect(buildPolicyRevisionRequestBody(draft)).toMatchObject({
      policy_kind: "admission",
      content: {
        rego: expect.stringContaining("package fdai.admission"),
        action_type_modes: { "aks.nodepool.scale": "enforce" },
        policy_tests: [],
      },
    });
    expect(
      decodePolicyRevisionReceipt({
        request_id: "req-1",
        request_digest: `sha256:${"a".repeat(64)}`,
        published: true,
      }),
    ).toEqual({
      requestId: "req-1",
      requestDigest: `sha256:${"a".repeat(64)}`,
      published: true,
    });
  });
});
