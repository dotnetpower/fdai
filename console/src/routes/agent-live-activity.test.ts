import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { AuditItem } from "../types";
import type { LiveAgentActivityEvent } from "./agents.model";
import {
  AGENT_LOG_LIMIT,
  agentLogFullscreenAction,
  buildAgentLogRows,
  DEFAULT_AGENT_LOG_COLUMNS,
  filterAgentLogRows,
  fallbackAfterFullscreenFailure,
  isNearLogBottom,
  toggleAgentLogColumn,
} from "./agent-activity-log-model";

function auditItem(
  seq: number,
  entry: Record<string, unknown> = {},
  recordedAt = `2026-07-24T10:00:${String(seq % 60).padStart(2, "0")}Z`,
): AuditItem {
  return {
    seq,
    event_id: `event-${seq}`,
    correlation_id: `corr-${seq}`,
    actor: "Odin",
    action_kind: "control_loop.review",
    mode: "shadow",
    entry,
    entry_hash: `hash-${seq}`,
    previous_hash: `hash-${seq - 1}`,
    recorded_at: recordedAt,
  };
}

function liveConversation(sequence = 1): LiveAgentActivityEvent {
  return {
    sequence,
    kind: "conversation.turn",
    agent: "Heimdall",
    agents: ["Heimdall", "Forseti"],
    state: null,
    summary: "Heimdall to Forseti - handoff",
    detail: "Investigate the anomaly before judgment.",
    correlationId: "corr-live",
    ts: "2026-07-24T10:01:00Z",
    source: "runtime-observed",
  };
}

describe("agent live log projection", () => {
  it("combines durable audit, recorded conversations, and runtime turns chronologically", () => {
    const audit = auditItem(1, {
      summary: "Plan reviewed",
      conversation: [
        { from: "Odin", to: "Huginn", text: "Build the bounded plan." },
        { from: "Huginn", to: "Forseti", text: "Verifier evidence is attached." },
      ],
    }, "2026-07-24T10:00:00Z");

    const rows = buildAgentLogRows([liveConversation()], [audit]);

    expect(rows).toHaveLength(4);
    expect(rows.map((row) => row.kind)).toEqual([
      "activity",
      "handoff",
      "handoff",
      "handoff",
    ]);
    expect(rows[1]).toMatchObject({
      route: ["Odin", "Huginn"],
      detail: "Build the bounded plan.",
      source: "audit-operational",
    });
    expect(rows.at(-1)).toMatchObject({
      route: ["Heimdall", "Forseti"],
      detail: "Investigate the anomaly before judgment.",
      source: "runtime-observed",
    });
  });

  it("retains only the newest bounded rows", () => {
    const audit = Array.from({ length: AGENT_LOG_LIMIT + 10 }, (_, index) =>
      auditItem(
        index,
        { summary: `row ${index}` },
        new Date(Date.UTC(2026, 6, 24, 10, 0, index)).toISOString(),
      ));

    const rows = buildAgentLogRows([], audit);

    expect(rows).toHaveLength(AGENT_LOG_LIMIT);
    expect(rows[0]?.eventId).toBe("event-10");
    expect(rows.at(-1)?.eventId).toBe(`event-${AGENT_LOG_LIMIT + 9}`);
  });

  it("filters conversations by either participant and normalized keyword", () => {
    const rows = buildAgentLogRows([liveConversation()], []);

    expect(filterAgentLogRows(rows, "Forseti", "anomaly")).toHaveLength(1);
    expect(filterAgentLogRows(rows, "Heimdall", "corr live")).toHaveLength(1);
    expect(filterAgentLogRows(rows, "Thor", "anomaly")).toHaveLength(0);
  });

  it("keeps live row identity stable across prepends and preserves identical events", () => {
    const existing = liveConversation();
    const newer: LiveAgentActivityEvent = {
      ...existing,
      sequence: 2,
      detail: "A newer handoff.",
      ts: "2026-07-24T10:02:00Z",
    };
    const identicalButDistinct = liveConversation(3);

    const before = buildAgentLogRows([existing], []);
    const after = buildAgentLogRows([identicalButDistinct, newer, existing], []);

    expect(after).toHaveLength(3);
    expect(after.find((row) => row.detail === existing.detail)?.id).toBe(before[0]?.id);
    expect(new Set(after.map((row) => row.id)).size).toBe(after.length);
  });

  it("preserves numeric audit sequence and conversation turn order at equal timestamps", () => {
    const turns = Array.from({ length: 12 }, (_, index) => ({
      from: "Odin",
      to: "Forseti",
      text: `turn-${index}`,
    }));
    const recordedAt = "2026-07-24T10:00:00Z";
    const rows = buildAgentLogRows([], [
      auditItem(10, { summary: "seq-10" }, recordedAt),
      auditItem(2, { summary: "seq-2", conversation: turns }, recordedAt),
    ]);

    expect(rows.filter((row) => row.kind === "activity").map((row) => row.detail))
      .toEqual(["seq-2", "seq-10"]);
    expect(rows.filter((row) => row.kind === "handoff").map((row) => row.detail))
      .toEqual(turns.map((turn) => turn.text));
  });

  it("retains malformed timestamps at the visible end instead of silently pruning them", () => {
    const rows = buildAgentLogRows([], [
      auditItem(1, { summary: "valid" }, "2026-07-24T10:00:00Z"),
      auditItem(2, { summary: "malformed" }, "not-a-timestamp"),
    ]);

    expect(rows.map((row) => row.detail)).toEqual(["valid", "malformed"]);
    expect(rows.at(-1)).toMatchObject({
      timestamp: "not-a-timestamp",
      timestampValid: false,
    });
  });

  it("bounds projection while expanding a large recorded conversation", () => {
    const turns = Array.from({ length: 1000 }, (_, index) => ({
      from: "Odin",
      to: "Forseti",
      text: `turn-${index}`,
    }));

    const rows = buildAgentLogRows([], [
      auditItem(1, { summary: "base", conversation: turns }),
    ]);

    expect(rows).toHaveLength(AGENT_LOG_LIMIT);
    expect(rows[0]?.detail).toBe("turn-800");
    expect(rows.at(-1)?.detail).toBe("turn-999");
  });
});

describe("agent live log controls", () => {
  it("hides Type by default and never allows every column to be hidden", () => {
    expect(DEFAULT_AGENT_LOG_COLUMNS).toEqual(["time", "route", "detail", "correlation"]);
    expect(toggleAgentLogColumn(["detail"], "detail")).toEqual(["detail"]);
    expect(toggleAgentLogColumn(DEFAULT_AGENT_LOG_COLUMNS, "type")).toEqual([
      "time",
      "route",
      "type",
      "detail",
      "correlation",
    ]);
  });

  it("uses a small bottom threshold for live-tail pause decisions", () => {
    expect(isNearLogBottom(1000, 380, 600)).toBe(true);
    expect(isNearLogBottom(1000, 300, 600)).toBe(false);
  });

  it("never layers fallback fullscreen over a failed native fullscreen exit", () => {
    const exitAction = agentLogFullscreenAction(true, true);
    const enterAction = agentLogFullscreenAction(false, true);

    expect(exitAction).toBe("exit-native");
    expect(fallbackAfterFullscreenFailure(exitAction)).toBe(false);
    expect(enterAction).toBe("enter-native");
    expect(fallbackAfterFullscreenFailure(enterAction)).toBe(true);
    expect(agentLogFullscreenAction(false, false)).toBe("enter-fallback");
  });

  it("owns row semantics with an ARIA table and explicit dimensions", () => {
    const source = readFileSync(
      fileURLToPath(new URL("./agent-live-activity.tsx", import.meta.url)),
      "utf8",
    );

    expect(source).toContain('role="log"');
    expect(source).toContain('role="table"');
    expect(source).toContain('aria-rowcount={Math.max(visibleRows.length, 1) + 1}');
    expect(source).toContain('aria-colcount={visibleColumns.length}');
  });
});
