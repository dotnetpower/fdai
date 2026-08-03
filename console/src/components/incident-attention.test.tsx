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
  test("opens a bounded incident conversation without auto-submitting a prompt", () => {
    expect(incidentDeckDetail(incident())).toMatchObject({
      sessionKey: "incident:corr-1",
      onlyWhenIdle: true,
      binding: {
        kind: "incident",
        incidentId: "INC-1",
        correlationId: "corr-1",
      },
    });
    expect(incidentDeckDetail(incident()).prompt).toBeUndefined();
  });
});
