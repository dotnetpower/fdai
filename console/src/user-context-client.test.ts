import { describe, expect, it } from "vitest";
import { decodeConversationSearch, decodeUserContext } from "./user-context-client";

const payload = {
  preference: {
    principal_id: "user-1",
    locale: "en",
    verbosity: "concise",
    answer_detail: "standard",
    answer_format: "prose",
    answer_preferences_enabled: true,
    answer_intent_detail: {},
    answer_intent_format: {},
    timezone: "UTC",
    share_with_learner: false,
    revision: 1,
  },
  memories: [],
  policies: [],
  subscriptions: [],
  briefing_runs: [],
  scheduled_continuations: [],
  conversations: [],
};

describe("user-context decoder", () => {
  it("decodes a complete account context", () => {
    const decoded = decodeUserContext(payload);
    expect(decoded.preference?.timezone).toBe("UTC");
    expect(decoded.memories).toEqual([]);
  });

  it.each([
    { ...payload, memories: null },
    { ...payload, preference: { ...payload.preference, share_with_learner: "false" } },
    { ...payload, preference: { ...payload.preference, revision: -1 } },
    { ...payload, preference: { ...payload.preference, locale: "fr" } },
  ])("rejects malformed account context %#", (value) => {
    expect(() => decodeUserContext(value)).toThrow();
  });
});

describe("conversation search decoder", () => {
  const searchPayload = {
    hits: [{
      result_id: "conversation-search:turn-1",
      turn_id: "turn-1",
      conversation_id: "conversation-1",
      channel_id: "web",
      role: "operator",
      snippet: { text: "Investigate latency", highlights: [{ start: 12, end: 19 }] },
      recorded_at: "2026-07-20T05:00:00+00:00",
      rank: 1,
      incident_id: null,
      correlation_id: "correlation-1",
      evidence_refs: ["audit:1"],
    }],
    result_cap: 20,
    index_rows: 1,
    index_bytes: 19,
  };

  it("decodes bounded provenance and highlight ranges", () => {
    const decoded = decodeConversationSearch(searchPayload);
    expect(decoded.hits[0]?.snippet.highlights[0]).toEqual({ start: 12, end: 19 });
    expect(decoded.hits[0]?.evidence_refs).toEqual(["audit:1"]);
  });

  it.each([
    { ...searchPayload, result_cap: 0 },
    { ...searchPayload, index_rows: -1 },
    { ...searchPayload, hits: [{ ...searchPayload.hits[0], role: "hidden" }] },
    { ...searchPayload, hits: [{ ...searchPayload.hits[0], recorded_at: "not-a-date" }] },
  ])("rejects malformed search payload %#", (value) => {
    expect(() => decodeConversationSearch(value)).toThrow();
  });
});
