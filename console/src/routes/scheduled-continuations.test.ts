import { describe, expect, test } from "vitest";
import { decodeScheduledContinuations } from "./scheduled-continuations";

function payload() {
  return {
    preference: null,
    memories: [],
    policies: [],
    subscriptions: [],
    briefing_runs: [],
    conversations: [],
    scheduled_continuations: [{
      anchor_id: "scheduled-anchor-example",
      task_id: "task-1",
      run_id: "run-1",
      owner_principal_id: "principal-a",
      scope_ref: "scope-a",
      mode: "origin_thread",
      origin: {
        channel_kind: "web",
        channel_ref: "console",
        conversation_ref: "conversation-1",
        thread_ref: null,
        audience: "direct",
      },
      result_digest: "a".repeat(64),
      result_summary: "No critical issues were found.",
      evidence_refs: ["audit:1"],
      observation_started_at: "2026-07-20T08:00:00+00:00",
      observation_ended_at: "2026-07-20T09:00:00+00:00",
      created_at: "2026-07-20T09:00:00+00:00",
      expires_at: "2026-07-27T09:00:00+00:00",
      state: "active",
    }],
  };
}

describe("scheduled continuation cards", () => {
  test("decodes exact run, provenance, scope, origin, and expiry", () => {
    const decoded = decodeScheduledContinuations(payload());
    expect(decoded.continuations[0]?.run_id).toBe("run-1");
    expect(decoded.continuations[0]?.evidence_refs).toEqual(["audit:1"]);
    expect(decoded.continuations[0]?.origin.conversation_ref).toBe("conversation-1");
  });

  test("rejects broadcast and malformed result digests", () => {
    const broadcast = payload();
    broadcast.scheduled_continuations[0]!.origin.audience = "broadcast";
    expect(() => decodeScheduledContinuations(broadcast)).toThrow(/audience/);
    const malformed = payload();
    malformed.scheduled_continuations[0]!.result_digest = "short";
    expect(() => decodeScheduledContinuations(malformed)).toThrow(/SHA-256/);
  });
});
