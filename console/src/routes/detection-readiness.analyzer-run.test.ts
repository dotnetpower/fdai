import { describe, expect, test } from "vitest";

import {
  decodeAnalyzerCoverage,
  decodeAnalyzerRun,
} from "./detection-readiness.analyzer-run";
import { sampleDetectionReadiness } from "./operations.sample-readiness";

const RUN = {
  source: "postgresql:state_kv:analyzer-tick-receipt",
  recorded_at: "2026-09-14T07:24:06Z",
  targets: 22,
  findings: 1,
  published: 1,
  duplicates_suppressed: 0,
  uncertain: 0,
  configured_targets: 0,
  discovered_targets: 22,
  candidate_count: 35,
  inventory_consulted: true,
  source_complete: true,
  truncated: false,
  skipped_reasons: ["unverified_state_fact"],
  skipped_reason_counts: { unverified_state_fact: 13 },
  unsupported_target_count: 0,
  analyzer_error_count: 0,
  publish_error_count: 0,
  receipt_error_count: 0,
  scheduling: "local_loop",
  metric_access: "available",
  event_publication: "verified",
  execution_authority: false,
};

describe("analyzer run decoder", () => {
  test("preserves evaluated and held target evidence", () => {
    expect(decodeAnalyzerRun(RUN)).toMatchObject({
      targets: 22,
      candidate_count: 35,
      held_count: 13,
      skipped_reasons: ["unverified_state_fact"],
      source_complete: true,
    });
  });

  test("keeps an absent receipt distinct from a zero-valued run", () => {
    expect(decodeAnalyzerRun(null)).toBeNull();
    expect(decodeAnalyzerRun(undefined)).toBeNull();
  });

  test("rejects widened authority and inconsistent target totals", () => {
    expect(() => decodeAnalyzerRun({ ...RUN, execution_authority: true }))
      .toThrow(/widened its read-only boundary/);
    expect(() => decodeAnalyzerRun({ ...RUN, targets: 21 }))
      .toThrow(/target totals do not reconcile/);
  });
});

describe("analyzer coverage decoder", () => {
  test("preserves five resource types without claiming health", () => {
    const coverage = decodeAnalyzerCoverage(
      sampleDetectionReadiness().analyzer_coverage,
    );

    expect(coverage).toMatchObject({
      status: "available",
      candidate_count: 7,
      selected_count: 5,
      evaluated_count: 4,
      held_count: 2,
      finding_count: 1,
      error_count: 1,
      cause_claim_supported: false,
      execution_authority: false,
    });
    expect(coverage.status === "available" ? coverage.resource_types : [])
      .toHaveLength(5);
  });

  test("keeps an absent section unavailable and rejects broken algebra", () => {
    expect(decodeAnalyzerCoverage(undefined)).toMatchObject({
      status: "unavailable",
      unavailable_reason: "section_absent",
    });
    const malformed = structuredClone(sampleDetectionReadiness().analyzer_coverage);
    malformed.candidate_count = 8;
    expect(() => decodeAnalyzerCoverage(malformed)).toThrow(
      /global totals do not reconcile/,
    );
    const unsupportedNoFinding = structuredClone(
      sampleDetectionReadiness().analyzer_coverage,
    );
    unsupportedNoFinding.resources[0]!.unsupported_count = 1;
    expect(() => decodeAnalyzerCoverage(unsupportedNoFinding)).toThrow(
      /resource state is inconsistent/,
    );
  });

  test("keeps a future schema section-local unavailable", () => {
    const future = {
      ...structuredClone(sampleDetectionReadiness().analyzer_coverage),
      schema_version: "2.0.0",
    };

    expect(decodeAnalyzerCoverage(future)).toMatchObject({
      status: "unavailable",
      unavailable_reason: "schema_unsupported",
    });
  });
});
