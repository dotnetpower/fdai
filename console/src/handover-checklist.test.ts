import { afterEach, describe, expect, it, vi } from "vitest";
import type { OperatorApiClient } from "./api";
import { fetchHandoverGoal } from "./handover-api";
import { decodeHandoverGoal, HANDOVER_SLOTS } from "./handover-model";

function completeGoal(): Record<string, unknown> {
  const owner = { reviewer_ref: "human:owner", goal_revision: 7, evidence_digest: "a".repeat(64), reviewed_at: "2026-09-14T00:00:00Z" };
  return {
    goal_id: "a".repeat(64), subject_ref: "human:subject", agent_name: "Muninn",
    revision: 9, state: "accepted", execution_authority: false,
    checklist_version: "1.0.0", required_slots: HANDOVER_SLOTS,
    evidence: HANDOVER_SLOTS.map((slot) => ({ slot, evidence_ref: "doc:example:v1", digest: "b".repeat(64), kind: "document" })),
    slot_exemptions: {}, high_impact: true, owner_review: owner,
    backup_review: { ...owner, reviewer_ref: "human:backup", goal_revision: 8 },
    allowed_operations: [],
  };
}

afterEach(() => { vi.unstubAllGlobals(); });

describe("handover checklist read boundary", () => {
  it("requires complete independent reviewed evidence without granting authority", () => {
    const goal = decodeHandoverGoal({ goal: completeGoal() });
    expect(goal.slots).toHaveLength(6);
    expect(goal.ownerReviewed && goal.backupReviewed).toBe(true);
    expect(goal.allowedOperations).toEqual([]);
  });

  it.each([
    { owner_review: null }, { backup_review: null }, { high_impact: undefined },
    { checklist_version: undefined }, { required_slots: [] }, { evidence: [null] },
    { state: "active" }, { execution_authority: true },
    { slot_exemptions: { scope_exclusions: "reason:conflict" } },
  ])("rejects incomplete or malformed accepted records: %j", (change) => {
    expect(() => decodeHandoverGoal({ goal: { ...completeGoal(), ...change } })).toThrow();
  });

  it.each([
    { reviewer_ref: "human:subject" }, { reviewer_ref: " human:owner " },
    { reviewer_ref: "HUMAN:BACKUP" }, { evidence_digest: "b".repeat(64) },
    { goal_revision: 9 }, { goal_revision: true }, { reviewed_at: "2026-09-14T00:00:00" },
  ])("rejects misattributed reviews: %j", (change) => {
    const goal = completeGoal();
    goal.owner_review = { ...(goal.owner_review as object), ...change };
    expect(() => decodeHandoverGoal({ goal })).toThrow();
  });

  it.each(["unknown", "", true])("rejects unknown slot %j", (slot) => {
    const goal = completeGoal();
    goal.evidence = [{ slot, evidence_ref: "doc:example:v1", digest: "a".repeat(64) }];
    expect(() => decodeHandoverGoal({ goal })).toThrow();
  });

  it("does not accept a response for another requested goal", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ goal: completeGoal() }))));
    const client = { operatorApiBaseUrl: "http://127.0.0.1:8010", authorizationHeader: async () => null } as unknown as OperatorApiClient;
    await expect(fetchHandoverGoal(client, "b".repeat(64))).rejects.toThrow("another goal");
  });
});
