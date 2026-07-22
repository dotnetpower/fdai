import {
  auditSampleParams,
  controlOutcomeGroup,
  dashboardEvidenceGaps,
  distributionRows,
  overviewAttentionCount,
  overviewCostActions,
  overviewHealth,
  overviewT0Share,
} from "./dashboard.model";
import { describe, expect, test } from "vitest";
import type { DashboardKpi } from "../types";

const KPI: DashboardKpi = {
  event_count: 10,
  shadow_share: 0.95,
  enforce_share: 0.05,
  hil_pending: 0,
  by_action_kind: {},
  by_outcome: {},
  by_tier: {},
  last_recorded_at: null,
  audit_sample: null,
};

const AUTONOMY = {
  synthetic: false,
  guards: [{ key: "escape", value: 0, baseline: 0, threshold: 0, ok: true }],
};

const COMPLETE_EVIDENCE = {
  confidence: 0.95,
  guards: AUTONOMY.guards,
  success: {
    auto_resolution_rate: { value: 0.8, baseline: 0.4, direction: "higher" as const },
    human_touchpoints_per_100: { value: 2, baseline: 4, direction: "lower" as const },
    mttr_seconds: { value: 60, baseline: 120, direction: "lower" as const },
    change_lead_time_seconds: { value: 80, baseline: 160, direction: "lower" as const },
    cost_per_resolved_event_usd: { value: 1, baseline: 2, direction: "lower" as const },
  },
  leading: {
    mixed_model_disagreement_rate: { value: 0.01, baseline: 0.02, direction: "lower" as const },
    verifier_failure_rate: { value: 0.01, baseline: 0.02, direction: "lower" as const },
    shadow_divergence_rate: { value: 0.01, baseline: 0.02, direction: "lower" as const },
  },
};

describe("overview health", () => {
  test("distinguishes unavailable cost evidence from a measured zero", () => {
    expect(overviewCostActions(null)).toBe("n/a");
    expect(overviewCostActions({ total_actions: 0 })).toBe(0);
  });

  test("distinguishes missing tier evidence from a measured zero share", () => {
    expect(overviewT0Share({})).toBe("unavailable");
    expect(overviewT0Share({ t1: 3 })).toBe("unavailable");
    expect(overviewT0Share({ t0: 0, t1: 3 })).toBe("0%");
  });

    test("adds immutable audit sample bounds to evidence links", () => {
      expect(auditSampleParams(KPI)).toEqual({});
      expect(auditSampleParams({
        ...KPI,
        audit_sample: { from_seq: 2, through_seq: 501, row_count: 500, limit: 500 },
      })).toEqual({ from_seq: 2, through_seq: 501 });
    });

  test("is healthy only when all required guard evidence passes", () => {
    expect(overviewHealth(KPI, 0, AUTONOMY)).toBe("healthy");
  });

  test("reports attention for any known failed guard", () => {
    expect(overviewHealth(KPI, 0, { ...AUTONOMY, guards: [{ ...AUTONOMY.guards[0]!, ok: false }] })).toBe("attention");
    expect(overviewHealth({ ...KPI, hil_pending: 1 }, 0, AUTONOMY)).toBe("attention");
  });

  test("reports unknown when required guard evidence is absent", () => {
    expect(overviewHealth(KPI, null, AUTONOMY)).toBe("unknown");
    expect(overviewHealth(KPI, 0, null)).toBe("unknown");
    expect(overviewHealth(KPI, 0, { ...AUTONOMY, guards: [] })).toBe("unknown");
  });

  test("does not let synthetic guards decide operational health or attention", () => {
    const synthetic = {
      synthetic: true,
      guards: [{ ...AUTONOMY.guards[0]!, ok: false }],
    };
    expect(overviewHealth(KPI, 0, synthetic)).toBe("unknown");
    expect(overviewAttentionCount(KPI, 0, synthetic)).toBe(0);
    expect(overviewHealth({ ...KPI, hil_pending: 1 }, 0, synthetic)).toBe("attention");
  });

  test("counts only actionable HIL, escape, and failed-guard signals", () => {
    expect(
      overviewAttentionCount(
        { ...KPI, hil_pending: 2 },
        1,
        {
          synthetic: false,
          guards: [
            AUTONOMY.guards[0]!,
            { ...AUTONOMY.guards[0]!, key: "rollback", ok: false },
          ],
        },
      ),
    ).toBe(4);
    expect(overviewAttentionCount(KPI, null, null)).toBe(0);
  });
});

describe("overview distributions", () => {
  test("sorts observed rows and preserves measured shares", () => {
    expect(distributionRows({ t0: 7, t1: 2, t2: 1 })).toEqual([
      { key: "t0", count: 7, share: 0.7 },
      { key: "t1", count: 2, share: 0.2 },
      { key: "t2", count: 1, share: 0.1 },
    ]);
    expect(distributionRows({})).toEqual([]);
  });

  test("groups machine outcomes into operator-facing control paths", () => {
    expect([
      "auto",
      "executed",
      "awaiting_approval",
      "abstained_routing",
      "denied",
      "failed",
    ].map(controlOutcomeGroup)).toEqual([
      "auto", "auto", "approval", "held", "deny", "other",
    ]);
  });
});

describe("overview evidence gaps", () => {
  test("reports category gaps without treating unavailable values as zero", () => {
    expect(dashboardEvidenceGaps(null)).toEqual([
      "baseline", "confidence", "guards", "leading", "outcomes",
    ]);
    expect(dashboardEvidenceGaps(COMPLETE_EVIDENCE)).toEqual([]);
    expect(dashboardEvidenceGaps({
      ...COMPLETE_EVIDENCE,
      confidence: null,
      guards: [],
      success: {
        ...COMPLETE_EVIDENCE.success,
        mttr_seconds: { ...COMPLETE_EVIDENCE.success.mttr_seconds, value: null, baseline: null },
      },
      leading: {
        ...COMPLETE_EVIDENCE.leading,
        verifier_failure_rate: { ...COMPLETE_EVIDENCE.leading.verifier_failure_rate, value: null },
      },
    })).toEqual(["baseline", "confidence", "guards", "leading", "outcomes"]);
  });
});
