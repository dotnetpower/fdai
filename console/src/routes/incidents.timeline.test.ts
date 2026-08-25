import { describe, expect, it } from "vitest";
import type { AuditItem } from "../types";
import { incidentTimelinePresentation } from "./incidents.timeline";

function interventionItem(): AuditItem {
  return {
    seq: 9,
    event_id: "event-nine",
    correlation_id: "correlation-one",
    actor: "Saga",
    action_kind: "incident.intervention-applied",
    mode: "enforce",
    entry: {
      kind: "incident.intervention-applied",
      action: "create_development_exception",
      comment: "Expected behavior during active development.",
      result_ref: "00000000-0000-0000-0000-000000000123",
      accountable_agent: "Saga",
    },
    entry_hash: "sha256:entry",
    previous_hash: "sha256:previous",
    recorded_at: "2026-08-24T12:00:00Z",
  };
}

describe("incident intervention timeline presentation", () => {
  it("renders the request, justification, accountable agent, and result for people", () => {
    const presentation = incidentTimelinePresentation(interventionItem());

    expect(presentation.title).toBe("Operator intervention recorded");
    expect(presentation.description).toContain("Create an intake exception");
    expect(presentation.description).toContain("Expected behavior during active development.");
    expect(presentation.owner).toBe("Saga");
    expect(presentation.ownerKind).toBe("agent");
    expect(presentation.facts).toContainEqual({
      label: "Result reference",
      value: "00000000-0000-0000-0000-000000000123",
    });
  });
});
