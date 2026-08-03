import { describe, expect, test } from "vitest";
import { decodeIncidentAttentionSnapshot } from "./use-incident-attention-stream";

function snapshot(overrides: Record<string, unknown> = {}): string {
  return JSON.stringify({
    event: "incident_attention.snapshot",
    ts: "2026-08-04T00:00:00Z",
    incidents: [{
      incident_id: "INC-1",
      correlation_id: "corr-1",
      title: "Pod restart detected",
      severity: "high",
      status: "open",
      opened_at: "2026-08-04T00:00:00Z",
      last_updated_at: "2026-08-04T00:01:00Z",
    }],
    ...overrides,
  });
}

describe("incident attention stream decoder", () => {
  test("accepts a bounded durable active-incident snapshot", () => {
    expect(decodeIncidentAttentionSnapshot(snapshot())?.incidents[0]).toMatchObject({
      incident_id: "INC-1",
      correlation_id: "corr-1",
      status: "open",
    });
  });

  test("rejects malformed, resolved, and control-character fields", () => {
    expect(decodeIncidentAttentionSnapshot("not-json")).toBeNull();
    expect(decodeIncidentAttentionSnapshot(snapshot({
      incidents: [{
        incident_id: "INC-1",
        correlation_id: "corr-1",
        title: "Resolved",
        severity: "high",
        status: "resolved",
        opened_at: "2026-08-04T00:00:00Z",
        last_updated_at: "2026-08-04T00:01:00Z",
      }],
    }))).toBeNull();
    expect(decodeIncidentAttentionSnapshot(snapshot({
      incidents: [{
        incident_id: "INC-1",
        correlation_id: "corr-1",
        title: "bad\nline",
        severity: "high",
        status: "open",
        opened_at: "2026-08-04T00:00:00Z",
        last_updated_at: "2026-08-04T00:01:00Z",
      }],
    }))).toBeNull();
  });
});
