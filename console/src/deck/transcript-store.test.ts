import { describe, expect, it } from "vitest";
import {
  parseTurns,
  serializeTurns,
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
    expect(parsed[1]!.answerPlanning?.consulted_agents).toEqual(["Freyr", "Njord"]);
    expect(parsed[1]!.verification?.status).toBe("corrected");
    expect(parsed[1]!.verification?.claims?.[0]?.claim_id).toBe("c001");
    expect(parsed[1]!.verification?.evidence_manifest?.manifest_id).toBe("sha256:abc");
    expect(parsed[2]!.agent).toBe("Forseti"); // agent identity survives reload
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
});

describe("parseTurns", () => {
  it("returns [] for null, empty, or malformed JSON", () => {
    expect(parseTurns(null)).toEqual([]);
    expect(parseTurns("")).toEqual([]);
    expect(parseTurns("not json")).toEqual([]);
    expect(parseTurns("{}")).toEqual([]);
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
});
