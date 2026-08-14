import { describe, expect, test } from "vitest";
import {
  decodeAuditPage,
  decodeAutonomyPayload,
  decodeDashboardKpi,
  decodeHilQueuePage,
  decodeIncidentPage,
  decodeRcaView,
  isOptionalOperatorApiUnavailable,
  OperatorApiError,
} from "./api";

describe("Operator API response decoders", () => {
  const metric = { value: 0.1, baseline: 0.2, direction: "lower" } as const;
  const autonomy = {
    synthetic: false,
    window_days: 30,
    sample_size: 1,
    confidence: 0.95,
    source: { name: "measurement-pipeline", kind: "measurement", as_of: null },
    rules: { active: 10, candidates_30d: 2, promoted_30d: 1 },
    success: {
      auto_resolution_rate: { ...metric, direction: "higher" },
      human_touchpoints_per_100: metric,
      mttr_seconds: metric,
      change_lead_time_seconds: metric,
      cost_per_resolved_event_usd: metric,
    },
    leading: {
      mixed_model_disagreement_rate: metric,
      verifier_failure_rate: metric,
      shadow_divergence_rate: metric,
    },
    guards: [{ key: "rollback", value: 0.01, baseline: 0.02, threshold: 0.02, ok: true }],
    finalization: { finalized_events: 1, pending_events: 0, adverse_events: 0 },
    attribution: { attributed_events: 1, unattributed_events: 0, coverage: 1 },
    verticals: [{ key: "resilience", events: 1, auto_resolved: 1, open_risks: 0, monthly_savings: 0 }],
    tier: { mix: { t0: 1 }, bands: { t0: [0.7, 0.8] } },
    trend: { auto_resolution_rate: [0.1, 0.2] },
  };

  test("decodes complete autonomy evidence and rejects partial KPI contracts", () => {
    expect(decodeAutonomyPayload(autonomy).source.name).toBe("measurement-pipeline");
    expect(() => decodeAutonomyPayload({
      ...autonomy,
      success: { ...autonomy.success, cost_per_resolved_event_usd: undefined },
    })).toThrow(OperatorApiError);
    expect(() => decodeAutonomyPayload({
      ...autonomy,
      attribution: { attributed_events: 0, unattributed_events: 1, coverage: 0 },
    })).toThrow(OperatorApiError);
    expect(() => decodeAutonomyPayload({
      ...autonomy,
      finalization: { finalized_events: 0, pending_events: 0, adverse_events: 1 },
    })).toThrow(OperatorApiError);
    expect(() => decodeAutonomyPayload({ ...autonomy, sample_size: 2 })).toThrow(OperatorApiError);
    expect(() => decodeAutonomyPayload({
      ...autonomy,
      finalization: { finalized_events: 1, pending_events: 0, adverse_events: 1 },
    })).toThrow(OperatorApiError);
  });

  test("keeps unobserved audit-derived measurements unavailable", () => {
    const decoded = decodeAutonomyPayload({
      ...autonomy,
      source: { name: "postgres-audit", kind: "audit", as_of: null },
      success: {
        ...autonomy.success,
        mttr_seconds: { value: null, baseline: null, direction: "lower" },
      },
    });
    expect(decoded.success.mttr_seconds.value).toBeNull();
    expect(decoded.success.mttr_seconds.baseline).toBeNull();
  });

  test("reject malformed always-on payloads with a uniform contract error", () => {
    for (const decode of [decodeAuditPage, decodeDashboardKpi, decodeHilQueuePage, decodeIncidentPage]) {
      expect(() => decode({})).toThrow(OperatorApiError);
      try { decode({}); } catch (error) {
        expect((error as OperatorApiError).status).toBe(502);
      }
    }
  });

  test("decodes empty audit and HIL pages", () => {
    expect(decodeAuditPage({ items: [], next_cursor: null })).toEqual({ items: [], next_cursor: null });
    expect(decodeHilQueuePage({ items: [], total: 0 })).toEqual({
      items: [],
      total: 0,
      detail_level: "full",
    });
  });

  test("decodes legacy and enriched HIL items without inventing safety facts", () => {
    const legacy = {
      idempotency_key: "idem-1",
      event_id: "event-1",
      action_kind: "compute.restart",
      reason: "Approval required by the risk gate.",
      requested_at: "2026-07-15T10:00:00Z",
      correlation_id: "corr-1",
    };
    const legacyItem = decodeHilQueuePage({ items: [legacy], total: 1 }).items[0];
    expect(legacyItem?.stop_condition).toBe("");
    expect(legacyItem?.citing_rule_ids).toEqual([]);
    expect(legacyItem?.ttl_expires_at).toBeNull();

    const enrichedItem = decodeHilQueuePage({
      items: [{
        ...legacy,
        approval_id: "approval-1",
        action_id: "action-1",
        target_resource_ref: "resource-1",
        mode: "shadow",
        stop_condition: "health probe fails",
        rollback_kind: "pr_revert",
        rollback_reference: "pr-1",
        blast_radius_scope: "single_resource",
        blast_radius_count: 1,
        blast_radius_rate_per_minute: null,
        blast_radius_summary: "1 resource, 0 downstream",
        reasons: ["Verifier requires operator review."],
        citing_rule_ids: ["example.rule"],
        ttl_expires_at: "2026-07-15T10:30:00Z",
      }],
      total: 1,
    }).items[0];
    expect(enrichedItem?.rollback_kind).toBe("pr_revert");
    expect(enrichedItem?.blast_radius_count).toBe(1);
    expect(enrichedItem?.citing_rule_ids).toEqual(["example.rule"]);

    expect(decodeHilQueuePage({ items: [], total: 3, detail_level: "count_only" }))
      .toEqual({ items: [], total: 3, detail_level: "count_only" });
  });

  test("rejects contradictory or ambiguous HIL queue evidence", () => {
    const item = {
      idempotency_key: "idem-1",
      event_id: "event-1",
      action_kind: "compute.restart",
      reason: "Approval required.",
      requested_at: "2026-07-15T10:00:00Z",
      correlation_id: "corr-1",
    };
    expect(() => decodeHilQueuePage({ items: [item], total: 0 })).toThrow(/total MUST/);
    expect(() => decodeHilQueuePage({ items: [item], total: 1, detail_level: "count_only" }))
      .toThrow(/MUST NOT include/);
    expect(() => decodeHilQueuePage({ items: [item, item], total: 2 }))
      .toThrow(/unique idempotency/);
    expect(() => decodeHilQueuePage({ items: [{ ...item, mode: "auto" }], total: 1 }))
      .toThrow(/mode MUST/);
    expect(() => decodeHilQueuePage({ items: [{ ...item, requested_at: "yesterday" }], total: 1 }))
      .toThrow(/RFC 3339/);
    expect(() => decodeHilQueuePage({ items: [{ ...item, ttl_expires_at: "later" }], total: 1 }))
      .toThrow(/RFC 3339/);
  });

  test("decodes an incident page and rejects invalid status", () => {
    const item = {
      correlation_id: "corr-1",
      incident_id: null,
      ticket_id: null,
      title: "Rule example.rule",
      title_source: "rule_id",
      source: {
        platform: "Azure Monitor",
        incident_id: "alert-example",
        status: "triggered",
        fired_at: "2026-07-14T09:59:00Z",
        description: "Latency exceeded the objective.",
        url: "https://example.com/incidents/alert-example",
      },
      response_plan: {
        id: "latency-response",
        revision: "rev-2",
        enabled: true,
        historical_match_count: 3,
        reinvestigation_cooldown_seconds: 10800,
        deduplication_key: "latency:example",
      },
      severity: "high",
      status: "in_progress",
      status_source: "audit_projection",
      disposition: "awaiting_hil",
      verdict: "hil",
      vertical: "change_safety",
      opened_at: "2026-07-14T10:00:00Z",
      last_updated_at: "2026-07-14T10:01:00Z",
      latest_mode: "shadow",
      history_count: 2,
    };
    const metrics = {
        source: "operator-postgres-incident-projection",
        snapshot_seq: 7,
        denominator: 2,
        truncated: false,
        window_from: "2026-07-14T09:59:00Z",
        window_to: "2026-07-14T10:01:00Z",
        cohorts: { agent_mitigated: 0, agent_assisted: 1, human_mitigated: 0, pending: 1, integrity_excluded: 0 },
        drilldown: { agent_mitigated: [], agent_assisted: ["corr-2"], human_mitigated: [], pending: ["corr-1"], integrity_excluded: [] },
        drilldown_truncated: { agent_mitigated: false, agent_assisted: false, human_mitigated: false, pending: false, integrity_excluded: false },
        median_time_to_mitigate_seconds: 120.5,
        time_to_mitigate_sample_size: 1,
        terminal_rule: "resolved_and_independently_verified",
    };
    expect(decodeIncidentPage({ items: [item], next_cursor: null, metrics }).items[0]?.status)
      .toBe("in_progress");
    expect(decodeIncidentPage({ items: [item], next_cursor: null, metrics }).items[0]?.response_plan)
      .toMatchObject({ revision: "rev-2", historical_match_count: 3 });
    expect(decodeIncidentPage({ items: [item], next_cursor: null, metrics }).metrics)
      .toMatchObject({ median_time_to_mitigate_seconds: 120.5, time_to_mitigate_sample_size: 1 });
    expect(() => decodeIncidentPage({
      items: [{ ...item, status: "closed" }],
      next_cursor: null,
      metrics,
    })).toThrow(/status MUST/);
    expect(() => decodeIncidentPage({
      items: [{ ...item, title_source: "browser_guess" }],
      next_cursor: null,
      metrics,
    })).toThrow(/title_source MUST/);
    expect(() => decodeIncidentPage({
      items: [{ ...item, source: { ...item.source, url: "javascript:alert(1)" } }],
      next_cursor: null,
      metrics,
    })).toThrow(/absolute HTTPS URL/);
    expect(() => decodeIncidentPage({
      items: [item],
      next_cursor: null,
      metrics: { ...metrics, denominator: 3 },
    })).toThrow(/equal denominator/);
  });

  test("decodes an RCA view and rejects an invalid tier", () => {
    const grounded = {
      correlation_id: "corr-1",
      incident_id: null,
      hypotheses: [
        {
          seq: 2,
          tier: "t0",
          outcome: "grounded",
          grounded: true,
          cause: "public access open",
          confidence: 0.9,
          reason: "matched control",
          citations: [{ kind: "rule", ref: "storage.public-access" }],
          remediation_ref: "storage.disable-public-access",
          causal_chain: {
            root_event_id: "change-1",
            failure_event_id: "failure-1",
            confidence: 0.82,
            ambiguity: 1,
            hops: [{
              cause_event_id: "change-1",
              effect_event_id: "failure-1",
              cause_resource_ref: "service-a",
              effect_resource_ref: "service-b",
              lead_seconds: 75,
              relationship: "dependency",
              confidence: 0.82,
            }],
          },
          mode: "shadow",
          recorded_at: "2026-07-14T10:02:00Z",
        },
      ],
      response: {
        verdict: "auto",
        decision: "auto",
        action_kind: "risk_gate.shadow_authority",
        mode: "enforce",
        rollback_reference: "pr-7",
        recorded_at: "2026-07-14T10:03:00Z",
      },
    };
    const view = decodeRcaView(grounded);
    expect(view.hypotheses[0]?.grounded).toBe(true);
    expect(view.hypotheses[0]?.causal_chain?.hops[0]?.lead_seconds).toBe(75);
    expect(view.response?.verdict).toBe("auto");
    expect(() =>
      decodeRcaView({
        ...grounded,
        hypotheses: [{ ...grounded.hypotheses[0], tier: "t9" }],
      }),
    ).toThrow(/tier MUST/);
    expect(() => decodeRcaView({ ...grounded, correlation_id: " " }))
      .toThrow(/correlation_id MUST NOT be empty/);
    expect(() => decodeRcaView({
      ...grounded,
      hypotheses: [grounded.hypotheses[0], grounded.hypotheses[0]],
    })).toThrow(/unique ascending seq/);
    expect(() => decodeRcaView({
      ...grounded,
      hypotheses: [{ ...grounded.hypotheses[0], recorded_at: "2026-07-14" }],
    })).toThrow(/RFC 3339/);
    expect(() => decodeRcaView({
      ...grounded,
      response: { ...grounded.response, recorded_at: "later" },
    })).toThrow(/RFC 3339/);
  });

  test("decodes an RCA view with an abstained hypothesis and null response", () => {
    const view = decodeRcaView({
      correlation_id: "corr-abstain",
      incident_id: null,
      hypotheses: [
        {
          seq: 1,
          tier: "t2",
          outcome: "abstained",
          grounded: false,
          cause: null,
          confidence: null,
          reason: "insufficient grounding",
          citations: [],
          remediation_ref: null,
          causal_chain: null,
          mode: "shadow",
          recorded_at: "2026-07-14T10:00:00Z",
        },
      ],
      response: null,
    });
    expect(view.hypotheses[0]?.grounded).toBe(false);
    expect(view.hypotheses[0]?.confidence).toBeNull();
    expect(view.response).toBeNull();
  });

  test("rejects non-finite KPI counters", () => {
    expect(() => decodeDashboardKpi({
      event_count: 1,
      shadow_share: Number.NaN,
      enforce_share: 0,
      hil_pending: 0,
      by_action_kind: {},
      by_outcome: {},
      by_tier: {},
      last_recorded_at: null,
    })).toThrow(/finite number/);
  });

  test("rejects semantically invalid KPI counters and shares", () => {
    const valid = {
      event_count: 1,
      shadow_share: 1,
      enforce_share: 0,
      hil_pending: 0,
      by_action_kind: {},
      by_outcome: {},
      by_tier: {},
      last_recorded_at: null,
    };
    expect(() => decodeDashboardKpi({ ...valid, event_count: -1 })).toThrow(/non-negative integer/);
    expect(() => decodeDashboardKpi({ ...valid, hil_pending: 0.5 })).toThrow(/non-negative integer/);
    expect(() => decodeDashboardKpi({ ...valid, shadow_share: 2 })).toThrow(/between 0 and 1/);
  });
});

  test("decodes a reproducible KPI audit sample and accepts legacy omission", () => {
    const base = {
      event_count: 2,
      shadow_share: 1,
      enforce_share: 0,
      hil_pending: 0,
      by_action_kind: {},
      by_outcome: {},
      by_tier: {},
      last_recorded_at: null,
    };
    expect(decodeDashboardKpi(base).audit_sample).toBeNull();
    expect(decodeDashboardKpi({
      ...base,
      audit_sample: { from_seq: 4, through_seq: 7, row_count: 2, limit: 500 },
    }).audit_sample).toEqual({ from_seq: 4, through_seq: 7, row_count: 2, limit: 500 });
    expect(() => decodeDashboardKpi({
      ...base,
      audit_sample: { from_seq: 7, through_seq: 4, row_count: 2, limit: 500 },
    })).toThrow(/inconsistent/);
  });

describe("optional Operator API availability", () => {
  test("treats only missing and unimplemented routes as unavailable", () => {
    expect(isOptionalOperatorApiUnavailable(new OperatorApiError(404, "missing"))).toBe(true);
    expect(isOptionalOperatorApiUnavailable(new OperatorApiError(501, "disabled"))).toBe(true);
    expect(isOptionalOperatorApiUnavailable(new OperatorApiError(502, "invalid contract"))).toBe(false);
    expect(isOptionalOperatorApiUnavailable(new Error("network"))).toBe(false);
  });
});
