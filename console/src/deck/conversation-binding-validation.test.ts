import { describe, expect, test } from "vitest";

import { normalizeIncidentBinding, parseConversationIndex } from "./conversation-sessions";

const VALID = {
  kind: "incident",
  incidentId: "INC-1",
  correlationId: "corr-1",
};

describe("incident conversation binding validation", () => {
  test("accepts a valid incident binding", () => {
    expect(normalizeIncidentBinding(VALID)).toEqual(VALID);
  });

  test("normalizes surrounding identifier whitespace", () => {
    expect(normalizeIncidentBinding({
      ...VALID,
      incidentId: "  INC-1 ",
      correlationId: " corr-1  ",
    })).toEqual(VALID);
  });

  test("accepts and normalizes a Pantheon agent", () => {
    expect(normalizeIncidentBinding({ ...VALID, selectedAgent: " Var " }))
      .toEqual({ ...VALID, selectedAgent: "Var" });
  });

  test("omits an unknown optional agent without losing the incident binding", () => {
    expect(normalizeIncidentBinding({ ...VALID, selectedAgent: "Unknown" })).toEqual(VALID);
  });

  test("rejects whitespace-only incident identifiers", () => {
    expect(normalizeIncidentBinding({ ...VALID, incidentId: "   " })).toBeNull();
    expect(normalizeIncidentBinding({ ...VALID, correlationId: "   " })).toBeNull();
  });

  test("rejects identifiers beyond the server cap", () => {
    expect(normalizeIncidentBinding({ ...VALID, incidentId: "x".repeat(257) })).toBeNull();
    expect(normalizeIncidentBinding({ ...VALID, correlationId: "x".repeat(257) })).toBeNull();
  });

  test("rejects non-incident and non-object values", () => {
    expect(normalizeIncidentBinding({ ...VALID, kind: "agent" })).toBeNull();
    expect(normalizeIncidentBinding([])).toBeNull();
    expect(normalizeIncidentBinding(null)).toBeNull();
  });

  test("ignores unknown fields", () => {
    expect(normalizeIncidentBinding({ ...VALID, executor_identity: "forged" })).toEqual(VALID);
  });

  test("keeps a conversation whose persisted binding is invalid", () => {
    const parsed = parseConversationIndex(JSON.stringify([{
      key: "conversation:1",
      label: "Incident",
      kind: "screen-thread",
      originPath: "/incidents",
      originLabel: "Incidents",
      createdAt: "2026-07-22T00:00:00Z",
      updatedAt: "2026-07-22T00:00:00Z",
      binding: { ...VALID, incidentId: "   " },
    }]));

    expect(parsed).toHaveLength(1);
    expect(parsed[0]?.binding).toBeUndefined();
  });

  test("recognizes every fixed Pantheon agent", () => {
    const names = [
      "Odin", "Heimdall", "Huginn", "Forseti", "Var", "Thor", "Vidar", "Saga",
      "Bragi", "Njord", "Freyr", "Loki", "Mimir", "Norns", "Muninn",
    ];

    for (const selectedAgent of names) {
      expect(normalizeIncidentBinding({ ...VALID, selectedAgent })?.selectedAgent)
        .toBe(selectedAgent);
    }
  });
});
