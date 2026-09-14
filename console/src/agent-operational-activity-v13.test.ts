import { describe, expect, test } from "vitest";

import { decodeAgentOperationalActivity } from "./agent-operational-activity";

const MEASURED_ZERO = {
  type: "agent.operational-activity",
  schema_version: "1.3.0",
  activity_id: "observation:resource-health:campaign-1:completed",
  activity_instance_id: "observation:resource-health:campaign-1",
  idempotency_key: "observation:resource-health:campaign-1:completed",
  kind: "observation",
  status: "completed",
  owner_agent: "Heimdall",
  producer: "observation-campaign-job",
  observation_domain: "resource-health",
  observed_at: "2026-08-14T00:00:00+00:00",
  source: "resource-health",
  freshness: "fresh",
  evidence_count: 0,
  duration_ms: 50,
  correlation_id: "campaign-1",
  reason_codes: [],
  summary_key: "source_observation",
  scope_class: "source-domain",
  target_count: null,
  result_state: "measured",
  result_count: 0,
  result_unit: "records",
  source_cutoff: "2026-08-14T00:00:00+00:00",
  started_at: "2026-08-13T23:59:59+00:00",
  completed_at: "2026-08-14T00:00:00+00:00",
  execution_authority: false,
};

describe("agent operational activity v1.3", () => {
  test("preserves measured zero with stable lifecycle identity", () => {
    expect(decodeAgentOperationalActivity(MEASURED_ZERO)).toMatchObject({
      activity_instance_id: "observation:resource-health:campaign-1",
      result_state: "measured",
      result_count: 0,
      result_unit: "records",
    });
  });

  test("rejects unavailable disguised as measured zero", () => {
    expect(decodeAgentOperationalActivity({
      ...MEASURED_ZERO,
      status: "failed",
      freshness: "unavailable",
      reason_codes: ["provider_failure"],
      result_state: "unavailable",
    })).toBeNull();
  });

  test("rejects forged summary and lifecycle timing", () => {
    expect(decodeAgentOperationalActivity({
      ...MEASURED_ZERO,
      summary_key: "inventory_collection",
      scope_class: "configured-estate",
    })).toBeNull();
    expect(decodeAgentOperationalActivity({
      ...MEASURED_ZERO,
      completed_at: "2026-08-13T23:59:58+00:00",
    })).toBeNull();
  });

  test("rejects lifecycle/result contradictions", () => {
    expect(decodeAgentOperationalActivity({
      ...MEASURED_ZERO,
      status: "started",
      result_state: "unavailable",
      result_count: null,
      result_unit: null,
      source_cutoff: null,
      completed_at: null,
    })).toBeNull();
  });
});
