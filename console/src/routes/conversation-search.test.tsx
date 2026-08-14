import { describe, expect, test } from "vitest";
import {
  conversationSearchHighlightSegments,
  conversationSearchInput,
  conversationSearchViewStatus,
  type SearchForm,
  toggleConversationSearchContext,
} from "./conversation-search.model";
import {
  decodeConversationSearch,
  type ConversationSearchHitPayload,
  UserContextRequestError,
} from "../user-context-client";

const form: SearchForm = {
  query: "  database latency  ",
  mode: "phrase",
  channel: " web ",
  role: "operator",
  conversationId: " conversation-1 ",
  incidentId: " INC-1 ",
  after: "2026-08-14T09:00",
  before: "2026-08-14T10:00",
};

const hit: ConversationSearchHitPayload = {
  result_id: "conversation-search:turn-1",
  turn_id: "turn-1",
  conversation_id: "conversation-1",
  channel_id: "web",
  role: "operator",
  snippet: { text: "database latency", highlights: [{ start: 0, end: 8 }] },
  recorded_at: "2026-08-14T00:00:00Z",
  rank: 1,
  incident_id: "INC-1",
  correlation_id: "correlation-1",
  evidence_refs: ["audit:1"],
};

describe("conversation search route decisions", () => {
  test("serializes every form filter with trimmed identifiers and UTC bounds", () => {
    expect(conversationSearchInput(form)).toEqual({
      query: "database latency",
      mode: "phrase",
      channel: "web",
      role: "operator",
      conversationId: "conversation-1",
      incidentId: "INC-1",
      recordedAfter: new Date(form.after).toISOString(),
      recordedBefore: new Date(form.before).toISOString(),
    });
  });

  test("renders valid highlight ranges and degrades malformed ranges to plain text", () => {
    expect(conversationSearchHighlightSegments(hit)).toEqual([
      { text: "database", highlighted: true },
      { text: " latency", highlighted: false },
    ]);
    expect(conversationSearchHighlightSegments({
      ...hit,
      snippet: { ...hit.snippet, highlights: [{ start: 4, end: 99 }] },
    })).toEqual([{ text: "database latency", highlighted: false }]);
  });

  test.each([404, 501, 503])("renders optional source status %i as unavailable", (status) => {
    expect(conversationSearchViewStatus(
      false,
      new UserContextRequestError("source unavailable", status),
      null,
    )).toBe("unavailable");
  });

  test("merges concurrent context results and toggles one without losing another", () => {
    const secondHit = { ...hit, result_id: "conversation-search:turn-2" };
    const firstContext = { hit, before: [], after: [] };
    const secondContext = { hit: secondHit, before: [], after: [] };

    const first = toggleConversationSearchContext({}, hit.result_id, firstContext);
    const both = toggleConversationSearchContext(
      first,
      secondHit.result_id,
      secondContext,
    );
    expect(both).toEqual({
      [hit.result_id]: firstContext,
      [secondHit.result_id]: secondContext,
    });
    expect(toggleConversationSearchContext(both, hit.result_id, null)).toEqual({
      [secondHit.result_id]: secondContext,
    });
  });

  test("keeps decoder failures visible without synthesizing search content", () => {
    let failure: unknown;
    try {
      decodeConversationSearch({ hits: null, result_cap: 20, index_rows: 0, index_bytes: 0 });
    } catch (reason) {
      failure = reason;
    }
    expect(conversationSearchViewStatus(false, failure, null)).toBe("error");
  });

  test("keeps an authorized empty result distinct from source unavailability", () => {
    expect(decodeConversationSearch({
      hits: [],
      result_cap: 20,
      index_rows: 0,
      index_bytes: 0,
    }).hits).toEqual([]);
    expect(conversationSearchViewStatus(
      false,
      new UserContextRequestError("source unavailable", 503),
      null,
    )).toBe("unavailable");
  });
});
