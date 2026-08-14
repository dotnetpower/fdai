import { describe, expect, it } from "vitest";
import type { AuditItem } from "../types";
import { incidentMilestones } from "./incidents.milestones";

function item(seq: number, actionKind: string, entry: Record<string, unknown> = {}): AuditItem {
  return {
    seq,
    event_id: `event-${seq}`,
    correlation_id: "correlation-1",
    actor: "Heimdall",
    action_kind: actionKind,
    mode: "shadow",
    entry,
    entry_hash: `hash-${seq}`,
    previous_hash: `hash-${seq - 1}`,
    recorded_at: `2026-08-14T00:00:${String(seq).padStart(2, "0")}Z`,
  };
}

describe("incident investigation milestones", () => {
  it("keeps the initial record and seven latest milestones", () => {
    const milestones = incidentMilestones([
      item(1, "incident.open"),
      ...Array.from({ length: 9 }, (_, index) => item(index + 2, "investigation.progress")),
    ]);

    expect(milestones).toHaveLength(8);
    expect(milestones.map((milestone) => milestone.item.seq)).toEqual([1, 4, 5, 6, 7, 8, 9, 10]);
    expect(milestones[0]?.status).toBe("initial");
  });

  it("projects exact evidence, gaps, evaluation receipts, and inert learning candidates", () => {
    const [milestone] = incidentMilestones([item(2, "investigation.verified", {
      outcome: "verified",
      evidence_refs: ["metric:memory", "deployment:rev-7"],
      citations: [{ kind: "audit", ref: "audit:22" }],
      evidence_gaps: ["dependency telemetry unavailable"],
      evaluation_receipt_id: "evaluation:2",
      learning_candidate_state: "review_pending",
      learning_candidate_ref: "learning:2",
    })]);

    expect(milestone).toMatchObject({
      status: "success",
      evidenceRefs: ["metric:memory", "deployment:rev-7", "audit:22"],
      gaps: ["dependency telemetry unavailable"],
      evaluationReceipt: "evaluation:2",
      learningCandidate: "learning:2",
    });
  });

  it("marks evidence and gap lists that exceed the five-item display bound", () => {
    const [milestone] = incidentMilestones([item(4, "investigation.progress", {
      evidence_refs: Array.from({ length: 6 }, (_, index) => `evidence:${index}`),
      evidence_gaps: Array.from({ length: 6 }, (_, index) => `gap:${index}`),
    })]);

    expect(milestone?.evidenceRefs).toHaveLength(5);
    expect(milestone?.evidenceRefsTruncated).toBe(true);
    expect(milestone?.gaps).toHaveLength(5);
    expect(milestone?.gapsTruncated).toBe(true);
  });

  it("does not treat transcript or self-evaluation prose as evidence, closure, or learning", () => {
    const [milestone] = incidentMilestones([item(3, "conversation.turn", {
      summary: "Everything is resolved.",
      transcript: "I verified and learned the fix.",
      evaluation: "Excellent result.",
      learning_candidate_ref: "learning:unsafe",
    })]);

    expect(milestone).toMatchObject({
      status: "progress",
      evidenceRefs: [],
      evaluationReceipt: null,
      learningCandidate: null,
    });
  });
});
