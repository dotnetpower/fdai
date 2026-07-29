import { describe, expect, it } from "vitest";
import {
  parseTurns,
  serializeTurns,
  MAX_TRANSCRIPT_JSON_CHARS,
  MAX_TRANSCRIPT_TURNS,
  transcriptKeyFor,
  TRANSCRIPT_KEY,
  type PersistedTurn,
} from "./transcript-store";

describe("transcriptKeyFor", () => {
  it("keeps the general session on the base key (back-compat)", () => {
    expect(transcriptKeyFor("screen")).toBe(TRANSCRIPT_KEY);
  });

  it("gives each non-general session its own namespaced key", () => {
    expect(transcriptKeyFor("agent:Forseti")).toBe(`${TRANSCRIPT_KEY}::agent:Forseti`);
    expect(transcriptKeyFor("agent:Forseti")).not.toBe(transcriptKeyFor("agent:Odin"));
  });
});

describe("serializeTurns", () => {
  it("round-trips completed turns", () => {
    const turns = [
      { id: "1", role: "operator" as const, text: "what is the tier mix?", at: "10:00:00" },
      {
        id: "2",
        role: "deck" as const,
        text: "T0 78%",
        at: "10:00:01",
        source: "llm:x",
        citations: [{ label: "tier", value: "T0" }],
        followUps: ["Show T1"],
        terminal: true,
        revision: 1,
        resourceContext: {
          name: "db-current",
          resource_type: "postgresql-server",
          evidence_ref: "inventory:/subscriptions/test/resourceGroups/rg/providers/db/current",
        },
        answerPlanning: {
          mode: "shadow" as const,
          status: "completed" as const,
          primary_agent: "Forseti",
          consulted_agents: ["Freyr", "Njord"],
          contributions: [
            {
              agent: "Freyr",
              evidence_refs: ["agent-owned:freyr:1"],
              confidence: 0.8,
              suggested_sections: ["trade_offs"],
            },
          ],
          failures: [],
          elapsed_ms: 12,
          unique_evidence_count: 1,
          duplicate_evidence_count: 0,
          conflicting_evidence_refs: [],
          covered_sections: ["trade_offs"],
          estimated_added_tokens: 24,
          budget: {
            max_contributors: 2,
            max_rounds: 1,
            max_wall_ms: 1200,
            max_added_tokens: 800,
            nested_rounds: false as const,
          },
          reason: null,
        },
        delegation: {
          primary_agent: "Heimdall",
          contributors: ["Forseti"],
          trace_ref: "trace-agent-grounding",
        },
        verification: {
          status: "corrected" as const,
          authority: "server_read_model",
          checks_completed: 1,
          checks_total: 1,
          evidence_refs: ["incident:corr-1"],
          reason_code: "grounded_rca",
          claims: [{
            claim_id: "c001",
            kind: "id" as const,
            text: "corr-1",
            span: { start: 0, end: 6 },
            raw_value: "corr-1",
            normalized_value: "corr-1",
            unit: null,
            anchors: ["correlation"],
            status: "supported" as const,
            evidence_refs: ["incident:corr-1"],
            reason_code: null,
          }],
          failed_claim_ids: [],
          evidence_manifest: {
            schema_version: 1,
            manifest_id: "sha256:abc",
            authority: "server_read_model",
            route_id: "incidents",
            captured_at: "2026-07-15T00:00:00Z",
            complete: true,
            source_entry_count: 1,
            entries: [{
              ref: "incident:corr-1",
              path: "/incident/correlation_id",
              field: "correlation_id",
              kind: "id",
              raw_value: "corr-1",
              normalized_value: "corr-1",
              anchors: ["correlation"],
            }],
          },
        },
      },
      {
        id: "3",
        role: "deck" as const,
        text: "Context for Forseti",
        groundingText: "Context for a conversation about the FDAI agent Forseti.",
        at: "10:00:02",
        source: "context",
        agent: "Forseti",
      },
    ];
    const parsed = parseTurns(serializeTurns(turns));
    expect(parsed).toHaveLength(3);
    expect(parsed[0]!.text).toBe("what is the tier mix?");
    expect(parsed[1]!.source).toBe("llm:x");
    expect(parsed[1]!.citations).toEqual([{ label: "tier", value: "T0" }]);
    expect(parsed[1]!.followUps).toEqual(["Show T1"]);
    expect(parsed[1]!.terminal).toBe(true);
    expect(parsed[1]!.revision).toBe(1);
    expect(parsed[1]!.resourceContext?.name).toBe("db-current");
    expect(parsed[1]!.answerPlanning?.consulted_agents).toEqual(["Freyr", "Njord"]);
    expect(parsed[1]!.delegation).toEqual({
      primary_agent: "Heimdall",
      contributors: ["Forseti"],
      trace_ref: "trace-agent-grounding",
    });
    expect(parsed[1]!.verification?.status).toBe("corrected");
    expect(parsed[1]!.verification?.claims?.[0]?.claim_id).toBe("c001");
    expect(parsed[1]!.verification?.evidence_manifest?.manifest_id).toBe("sha256:abc");
    expect(parsed[2]!.agent).toBe("Forseti"); // agent identity survives reload
    expect(parsed[2]!.groundingText).toContain("FDAI agent Forseti");
  });

  it("drops a still-streaming turn", () => {
    const turns = [
      { id: "1", role: "operator" as const, text: "hi", at: "10:00:00" },
      { id: "2", role: "deck" as const, text: "partial", at: "10:00:01", streaming: true },
    ];
    const parsed = parseTurns(serializeTurns(turns));
    expect(parsed).toHaveLength(1);
    expect(parsed[0]!.id).toBe("1");
  });

  it("round-trips a completed investigation timeline", () => {
    const turns = [{
      id: "activity-1",
      role: "deck" as const,
      kind: "activity" as const,
      text: "Resolve scope\nCheck health",
      at: "10:00:00",
      terminal: true,
      branches: [
        {
          branchId: "request-1:tool",
          kind: "tool" as const,
          parentBranchId: null,
          status: "completed" as const,
          summary: "tool evidence ready",
          startedAt: "2026-07-27T01:00:00Z",
          completedAt: "2026-07-27T01:00:01Z",
          durationMs: 1000,
          evidenceRefs: ["tool:result:1"],
        },
      ],
      activities: [
        {
          activityId: "scope",
          kind: "scope.resolved",
          status: "completed" as const,
          label: "Resolve scope",
          completed: 1,
          total: 1,
          execution: {
            tool: "Azure CLI",
            command: "az resource show --ids <resource-id>",
            redacted: true as const,
            output: "{\"status\": \"available\"}",
            exitCode: 0,
            durationMs: 250,
          },
        },
      ],
    }];

    const parsed = parseTurns(serializeTurns(turns));

    expect(parsed[0]?.kind).toBe("activity");
    expect(parsed[0]?.branches?.[0]?.status).toBe("completed");
    expect(parsed[0]?.activities?.[0]?.activityId).toBe("scope");
    expect(parsed[0]?.activities?.[0]?.execution?.command).toContain("az resource show");
    expect(parsed[0]?.activities?.[0]?.execution?.output).toContain("available");
  });

  it("restores phased activity groups around progress milestones in causal order", () => {
    const turns = [
      {
        id: "activity-1",
        role: "deck" as const,
        kind: "activity" as const,
        text: "Resolve resource",
        at: "10:00:00",
        streaming: false,
        terminal: true,
        activities: [{
          activityId: "resource",
          kind: "resource.resolved",
          status: "completed" as const,
          label: "Resource resolved",
          completed: 1,
          total: 1,
        }],
      },
      {
        id: "milestone-resource",
        role: "deck" as const,
        kind: "message" as const,
        text: "The resource is resolved. I am checking evidence next.",
        at: "10:00:01",
        streaming: false,
        terminal: true,
      },
      {
        id: "activity-2",
        role: "deck" as const,
        kind: "activity" as const,
        text: "Check health",
        at: "10:00:02",
        streaming: false,
        terminal: true,
        activities: [{
          activityId: "health",
          kind: "health.completed",
          status: "completed" as const,
          label: "Resource Health checked",
          completed: 1,
          total: 1,
        }],
      },
    ];

    const parsed = parseTurns(serializeTurns(turns));

    expect(parsed.map((turn) => turn.id)).toEqual([
      "activity-1",
      "milestone-resource",
      "activity-2",
    ]);
    expect(parsed.map((turn) => turn.kind)).toEqual(["activity", "message", "activity"]);
    expect(parsed.filter((turn) => turn.kind === "activity").every(
      (turn) => turn.terminal === true,
    )).toBe(true);
  });

  it("drops a stopped provisional assistant turn", () => {
    const turns = [
      { id: "1", role: "operator" as const, text: "hi", at: "10:00:00" },
      {
        id: "2",
        role: "deck" as const,
        text: "provisional",
        at: "10:00:01",
        streaming: false,
        terminal: false,
      },
    ];

    const parsed = parseTurns(serializeTurns(turns));

    expect(parsed.map((turn) => turn.id)).toEqual(["1"]);
  });

  it("drops empty-text turns", () => {
    const turns = [
      { id: "1", role: "operator" as const, text: "   ", at: "10:00:00" },
      { id: "2", role: "deck" as const, text: "real", at: "10:00:01" },
    ];
    const parsed = parseTurns(serializeTurns(turns));
    expect(parsed).toHaveLength(1);
    expect(parsed[0]!.id).toBe("2");
  });

  it("caps to the most recent maxTurns", () => {
    const turns: PersistedTurn[] = Array.from({ length: 5 }, (_, i) => ({
      id: String(i),
      role: "operator" as const,
      text: `q${i}`,
      at: "10:00:00",
    }));
    const parsed = parseTurns(serializeTurns(turns, 2));
    expect(parsed.map((t) => t.id)).toEqual(["3", "4"]);
  });

  it("uses the default cap when maxTurns is invalid and honors zero", () => {
    const turns: PersistedTurn[] = Array.from({ length: 45 }, (_, index) => ({
      id: String(index),
      role: "operator",
      text: `q${index}`,
      at: "10:00:00",
    }));

    expect(parseTurns(serializeTurns(turns, -1))).toHaveLength(MAX_TRANSCRIPT_TURNS);
    expect(parseTurns(serializeTurns(turns, Number.POSITIVE_INFINITY))).toHaveLength(
      MAX_TRANSCRIPT_TURNS,
    );
    expect(parseTurns(serializeTurns(turns, 0))).toEqual([]);
  });

  it("drops oldest turns until the serialized transcript fits the aggregate cap", () => {
    const turns: PersistedTurn[] = Array.from({ length: 40 }, (_, index) => ({
      id: String(index),
      role: "deck",
      text: "x".repeat(200_000),
      at: "10:00:00",
    }));

    const serialized = serializeTurns(turns);
    expect(serialized.length).toBeLessThanOrEqual(MAX_TRANSCRIPT_JSON_CHARS);
    const parsed = parseTurns(serialized);
    expect(parsed.length).toBeLessThan(40);
    expect(parsed.at(-1)?.id).toBe("39");
  });
});

describe("parseTurns", () => {
  it("returns [] for null, empty, or malformed JSON", () => {
    expect(parseTurns(null)).toEqual([]);
    expect(parseTurns("")).toEqual([]);
    expect(parseTurns("not json")).toEqual([]);
    expect(parseTurns("{}")).toEqual([]);
    expect(parseTurns(" ".repeat(MAX_TRANSCRIPT_JSON_CHARS + 1))).toEqual([]);
  });

  it("skips entries missing required fields or with a bad role", () => {
    const raw = JSON.stringify([
      { id: "1", role: "operator", text: "ok", at: "10:00:00" },
      { id: "2", role: "system", text: "bad role", at: "10:00:00" },
      { role: "deck", text: "no id", at: "10:00:00" },
      { id: "4", role: "deck", at: "10:00:00" },
    ]);
    const parsed = parseTurns(raw);
    expect(parsed).toHaveLength(1);
    expect(parsed[0]!.id).toBe("1");
  });

  it("replays malformed verification counters as bounded unverified metadata", () => {
    const raw = JSON.stringify([{
      id: "1",
      role: "deck",
      text: "answer",
      at: "10:00:00",
      verification: {
        status: "verified",
        authority: "server_read_model",
        checks_completed: 3,
        checks_total: 1,
        evidence_refs: [],
        reason_code: null,
      },
    }]);

    expect(parseTurns(raw)[0]?.verification).toMatchObject({
      status: "unverified",
      checks_completed: 0,
      checks_total: 0,
      reason_code: "malformed_verification_artifact",
    });
  });

  it("does not restore an oversized verification claim array", () => {
    const raw = JSON.stringify([{
      id: "1",
      role: "deck",
      text: "answer",
      at: "10:00:00",
      verification: {
        status: "verified",
        authority: "server_read_model",
        checks_completed: 1,
        checks_total: 1,
        evidence_refs: [],
        reason_code: null,
        claims: Array(65).fill({}),
      },
    }]);

    const verification = parseTurns(raw)[0]?.verification;
    expect(verification?.status).toBe("unverified");
    expect(verification?.claims).toEqual([]);
    expect(verification?.reason_code).toBe("malformed_verification_artifact");
  });

  it("bounds replay turn count and text", () => {
    const turns = Array.from({ length: MAX_TRANSCRIPT_TURNS + 5 }, (_, index) => ({
      id: String(index),
      role: "deck",
      text: index === MAX_TRANSCRIPT_TURNS + 4 ? "x".repeat(256 * 1024 + 1) : `a${index}`,
      at: "10:00:00",
    }));

    const parsed = parseTurns(JSON.stringify(turns));
    expect(parsed).toHaveLength(MAX_TRANSCRIPT_TURNS - 1);
    expect(parsed[0]?.id).toBe("5");
    expect(parsed.at(-1)?.id).toBe(String(MAX_TRANSCRIPT_TURNS + 3));
  });

  it("drops oversized optional replay collections", () => {
    const raw = JSON.stringify([{
      id: "1",
      role: "deck",
      text: "answer",
      at: "10:00:00",
      agent: "A".repeat(65),
      citations: Array(513).fill({ label: "source" }),
      followUps: Array(9).fill("next"),
      activities: [{
        activityId: "activity",
        kind: "read",
        status: "running",
        label: "x".repeat(513),
        completed: 2,
        total: 1,
      }],
    }]);

    const turn = parseTurns(raw)[0];
    expect(turn?.agent).toBeUndefined();
    expect(turn?.citations).toBeUndefined();
    expect(turn?.followUps).toBeUndefined();
    expect(turn?.activities).toBeUndefined();
  });
});
