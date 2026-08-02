import { describe, expect, test } from "vitest";

import type { OperatorApiClient } from "../api";
import { decodeDetectionReadiness, loadDetectionReadinessState } from "./detection-readiness";

const RESPONSE = {
  source: "muninn-state-snapshot",
  observed_at: "2026-07-24T01:00:00Z",
  target_count: 1,
  counts: { ready: 0, partial: 1, blocked: 0, stale: 0, unauthorized: 0, unknown: 0 },
  targets: [{
    resource_ref: "cluster/example",
    generated_at: "2026-07-24T01:00:00Z",
    decision: "partial",
    authority_ceiling: "shadow",
    observations: [{ dimension: "discovered", status: "passed" }],
    missing_dimensions: ["collector_configured"],
    stale_dimensions: [],
  }],
};

describe("detection readiness decoder", () => {
  test("decodes agent-owned snapshots", () => {
    const view = decodeDetectionReadiness(RESPONSE);
    expect(view.targets[0]?.decision).toBe("partial");
    expect(view.targets[0]?.observations[0]?.dimension).toBe("discovered");
  });

  test("rejects totals that do not reconcile", () => {
    expect(() => decodeDetectionReadiness({ ...RESPONSE, target_count: 2 })).toThrow(/totals do not reconcile/);
  });

  test("rejects duplicate dimensions", () => {
    const target = RESPONSE.targets[0]!;
    expect(() => decodeDetectionReadiness({
      ...RESPONSE,
      targets: [{ ...target, observations: [target.observations[0], target.observations[0]] }],
    })).toThrow(/duplicate detection readiness dimension/);
  });

  test("turns a malformed successful response into an error state", async () => {
    const client = {
      panel: async () => ({ ...RESPONSE, target_count: 2 }),
    } as unknown as OperatorApiClient;

    await expect(loadDetectionReadinessState(client)).resolves.toEqual({
      status: "error",
      message: "invalid Operator API response: detection readiness totals do not reconcile",
    });
  });
});
