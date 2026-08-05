import { afterEach, describe, expect, test, vi } from "vitest";
import {
  clearScheduledTimeouts,
  matchingTurnIndexes,
  clampDockWidth,
  parseDeckLayoutMode,
  provisionalReplyAgent,
  replyAgent,
  replyAgentLabel,
  restoredTurn,
  sessionIdFor,
} from "./command-deck";
import { sessionStore } from "./use-command-deck-sessions";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Deck scheduled work", () => {
  test("cancels every tracked context timeout", () => {
    const timers = new Set([11, 12, 13]);
    const cleared: number[] = [];

    clearScheduledTimeouts(timers, (timer) => cleared.push(timer));

    expect(cleared).toEqual([11, 12, 13]);
    expect(timers.size).toBe(0);
  });
});

describe("Deck layout mode", () => {
  test("restores supported modes and defaults malformed values to the right dock", () => {
    expect(parseDeckLayoutMode("floating")).toBe("floating");
    expect(parseDeckLayoutMode("dock")).toBe("dock");
    expect(parseDeckLayoutMode("workspace")).toBe("workspace");
    expect(parseDeckLayoutMode("unknown")).toBe("dock");
    expect(parseDeckLayoutMode(null)).toBe("dock");
  });

  test("clamps right-sidebar width to a usable viewport range", () => {
    expect(clampDockWidth(100, 1440)).toBe(340);
    expect(clampDockWidth(500, 1440)).toBe(500);
    expect(clampDockWidth(900, 1440)).toBe(720);
    expect(clampDockWidth(600, 800)).toBe(480);
  });
});

describe("Deck backend session IDs", () => {
  test("isolates transcripts and restores an existing session ID", () => {
    const sessions = new Map<string, string>();
    let next = 0;
    const create = () => `session-${++next}`;

    const general = sessionIdFor(sessions, "screen", create);
    const forseti = sessionIdFor(sessions, "agent:Forseti", create);

    expect(general).not.toBe(forseti);
    expect(sessionIdFor(sessions, "screen", create)).toBe(general);
    expect(next).toBe(2);
  });

  test("reconstructs the same server ID after browser state is recreated", () => {
    const sessionKey = "screen:abc12345:/overview";

    expect(sessionIdFor(new Map(), sessionKey)).toBe(sessionKey);
    expect(sessionIdFor(new Map(), sessionKey)).toBe(sessionKey);
  });

  test("bounds long route keys without losing deterministic identity", () => {
    const firstKey = `screen:abc12345:/${"a".repeat(240)}`;
    const secondKey = `screen:abc12345:/${"a".repeat(239)}b`;

    const first = sessionIdFor(new Map(), firstKey);
    expect(first).toHaveLength(200);
    expect(sessionIdFor(new Map(), firstKey)).toBe(first);
    expect(sessionIdFor(new Map(), secondKey)).not.toBe(first);
  });
});

describe("Deck browser persistence", () => {
  test("uses persistent local storage for the conversation cache", () => {
    const localStorage = {} as Storage;
    vi.stubGlobal("window", {
      localStorage,
      sessionStorage: {} as Storage,
    });

    expect(sessionStore()).toBe(localStorage);
  });
});

describe("Deck transcript search", () => {
  test("matches case-insensitively and ignores a blank query", () => {
    const turns = [
      { text: "Explain the current HIL decision" },
      { text: "No matching content" },
      { text: "HIL is waiting for Var" },
    ];

    expect(matchingTurnIndexes(turns, " hil ")).toEqual([0, 2]);
    expect(matchingTurnIndexes(turns, "   ")).toEqual([]);
  });
});

describe("terminal reply attribution", () => {
  test("keeps the selected agent visible while its reply is streaming", () => {
    expect(provisionalReplyAgent("Heimdall")).toBe("Heimdall");
    expect(provisionalReplyAgent(undefined)).toBe("Bragi");
  });

  test("keeps the delegated specialist as the reply owner", () => {
    const delegation = { primary_agent: "Saga", contributors: [] };
    const verification = {
      authority: "client_snapshot",
      checks_completed: 0,
      checks_total: 1,
      evidence_refs: [],
      reason_code: "screen_claim_mismatch",
    } as const;

    expect(replyAgent({ delegation, verification: { ...verification, status: "unverified" } }))
      .toBe("Saga");
    expect(replyAgent({ delegation, verification: { ...verification, status: "corrected" } }))
      .toBe("Saga");
    expect(replyAgent({ delegation, verification: { ...verification, status: "consistent" } }))
      .toBe("Saga");
    expect(replyAgent({ verification: { ...verification, status: "consistent" } }))
      .toBe("Bragi");
  });

  test("shows the selected specialist when a turn is handed back to Bragi", () => {
    expect(replyAgentLabel("Bragi", {
      primary_agent: "Bragi",
      contributors: [],
      handoff_from: "Heimdall",
      handoff_reason: "insufficient_agent_evidence",
    })).toBe("Heimdall -> Bragi");
    expect(replyAgentLabel("Heimdall", {
      primary_agent: "Heimdall",
      contributors: [],
    })).toBe("Heimdall");
  });
});

describe("durable transcript restoration", () => {
  test("maps principal-scoped operator and assistant records into deck turns", () => {
    const operator = restoredTurn({
      turn_id: "turn-1",
      conversation_id: "conversation-1",
      turn_index: 0,
      role: "operator",
      content: "Show major issues.",
      recorded_at: "2026-07-16T07:00:00Z",
      metadata: {
        attachments: JSON.stringify([{
          id: "att-image-1",
          name: "screenshot.png",
          media_type: "image/png",
        }]),
      },
    });
    const assistant = restoredTurn({
      turn_id: "turn-2",
      conversation_id: "conversation-1",
      turn_index: 1,
      role: "assistant",
      content: "No high issues.",
      recorded_at: "2026-07-16T07:00:01Z",
      metadata: { source: "llm:test", agent: "Bragi" },
    });

    expect(operator).toMatchObject({ id: "turn-1", role: "operator", text: "Show major issues." });
    expect(assistant).toMatchObject({
      id: "turn-2",
      role: "deck",
      text: "No high issues.",
      source: "llm:test",
      agent: "Bragi",
      terminal: true,
    });
    expect(operator.recordedAt).toBe("2026-07-16T07:00:00Z");
    expect(operator.attachments).toEqual([{
      id: "att-image-1",
      name: "screenshot.png",
      mediaType: "image/png",
      conversationId: "conversation-1",
    }]);
  });

  test("restores bounded terminal replay metadata for historical trajectories", () => {
    const presentationRef = "inventory:snapshot";
    const assistant = restoredTurn({
      turn_id: "turn-2",
      conversation_id: "conversation-1",
      turn_index: 1,
      role: "assistant",
      content: "One service is unavailable.",
      recorded_at: "2026-07-16T07:00:03Z",
      metadata: {
        replay_payload: JSON.stringify({
          answer: "One service is unavailable.",
          model: "test-model",
          latency_ms: 3000,
          answer_plan: {
            intent: "status",
            detail_level: "standard",
            format: "prose",
            sections: ["Summary"],
            evidence_requirement: "server_read_model",
            max_words: 300,
            discuss: "skip",
            explicit_overrides: [],
            preference_applied: false,
          },
          delegation: { primary_agent: "Bragi", contributors: ["Heimdall"] },
          verification: {
            status: "consistent",
            authority: "server_evidence",
            checks_completed: 1,
            checks_total: 1,
            evidence_refs: ["inventory:snapshot"],
            reason_code: null,
          },
          presentation_artifact: {
            schema_version: 1,
            layout: "stack",
            evidence_refs: [presentationRef],
            blocks: [{
              slot_id: "overview",
              kind: "summary",
              title: "Inventory",
              emphasis: "primary",
              collapsed: false,
              evidence_refs: [presentationRef],
              data: { items: [{ label: "Resources", value: "2", tone: "neutral" }] },
            }],
          },
          resource_context: {
            name: "example-service",
            resource_type: "compute.service",
            evidence_ref: "inventory:snapshot",
          },
          model_trace: {
            schema_version: 1,
            redacted: true,
            omitted_calls: 0,
            calls: [{
              call_id: "model-call-1",
              kind: "answer-stream",
              model: "test-model",
              status: "completed",
              started_at: "2026-07-16T07:00:00Z",
              completed_at: "2026-07-16T07:00:03Z",
              duration_ms: 3000,
              request: {
                messages: [{ role: "user", content: "question" }],
                sha256: "a".repeat(64),
              },
              response: {
                role: "assistant",
                content: "One service is unavailable.",
                sha256: "b".repeat(64),
              },
              usage: { total_tokens: 12 },
              redactions: [],
            }],
          },
          turn_timing: {
            schema_version: 1,
            started_at: "2026-07-16T07:00:00Z",
            completed_at: "2026-07-16T07:00:03Z",
            duration_ms: 3000,
            phases: [{
              phase: "generation",
              status: "completed",
              started_at: "2026-07-16T07:00:00Z",
              completed_at: "2026-07-16T07:00:03Z",
              duration_ms: 3000,
            }],
          },
          trajectory_detail: {
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
              },
            }],
            branches: [],
            milestones: [{
              message_id: "milestone-1",
              text: "Inventory complete",
              recorded_at: "2026-07-16T07:00:02Z",
            }],
            omitted: { activities: 0, branches: 0, milestones: 0 },
            truncated_outputs: 0,
          },
        }),
      },
    });

    expect(assistant).toMatchObject({
      recordedAt: "2026-07-16T07:00:03Z",
      source: "llm:test-model / 3000ms",
      agent: "Bragi",
      answerPlan: { intent: "status", format: "prose" },
      delegation: { primary_agent: "Bragi", contributors: ["Heimdall"] },
      verification: { status: "consistent", evidence_refs: ["inventory:snapshot"] },
      resourceContext: { name: "example-service" },
      modelTrace: { calls: [{ kind: "answer-stream", duration_ms: 3000 }] },
      turnTiming: { phases: [{ phase: "generation", duration_ms: 3000 }] },
      trajectoryDetail: {
        activities: [{ execution: { output: '{"count":2}' } }],
        milestones: [{ text: "Inventory complete" }],
      },
      presentationArtifact: { blocks: [{ slotId: "overview" }] },
    });
  });

  test("ignores malformed or mismatched durable replay metadata", () => {
    const base = {
      turn_id: "turn-2",
      conversation_id: "conversation-1",
      turn_index: 1,
      role: "assistant" as const,
      content: "Canonical answer",
      recorded_at: "2026-07-16T07:00:03Z",
    };

    expect(restoredTurn({ ...base, metadata: { replay_payload: "not-json" } }).answerPlan)
      .toBeUndefined();
    expect(restoredTurn({
      ...base,
      metadata: { replay_payload: JSON.stringify({ answer: "Different answer", answer_plan: {} }) },
    }).answerPlan).toBeUndefined();
  });
});
