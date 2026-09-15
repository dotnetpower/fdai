import { describe, expect, test } from "vitest";

import {
  decodeAgentOperationalActivity,
  type AgentOperationalActivityMessage,
} from "../agent-operational-activity";
import {
  activityDurationLabel,
  activityResultLabel,
  activityTitle,
  liveObservationUpdateKey,
  mergeLiveObservations,
} from "./live.observations";

function activity(
  status: "started" | "completed",
): AgentOperationalActivityMessage {
  const measured = status === "completed";
  const observedAt = "2026-09-14T00:00:00Z";
  const decoded = decodeAgentOperationalActivity({
    type: "agent.operational-activity",
    schema_version: "1.3.0",
    activity_id: `inventory.scan:attempt-1:${status}`,
    activity_instance_id: "inventory.scan:attempt-1",
    idempotency_key: `inventory.scan:attempt-1:${status}`,
    kind: "inventory.scan",
    status,
    owner_agent: "Huginn",
    producer: "inventory-sync-job",
    observation_domain: null,
    observed_at: observedAt,
    source: "inventory",
    freshness: measured ? "fresh" : "unknown",
    evidence_count: 0,
    duration_ms: measured ? 45 : null,
    correlation_id: "attempt-1",
    reason_codes: [],
    summary_key: "inventory_collection",
    scope_class: "configured-estate",
    target_count: null,
    result_state: measured ? "measured" : "not-recorded",
    result_count: measured ? 0 : null,
    result_unit: measured ? "evidence-items" : null,
    source_cutoff: measured ? observedAt : null,
    started_at: status === "started" ? observedAt : null,
    completed_at: measured ? observedAt : null,
    execution_authority: false,
  });
  if (decoded === null) throw new Error("test activity MUST satisfy decoder");
  return decoded;
}

function legacyActivity(): AgentOperationalActivityMessage {
  const decoded = decodeAgentOperationalActivity({
    type: "agent.operational-activity",
    schema_version: "1.0.0",
    activity_id: "inventory.scan:legacy:completed",
    idempotency_key: "inventory.scan:legacy:completed",
    kind: "inventory.scan",
    status: "completed",
    owner_agent: "Huginn",
    producer: "inventory-sync-job",
    observed_at: "2026-09-14T00:00:00Z",
    source: "inventory",
    freshness: "unknown",
    evidence_count: 0,
    duration_ms: null,
    correlation_id: "legacy",
    reason_codes: [],
    execution_authority: false,
  });
  if (decoded === null) throw new Error("legacy activity MUST satisfy decoder");
  return decoded;
}

describe("Live current observation merge", () => {
  test("collapses transitions by stable instance and keeps terminal tie", () => {
    const completed = mergeLiveObservations(
      [activity("started")],
      [activity("completed")],
    );
    const replayedStart = mergeLiveObservations(
      completed,
      [activity("started")],
    );

    expect(completed).toHaveLength(1);
    expect(completed[0]?.status).toBe("completed");
    expect(completed[0]?.started_at).toBe(activity("started").started_at);
    expect(replayedStart[0]?.status).toBe("completed");
  });

  test("pulses source facts but not timestamp-only updates", () => {
    const completed = activity("completed");
    expect(liveObservationUpdateKey(completed))
      .not.toBe(liveObservationUpdateKey(activity("started")));
    expect(liveObservationUpdateKey({
      ...completed,
      observed_at: "2026-09-14T00:00:10Z",
      duration_ms: 500,
    })).toBe(liveObservationUpdateKey(completed));
  });

  test("distinguishes measured zero from missing legacy evidence", () => {
    expect(activityResultLabel(activity("completed"))).toContain("0");
    expect(activityResultLabel(legacyActivity())).not.toContain("0");
    expect(activityTitle(activity("completed"))).toBe("Inventory collection");
    expect(activityDurationLabel(45)).toContain("45");
    expect(activityDurationLabel(null)).not.toContain("0");
  });
});
