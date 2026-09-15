import { describe, expect, it } from "vitest";
import { parseTestContextDraft } from "./test-context";
import { parseTurns, serializeTurns } from "./transcript-store";
import { restoredTurn } from "./command-deck-session";

export const draft = {
  target_ref: "resource-example", signal_code: "cpu_percent", source_ref: "turn:example",
  semantic_receipt: `sha256:${"a".repeat(64)}`, authority: "candidate_only", execution_authority: false,
  window: { expected_min: 60, expected_max: 90,
    effective_from: "2026-09-15T10:00:00+00:00", effective_to: "2026-09-15T11:00:00+00:00" },
};

describe("test context draft", () => {
  it("retains exact source values without granting authority", () => {
    expect(parseTestContextDraft(draft)).toEqual(draft);
  });
  it("preserves microsecond ordering across equivalent timezones", () => {
    const value = { ...draft, window: { ...draft.window,
      effective_from: "2026-09-15T10:00:00.000001+00:00",
      effective_to: "2026-09-15T19:00:00.000002+09:00",
    } };
    expect(parseTestContextDraft(value)).toEqual(value);
    expect(parseTestContextDraft({ ...value, window: { ...value.window,
      effective_from: value.window.effective_to, effective_to: value.window.effective_from,
    } })).toBeUndefined();
  });
  it("preserves the candidate through server replay and local transcript round-trip", () => {
    const replay = {
      status: "action_draft", source: "ontology-query", answer: "Context draft",
      test_context_draft: draft,
      semantic_receipt: {
        schema_version: "1.0.0", projection_id: "00000000-0000-4000-8000-000000000002",
        request_id: "00000000-0000-4000-8000-000000000001", disposition: "action_draft",
        reason_code: "semantic_action_draft", semantic_route: "semantic_action_draft",
        execution_authority: false,
      },
    };
    const turn = {
      conversation_id: "conversation-example", turn_id: "draft-turn", turn_index: 1,
      role: "assistant" as const, content: replay.answer, recorded_at: "2026-09-15T00:00:00Z",
      metadata: { replay_payload: JSON.stringify(replay) },
    };
    const restored = restoredTurn(turn);
    expect(restored.testContextDraft).toEqual(draft);
    expect(parseTurns(serializeTurns([restored]))[0]?.testContextDraft).toEqual(draft);
    expect(restoredTurn({ ...turn, metadata: { replay_payload: JSON.stringify({
      ...replay, status: "answered", test_context_draft: draft,
    }) } }).testContextDraft).toBeUndefined();
  });
  it("does not restore a draft without an action-draft receipt", () => {
    const parsed = parseTestContextDraft(draft);
    if (!parsed) throw new Error("Expected a valid test context fixture");
    const turns = [{ id: "example", role: "deck" as const, text: "Draft", at: "10:00",
      testContextDraft: parsed }];
    expect(parseTurns(serializeTurns(turns))[0]?.testContextDraft).toBeUndefined();
  });
  it.each([null, [], {}, { ...draft, execution_authority: true }, { ...draft, actor_id: "injected" },
    { ...draft, semantic_receipt: "unknown" }, { ...draft, target_ref: " " },
    { ...draft, window: { ...draft.window, expected_min: true } },
    { ...draft, window: { ...draft.window, expected_max: Infinity } },
    { ...draft, window: { ...draft.window, expected_min: 100 } },
    { ...draft, window: { ...draft.window, effective_from: "2026-09-15T10:00:00" } },
    { ...draft, window: { ...draft.window, effective_from: "2026-02-30T10:00:00Z" } },
    { ...draft, window: { ...draft.window, effective_from: "0000-01-01T10:00:00Z" } },
    { ...draft, window: { ...draft.window, effective_from: "2026-09-14T24:00:00Z" } },
    { ...draft, window: { ...draft.window, effective_from: "2026-09-15 10:00:00Z" } },
    { ...draft, window: { ...draft.window, effective_to: draft.window.effective_from } },
  ])("rejects malformed or authority-bearing input", (value) => {
    expect(parseTestContextDraft(value)).toBeUndefined();
  });
});