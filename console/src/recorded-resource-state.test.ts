import { describe, expect, test } from "vitest";
import { decodeRecordedResourceStates } from "./recorded-resource-state";

const missing = (reason: string) => ({
  value: null,
  source_path: null,
  observed_at: null,
  recorded_at: null,
  freshness: "unknown",
  completeness: null,
  conflicts: [],
  reason,
});

describe("recorded resource state decoder", () => {
  test.each([
    "state_source_not_recorded",
    "provider_operational_state_not_exposed",
    "resource_health_projection_not_bound",
    "state_not_applicable",
    "state_applicability_unknown",
    "resource_type_unclassified",
  ])("preserves the operational qualification %s", (reason) => {
    const states = decodeRecordedResourceStates({
      schema_version: "1.0.0",
      operational: missing(reason),
      provisioning: {
        value: "Succeeded",
        source_path: "properties.provisioningState",
        observed_at: "2026-09-06T01:43:22Z",
        recorded_at: "2026-09-06T01:43:30Z",
        freshness: "fresh",
        completeness: 1,
        conflicts: [],
        reason: null,
      },
      availability: missing("state_not_recorded"),
    });

    expect(states.operational.reason).toBe(reason);
    expect(states.operational.freshness).toBe("unknown");
    expect(states.provisioning.value).toBe("Succeeded");
    expect(states.provisioning.observed_at).toBe("2026-09-06T01:43:22Z");
    expect(states.provisioning.completeness).toBe(1);
  });
});
