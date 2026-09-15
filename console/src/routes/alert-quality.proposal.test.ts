import { describe, expect, it } from "vitest";
import { alertTreatmentCandidates, decodeAlertQuality, type AlertQualityPayload } from "./alert-quality.model";
import { initialAlertProposal, parseAlertSeconds, parseAlertThreshold, validateAlertProposal, type AlertProposalDraft } from "./alert-quality.proposal";

// Frozen synthetic mechanics, not provider conformance or completed hardening rounds.
const scope = "scope:example";
const digest = `sha256:${"a".repeat(64)}`;
const now = Date.parse("2026-09-14T10:30:00Z");
const routing: Extract<AlertProposalDraft, { kind: "routing" }> = {
  kind: "routing", target_ref: "rule:example_routing", remove_group_ref: "group:example_before", replacement_group_ref: "group:example_after",
};
const suppression: Extract<AlertProposalDraft, { kind: "suppression" }> = {
  kind: "suppression", target_ref: routing.target_ref, processing_rule_ref: "processing:example_rule",
  starts_at: "2026-09-14T20:00:00+09:00", ends_at: "2026-09-14T21:00:00+09:00", preprovisioned: true,
};
const evaluation: Extract<AlertProposalDraft, { kind: "evaluation" }> = {
  kind: "evaluation", target_ref: "rule:example_evaluation", parameter: "threshold", proposed_value: "1e-9",
  baseline: { metric_ref: "metric:example_value", operator: "above", threshold: "0", window_seconds: "300", frequency_seconds: "60", aggregation: "average" },
};
const report = {
  schema_version: "1.0.0", source: "alert-noise-evidence", evidence_digest: digest, policy_digest: digest,
  tenant_ref: "tenant:example", scope_ref: scope, observed_at: "2026-09-14T10:00:00Z", valid_until: "2026-09-14T11:00:00Z",
  coverage: "complete", reasons: [], source_episodes: null, notification_attempts: null,
  confirmed_deliveries: null, acknowledgements: null, execution_authority: false,
  findings: [routing.target_ref, evaluation.target_ref].map((rule_ref, index) => ({
    rule_ref, service_ref: "service:example", reason: index === 0 ? "overlap" : "flapping",
    guidance: index === 0 ? "review-routing" : "review-evaluation", protected: false,
    source_episodes: null, observed_deliveries: null, potential_recipients_lower: null,
    potential_recipients_upper: null, duplicate_paths: 0,
  })),
};
const data = () => decodeAlertQuality({ source: "alert-noise-governance", available: true, enabled: true,
  authority: "shadow", unavailable_reason: null, assessment: report, plans: [] }, scope);
const validate = (draft: AlertProposalDraft, view = data(), at = now) => validateAlertProposal(view, scope, draft, at);

describe("explicit one-axis drafts", () => {
  it("does not seed resource identities, processing rules, calendar windows or baselines", () => {
    for (const kind of ["routing", "suppression", "evaluation"] as const) {
      expect(initialAlertProposal(kind).target_ref).toBe("");
      expect(validate(initialAlertProposal(kind)).body).toBeNull();
    }
    expect(initialAlertProposal("suppression")).toMatchObject({ starts_at: "", ends_at: "", preprovisioned: false });
    expect(initialAlertProposal("evaluation")).toMatchObject({ baseline: { threshold: "", window_seconds: "", frequency_seconds: "" } });
  });

  it("keeps existing routing wire fields and excludes foreign-axis input", () => {
    const result = validate({ ...routing, ...{ processing_rule_ref: "processing:other" } });
    expect(result.body).toEqual({ scope_ref: scope, evidence_digest: digest, treatment: routing });
    expect(result.errors).toEqual({});
    expect(validate({ ...routing, replacement_group_ref: routing.remove_group_ref }).body).toBeNull();
    expect(validate({ ...routing, target_ref: "rule:unobserved" }).body).toBeNull();
    expect(validate({ ...routing, target_ref: evaluation.target_ref }).body).toBeNull();
  });

  it("uses exact opaque references without trimming or inventing provider IDs", () => {
    for (const reference of ["", "group:example\n", " group:example", "GROUP:example", "/provider/example", "user@example.com"]) {
      expect(validate({ ...routing, remove_group_ref: reference }).body).toBeNull();
      expect(validate({ ...suppression, processing_rule_ref: reference }).body).toBeNull();
      expect(validate({ ...evaluation, baseline: { ...evaluation.baseline, metric_ref: reference } }).body).toBeNull();
    }
  });
});

describe("finite pre-provisioned suppression inputs", () => {
  it("preserves exact start/end offsets and sends neither local acknowledgement nor approval", () => {
    expect(validate(suppression).body).toEqual({
      scope_ref: scope, evidence_digest: digest,
      treatment: { kind: "suppression", target_ref: suppression.target_ref, processing_rule_ref: suppression.processing_rule_ref,
        starts_at: suppression.starts_at, ends_at: suppression.ends_at },
    });
    expect(validate({ ...suppression, preprovisioned: false }).body).toBeNull();
  });

  it.each(["2026-02-30T11:00:00Z", "2026-09-14T11:00:00", "2026-09-14T11:00:00-00:00",
    "2026-09-14T11:00:00+24:00", "2026-09-14T11:00:00.1234567Z", "tomorrow", "2026-09-14T11:00:00Z\n"])(
    "rejects invalid or ambiguous absolute time %s", (starts_at) => {
      expect(validate({ ...suppression, starts_at }).body).toBeNull();
    },
  );

  it("compares instants and microseconds rather than clock text", () => {
    expect(validate({ ...suppression, ends_at: "2026-09-14T11:00:00Z" }).body).toBeNull();
    expect(validate({ ...suppression, ends_at: "2026-09-14T10:59:59Z" }).body).toBeNull();
    expect(validate({ ...suppression, starts_at: "2026-09-14T10:30:00Z" }).errors.starts_at).toBe("future");
    expect(validate({ ...suppression, starts_at: "2026-09-14T11:00:00.123001Z", ends_at: "2026-09-14T11:00:00.123002Z" }).body).not.toBeNull();
  });

  it("does not invent a universal minimum propagation delay or a policy duration", () => {
    expect(validate({ ...suppression, starts_at: "2026-09-14T10:30:01Z", ends_at: "2026-09-14T14:30:01Z" }).body).not.toBeNull();
    // The server, not this grammar check, must hold insufficient propagation or excessive duration.
  });
});

describe("baseline-bound evaluation grammar", () => {
  it.each(["", " ", "1 ", "1\n", "0x10", "1,000", "Infinity", "NaN", "1e309", "1e-9999", ".5", "01"])(
    "rejects ambiguous, non-finite or lossy threshold input %s", (value) => expect(parseAlertThreshold(value)).toBeNull(),
  );

  it("preserves legitimate finite negative, zero and scientific thresholds", () => {
    expect(parseAlertThreshold("-5.25")).toBe(-5.25);
    expect(parseAlertThreshold("0")).toBe(0);
    expect(parseAlertThreshold("1e-9")).toBe(1e-9);
    expect(parseAlertThreshold("1.7976931348623157e308")).toBe(Number.MAX_VALUE);
  });

  it.each(["0", "86401", "1.5", "+60", "060", " 60", "60\n", "6e1"])(
    "rejects noncanonical bounded seconds %s", (value) => expect(parseAlertSeconds(value)).toBeNull(),
  );

  it.each(["threshold", "window_seconds", "frequency_seconds"] as const)("changes only %s and keeps the full baseline grammar", (parameter) => {
    const draft = { ...evaluation, parameter, proposed_value: parameter === "threshold" ? "1e-9" : "120" };
    const body = validate(draft).body!;
    expect(Object.keys(body).sort()).toEqual(["evidence_digest", "scope_ref", "treatment"]);
    expect(Object.keys(body.treatment).sort()).toEqual(["evaluation", "kind", "target_ref"]);
    const baseline = { metric_ref: "metric:example_value", operator: "above", threshold: 0, window_seconds: 300, frequency_seconds: 60, aggregation: "average" };
    expect(body.treatment).toEqual({ kind: "evaluation", target_ref: evaluation.target_ref,
      evaluation: { ...baseline, [parameter]: parameter === "threshold" ? 1e-9 : 120 } });
    expect(body).not.toHaveProperty("baseline");
    expect(body).not.toHaveProperty("execution_authority");
  });

  it("rejects unchanged, incomplete or unsupported baseline inputs without widening semantics", () => {
    expect(validate({ ...evaluation, proposed_value: "0.0" }).errors.proposed_value).toBe("changed");
    expect(validate({ ...evaluation, baseline: { ...evaluation.baseline, operator: "" } }).body).toBeNull();
    expect(validate({ ...evaluation, baseline: { ...evaluation.baseline, aggregation: "" } }).body).toBeNull();
    expect(validate({ ...evaluation, baseline: { ...evaluation.baseline, frequency_seconds: "" } }).body).toBeNull();
    expect(validate({ ...evaluation, parameter: "window_seconds", proposed_value: "300" }).body).toBeNull();
  });
});

describe("proposal evidence and target holds", () => {
  it("keeps the initial, expired, disabled, unavailable and server-held cases inert for every axis", () => {
    const view = data();
    const held: AlertQualityPayload[] = [
      { ...view, assessment: null }, { ...view, available: false }, { ...view, enabled: false }, { ...view, requestable: false },
      { ...view, assessment: { ...view.assessment!, coverage: "partial" } },
      { ...view, assessment: { ...view.assessment!, reasons: ["missing:history"] } },
    ];
    for (const draft of [routing, suppression, evaluation]) {
      for (const payload of held) expect(validate(draft, payload).body).toBeNull();
      expect(validate(draft, view, Date.parse(report.valid_until)).body).toBeNull();
      expect(validate(draft, view, NaN).body).toBeNull();
    }
  });

  it("lets any protected or incomplete finding block the target across treatment choices", () => {
    const view = data();
    for (const kind of ["routing", "suppression", "evaluation"] as const) {
      const report = { ...view.assessment!, findings: view.assessment!.findings.flatMap((item) => [item, { ...item, protected: true }]) };
      expect(alertTreatmentCandidates(report, kind)).toEqual([]);
    }
  });
});
