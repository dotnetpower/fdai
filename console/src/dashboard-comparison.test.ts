import { describe, expect, test } from "vitest";
import { decodeDashboardComparison } from "./dashboard-comparison";

function publication() {
  const arm = (name: string, value: number) => ({
    arm: name, sample_count: 30,
    window_start: "2026-08-01T00:00:00Z", window_end: "2026-08-30T00:00:00Z",
    metrics: [{
      metric_id: "auto_resolution_rate", absolute_value: value, sample_size: 30,
      lower_bound: 0.1, upper_bound: 0.9, confidence_level_basis_points: 9500,
    }],
    guards: [{
      guard_id: "policy_violation_escape_rate", sample_size: 30,
      observed_basis_points: 0, maximum_basis_points: 0, breached: false,
    }],
  });
  return {
    schema_version: "1.0.0",
    publication_id: `sha256:${"a".repeat(64)}`,
    cohort_id: "example-cohort",
    fdai_revision: "a".repeat(40),
    measurement_protocol_version: "1.0.0",
    artifact_origin: "governed_external",
    synthetic: false, execution_authority: false, promotion_authority: false,
    published_at: "2026-09-01T00:00:00Z",
    valid_until: "2026-09-02T00:00:00Z",
    baseline: arm("baseline", 0.4),
    treatment: arm("treatment", 0.8),
  };
}

describe("admitted comparison display contract", () => {
  test("keeps separate paired values, intervals and evidence windows", () => {
    const result = decodeDashboardComparison(publication())!;
    expect(result.baseline.metrics[0]?.absolute_value).toBe(0.4);
    expect(result.treatment.metrics[0]?.absolute_value).toBe(0.8);
    expect(result.baseline.sample_count).toBe(30);
    expect(result.valid_until).toBe("2026-09-02T00:00:00Z");
    expect(decodeDashboardComparison(undefined)).toBeNull();
  });
  test.each([
    { synthetic: true }, { execution_authority: true }, { promotion_authority: true },
    { artifact_origin: "repository" }, { schema_version: "2.0.0" },
    { valid_until: "2026-08-01T00:00:00Z" }, { published_at: "2026-09-01" },
  ])("rejects unsupported provenance and lifetime %j", (change) => {
    expect(() => decodeDashboardComparison({ ...publication(), ...change })).toThrow();
  });
  test("rejects undersized arms, missing guards and mismatched measures", () => {
    const data = publication();
    expect(() => decodeDashboardComparison({
      ...data, baseline: { ...data.baseline, sample_count: 29 },
    })).toThrow();
    expect(() => decodeDashboardComparison({
      ...data, treatment: { ...data.treatment, guards: [] },
    })).toThrow();
    expect(() => decodeDashboardComparison({
      ...data, treatment: { ...data.treatment, metrics: [
        { ...data.treatment.metrics[0], metric_id: "mttr_seconds" },
      ] },
    })).toThrow();
  });
  test("rejects a breached guard rather than presenting admitted evidence", () => {
    const data = publication();
    expect(() => decodeDashboardComparison({
      ...data, baseline: { ...data.baseline, guards: [
        { ...data.baseline.guards[0], breached: true, observed_basis_points: 1 },
      ] },
    })).toThrow();
  });
  test("rejects an auto-resolution interval above 100 percent", () => {
    const data = publication();
    expect(() => decodeDashboardComparison({
      ...data, baseline: { ...data.baseline, metrics: [
        { ...data.baseline.metrics[0], upper_bound: 1.1 },
      ] },
    })).toThrow();
  });
});
