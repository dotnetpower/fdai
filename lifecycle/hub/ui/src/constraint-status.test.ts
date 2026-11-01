import { describe, expect, test } from "vitest";
import {
  constraintVerdict,
  describeConstraintReason,
  isTimingReason,
  normalizeConstraintOutcome,
} from "./constraint-status";

describe("isTimingReason", () => {
  test("a closed maintenance window and an active suppression are timing reasons", () => {
    expect(isTimingReason("maintenance_window_unavailable")).toBe(true);
    expect(isTimingReason("suppression_window_active")).toBe(true);
  });

  test("a release outside the version range or missing data residency is not a timing reason", () => {
    expect(isTimingReason("release_version_outside_range")).toBe(false);
    expect(isTimingReason("data_residency_missing")).toBe(false);
  });
});

describe("constraintVerdict", () => {
    test("a candidate with no blocks passed", () => {
      expect(constraintVerdict({ release_id: "1.6.0", blocks: [] })).toBe("passed");
    });

    test("only timing blocks mean waiting", () => {
      expect(constraintVerdict({
        release_id: "1.6.0",
        blocks: [
          { reason_code: "maintenance_window_unavailable", details: [] },
          { reason_code: "suppression_window_active", details: [] },
        ],
      })).toBe("waiting");
    });

    test("a hard block must not be hidden by a first timing block", () => {
      expect(constraintVerdict({
        release_id: "1.6.0",
        blocks: [
          { reason_code: "maintenance_window_unavailable", details: [] },
          { reason_code: "data_residency_missing", details: ["region unavailable"] },
        ],
      })).toBe("blocked");
    });

    test("unknown reason codes remain blocked", () => {
      expect(constraintVerdict({
        release_id: "1.6.0",
        blocks: [{ reason_code: "new_constraint", details: [] }],
      })).toBe("blocked");
    });

    test("describes shared constraint reason codes as human-readable sentences", () => {
      expect(describeConstraintReason("maintenance_window_unavailable")).toContain("maintenance window");
      expect(describeConstraintReason("data_residency_mismatch")).toContain("data-residency");
      expect(describeConstraintReason("custom_future_code")).toContain("custom future code");
    });

    test("normalizeConstraintOutcome maps unknown or unexpected values to blocking fail-closed", () => {
      expect(normalizeConstraintOutcome("passed")).toBe("passed");
      expect(normalizeConstraintOutcome("waiting")).toBe("waiting");
      expect(normalizeConstraintOutcome("blocking")).toBe("blocking");
      expect(normalizeConstraintOutcome("unexpected_outcome")).toBe("blocking");
      expect(normalizeConstraintOutcome("")).toBe("blocking");
      expect(normalizeConstraintOutcome(null)).toBe("blocking");
      expect(normalizeConstraintOutcome(undefined)).toBe("blocking");
    });
});
