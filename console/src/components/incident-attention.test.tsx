import { describe, expect, test } from "vitest";
import type { IncidentAttentionProjection } from "../hooks/use-incident-attention-stream";
import { incidentDeckDetail } from "./incident-attention";

function incident(overrides: Partial<IncidentAttentionProjection> = {}): IncidentAttentionProjection {
  return {
    incident_id: "INC-1",
    correlation_id: "corr-1",
    status: "open",
    title: "Pod restart detected",
    severity: "high",
    opened_at: "2026-08-04T00:00:00Z",
    last_updated_at: "2026-08-04T00:00:00Z",
    ...overrides,
  };
}

describe("incident attention", () => {
  test("opens a bounded incident conversation and starts one read-only investigation", () => {
    expect(incidentDeckDetail(incident())).toMatchObject({
      sessionKey: "incident:corr-1",
      onlyWhenIdle: true,
      prompt: "Report what the evidence for this incident establishes, which evidence is missing, and the next safe read-only step.",
      submitPrompt: true,
      binding: {
        kind: "incident",
        incidentId: "INC-1",
        correlationId: "corr-1",
      },
    });
  });
});
