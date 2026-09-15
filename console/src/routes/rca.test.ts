import { describe, expect, it } from "vitest";
import type { RcaView } from "../types";
import { hasRecordedRca, linkedRcaResponse } from "./rca.presentation";

function view(hypotheses: RcaView["hypotheses"]): RcaView {
  return {
    correlation_id: "correlation-1",
    incident_id: "incident-1",
    hypotheses,
    response: null,
  };
}

describe("RCA availability", () => {
  it("does not treat a generic response fallback as recorded RCA", () => {
    expect(hasRecordedRca({
      ...view([]),
      response: {
        verdict: "unknown",
        decision: null,
        action_kind: "incident.members",
        mode: "shadow",
        rollback_reference: null,
        recorded_at: "2026-07-28T07:11:38Z",
      },
    })).toBe(false);
  });

  it("requires at least one evidence-backed hypothesis", () => {
    expect(hasRecordedRca(view([{
      seq: 1,
      tier: "t0",
      outcome: "grounded",
      grounded: true,
      cause_domain: "infrastructure",
      cause: "Configuration changed before the failure.",
      confidence: 1,
      reason: null,
      citations: [],
      remediation_ref: null,
      causal_chain: null,
      mode: "shadow",
      recorded_at: "2026-07-28T07:11:38Z",
    }]))).toBe(true);
  });
});

describe("RCA response association", () => {
  const grounded = view([{
    seq: 1,
    tier: "t1",
    outcome: "grounded",
    grounded: true,
    cause_domain: "infrastructure",
    cause: "Configuration changed before the failure.",
    confidence: 0.9,
    reason: null,
    citations: [{ kind: "change", ref: "change-1" }],
    remediation_ref: "rollback-1",
    causal_chain: null,
    mode: "shadow",
    recorded_at: "2026-07-28T07:11:38Z",
  }]);
  const response: NonNullable<RcaView["response"]> = {
    verdict: "auto",
    decision: "approved",
    action_kind: "config.rollback",
    mode: "shadow",
    rollback_reference: "rollback-1",
    recorded_at: "2026-07-28T07:12:38Z",
  };

  it("keeps an action response for a grounded primary hypothesis", () => {
    expect(linkedRcaResponse({ ...grounded, response })).toEqual(response);
  });

  it("suppresses a response when the primary hypothesis abstained", () => {
    expect(linkedRcaResponse({
      ...grounded,
      hypotheses: [{ ...grounded.hypotheses[0]!, outcome: "abstained", grounded: false }],
      response,
    })).toBeNull();
  });

  it("suppresses the generic incident-members audit fallback", () => {
    expect(linkedRcaResponse({
      ...grounded,
      response: { ...response, verdict: "unknown", action_kind: "incident.members" },
    })).toBeNull();
  });
});
