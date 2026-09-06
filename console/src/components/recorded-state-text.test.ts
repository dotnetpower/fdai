import { describe, expect, test } from "vitest";
import type { RecordedStateFact } from "../recorded-resource-state";
import {
  recordedStateReasonText,
  recordedStateValueText,
} from "./recorded-state-text";

function missingFact(reason: string): RecordedStateFact {
  return {
    value: null,
    source_path: null,
    observed_at: null,
    recorded_at: null,
    freshness: "unknown",
    completeness: null,
    conflicts: [],
    reason,
  };
}

describe("recorded state text", () => {
  test.each([
    ["state_source_not_recorded", "Not recorded"],
    ["provider_operational_state_not_exposed", "Unavailable"],
    ["resource_health_projection_not_bound", "State source not connected"],
    ["state_not_applicable", "Not applicable"],
    ["state_applicability_unknown", "Applicability unknown"],
    ["resource_type_unclassified", "Unavailable"],
  ])("distinguishes %s from a generic missing record", (reason, expected) => {
    expect(recordedStateValueText(missingFact(reason))).toBe(expected);
  });

  test("keeps an exact provider value ahead of its qualification", () => {
    expect(recordedStateValueText({
      ...missingFact("state_stale"),
      value: "PowerState/deallocated",
      source_path: "status",
    })).toBe("PowerState/deallocated");
  });

  test("explains reviewed unavailability while preserving machine reasons separately", () => {
    expect(recordedStateReasonText("provider_operational_state_not_exposed")).toBe(
      "The provider inventory does not expose operational state for this resource type.",
    );
    expect(recordedStateReasonText("resource_health_projection_not_bound")).toBe(
      "Azure Resource Health is not connected to recorded resource state for this resource type.",
    );
    expect(recordedStateReasonText("state_metadata_invalid")).toBeNull();
  });
});
