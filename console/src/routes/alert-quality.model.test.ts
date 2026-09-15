import { describe, expect, it } from "vitest";
import backendFixture from "./alert-quality.backend.fixture.json";
import {
  ALERT_MAX_PLANS, alertQualityFreshness, alertQualityRequestable, alertQualityScope, alertQualityTimestamp,
  alertRoutingCandidates, buildAlertRoutingProposal, decodeAlertQuality, decodeAlertQualityTreatment,
} from "./alert-quality.model";

// Synthetic JSON mirrors the actual AlertQualityResponse / NoiseAssessment / AlertChangePlan
// model_dump(mode="json") fields, including nullable defaults. It is not a captured live response.
const assessment = backendFixture.assessment;
const digest = assessment.evidence_digest;
const scope = assessment.scope_ref;
const finding = assessment.findings[0]!;
const routing = { kind: "routing", target_ref: finding.rule_ref, remove_group_ref: "group:source", replacement_group_ref: "group:replacement" };
const evaluation = { metric_ref: "metric:example", operator: "above", threshold: 75.25, window_seconds: 300, frequency_seconds: 60, aggregation: "average" };
const suppression = { kind: "suppression", target_ref: finding.rule_ref, processing_rule_ref: "processing:example", starts_at: "2026-09-14T11:00:00+00:00", ends_at: "2026-09-14T12:00:00+00:00" };
const plan = backendFixture.plans[0]!;
const payload = (report: unknown = assessment, plans: readonly unknown[] = [plan]) => ({
  ...backendFixture, assessment: report, plans,
});

describe("current backend serialized shape and retained-v1 compatibility", () => {
  it("accepts the full current serialized object without stripping additive fields to make it pass", () => {
    const decoded = decodeAlertQuality(JSON.parse(JSON.stringify(backendFixture)), scope);
    expect(decoded.assessment).toEqual(assessment);
    expect(decoded.plans[0]?.treatment).toEqual(routing);
    expect(decoded.plans[0]).toHaveProperty("evaluation_receipt_digest", null);
    expect(decoded.requestable).toBe(true);
  });

  it("preserves explicit nulls and narrowly permits omission in retained v1 records", () => {
    const retained: Record<string, unknown> = { ...assessment };
    const oldPlan: Record<string, unknown> = { ...plan };
    delete retained.window_start;
    delete retained.window_end;
    delete oldPlan.evaluation_receipt_digest;
    const decoded = decodeAlertQuality(payload(retained, [oldPlan]), scope);
    expect(decoded.assessment).not.toHaveProperty("window_start");
    expect(decoded.assessment).not.toHaveProperty("window_end");
    expect(decoded.plans[0]).not.toHaveProperty("evaluation_receipt_digest");
    const nulls = decodeAlertQuality(payload({ ...assessment, window_start: null, window_end: null }), scope);
    expect(nulls.assessment).toHaveProperty("window_start", null);
    expect(nulls.assessment).toHaveProperty("window_end", null);
    expect(() => decodeAlertQuality(payload({ ...retained, window_start: undefined }), scope)).toThrow();
    expect(() => decodeAlertQuality(payload(retained, [{ ...oldPlan, evaluation_receipt_digest: undefined }]), scope)).toThrow();
    expect(() => decodeAlertQuality(payload({ ...retained, notification_attempts: undefined }), scope)).toThrow();
  });

  it("requires paired positive observation bounds no later than cutoff, including microseconds", () => {
    for (const change of [
      { window_start: null }, { window_end: null }, { window_start: undefined }, { window_end: "not-a-time" },
      { window_start: assessment.window_end }, { window_start: "2026-09-14T10:00:01Z" },
      { window_end: "2026-09-14T10:00:00.000001Z" }, { window_start: "2026-02-30T09:00:00Z" },
    ]) expect(() => decodeAlertQuality(payload({ ...assessment, ...change }), scope)).toThrow();
    const precise = { ...assessment, window_start: "2026-09-14T18:59:59.999998+09:00",
      window_end: "2026-09-14T18:59:59.999999+09:00" };
    expect(decodeAlertQuality(payload(precise), scope).assessment?.window_start).toBe(precise.window_start);
    expect(() => decodeAlertQuality(payload({ ...assessment, window_begin: assessment.window_start }), scope)).toThrow();
  });

  it("accepts only a real digest or null for the additive evaluation receipt", () => {
    const evaluationPlan = { ...plan, action_type: "ops.tune-alert-evaluation",
      treatment: { kind: "evaluation", target_ref: finding.rule_ref, replacement_group_ref: null,
        remove_group_ref: null, processing_rule_ref: null, starts_at: null, ends_at: null, evaluation } };
    expect(decodeAlertQuality(payload(assessment, [{ ...evaluationPlan, evaluation_receipt_digest: digest }]), scope)
      .plans[0]?.evaluation_receipt_digest).toBe(digest);
    for (const invalid of [true, 0, "", "sha256:short", `${digest}\n`, undefined, { digest }]) {
      expect(() => decodeAlertQuality(payload(assessment, [{ ...evaluationPlan, evaluation_receipt_digest: invalid }]), scope)).toThrow();
    }
    expect(() => decodeAlertQuality(payload(assessment, [{ ...evaluationPlan, baseline_threshold: 0 }]), scope)).toThrow();
  });
});

describe("strict bounded assessment counts", () => {
  it("preserves null, observed zero and independent denominators", () => {
    const report = decodeAlertQuality(payload(), scope).assessment!;
    expect(report.source_episodes).toBe(3);
    expect(report.notification_attempts).toBeNull();
    expect(report.confirmed_deliveries).toBe(0);
    expect(report.acknowledgements).toBeNull();
    expect(report.findings[0]?.potential_recipients_upper).toBe(10);
    expect(decodeAlertQuality(payload({ ...assessment, confirmed_deliveries: 9 }), scope).assessment?.confirmed_deliveries).toBe(9);
  });

  it("preserves unknown episode counts in both the report and findings", () => {
    const result = decodeAlertQuality(payload({ ...assessment, source_episodes: null,
      findings: [{ ...finding, source_episodes: null }] }), scope).assessment!;
    expect(result.source_episodes).toBeNull();
    expect(result.findings[0]?.source_episodes).toBeNull();
    expect(result.confirmed_deliveries).toBe(0);
  });

  it.each([true, "0", -1, 1.25, NaN, Infinity, 10_000_001, undefined])("rejects invalid count %s", (count) => {
    expect(() => decodeAlertQuality(payload({ ...assessment, source_episodes: count }), scope)).toThrow();
    expect(() => decodeAlertQuality(payload({ ...assessment, confirmed_deliveries: count }), scope)).toThrow();
    expect(() => decodeAlertQuality(payload({ ...assessment, findings: [{ ...finding, duplicate_paths: count }] }), scope)).toThrow();
  });

  it("accepts exact bounds and rejects oversized arrays without silently truncating", () => {
    expect(decodeAlertQuality(payload({ ...assessment, source_episodes: 10_000_000 }), scope).assessment?.source_episodes).toBe(10_000_000);
    expect(() => decodeAlertQuality(payload({ ...assessment, findings: Array.from({ length: 10_001 }, () => finding) }), scope)).toThrow();
    expect(() => decodeAlertQuality(payload({ ...assessment, reasons: Array.from({ length: 33 }, (_, index) => `reason:${index}`) }), scope)).toThrow();
    expect(() => decodeAlertQuality(payload(assessment, Array.from({ length: ALERT_MAX_PLANS + 1 }, () => plan)), scope)).toThrow();
  });

  it("rejects a within-row-limit projection that exceeds the shared byte budget", () => {
    const large = payload({ ...assessment, findings: Array.from({ length: 6_000 }, () => finding) }, []);
    expect(new TextEncoder().encode(JSON.stringify(large)).byteLength).toBeGreaterThan(1_048_576);
    expect(() => decodeAlertQuality(large, scope)).toThrow(/byte bound/);
  });

  it("rejects missing nullable fields and reversed potential reach", () => {
    for (const field of ["notification_attempts", "confirmed_deliveries", "acknowledgements"]) {
      const report: Record<string, unknown> = { ...assessment };
      delete report[field];
      expect(() => decodeAlertQuality(payload(report), scope)).toThrow();
    }
    expect(() => decodeAlertQuality(payload({ ...assessment, findings: [{ ...finding, potential_recipients_lower: 11 }] }), scope)).toThrow();
  });
});

describe("exact schema and no-authority flags", () => {
  it.each([true, 0, "false", null, undefined])("rejects noncanonical no-authority value %s", (value) => {
    expect(() => decodeAlertQuality(payload({ ...assessment, execution_authority: value }), scope)).toThrow();
    expect(() => decodeAlertQuality(payload(assessment, [{ ...plan, execution_authority: value }]), scope)).toThrow();
  });

  it("rejects authority escalation, unknown versions and extra fields", () => {
    for (const override of [{ authority: "enforce" }, { available: 1 }, { enabled: "true" }, { approval_available: true }]) {
      expect(() => decodeAlertQuality({ ...payload(), ...override }, scope)).toThrow();
    }
    for (const override of [{ default_mode: "enforce" }, { execution_path: "direct" }, { quorum_required: 1 }, { schema_version: "2.0.0" }, { can_approve: false }]) {
      expect(() => decodeAlertQuality(payload(assessment, [{ ...plan, ...override }]), scope)).toThrow();
    }
    expect(() => decodeAlertQuality(payload({ ...assessment, source: "fixture" }), scope)).toThrow();
    expect(() => decodeAlertQuality(payload({ ...assessment, coverage: "healthy" }), scope)).toThrow();
    expect(() => decodeAlertQuality(payload({ ...assessment, schema_version: "2.0.0" }), scope)).toThrow();
    expect(() => decodeAlertQuality(payload({ ...assessment, evidence_digest: "sha256:invalid" }), scope)).toThrow();
  });

  it("keeps available, enabled, pending and unavailable separate", () => {
    const pending = decodeAlertQuality({ ...payload(null, []), available: false, unavailable_reason: "assessment_pending" }, scope);
    expect(pending.assessment).toBeNull();
    expect(pending.available).toBe(false);
    expect(decodeAlertQuality({ ...payload(), enabled: false }, scope).enabled).toBe(false);
    expect(decodeAlertQuality({ ...payload(null, []), available: false, unavailable_reason: "runtime-unavailable" }, scope).available).toBe(false);
    expect(() => decodeAlertQuality({ ...payload(null, []), available: false }, scope)).toThrow();
    expect(decodeAlertQuality(payload(null, []), scope).available).toBe(true);
    expect(decodeAlertQuality(payload(null, []), scope).assessment).toBeNull();
    expect(decodeAlertQuality({ ...payload(), unavailable_reason: "assessment_expired" }, scope).assessment).not.toBeNull();
    const stopped = decodeAlertQuality({ ...payload(), available: false, unavailable_reason: "source_unavailable" }, scope);
    expect(stopped.assessment).not.toBeNull();
    expect(stopped.plans).toHaveLength(1);
    expect(alertQualityRequestable(stopped)).toBe(false);
    expect(decodeAlertQuality(payload(null), scope).plans).toHaveLength(1);
  });

  it("keeps requestability backward compatible and independent of report age or existence", () => {
    const legacy: Record<string, unknown> = payload(null, []);
    delete legacy.requestable;
    const missing = decodeAlertQuality(legacy, scope);
    const expired = decodeAlertQuality({ ...payload(), unavailable_reason: "assessment_expired" }, scope);
    expect(missing).not.toHaveProperty("requestable");
    expect(alertQualityRequestable(missing)).toBe(true);
    expect(alertQualityRequestable(expired)).toBe(true);
    expect(alertQualityRequestable(decodeAlertQuality({ ...payload(), requestable: false }, scope))).toBe(false);
    expect(alertQualityRequestable(decodeAlertQuality({ ...payload(), available: false,
      requestable: true, unavailable_reason: "source_unavailable" }, scope))).toBe(false);
    for (const value of [null, "true", 1, undefined]) {
      expect(() => decodeAlertQuality({ ...payload(), requestable: value }, scope)).toThrow();
    }
  });
});

describe("calendar, offset, microsecond and expiry correctness", () => {
  it.each(["2026-02-30T10:00:00Z", "2026-09-14T24:00:00Z", "2026-09-14T10:00:00", "2026-09-14T10:00:00-00:00", "2026-09-14T10:00:00+24:00", "2026-09-14T10:00:00+00:60", "2026-09-14T10:00:60Z", "2026-09-14T10:00:00.1234567Z", "0000-01-01T00:00:00Z", "yesterday"]) ("rejects unsafe timestamp %s", (value) => {
    expect(() => alertQualityTimestamp(value)).toThrow();
  });

  it("accepts leap dates and preserves exact non-UTC timestamps", () => {
    expect(alertQualityTimestamp("2028-02-29T12:00:00+09:00")).toBe("2028-02-29T12:00:00+09:00");
    expect(alertQualityFreshness("2026-09-14T19:00:00+09:00", "2026-09-14T20:00:00+09:00", Date.parse("2026-09-14T11:00:00Z"))).toBe("expired");
  });

  it("compares microseconds instead of collapsing distinct contract instants", () => {
    const report = { ...assessment, observed_at: "2026-09-14T10:00:00.123001Z", valid_until: "2026-09-14T10:00:00.123002Z" };
    expect(decodeAlertQuality(payload(report, []), scope).assessment?.valid_until).toBe(report.valid_until);
    expect(() => decodeAlertQuality(payload({ ...report, observed_at: report.valid_until, valid_until: report.observed_at }), scope)).toThrow();
    expect(alertQualityFreshness(report.observed_at, report.valid_until, Date.parse("2026-09-14T10:00:00.123Z"))).toBe("future");
    expect(alertQualityFreshness(report.observed_at, report.valid_until, Date.parse("2026-09-14T10:00:00.124Z"))).toBe("expired");
    expect(alertQualityFreshness(report.observed_at, report.valid_until, NaN)).toBe("unknown");
  });

  it("rejects equal or reversed plan windows and invalid execution limits", () => {
    expect(() => decodeAlertQuality(payload(assessment, [{ ...plan, expires_at: plan.created_at }]), scope)).toThrow();
    for (const max of [0, 86_401, 1.2, "60", false]) {
      expect(() => decodeAlertQuality(payload(assessment, [{ ...plan, max_execution_seconds: max }]), scope)).toThrow();
    }
  });
});

describe("opaque scope, privacy and exact binding", () => {
  it.each(["", "scope_ref=", "scope_ref=Scope:example", "scope_ref=scope:one&scope_ref=scope:two", "scope_ref=scope:one&scope_ref=scope:one", "scope_ref=%20scope:one", "scope_ref=%2Fsubscriptions%2Fexample", "scope_ref=user%40example.com"]) ("never broadens unsafe selectors %s", (query) => {
    expect(alertQualityScope(new URLSearchParams(query))).toBeNull();
  });

  it("preserves all allowed reference characters without slugification", () => {
    const value = "scope:example_team.alpha-1";
    expect(alertQualityScope(new URLSearchParams({ scope_ref: value }))).toBe(value);
  });

  it("rejects trailing newlines that JavaScript dollar anchors otherwise accept", () => {
    expect(alertQualityScope(new URLSearchParams({ scope_ref: `${scope}\n` }))).toBeNull();
    expect(() => decodeAlertQuality(payload({ ...assessment, evidence_digest: `${digest}\n` }), scope)).toThrow();
    expect(() => alertQualityTimestamp(`${assessment.observed_at}\n`)).toThrow();
    expect(() => decodeAlertQuality(payload({ ...assessment, findings: [{ ...finding, rule_ref: `${finding.rule_ref}\n` }] }), scope)).toThrow();
  });

  it("rejects cross-scope or cross-tenant records and divergent rule-service identities", () => {
    expect(() => decodeAlertQuality(payload(), "scope:other")).toThrow();
    expect(() => decodeAlertQuality(payload(assessment, [{ ...plan, scope_ref: "scope:other" }]), scope)).toThrow();
    expect(() => decodeAlertQuality(payload(assessment, [{ ...plan, tenant_ref: "tenant:other" }]), scope)).toThrow();
    expect(() => decodeAlertQuality(payload({ ...assessment, findings: [finding, { ...finding, service_ref: "service:other" }] }), scope)).toThrow();
    expect(() => decodeAlertQuality(payload({ ...assessment, findings: [{ ...finding, rule_ref: "user@example.com" }] }), scope)).toThrow();
  });
});

describe("single-axis treatment and bounded dependency snapshots", () => {
  it("accepts all three treatment kinds and nullable wire defaults", () => {
    expect(decodeAlertQualityTreatment({ ...routing, processing_rule_ref: null, starts_at: null, ends_at: null, evaluation: null })).toEqual(routing);
    expect(decodeAlertQualityTreatment(suppression)).toEqual(suppression);
    expect(decodeAlertQualityTreatment({ kind: "evaluation", target_ref: finding.rule_ref, evaluation })).toMatchObject({ evaluation });
    for (const [action_type, treatment] of [
      ["ops.set-alert-notification-window", suppression],
      ["ops.tune-alert-evaluation", { kind: "evaluation", target_ref: finding.rule_ref, evaluation }],
    ]) expect(decodeAlertQuality(payload(assessment, [{ ...plan, action_type, treatment }]), scope).plans).toHaveLength(1);
  });

  it("rejects mixed axes even when only half of the foreign axis is supplied", () => {
    for (const override of [{ starts_at: suppression.starts_at }, { ends_at: suppression.ends_at }, { evaluation }, { processing_rule_ref: "processing:example" }]) {
      expect(() => decodeAlertQualityTreatment({ ...routing, ...override })).toThrow();
    }
    for (const key of ["remove_group_ref", "replacement_group_ref"]) {
      expect(() => decodeAlertQualityTreatment({ ...suppression, [key]: "group:other" })).toThrow();
      expect(() => decodeAlertQualityTreatment({ kind: "evaluation", target_ref: finding.rule_ref, evaluation, [key]: "group:other" })).toThrow();
    }
    expect(() => decodeAlertQualityTreatment({ ...routing, replacement_group_ref: routing.remove_group_ref })).toThrow();
    expect(() => decodeAlertQualityTreatment({ ...suppression, ends_at: suppression.starts_at })).toThrow();
    expect(() => decodeAlertQualityTreatment({ ...routing, script: "arbitrary" })).toThrow();
  });

  it("rejects unsupported evaluation semantics and action/treatment mismatch", () => {
    for (const override of [{ operator: "equal" }, { aggregation: "total" }, { threshold: Infinity }, { window_seconds: 0 }, { frequency_seconds: 86_401 }]) {
      expect(() => decodeAlertQualityTreatment({ kind: "evaluation", target_ref: finding.rule_ref, evaluation: { ...evaluation, ...override } })).toThrow();
    }
    expect(() => decodeAlertQuality(payload(assessment, [{ ...plan, treatment: suppression }]), scope)).toThrow();
    expect(() => decodeAlertQuality(payload(assessment, [{ ...plan, action_type: "ops.restore-alert-configuration" }]), scope)).toThrow();
    for (const override of [{ lock_refs: [] }, { lock_refs: ["lock:z", "lock:a"] }, { service_refs: ["service:a", "service:a"] }, { service_refs: Array.from({ length: 65 }, (_, index) => `service:${index}`) }]) {
      expect(() => decodeAlertQuality(payload(assessment, [{ ...plan, ...override }]), scope)).toThrow();
    }
  });
});

describe("evidence admission does not become authority", () => {
  const now = Date.parse("2026-09-14T10:30:00Z");
  const build = (raw: unknown, target = finding.rule_ref, at = now) => buildAlertRoutingProposal(decodeAlertQuality(raw, scope), scope, target, "group:source", "group:replacement", at);

  it("requires a deliberate report target and two distinct existing reference inputs", () => {
    expect(build(payload())).toEqual({ scope_ref: scope, evidence_digest: digest, treatment: routing });
    expect(build(payload(), "rule:unobserved")).toBeNull();
    expect(buildAlertRoutingProposal(decodeAlertQuality(payload(), scope), scope, finding.rule_ref, "group:source", "group:source", now)).toBeNull();
    expect(buildAlertRoutingProposal(decodeAlertQuality(payload(), scope), scope, finding.rule_ref, "/provider/path", "group:replacement", now)).toBeNull();
  });

  it("blocks unavailable, disabled, absent, partial, future and expired evidence", () => {
    for (const raw of [
      { ...payload(null, []), available: false, unavailable_reason: "source_unavailable" }, { ...payload(), enabled: false },
      { ...payload(null, []), available: false, unavailable_reason: "assessment_missing" },
      payload({ ...assessment, coverage: "partial", reasons: ["missing:audience"] }), payload({ ...assessment, reasons: ["missing:backup"] }),
    ]) expect(build(raw)).toBeNull();
    expect(build(payload(), finding.rule_ref, Date.parse(assessment.observed_at) - 1)).toBeNull();
    expect(build(payload(), finding.rule_ref, Date.parse(assessment.valid_until))).toBeNull();
  });

  it("lets any protection or evidence hold on the same rule block a routing suggestion", () => {
    for (const override of [{ protected: true }, { reason: "incomplete", guidance: "collect-evidence" }, { reason: "unowned", guidance: "review-ownership" }]) {
      const report = decodeAlertQuality(payload({ ...assessment, findings: [finding, { ...finding, ...override }] }), scope).assessment!;
      expect(alertRoutingCandidates(report)).toEqual([]);
    }
    expect(() => decodeAlertQuality(payload({ ...assessment, findings: [{ ...finding, reason: "protected" }] }), scope)).toThrow();
  });
});
