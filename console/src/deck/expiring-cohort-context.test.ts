import { expect, test } from "vitest";
import { withdrawExpiredCohortContext } from "./expiring-cohort-context";

test("withdraws expired pinned evidence without mutating unrelated or original records", () => {
  const source = {
    routeId: "dashboard", routeLabel: "Dashboard", headline: "Measured view",
    capturedAt: "2026-09-01T00:00:00Z", facts: [],
    records: {
      cohort_comparison_context: [{ valid_until: "2026-09-01T00:01:00Z" }],
      cohort_comparison_metrics: [{ baseline: 1, treatment: 2 }],
      unrelated: [{ value: 3 }],
    },
  };
  expect(withdrawExpiredCohortContext(source, Date.parse("2026-09-01T00:00:30Z"))).toBe(source);
  const expired = withdrawExpiredCohortContext(source, Date.parse("2026-09-01T00:01:00Z"));
  expect(expired.records?.cohort_comparison_metrics).toEqual([]);
  expect(expired.records?.cohort_comparison_context).toEqual([]);
  expect(expired.records?.unrelated).toEqual([{ value: 3 }]);
  expect(source.records.cohort_comparison_metrics).toHaveLength(1);
  const malformed = { ...source, records: { ...source.records, cohort_comparison_context: [] } };
  expect(withdrawExpiredCohortContext(malformed, 0).records?.cohort_comparison_metrics).toEqual([]);
});
