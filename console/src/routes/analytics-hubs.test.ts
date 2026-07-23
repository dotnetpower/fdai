import { describe, expect, it } from "vitest";
import type { AutonomyPayload } from "../types";
import {
  formatMeasuredSavings,
  indicatorMeterPercent,
  measuredTierValue,
  routingParamsForTier,
  searchParamsRecord,
  verticalResolutionRate,
} from "./analytics-hubs";
import {
  assurancePostureHref,
  assuranceSectionHref,
  guardDisplayState,
  measuredFailedGuardCount,
  meterPercent,
} from "./control-assurance";
import { buildOperatingOutcomeViewSnapshot } from "./analytics-hubs.view";
import {
  OUTCOME_KEYS,
  autoResolutionCounts,
  formatOutcomeMetric,
  outcomeMetric,
  outcomeViewContract,
} from "./operating-outcomes";
import {
  verticalDisplayState,
  verticalPayloadKey,
  verticalPrimaryMetric,
  verticalRouteSlug,
} from "./vertical-outcomes";

const AUTONOMY: AutonomyPayload = {
  synthetic: false,
  window_days: 30,
  sample_size: 34,
  confidence: null,
  source: {
    name: "postgres-audit",
    kind: "audit",
    as_of: "2026-07-23T01:25:21Z",
  },
  rules: { active: 0, candidates_30d: 0, promoted_30d: 0 },
  success: {
    auto_resolution_rate: { value: 14 / 34, baseline: null, direction: "higher" },
    human_touchpoints_per_100: { value: null, baseline: null, direction: "lower" },
    mttr_seconds: { value: null, baseline: null, direction: "lower" },
    change_lead_time_seconds: { value: null, baseline: null, direction: "lower" },
    cost_per_resolved_event_usd: { value: null, baseline: null, direction: "lower" },
  },
  leading: {
    mixed_model_disagreement_rate: { value: null, baseline: null, direction: "lower" },
    verifier_failure_rate: { value: null, baseline: null, direction: "lower" },
    shadow_divergence_rate: { value: null, baseline: null, direction: "lower" },
  },
  guards: [],
  verticals: [
    { key: "resilience", events: 0, auto_resolved: 0, open_risks: 0, monthly_savings: 0 },
    { key: "change-safety", events: 34, auto_resolved: 14, open_risks: 0, monthly_savings: 0 },
    { key: "cost-governance", events: 0, auto_resolved: 0, open_risks: 0, monthly_savings: 0 },
  ],
  tier: { mix: {}, bands: {} },
  trend: {},
};

describe("trust-routing measurements", () => {
  it("gives every operating outcome an independent analysis contract", () => {
    const contracts = OUTCOME_KEYS.map((key) => outcomeViewContract(key));
    expect(new Set(contracts.map((contract) => contract.titleKey)).size).toBe(5);
    expect(new Set(contracts.map((contract) => contract.analysisTitleKey)).size).toBe(5);
    expect(contracts.filter((contract) => contract.measuredBreakdown)).toHaveLength(1);
  });

  it("selects and formats each outcome without inventing missing evidence", () => {
    expect(outcomeMetric(AUTONOMY, "auto-resolution")).toBe(AUTONOMY.success.auto_resolution_rate);
    expect(outcomeMetric(AUTONOMY, "cost-per-resolved-event")).toBe(AUTONOMY.success.cost_per_resolved_event_usd);
    expect(formatOutcomeMetric(null, "mttr")).toBe("Unavailable");
    expect(formatOutcomeMetric(540, "mttr")).toBe("9m");
    expect(formatOutcomeMetric(0.125, "cost-per-resolved-event")).toBe("$0.13");
  });

  it("derives only the supported observed and auto-resolved record counts", () => {
    expect(autoResolutionCounts(AUTONOMY.verticals)).toEqual({ observed: 34, resolved: 14 });
  });

  it("publishes visible outcome evidence for Command Deck grounding", () => {
    const snapshot = buildOperatingOutcomeViewSnapshot({
      autonomy: AUTONOMY,
      metric: AUTONOMY.success.cost_per_resolved_event_usd,
      metricKey: "cost-per-resolved-event",
      metricLabel: "Cost per resolved event",
      unavailableLabel: "Unavailable",
      routeLabel: "Operating outcomes",
    });

    expect(snapshot).toMatchObject({
      routeId: "operating-outcomes",
      routeLabel: "Operating outcomes",
      capturedAt: "2026-07-23T01:25:21Z",
      explanations: {
        provenance: { authority: "audit", refs: ["postgres-audit"] },
      },
    });
    expect(snapshot.headline).toContain("current Unavailable, baseline Unavailable");
    expect(snapshot.facts).toEqual(expect.arrayContaining([
      expect.objectContaining({ key: "current_value", value: null }),
      expect.objectContaining({ key: "window_days", value: 30 }),
      expect.objectContaining({ key: "sample_size", value: 34 }),
    ]));
    expect(snapshot.records).toBeUndefined();

    const autoResolution = buildOperatingOutcomeViewSnapshot({
      autonomy: AUTONOMY,
      metric: AUTONOMY.success.auto_resolution_rate,
      metricKey: "auto-resolution",
      metricLabel: "Auto-resolution",
      unavailableLabel: "Unavailable",
      routeLabel: "Operating outcomes",
    });
    expect(autoResolution.headline).toContain("current 41%");
    expect(autoResolution.facts).toEqual(expect.arrayContaining([
      expect.objectContaining({ key: "current_rate", value: 0.41 }),
    ]));
    expect(autoResolution.records?.verticals).toContainEqual(expect.objectContaining({
      key: "change-safety",
      events: 34,
      auto_resolved: 14,
    }));
  });

  it("preserves observed zero and negative monthly savings", () => {
    expect(formatMeasuredSavings(0)).toContain("0");
    expect(formatMeasuredSavings(-25)).toBe("-$25");
  });

  it("distinguishes an observed zero from a missing tier", () => {
    expect(measuredTierValue({ t0: 0 }, "t0")).toBe(0);
    expect(measuredTierValue({ t0: 0 }, "t1")).toBeNull();
  });

  it("scales leading indicators against their measured baseline", () => {
    expect(indicatorMeterPercent(0.04, 0.1)).toBe(40);
    expect(indicatorMeterPercent(0.12, 0.1)).toBe(100);
    expect(indicatorMeterPercent(null, 0.1)).toBeNull();
    expect(indicatorMeterPercent(0, 0)).toBe(0);
  });

  it("does not infer a zero resolution rate from an empty vertical", () => {
    expect(verticalResolutionRate({
      key: "resilience",
      events: 0,
      auto_resolved: 0,
      open_risks: 0,
      monthly_savings: 0,
    })).toBeNull();
    expect(verticalResolutionRate({
      key: "resilience",
      events: 4,
      auto_resolved: 3,
      open_risks: 0,
      monthly_savings: 0,
    })).toBe(0.75);
  });

  it("maps vertical routes and evidence states without inventing health", () => {
    expect(verticalPayloadKey("change-safety")).toBe("change_safety");
    expect(verticalRouteSlug("cost")).toBe("cost-governance");
    expect(verticalDisplayState(AUTONOMY.verticals[0]!, false)).toBe("unavailable");
    expect(verticalDisplayState(AUTONOMY.verticals[1]!, false)).toBe("measured");
    expect(verticalDisplayState({ ...AUTONOMY.verticals[1]!, open_risks: 2 }, false)).toBe("review");
    expect(verticalDisplayState(AUTONOMY.verticals[1]!, true)).toBe("simulated");
  });

  it("gives each vertical a distinct primary outcome contract", () => {
    const metrics = [
      verticalPrimaryMetric("resilience"),
      verticalPrimaryMetric("change-safety"),
      verticalPrimaryMetric("cost-governance"),
    ];
    expect(metrics).toEqual(["auto-resolution", "change-failure-rate", "monthly-savings"]);
    expect(new Set(metrics)).toHaveLength(3);
  });

  it("never turns synthetic guard values into operational verdicts", () => {
    expect(guardDisplayState(true, true)).toBe("simulated");
    expect(guardDisplayState(true, false)).toBe("simulated");
    expect(guardDisplayState(false, true)).toBe("passing");
    expect(guardDisplayState(false, false)).toBe("blocked");
  });

  it("keeps synthetic guard failures out of measured attention", () => {
    expect(measuredFailedGuardCount({ ...AUTONOMY, synthetic: true })).toBeNull();
    expect(measuredFailedGuardCount({
      ...AUTONOMY,
      guards: [{ key: "rollback", value: 0.9, baseline: 1, threshold: 1, ok: false }],
    })).toBe(1);
    expect(meterPercent(-0.1)).toBe(0);
    expect(meterPercent(1.2)).toBe(100);
  });

  it("navigates assurance summaries to visible evidence sections", () => {
    expect(assuranceSectionHref("required-attention", { window: "30d" })).toBe(
      "/control-assurance?window=30d#required-attention",
    );
    expect(assuranceSectionHref("promotion-guards")).toBe(
      "/control-assurance#promotion-guards",
    );
  });

  it("routes operating posture to the highest-priority attention owner", () => {
    const clear = {
      policyEscapes: 0,
      failedGuardKey: null,
      pendingApprovals: 0,
      blockedCapabilities: 0,
      shadowShare: 1,
      window: "30d",
    };
    expect(assurancePostureHref({ ...clear, pendingApprovals: 8 })).toBe("/approvals");
    expect(assurancePostureHref({ ...clear, failedGuardKey: "rollback" })).toBe(
      "/control-assurance?guard=rollback#promotion-guards",
    );
    expect(assurancePostureHref({ ...clear, policyEscapes: 1, pendingApprovals: 8 })).toBe(
      "/promotion-gates?status=blocked",
    );
    expect(assurancePostureHref({ ...clear, shadowShare: 0.82 })).toBe(
      "/audit?window=30d&mode=shadow",
    );
  });

  it("preserves active query state across analytical tabs", () => {
    const search = new URLSearchParams("window=30d&guard=rollback");
    expect(searchParamsRecord(search)).toEqual({ window: "30d", guard: "rollback" });
  });

  it("drops a T2-only indicator when navigating to another tier", () => {
    const search = new URLSearchParams("window=30d&indicator=verifier");
    expect(routingParamsForTier("t2", search)).toEqual({
      window: "30d",
      indicator: "verifier",
    });
    expect(routingParamsForTier("t0", search)).toEqual({ window: "30d" });
  });
});
