import { describe, expect, it } from "vitest";
import type { AnswerVerification } from "./backend";
import type { Citation } from "./citations";
import {
  buildSources,
  citationMarks,
  groundingAgents,
  groundingStages,
  handoffReasonKey,
  parseReplySource,
  pillStats,
} from "./grounded-sources";

function manifestVerification(
  entries: AnswerVerification["evidence_manifest"] extends infer M
    ? M extends { entries: infer E }
      ? E
      : never
    : never,
): AnswerVerification {
  return {
    status: "verified",
    authority: "server_read_model",
    checks_completed: 2,
    checks_total: 2,
    evidence_refs: ["e-1", "e-2"],
    reason_code: null,
    evidence_manifest: {
      schema_version: 1,
      manifest_id: "m-1",
      authority: "server_read_model",
      route_id: "incident",
      captured_at: null,
      complete: true,
      source_entry_count: 2,
      entries,
    },
  };
}

describe("parseReplySource", () => {
  it("splits the canonical model, latency, and token descriptor", () => {
    expect(parseReplySource("llm:narrator-gpt-4-1-mini · 7146ms · 8.1k tok")).toEqual({
      kind: "llm",
      model: "narrator-gpt-4-1-mini",
      timing: "7146ms · 8.1k tok",
    });
  });

  it("accepts a canonical descriptor with token usage but no latency", () => {
    expect(parseReplySource("llm:narrator-gpt-4-1-mini · 8.1k tok")).toEqual({
      kind: "llm",
      model: "narrator-gpt-4-1-mini",
      timing: "8.1k tok",
    });
  });

  it("splits an llm descriptor into model and timing", () => {
    expect(parseReplySource("llm:gpt-4o-mini - 240ms")).toEqual({
      kind: "llm",
      model: "gpt-4o-mini",
      timing: "240ms",
    });
  });

  it("keeps a model with no timing", () => {
    expect(parseReplySource("llm:gpt-4o")).toEqual({
      kind: "llm",
      model: "gpt-4o",
      timing: null,
    });
  });

  it("recognises the deterministic answerer", () => {
    expect(parseReplySource("deterministic")).toEqual({
      kind: "deterministic",
      reason: null,
    });
  });

  it.each([
    ["deterministic (offline)", "offline"],
    ["deterministic (LLM not configured)", "LLM not configured"],
    ["deterministic (blocked by content policy)", "blocked by content policy"],
    ["deterministic (backend 503)", "backend 503"],
    ["deterministic (stream interrupted)", "stream interrupted"],
  ])("recognises a reason-bearing fallback: %s", (source, reason) => {
    expect(parseReplySource(source)).toEqual({ kind: "deterministic", reason });
  });

  it.each([
    "llm:",
    "llm: · 10ms",
    "llm:model · eventually",
    "llm:model · 1ms · 2ms",
    `llm:${"m".repeat(129)}`,
    "llm:model\nforged",
    `deterministic (${"r".repeat(161)})`,
  ])("rejects a malformed or oversized descriptor: %s", (source) => {
    expect(parseReplySource(source)).toEqual({ kind: "other", raw: source });
  });

  it("returns null for an absent or blank source", () => {
    expect(parseReplySource(undefined)).toBeNull();
    expect(parseReplySource("  ")).toBeNull();
  });
});

describe("buildSources", () => {
  it("prefers the evidence manifest and numbers entries in order", () => {
    const verification = manifestVerification([
      {
        ref: "e-1",
        path: "/incident/correlation_id",
        field: "correlation_id",
        kind: "id",
        raw_value: "corr-9f3a",
        normalized_value: "corr-9f3a",
        anchors: ["correlation"],
      },
      {
        ref: "e-2",
        path: "/incident/failed_count",
        field: "failed_count",
        kind: "number",
        raw_value: "3",
        normalized_value: "3",
        anchors: [],
      },
    ]);
    const sources = buildSources(verification, []);
    expect(sources).toHaveLength(2);
    expect(sources[0]).toMatchObject({ n: 1, badge: "ID", tone: "identifier", value: "corr-9f3a" });
    expect(sources[1]).toMatchObject({ n: 2, badge: "NUM", tone: "metric", value: "3" });
  });

  it("falls back to plain citations with derived badges", () => {
    const cites: Citation[] = [
      { label: "screen" },
      { label: "records.incidents", value: "12 rows" },
      { label: "tiles.failed", value: "3" },
    ];
    const sources = buildSources(undefined, cites);
    expect(sources.map((s) => s.badge)).toEqual(["SCREEN", "RECORDS", "SOURCE"]);
    // screen has no value; "12 rows" is matchable; "3" is below the 2-char
    // inline-anchor threshold so it carries no inline value.
    expect(sources[0]?.value).toBeNull();
    expect(sources[1]?.value).toBe("12 rows");
    expect(sources[2]?.value).toBeNull();
  });

  it("returns nothing when the reply carries no grounding", () => {
    expect(buildSources(undefined, [])).toEqual([]);
  });
});

describe("citationMarks", () => {
  it("keeps values of two or more characters and dedupes", () => {
    const marks = citationMarks([
      { n: 1, badge: "ID", tone: "identifier", title: "correlation_id", meta: "corr-9", path: null, value: "corr-9" },
      { n: 2, badge: "NUM", tone: "metric", title: "count", meta: "3", path: null, value: "3" },
      { n: 3, badge: "NUM", tone: "metric", title: "dup", meta: "corr-9", path: null, value: "corr-9" },
      { n: 4, badge: "SCREEN", tone: "screen", title: "screen", meta: "", path: null, value: null },
    ]);
    // "3" is one char -> dropped; "corr-9" deduped -> one mark; null -> dropped.
    expect(marks).toEqual([{ n: 1, value: "corr-9", title: "correlation_id - corr-9" }]);
  });
});

describe("pillStats", () => {
  it("emits only stats with real values", () => {
    expect(
      pillStats({ sourceCount: 7, checksCompleted: 2, checksTotal: 2, agentCount: 0 }),
    ).toEqual([
      { value: "7", label: "sources" },
      { value: "2/2", label: "checks" },
    ]);
  });

  it("uses singular labels and drops empty groups", () => {
    expect(
      pillStats({ sourceCount: 1, checksCompleted: 0, checksTotal: 0, agentCount: 1 }),
    ).toEqual([
      { value: "1", label: "source" },
      { value: "1", label: "agent" },
    ]);
  });
});

describe("groundingStages", () => {
  it("reconstructs stages from reply metadata", () => {
    const verification = manifestVerification([
      {
        ref: "e-1",
        path: "/incident/id",
        field: "id",
        kind: "id",
        raw_value: "inc-1",
        normalized_value: "inc-1",
        anchors: [],
      },
    ]);
    const sources = buildSources(verification, []);
    const stages = groundingStages({
      sources,
      source: "llm:gpt-4o-mini - 120ms",
      verification,
      agents: ["Forseti"],
    });
    expect(stages.map((s) => s.side)).toEqual(["read", "route", "read", "ground", "verify"]);
    expect(stages.map((s) => s.status)).toEqual([
      "complete",
      "complete",
      "complete",
      "complete",
      "complete",
    ]);
    expect(stages[1]).toMatchObject({
      action: "infer",
      label: "Reasoned with gpt-4o-mini",
      detail: "120ms",
      model: "gpt-4o-mini",
    });
    expect(stages[2]).toMatchObject({
      action: "consult",
      label: "Consulted specialist agents",
      detail: "Forseti",
    });
  });

  it("keeps model inference visible when a follow-up has no new citations", () => {
    expect(
      groundingStages({
        sources: [],
        source: "llm:gpt-4o-mini - 95ms",
        verification: undefined,
        agents: [],
      }),
    ).toEqual([{
      action: "infer",
      label: "Reasoned with gpt-4o-mini",
      detail: "95ms",
      side: "route",
      status: "complete",
      model: "gpt-4o-mini",
    }]);
  });

  it("keeps a deterministic fallback visible without adding an LLM stage", () => {
    const stages = groundingStages({
      sources: [],
      source: "deterministic (offline)",
      verification: undefined,
      agents: [],
    });

    expect(stages).toEqual([{
      action: "deterministic",
      label: "Used deterministic answerer",
      detail: "offline",
      side: "route",
      status: "complete",
    }]);
    expect(stages.some((stage) => stage.action === "infer")).toBe(false);
  });

  it("shows a specialist handoff to Bragi", () => {
    const stages = groundingStages({
      sources: [],
      source: "llm:narrator-mini",
      verification: undefined,
      agents: ["Heimdall"],
      handoff: {
        from: "Heimdall",
        to: "Bragi",
        reason: "insufficient_agent_evidence",
      },
    });

    expect(stages.find((stage) => stage.action === "handoff")).toEqual({
      action: "handoff",
      label: "Agent handoff: Heimdall to Bragi",
      detail: "insufficient_agent_evidence",
      side: "route",
      status: "attention",
      from: "Heimdall",
      to: "Bragi",
      reasonCode: "insufficient_agent_evidence",
    });
  });

  it("does not claim a failed handoff agent was consulted", () => {
    expect(groundingAgents({
      primary_agent: "Bragi",
      contributors: [],
      handoff_from: "Huginn",
      handoff_reason: "agent_conversational_port_unavailable",
    }, undefined)).toEqual([]);
    expect(groundingAgents({
      primary_agent: "Huginn",
      contributors: [],
    }, undefined)).toEqual(["Huginn"]);
    expect(groundingAgents(undefined, { contributions: [] })).toEqual([]);
  });

  it("maps handoff machine reasons to bounded display keys", () => {
    expect(handoffReasonKey("agent_conversational_port_unavailable"))
      .toBe("deck.grounded.handoffReason.portUnavailable");
    expect(handoffReasonKey("unrecognized"))
      .toBe("deck.grounded.handoffReason.default");
  });

  it("marks an unverified answer check as requiring attention", () => {
    const verification = {
      ...manifestVerification([]),
      status: "unverified" as const,
      checks_completed: 1,
      checks_total: 2,
    };

    expect(
      groundingStages({
        sources: [],
        source: "llm:gpt-4o-mini",
        verification,
        agents: [],
      }).at(-1),
    ).toMatchObject({
      action: "verify",
      label: "Checked answer",
      detail: "1/2 checks",
      status: "attention",
    });
  });

  it("marks an incomplete evidence manifest as partial grounding", () => {
    const completeVerification = manifestVerification([
      {
        ref: "e-1",
        path: "/incident/id",
        field: "id",
        kind: "id",
        raw_value: "inc-1",
        normalized_value: "inc-1",
        anchors: [],
      },
    ]);
    const verification: AnswerVerification = {
      ...completeVerification,
      evidence_manifest: {
        ...completeVerification.evidence_manifest!,
        complete: false,
        source_entry_count: 3,
      },
    };

    expect(
      groundingStages({
        sources: buildSources(verification, []),
        source: "llm:gpt-4o-mini",
        verification,
        agents: [],
      }).find((stage) => stage.action === "ground"),
    ).toMatchObject({
      action: "ground",
      detail: "1/3 manifest sources available",
      status: "attention",
    });
  });

  it("returns nothing when the reply carries no grounding metadata", () => {
    expect(
      groundingStages({ sources: [], source: undefined, verification: undefined, agents: [] }),
    ).toEqual([]);
  });
});
