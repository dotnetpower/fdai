import type { AutonomyPayload, DashboardKpi } from "../types";
import type { DashboardOverviewData } from "./dashboard.loading";
import { sampleCostGovernance } from "./cost-governance.sample";

const SAMPLE_AT = "2026-08-31T09:00:00Z";

const SAMPLE_KPI: DashboardKpi = {
  event_count: 1280,
  shadow_share: 0.96,
  enforce_share: 0.04,
  hil_pending: 3,
  by_action_kind: {
    investigate: 520,
    recommend: 410,
    remediate: 280,
    verify: 70,
  },
  by_outcome: {
    auto_resolved: 922,
    approval_required: 146,
    held_for_review: 124,
    denied: 88,
  },
  by_tier: {
    t0: 896,
    t1: 320,
    t2: 64,
  },
  last_recorded_at: SAMPLE_AT,
  audit_sample: {
    from_seq: 1001,
    through_seq: 2280,
    row_count: 1280,
    limit: 1280,
  },
};

const SAMPLE_AUTONOMY: AutonomyPayload = {
  synthetic: true,
  window_days: 30,
  sample_size: 1280,
  confidence: 0.94,
  source: {
    name: "sample-preview",
    kind: "synthetic",
    as_of: SAMPLE_AT,
  },
  rules: {
    active: 42,
    candidates_30d: 7,
    promoted_30d: 3,
  },
  success: {
    auto_resolution_rate: { value: 922 / 1280, baseline: 0.48, direction: "higher" },
    human_touchpoints_per_100: { value: 11, baseline: 24, direction: "lower" },
    mttr_seconds: { value: 540, baseline: 1320, direction: "lower" },
    change_lead_time_seconds: { value: 960, baseline: 2100, direction: "lower" },
    cost_per_resolved_event_usd: { value: 0.31, baseline: 0.72, direction: "lower" },
  },
  metric_samples: {
    auto_resolution_rate: 1280,
    human_touchpoints_per_100: 1280,
    mttr_seconds: 116,
    change_lead_time_seconds: 94,
    cost_per_resolved_event_usd: 922,
  },
  measurement_gaps: [],
  leading: {
    mixed_model_disagreement_rate: { value: 0.018, baseline: 0.041, direction: "lower" },
    verifier_failure_rate: { value: 0.009, baseline: 0.025, direction: "lower" },
    shadow_divergence_rate: { value: 0.014, baseline: 0.036, direction: "lower" },
  },
  guards: [
    { key: "rollback_success", value: 0.995, baseline: 0.97, threshold: 0.98, ok: true },
    { key: "policy_escape_rate", value: 0, baseline: 0.004, threshold: 0, ok: true },
    { key: "effect_verification", value: 0.992, baseline: 0.95, threshold: 0.98, ok: true },
  ],
  finalization: {
    finalized_events: 922,
    pending_events: 88,
    adverse_events: 0,
  },
  attribution: {
    attributed_events: 1244,
    unattributed_events: 36,
    coverage: 1244 / 1280,
  },
  verticals: [
    { key: "resilience", events: 480, auto_resolved: 358, open_risks: 2, monthly_savings: 18400 },
    { key: "change_safety", events: 510, auto_resolved: 372, open_risks: 1, monthly_savings: 12600 },
    { key: "cost", events: 254, auto_resolved: 188, open_risks: 0, monthly_savings: 37200 },
    { key: "unattributed", events: 36, auto_resolved: 4, open_risks: 0, monthly_savings: 0 },
  ],
  tier: {
    mix: { t0: 0.7, t1: 0.25, t2: 0.05 },
    bands: { t0: [0.7, 0.8], t1: [0.15, 0.2], t2: [0.05, 0.1] },
  },
  trend: {
    auto_resolution_rate: [0.54, 0.57, 0.59, 0.61, 0.64, 0.66, 0.69, 922 / 1280],
    human_touchpoints: [22, 20, 18, 17, 15, 14, 12, 11],
    mttr: [1260, 1170, 1080, 960, 840, 720, 630, 540],
    change_lead_time: [2040, 1920, 1740, 1560, 1380, 1200, 1080, 960],
    cost_per_resolved_event: [0.68, 0.62, 0.56, 0.51, 0.46, 0.4, 0.35, 0.31],
  },
};

export const DASHBOARD_SAMPLE_DATA: DashboardOverviewData = {
  kpi: SAMPLE_KPI,
  cost: sampleCostGovernance("overview"),
  gates: {
    rows: [
      { policy_escapes: 0, ready: true },
      { policy_escapes: 0, ready: true },
      { policy_escapes: 0, ready: true },
      { policy_escapes: 0, ready: false },
    ],
    ready_count: 3,
    blocked_count: 1,
  },
  autonomy: SAMPLE_AUTONOMY,
};
