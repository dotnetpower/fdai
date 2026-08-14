import { describe, expect, test, vi } from "vitest";
import { UserContextRequestError } from "../user-context-client";
import type {
  ConversationSearchContextPayload,
  ConversationSearchHitPayload,
  ConversationSearchPayload,
} from "../user-context-client";
import {
  conversationSearchHighlightSegments,
  conversationSearchInput,
  conversationSearchViewStatus,
  EMPTY_FORM,
  toggleConversationSearchContext,
} from "./conversation-search.model";

function hit(): ConversationSearchHitPayload {
  return {
    result_id: "conversation-search:turn-one",
    turn_id: "turn-one",
    conversation_id: "conversation-one",
    channel_id: "web",
    role: "assistant",
    snippet: {
      text: "Database latency changed.",
      highlights: [{ start: 0, end: 8 }, { start: 9, end: 16 }],
    },
    recorded_at: "2026-08-14T07:00:00Z",
    rank: 1,
    incident_id: "incident-one",
    correlation_id: "correlation-one",
    evidence_refs: ["audit:one"],
  };
}

function result(hits: readonly ConversationSearchHitPayload[]): ConversationSearchPayload {
  return { hits, result_cap: 20, index_rows: hits.length, index_bytes: 100 };
}

describe("conversation search route interactions", () => {
  test("compiles trimmed filters and timezone-aware windows", () => {
    expect(conversationSearchInput({
      ...EMPTY_FORM,
      query: "  database latency  ",
      mode: "phrase",
      channel: " web ",
      role: "assistant",
      conversationId: " conversation-one ",
      incidentId: " incident-one ",
      after: "2026-08-14T06:00",
      before: "2026-08-14T08:00",
    })).toEqual({
      query: "database latency",
      mode: "phrase",
      channel: "web",
      role: "assistant",
      conversationId: "conversation-one",
      incidentId: "incident-one",
      recordedAfter: new Date("2026-08-14T06:00").toISOString(),
      recordedBefore: new Date("2026-08-14T08:00").toISOString(),
    });
  });

  test("keeps safe ordered highlight segments without injecting markup", () => {
    expect(conversationSearchHighlightSegments(hit())).toEqual([
      { text: "Database", highlighted: true },
      { text: " ", highlighted: false },
      { text: "latency", highlighted: true },
      { text: " changed.", highlighted: false },
    ]);
    const plain = { ...hit(), snippet: { text: "<script>alert(1)</script>", highlights: [] } };
    expect(conversationSearchHighlightSegments(plain)).toEqual([
      { text: "<script>alert(1)</script>", highlighted: false },
    ]);
  });

  test("loads and hides one exact context without mutating prior state", async () => {
    const context: ConversationSearchContextPayload = {
      hit: hit(),
      before: [],
      after: [],
    };
    const fetcher = vi.fn(async () => context);
    const prior = {};

    const loaded = await toggleConversationSearchContext(
      prior,
      "conversation-search:turn-one",
      fetcher,
    );
    const hidden = await toggleConversationSearchContext(
      loaded,
      "conversation-search:turn-one",
      fetcher,
    );

    expect(fetcher).toHaveBeenCalledWith("conversation-search:turn-one", 1, 1);
    expect(loaded).toEqual({ "conversation-search:turn-one": context });
    expect(hidden).toEqual({});
    expect(prior).toEqual({});
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  test("distinguishes idle, loading, empty, unavailable, error, and results", () => {
    expect(conversationSearchViewStatus(false, null, null)).toBe("idle");
    expect(conversationSearchViewStatus(true, null, null)).toBe("loading");
    expect(conversationSearchViewStatus(false, null, result([]))).toBe("empty");
    expect(conversationSearchViewStatus(
      false,
      new UserContextRequestError("projection unavailable", 503),
      null,
    )).toBe("unavailable");
    expect(conversationSearchViewStatus(false, new Error("decoder failed"), null)).toBe("error");
    expect(conversationSearchViewStatus(false, null, result([hit()]))).toBe("results");
  });

  test("decoder failure stays an error with no synthesized result", () => {
    const decoderFailure = new Error("conversation search hit.role is invalid");
    const currentResult = null;

    expect(conversationSearchViewStatus(false, decoderFailure, currentResult)).toBe("error");
    expect(currentResult).toBeNull();
  });
});
