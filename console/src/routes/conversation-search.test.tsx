import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
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

const ROUTES_DIR = fileURLToPath(new URL("./", import.meta.url));

function readRoute(name: string): string {
  return readFileSync(`${ROUTES_DIR}${name}`, "utf8");
}

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

describe("evidence domain Wave 1 UI invariants", () => {
  test("eliminates raw select, input, and details elements across evidence routes", () => {
    const routeFiles = [
      "audit.filters.tsx",
      "audit.workspace.tsx",
      "rule-trace.tsx",
      "rule-trace-discovery.tsx",
      "rule-trace-workspace.tsx",
      "rule-trace-supporting-evidence.tsx",
      "rca.tsx",
      "rca-causal-chain.tsx",
      "browser-evidence.filters.tsx",
      "browser-evidence.detail.tsx",
      "reports.presentation.tsx",
      "conversation-search.tsx",
    ];
    for (const file of routeFiles) {
      const source = readRoute(file);
      expect(source, file).not.toMatch(/<(select|input|textarea|details)\b/);
    }
  });

  test("enforces >= 12px font-size floor and zero colored accent bars across evidence CSS", () => {
    const cssFiles = [
      "audit.workspace.css",
      "rule-trace.css",
      "rule-trace-experience.css",
      "rule-trace-lifecycle.css",
      "rca.css",
      "browser-evidence.css",
      "reports.css",
      "conversation-search.css",
    ];
    for (const file of cssFiles) {
      const css = readRoute(file);
      const sub12Px = [...css.matchAll(/font-size:\s*(\d+(?:\.\d+)?)px\b/g)]
        .filter((m) => Number.parseFloat(m[1] ?? "12") < 12)
        .map((m) => `${file}: ${m[0]}`);
      expect(sub12Px).toEqual([]);
      expect(css, file).not.toMatch(/border-(left|top):\s*[2-9]px\s+solid/);
    }
  });

  test("wires Wave 0 domain primitives and removes duplicate conversation-search banner", () => {
    const conv = readRoute("conversation-search.tsx");
    expect(conv).not.toContain("governance-readonly-banner");
    expect(conv).toContain("ConversationTurnItem");
    expect(readRoute("audit.workspace.tsx")).toContain("HashChainBadge");
    expect(readRoute("audit.workspace.tsx")).toContain("CorrelationTimeline");
    expect(readRoute("browser-evidence.detail.tsx")).toContain("HashChainBadge");
    expect(readRoute("rule-trace-supporting-evidence.tsx")).toContain("CorrelationTimeline");
    expect(readRoute("rca-causal-chain.tsx")).toContain("CorrelationTimeline");
  });
});
