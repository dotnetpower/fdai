import { describe, expect, it } from "vitest";
import type { AuditItem } from "../types";
import type { LiveAgentActivityEvent } from "./agents.model";
import {
  AGENT_LOG_LIMIT,
  buildAgentLogRows,
  DEFAULT_AGENT_LOG_COLUMNS,
  filterAgentLogRows,
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

function liveConversation(): LiveAgentActivityEvent {
  return {
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
});
