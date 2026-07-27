import { describe, expect, it } from "vitest";
import {
  parseConfirmedAnswerSegment,
  parseEvidenceBranch,
  parseInvestigationActivity,
  parseInvestigationMilestone,
  parseRetrievalSourcePreviews,
} from "./backend-normalizers";

function activity(execution: Record<string, unknown>) {
  return {
    activity_id: "metrics",
    kind: "metrics.querying",
    status: "completed",
    label: "Query metrics",
    agent: "Heimdall",
    completed: 1,
    total: 1,
    execution,
  };
}

describe("parseInvestigationActivity execution evidence", () => {
  it("accepts bounded evidence attested as redacted", () => {
    const parsed = parseInvestigationActivity(activity({
      tool: "Azure CLI",
      command: "az monitor metrics list --resource <resource-id>",
      redacted: true,
      output: "{\"value\": []}",
      output_truncated: true,
      exit_code: 0,
      started_at: "2026-07-24T05:00:00Z",
      completed_at: "2026-07-24T05:00:04Z",
      duration_ms: 4000,
    }));

    expect(parsed?.execution).toEqual({
      tool: "Azure CLI",
      command: "az monitor metrics list --resource <resource-id>",
      redacted: true,
      output: "{\"value\": []}",
      outputTruncated: true,
      exitCode: 0,
      startedAt: "2026-07-24T05:00:00Z",
      completedAt: "2026-07-24T05:00:04Z",
      durationMs: 4000,
    });
    expect(parsed?.agent).toBe("Heimdall");
  });

  it("drops execution evidence without a redaction attestation", () => {
    const parsed = parseInvestigationActivity(activity({
      tool: "Azure CLI",
      command: "az account show",
      redacted: false,
    }));

    expect(parsed?.execution).toBeUndefined();
  });

  it("rejects oversized or contradictory activity metadata", () => {
    expect(parseInvestigationActivity({
      ...activity({}),
      label: "x".repeat(513),
    })).toBeNull();
    expect(parseInvestigationActivity({
      ...activity({}),
      completed: 2,
      total: 1,
    })).toBeNull();
  });
});

describe("bounded investigation presentation metadata", () => {
  it("rejects oversized milestones", () => {
    expect(parseInvestigationMilestone({
      message_id: "milestone",
      text: "x".repeat(16 * 1024 + 1),
    })).toBeNull();
  });

  it("drops an oversized milestone agent identity", () => {
    expect(parseInvestigationMilestone({
      message_id: "milestone",
      text: "done",
      agent: "A".repeat(65),
    })).toEqual({ messageId: "milestone", text: "done" });
  });

  it("drops oversized retrieval previews", () => {
    expect(parseRetrievalSourcePreviews([{
      kind: "source",
      label: "x".repeat(513),
      detail: "detail",
      side_effect_class: "read",
    }])).toEqual([]);
  });
});

describe("progressive branch and confirmed segment boundaries", () => {
  it("accepts a bounded terminal branch and confirmed replacement", () => {
    expect(parseEvidenceBranch({
      branch_id: "request-1:tool",
      branch_kind: "tool",
      parent_branch_id: null,
      status: "completed",
      summary: "tool evidence ready",
      started_at: "2026-07-27T01:00:00Z",
      completed_at: "2026-07-27T01:00:01Z",
      duration_ms: 1000,
      evidence_refs: ["tool:result:1"],
    })).toEqual(expect.objectContaining({
      branchId: "request-1:tool",
      status: "completed",
      evidenceRefs: ["tool:result:1"],
    }));
    expect(parseConfirmedAnswerSegment({
      segment_index: 0,
      text: "Verified answer",
      status: "corrected",
      evidence_refs: ["tool:result:1"],
      replace_start: 0,
      replace_end: 5,
    }, 1)).toEqual(expect.objectContaining({
      text: "Verified answer",
      revision: 1,
      status: "corrected",
    }));
  });

  it("rejects premature evidence, reversed time, and unverified confirmation", () => {
    const running = {
      branch_id: "request-1:tool",
      branch_kind: "tool",
      parent_branch_id: null,
      status: "running",
      summary: "checking",
      started_at: "2026-07-27T01:00:01Z",
      evidence_refs: ["premature"],
    };
    expect(parseEvidenceBranch(running)).toBeNull();
    expect(parseEvidenceBranch({
      ...running,
      status: "completed",
      completed_at: "2026-07-27T01:00:00Z",
      evidence_refs: [],
    })).toBeNull();
    expect(parseConfirmedAnswerSegment({
      segment_index: 0,
      text: "Draft",
      status: "unverified",
      evidence_refs: [],
    }, 0)).toBeNull();
  });
});
