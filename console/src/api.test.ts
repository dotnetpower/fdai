import { describe, expect, test } from "vitest";
import {
  decodeAuditPage,
  decodeAutonomyPayload,
  decodeDashboardKpi,
  decodeHilQueuePage,
  decodeIncidentPage,
  decodeRcaView,
  ReadApiError,
} from "./api";

describe("read API response decoders", () => {
  const metric = { value: 0.1, baseline: 0.2, direction: "lower" } as const;
  const autonomy = {
    synthetic: false,
    window_days: 30,
    sample_size: 100,
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
    verticals: [{ key: "resilience", events: 1, auto_resolved: 1, open_risks: 0, monthly_savings: 0 }],
    tier: { mix: { t0: 1 }, bands: { t0: [0.7, 0.8] } },
    trend: { auto_resolution_rate: [0.1, 0.2] },
  };

  test("decodes complete autonomy evidence and rejects partial KPI contracts", () => {
    expect(decodeAutonomyPayload(autonomy).source.name).toBe("measurement-pipeline");
    expect(() => decodeAutonomyPayload({
      ...autonomy,
      success: { ...autonomy.success, cost_per_resolved_event_usd: undefined },
    })).toThrow(ReadApiError);
  });

  test("reject malformed always-on payloads with a uniform contract error", () => {
    for (const decode of [decodeAuditPage, decodeDashboardKpi, decodeHilQueuePage, decodeIncidentPage]) {
      expect(() => decode({})).toThrow(ReadApiError);
      try { decode({}); } catch (error) {
        expect((error as ReadApiError).status).toBe(502);
      }
    }
  });

  test("decodes empty audit and HIL pages", () => {
    expect(decodeAuditPage({ items: [], next_cursor: null })).toEqual({ items: [], next_cursor: null });
    expect(decodeHilQueuePage({ items: [], total: 0 })).toEqual({ items: [], total: 0 });
  });

  test("decodes an incident page and rejects invalid status", () => {
    const item = {
      correlation_id: "corr-1",
      incident_id: null,
      ticket_id: null,
      title: "Rule example.rule",
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
    expect(decodeIncidentPage({ items: [item], next_cursor: null }).items[0]?.status)
      .toBe("in_progress");
    expect(() => decodeIncidentPage({
      items: [{ ...item, status: "closed" }],
      next_cursor: null,
    })).toThrow(/status MUST/);
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