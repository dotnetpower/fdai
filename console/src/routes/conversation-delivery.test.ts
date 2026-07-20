import { describe, expect, test } from "vitest";
import { decodeConversationDelivery } from "./conversation-delivery";

function payload() {
  return {
    source: "postgres",
    read_only: true,
    mutations_available: false,
    delivery_count: 4,
    states: { delivered: 2, ambiguous: 1, abandoned: 1 },
    delivery_latency_ms: { count: 2, average: 125, p95: 150 },
    duplicate_risk_count: 1,
    retry_count: 2,
    abandonment_count: 1,
    breaker_states: { closed: 1, paused: 1 },
    attempt_count: 6,
    acknowledgement_count: 2,
  };
}

describe("conversation delivery dashboard", () => {
  test("decodes latency, duplicate risk, retry, abandonment, and breaker evidence", () => {
    const decoded = decodeConversationDelivery(payload());
    expect(decoded.delivery_latency_ms.p95).toBe(150);
    expect(decoded.duplicate_risk_count).toBe(1);
    expect(decoded.retry_count).toBe(2);
    expect(decoded.abandonment_count).toBe(1);
    expect(decoded.breaker_states).toEqual({ closed: 1, paused: 1 });
  });

  test("rejects mutation controls and invalid counters", () => {
    expect(() => decodeConversationDelivery({ ...payload(), mutations_available: true }))
      .toThrow(/MUST be read-only/);
    expect(() => decodeConversationDelivery({ ...payload(), states: { delivered: -1 } }))
      .toThrow(/non-negative integer/);
  });
});
