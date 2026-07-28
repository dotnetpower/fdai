import { describe, expect, it } from "vitest";
import type { RcaView } from "../types";
import { hasRecordedRca } from "./rca";

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
