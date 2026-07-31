import { describe, expect, it } from "vitest";

import { parseTrajectoryDetail } from "./trajectory-detail";

function detail() {
  return {
    schema_version: 1,
    activities: [{
      activity_id: "query-1",
      kind: "query",
      status: "completed",
      label: "Query inventory",
      completed: 1,
      total: 1,
      execution: {
        tool: "inventory",
        command: '{"query":"status"}',
        input_kind: "query",
        redacted: true,
        output: '{"count":2}',
        output_truncated: false,
      },
    }],
    branches: [{
      branch_id: "branch-1",
      branch_kind: "operational",
      parent_branch_id: null,
      status: "completed",
      summary: "Evidence ready",
      started_at: "2026-07-31T01:00:00Z",
      completed_at: "2026-07-31T01:00:01Z",
      duration_ms: 1000,
      evidence_refs: ["evidence:1"],
    }],
    milestones: [{
      message_id: "milestone-1",
      text: "Inventory complete",
      agent: "Bragi",
      recorded_at: "2026-07-31T01:00:01Z",
    }],
    omitted: { activities: 0, branches: 0, milestones: 0 },
    truncated_outputs: 0,
  };
}

describe("parseTrajectoryDetail", () => {
  it("accepts bounded wire detail and preserves execution evidence", () => {
    const parsed = parseTrajectoryDetail(detail());

    expect(parsed?.activities[0]?.execution?.output).toBe('{"count":2}');
    expect(parsed?.branches[0]?.status).toBe("completed");
    expect(parsed?.milestones[0]?.recordedAt).toBe("2026-07-31T01:00:01Z");
  });

  it("accepts the normalized browser-local shape", () => {
    const parsed = parseTrajectoryDetail(detail());

    expect(parseTrajectoryDetail(parsed)).toEqual(parsed);
  });

  it.each([
    { schema_version: 2 },
    { activities: Array(9).fill(detail().activities[0]) },
    { branches: [detail().branches[0], detail().branches[0]] },
    { omitted: { activities: -1, branches: 0, milestones: 0 } },
    { milestones: [{ ...detail().milestones[0], recorded_at: "invalid" }] },
    { activities: [{ ...detail().activities[0], execution: {
      ...detail().activities[0]!.execution,
      redacted: false,
    } }] },
  ])("rejects malformed, oversized, or duplicate detail", (override) => {
    expect(parseTrajectoryDetail({ ...detail(), ...override })).toBeUndefined();
  });
});
