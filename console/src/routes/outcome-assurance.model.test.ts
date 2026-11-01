import { describe, expect, it } from "vitest";
import {
  decodeOutcomeAssuranceOperatorProjection,
  formatOutcomeAssuranceViewModel,
} from "./outcome-assurance.model";

const COMPLETE_PROJECTION = {
  type: "outcome-assurance.projection",
  schema_version: "1.0.0",
  state: "complete",
  reason: null,
  scope: {
    scope_ref: "scope.payments",
    service_refs: ["svc.payments-api"],
    workload_refs: ["wl.payments-worker"],
    vertical: "change_safety",
  },
  window: {
    start: "2026-10-02T00:00:00Z",
    end: "2026-11-01T00:00:00Z",
    label: "30d",
    scenario_set_version: "scenarios-v1",
  },
  sources: [{
    name: "outcome-assurance-measurement",
    state: "complete",
    reason: null,
    observed_at: "2026-11-01T00:00:00Z",
    expires_at: "2026-11-01T01:00:00Z",
    evidence_refs: ["measurement:payments-window"],
  }],
  readiness: [{
    facet: "measurement",
    state: "ready",
    reason: null,
    observed_at: "2026-11-01T00:00:00Z",
    expires_at: "2026-11-01T01:00:00Z",
    evidence_refs: ["readiness:measurement-ready"],
  }],
  alignment: {
    state: "partial",
    finalized_events: 20,
    attributed_events: 19,
    unattributed_events: 1,
    coverage: 0.95,
    objective_refs: ["objective.change-failure-rate@1.0.0"],
    workflow_refs: ["workflow.canary-rollout@1.0.0"],
    action_type_ids: ["ops.rollback-kubernetes-rollout"],
    evidence_refs: ["audit:decision-case-101"],
    reason: null,
  },
  outcomes: [{
    objective_ref: "objective.change-failure-rate@1.0.0",
    metric: "change_failure_rate",
    state: "measured",
    reason: null,
    current_value: 0.02,
    baseline_value: 0.03,
    target_value: 0.025,
    unit: "ratio",
    sample_size: 60,
    confidence_interval: { low: 0.01, high: 0.03 },
    source_time: "2026-11-01T00:00:00Z",
    evidence_refs: ["measurement:cfr-obs-1"],
  }],
  guards: {
    state: "healthy",
    reason: null,
    guard_evaluations: [{
      guard_id: "rollback_rate_ceiling",
      threshold: 0.05,
      observed_value: 0.02,
      passed: true,
      evidence_ref: "guard:rollback-rate",
    }],
    policy_escape_count: 0,
    evidence_refs: ["promotion:change-safety-gate"],
  },
  provenance: {
    as_of: "2026-11-01T00:00:00Z",
    generated_at: "2026-11-01T00:00:00Z",
    source_names: ["outcome-assurance-measurement"],
    synthetic: false,
  },
  principal_scoped: true,
  execution_authority: false,
  approval_authority: false,
  promotion_authority: false,
} as const;

const COMPLETE_OPERATOR_PAYLOAD = {
  type: "outcome-assurance.operator-projection",
  schema_version: "1.0.0",
  read_only: true,
  authority: "none",
  principal_id: "operator-reader-1",
  state: "complete",
  reason: null,
  summary_cards: [
    {
      card_id: "operational_readiness",
      state: "ready",
      available: true,
      headline_metric: 1.0,
      unit: "ratio",
      reason: null,
      evidence_refs: ["readiness:measurement-ready"],
    },
    {
      card_id: "objective_alignment",
      state: "partial",
      available: true,
      headline_metric: 0.95,
      unit: "ratio",
      reason: null,
      evidence_refs: ["audit:decision-case-101"],
    },
    {
      card_id: "control_assurance",
      state: "healthy",
      available: true,
      headline_metric: 1.0,
      unit: "ratio",
      reason: null,
      evidence_refs: ["guard:rollback-rate", "promotion:change-safety-gate"],
    },
  ],
  objective_drilldowns: [{
    objective_ref: "objective.change-failure-rate@1.0.0",
    state: "partial",
    workflow_refs: ["workflow.canary-rollout@1.0.0"],
    action_type_ids: ["ops.rollback-kubernetes-rollout"],
    finalized_events: 20,
    attributed_events: 19,
    unattributed_events: 1,
    coverage: 0.95,
    metrics: COMPLETE_PROJECTION.outcomes,
    evidence_refs: ["audit:decision-case-101", "measurement:cfr-obs-1"],
    reason: null,
  }],
  guard_status: COMPLETE_PROJECTION.guards,
  projection: COMPLETE_PROJECTION,
} as const;

describe("outcome-assurance.model", () => {
  it("decodes and formats complete bilingual (en/ko) summary and objective drill-downs", () => {
    const decoded = decodeOutcomeAssuranceOperatorProjection(COMPLETE_OPERATOR_PAYLOAD);
    expect(decoded.read_only).toBe(true);
    expect(decoded.authority).toBe("none");

    const enView = formatOutcomeAssuranceViewModel(decoded, "en");
    expect(enView.unavailableBanner).toBeNull();
    expect(enView.summaryCards[0]?.title).toBe("Operational readiness");
    expect(enView.summaryCards[1]?.headlineDisplay).toBe("95%");
    expect(enView.objectiveDrilldowns[0]?.attributionCountDisplay).toBe(
      "19/20 attributed (1 unattributed)",
    );
    expect(enView.objectiveDrilldowns[0]?.metrics[0]?.currentDisplay).toBe("2%");

    const koView = formatOutcomeAssuranceViewModel(decoded, "ko");
    expect(koView.unavailableBanner).toBeNull();
    expect(koView.summaryCards[0]?.title).toBe("운영 준비도");
    expect(koView.summaryCards[1]?.stateLabel).toBe("부분 귀속");
    expect(koView.objectiveDrilldowns[0]?.attributionCountDisplay).toBe(
      "19/20 귀속됨 (미귀속 1)",
    );
  });

  it("rejects authority-bearing or non-read-only payloads", () => {
    expect(() =>
      decodeOutcomeAssuranceOperatorProjection({
        ...COMPLETE_OPERATOR_PAYLOAD,
        read_only: false,
      }),
    ).toThrow("read_only MUST be true");

    expect(() =>
      decodeOutcomeAssuranceOperatorProjection({
        ...COMPLETE_OPERATOR_PAYLOAD,
        authority: "execute",
      }),
    ).toThrow("authority MUST be none");
  });

  it("rejects unavailable summary cards carrying synthetic headline values", () => {
    expect(() =>
      decodeOutcomeAssuranceOperatorProjection({
        ...COMPLETE_OPERATOR_PAYLOAD,
        state: "unavailable",
        reason: "source_stale",
        summary_cards: [{
          card_id: "operational_readiness",
          state: "unavailable",
          available: false,
          headline_metric: 0,
          unit: "ratio",
          reason: "source_stale",
          evidence_refs: [],
        }],
      }),
    ).toThrow("cannot carry synthetic headline_metric when unavailable");
  });

  it("renders explicit unavailable and stale states in en and ko without synthetic values", () => {
    const nullEn = formatOutcomeAssuranceViewModel(null, "en");
    expect(nullEn.state).toBe("unavailable");
    expect(nullEn.unavailableBanner).toContain("not connected");
    expect(nullEn.summaryCards.every((c) => c.headlineDisplay === "Unavailable")).toBe(true);

    const nullKo = formatOutcomeAssuranceViewModel(null, "ko");
    expect(nullKo.unavailableBanner).toContain("연결되지 않았습니다");
    expect(nullKo.summaryCards.every((c) => c.headlineDisplay === "사용 불가")).toBe(true);

    const stalePayload = decodeOutcomeAssuranceOperatorProjection({
      ...COMPLETE_OPERATOR_PAYLOAD,
      state: "stale",
      reason: "source_stale",
      summary_cards: COMPLETE_OPERATOR_PAYLOAD.summary_cards.map((card) => ({
        ...card,
        state: "unavailable",
        available: false,
        headline_metric: null,
        unit: null,
        reason: "source_stale",
      })),
      objective_drilldowns: [],
      guard_status: {
        state: "unavailable",
        reason: "source_stale",
        policy_escape_count: 0,
        guard_evaluations: [],
        evidence_refs: [],
      },
    });
    const staleKo = formatOutcomeAssuranceViewModel(stalePayload, "ko");
    expect(staleKo.unavailableBanner).toContain("만료되어 사용 불가 처리되었습니다");
    expect(staleKo.guardSummary.policyEscapeDisplay).toBe("사용 불가");
  });
});
