import { describe, expect, test } from "vitest";
import { parseIncidentCandidates } from "./backend";
import {
  incidentCandidateAnswerLead,
  incidentCandidateDeckDetail,
} from "./grounded-reply";
import { parseTurns, serializeTurns } from "./transcript-store";

const artifact = {
  schema_version: 1,
  locale: "ko",
  candidates: [{
    incident_id: "INC-1",
    correlation_id: "corr-1",
    title: "Pod restart",
    severity: "high",
    status: "open",
    last_updated_at: "2026-08-04T00:01:00Z",
  }],
};

describe("incident candidate selection", () => {
  test("parses a bounded candidate and creates an exact incident binding", () => {
    const candidates = parseIncidentCandidates(artifact);
    expect(candidates).toHaveLength(1);
    expect(incidentCandidateDeckDetail(candidates[0]!)).toMatchObject({
      sessionKey: "incident:corr-1",
      binding: {
        kind: "incident",
        incidentId: "INC-1",
        correlationId: "corr-1",
      },
      onlyWhenIdle: true,
      newConversation: true,
      prompt: "이 인시던트의 원인을 조사해줘.",
      submitPrompt: true,
    });
  });

  test("shows one lead sentence instead of repeating candidate bullets", () => {
    expect(incidentCandidateAnswerLead(
      "여러 인시던트가 일치합니다. 선택해 주세요:\n- corr-1: Pod restart\n- corr-2: Memory",
    )).toBe("여러 인시던트가 일치합니다. 선택해 주세요:");
  });

  test("rejects an unbounded or malformed candidate artifact", () => {
    expect(parseIncidentCandidates({ ...artifact, candidates: [] })).toEqual([]);
    expect(parseIncidentCandidates({
      ...artifact,
      candidates: [{ ...artifact.candidates[0], incident_id: "bad\nvalue" }],
    })).toEqual([]);
  });

  test("persists verified candidates across transcript reload", () => {
    const candidates = parseIncidentCandidates(artifact);
    const turns = parseTurns(serializeTurns([{
      id: "deck-1",
      role: "deck",
      text: "Choose an incident.",
      at: "05:00:00",
      terminal: true,
      incidentCandidates: candidates,
    }]));

    expect(turns[0]?.incidentCandidates).toEqual(candidates);
  });
});
