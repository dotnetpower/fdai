import { describe, expect, it } from "vitest";
import { decodeAgentOperationalActivity } from "./agent-operational-activity";

const OBSERVATION = {
  type: "agent.operational-activity",
  schema_version: "1.1.0",
  activity_id: "observation:resource-health:campaign-1:completed",
  idempotency_key: "observation:resource-health:campaign-1:completed",
  kind: "observation",
  status: "completed",
  owner_agent: "Heimdall",
  producer: "observation-campaign-job",
  observation_domain: "resource-health",
  observed_at: "2026-08-14T00:00:00+00:00",
  source: "resource-health",
  freshness: "fresh",
  evidence_count: 2,
  duration_ms: 50,
  correlation_id: "campaign-1",
  reason_codes: [],
  execution_authority: false,
};

describe("agent operational activity v1.1", () => {
  it("accepts a bounded observation with matching ownership", () => {
    expect(decodeAgentOperationalActivity(OBSERVATION)).toMatchObject({
      kind: "observation",
      observation_domain: "resource-health",
      owner_agent: "Heimdall",
    });
  });

  it("rejects an observation whose domain owner is forged", () => {
    expect(decodeAgentOperationalActivity({ ...OBSERVATION, owner_agent: "Njord" })).toBeNull();
  });

  it("rejects observation reason text that can carry provider identifiers", () => {
    expect(decodeAgentOperationalActivity({
      ...OBSERVATION,
      status: "degraded",
      freshness: "unavailable",
      reason_codes: ["resource /subscriptions/example failed"],
    })).toBeNull();
  });

  it("normalizes a legacy payload without a domain", () => {
    const legacy = decodeAgentOperationalActivity({
      ...OBSERVATION,
      schema_version: "1.0.0",
      kind: "inventory.scan",
      owner_agent: "Huginn",
      producer: "inventory-sync-job",
      observation_domain: undefined,
    });

    expect(legacy?.observation_domain).toBeNull();
  });
});
