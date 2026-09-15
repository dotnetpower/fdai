/** Exact request/terminal projections; this decoder grants no approval or execution authority. */
import {
  ALERT_MAX_PROJECTION_BYTES, alertQualityTimestamp, alertQualityTimestampMicros,
  decodeAlertQualityEvaluation, decodeAlertQualityPlan, isAlertQualityRef,
  type AlertEvaluation, type AlertQualityPlan,
} from "./alert-quality.model";
import { panelContractError, panelRecord } from "./panel-decode";

export type AlertRequestStatus = "pending" | "unconfirmed" | "assessment_ready" | "proposal_ready" | "held";
const CLASSIFICATIONS = ["informational", "operational", "security", "compliance", "slo", "recovery", "service_health", "telemetry_loss", "approval", "unknown"] as const;
export type AlertProcessStatus = "pending" | "running" | "waiting" | "compensating" | "compensated" | "succeeded" | "failed" | "cancelled" | "timed_out";
export interface AlertBaselineRule {
  readonly ref: string; readonly revision: string; readonly service_ref: string; readonly resource_ref: string;
  readonly group_refs: readonly string[]; readonly enabled: boolean; readonly stateful: boolean;
  readonly active_incident: boolean; readonly iac_owned: boolean; readonly ownership_verified: boolean;
  readonly severity: number | null; readonly classification: typeof CLASSIFICATIONS[number]; readonly kind: string;
  readonly evaluation: AlertEvaluation | null;
}
export interface AlertReplayMetrics {
  readonly baseline_true_positive: number; readonly treatment_true_positive: number;
  readonly baseline_false_positive: number; readonly treatment_false_positive: number;
  readonly baseline_false_negative: number; readonly treatment_false_negative: number;
  readonly baseline_max_latency_seconds: number | null; readonly treatment_max_latency_seconds: number | null;
  readonly replay_method: "same-bucket-threshold-v1" | "uniform-metric-series-v1";
  readonly accepted: boolean; readonly scenario_digest: string;
}
export interface AlertProposalDetail {
  readonly plan_digest: string; readonly recorded_at: string;
  readonly baseline: { readonly rule: AlertBaselineRule; readonly processing_rule: {
    readonly ref: string; readonly enabled: boolean; readonly effective_from: string | null;
    readonly effective_to: string | null;
  } | null };
  readonly evaluation: AlertReplayMetrics | null;
  readonly process: { readonly process_id: string; readonly workflow_ref: string; readonly status: AlertProcessStatus; readonly mode: "shadow" | "enforce" } | null;
}
export interface AlertRequestRecord {
  readonly request_ref: string; readonly request_key: string;
  readonly operation: "alert_noise.assess" | "alert_noise.propose";
  readonly accepted_at: string; readonly expires_at: string; readonly status: AlertRequestStatus;
  readonly reason: string | null; readonly result_recorded_at: string | null;
  readonly plan: AlertQualityPlan | null; readonly detail: AlertProposalDetail | null;
}
export interface AlertRequestHistory {
  readonly source: "alert-noise-requests"; readonly scope_ref: string; readonly read_at: string;
  readonly requests: readonly AlertRequestRecord[]; readonly truncated: boolean;
}

function fail(): never { throw panelContractError("alert request history is invalid"); }
function row(value: unknown, keys: string) {
  const result = panelRecord(value, "alert request history");
  const allowed = new Set(keys.split(" "));
  if (Object.keys(result).some((key) => !allowed.has(key))) fail();
  return result;
}
function ref(value: unknown): string { if (!isAlertQualityRef(value)) fail(); return value; }
function digest(value: unknown): string {
  if (typeof value !== "string" || value.length !== 71 || !/^sha256:[a-f0-9]{64}$/.test(value)) fail();
  return value;
}
function bool(value: unknown): boolean { if (typeof value !== "boolean") fail(); return value; }
function noAuthority(value: unknown) { if (value !== false) fail(); }
function count(value: unknown, max = 10_000_000): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0 || value > max) fail();
  return value;
}
function nullableCount(value: unknown): number | null { return value === null ? null : count(value); }
function choice<T extends string>(value: unknown, allowed: readonly T[]): T {
  if (typeof value !== "string" || !allowed.includes(value as T)) fail(); return value as T;
}
function list(value: unknown, limit: number): unknown[] { if (!Array.isArray(value) || value.length > limit) fail(); return value; }
function timeOrNull(value: unknown): string | null { return value === null ? null : alertQualityTimestamp(value); }

function baselineRule(value: unknown): AlertBaselineRule {
  const r = row(value, "ref resource_ref service_ref revision kind severity classification group_refs enabled stateful evaluation active_incident iac_owned ownership_verified");
  const groups = list(r.group_refs, 5).map(ref);
  if (new Set(groups).size !== groups.length) fail();
  return {
    ref: ref(r.ref), service_ref: ref(r.service_ref), revision: digest(r.revision), resource_ref: ref(r.resource_ref),
    active_incident: bool(r.active_incident), iac_owned: bool(r.iac_owned), ownership_verified: bool(r.ownership_verified),
    kind: choice(r.kind, ["metric", "log", "activity", "processing", "unknown"]),
    severity: r.severity === null ? null : count(r.severity, 4), classification: choice(r.classification, CLASSIFICATIONS),
    group_refs: groups, enabled: bool(r.enabled), stateful: bool(r.stateful),
    evaluation: r.evaluation === null ? null : decodeAlertQualityEvaluation(r.evaluation),
  };
}

function replayMetrics(value: unknown, plan: AlertQualityPlan): AlertReplayMetrics {
  const r = row(value, "rule_ref rule_revision scenario_digest baseline treatment evaluated_at expires_at baseline_true_positive treatment_true_positive baseline_false_positive treatment_false_positive baseline_false_negative treatment_false_negative accepted reason replay_method baseline_max_latency_seconds treatment_max_latency_seconds case_results execution_authority");
  noAuthority(r.execution_authority); ref(r.reason); digest(r.rule_revision);
  if (ref(r.rule_ref) !== plan.treatment.target_ref || plan.treatment.kind !== "evaluation") fail();
  const treatment = decodeAlertQualityEvaluation(r.treatment);
  if (JSON.stringify(treatment) !== JSON.stringify(plan.treatment.evaluation)) fail();
  decodeAlertQualityEvaluation(r.baseline);
  const from = alertQualityTimestamp(r.evaluated_at), to = alertQualityTimestamp(r.expires_at);
  if (alertQualityTimestampMicros(from) >= alertQualityTimestampMicros(to)) fail();
  const method = choice(r.replay_method, ["same-bucket-threshold-v1", "uniform-metric-series-v1"]);
  const cases = list(r.case_results, 128);
  for (const entry of cases) {
    const c = row(entry, "ref actionable baseline_detected treatment_detected baseline_latency_seconds treatment_latency_seconds");
    ref(c.ref); bool(c.actionable); bool(c.baseline_detected); bool(c.treatment_detected);
    nullableCount(c.baseline_latency_seconds); nullableCount(c.treatment_latency_seconds);
  }
  const before = nullableCount(r.baseline_max_latency_seconds), after = nullableCount(r.treatment_max_latency_seconds);
  if (method === "uniform-metric-series-v1" && (cases.length < 2 || before === null || after === null || after > before)) fail();
  if (method === "same-bucket-threshold-v1" && (cases.length > 0 || before !== null || after !== null)) fail();
  return {
    baseline_true_positive: count(r.baseline_true_positive), treatment_true_positive: count(r.treatment_true_positive),
    baseline_false_positive: count(r.baseline_false_positive), treatment_false_positive: count(r.treatment_false_positive),
    baseline_false_negative: count(r.baseline_false_negative), treatment_false_negative: count(r.treatment_false_negative),
    baseline_max_latency_seconds: before, treatment_max_latency_seconds: after,
    replay_method: method, accepted: bool(r.accepted), scenario_digest: digest(r.scenario_digest),
  };
}

function detail(value: unknown, plan: AlertQualityPlan): AlertProposalDetail {
  const d = row(value, "plan_digest baseline evaluation process recorded_at execution_authority");
  noAuthority(d.execution_authority);
  const b = row(d.baseline, "rule processing_rule"), rule = baselineRule(b.rule);
  if (rule.ref !== plan.treatment.target_ref || (plan.treatment.kind !== "suppression" && rule.revision !== plan.target_revision)) fail();
  let processing: AlertProposalDetail["baseline"]["processing_rule"] = null;
  if (b.processing_rule !== null) {
    const p = row(b.processing_rule, "ref revision rule_refs action group_refs enabled effective_from effective_to semantics_complete");
    const id = ref(p.ref);
    if (plan.treatment.kind !== "suppression" || id !== plan.treatment.processing_rule_ref || digest(p.revision) !== plan.target_revision) fail();
    list(p.rule_refs, 2000).map(ref); list(p.group_refs, 5).map(ref); bool(p.semantics_complete); ref(p.action);
    processing = { ref: id, enabled: bool(p.enabled), effective_from: timeOrNull(p.effective_from), effective_to: timeOrNull(p.effective_to) };
  } else if (plan.treatment.kind === "suppression") fail();
  let process: AlertProposalDetail["process"] = null;
  if (d.process !== null) {
    const p = row(d.process, "process_id workflow_ref status mode");
    if (typeof p.process_id !== "string" || !/^[A-Za-z0-9_.:-]{1,200}$/.test(p.process_id) || p.process_id.endsWith("\n")) fail();
    process = { process_id: p.process_id, workflow_ref: ref(p.workflow_ref),
      status: choice(p.status, ["pending", "running", "waiting", "compensating", "compensated", "succeeded", "failed", "cancelled", "timed_out"]),
      mode: choice(p.mode, ["shadow", "enforce"]) };
  }
  return { plan_digest: digest(d.plan_digest), recorded_at: alertQualityTimestamp(d.recorded_at),
    baseline: { rule, processing_rule: processing }, evaluation: d.evaluation === null ? null : replayMetrics(d.evaluation, plan), process };
}

/** Strict one-scope decode; schema, identity and time errors reject the page rather than drop rows. */
export function decodeAlertRequestHistory(value: unknown, scope: string): AlertRequestHistory {
  if (new TextEncoder().encode(JSON.stringify(value)).byteLength > ALERT_MAX_PROJECTION_BYTES) fail();
  const h = row(value, "source scope_ref read_at requests truncated execution_authority");
  if (h.source !== "alert-noise-requests" || ref(h.scope_ref) !== scope) fail();
  noAuthority(h.execution_authority);
  const read_at = alertQualityTimestamp(h.read_at);
  const requests = list(h.requests, 25).map((value): AlertRequestRecord => {
    const r = row(value, "request_ref request_key operation accepted_at expires_at status reason result_recorded_at plan detail execution_authority");
    noAuthority(r.execution_authority);
    if (typeof r.request_key !== "string" || r.request_key.length > 256 || !/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/.test(r.request_key) || r.request_key.endsWith("\n")) fail();
    const accepted_at = alertQualityTimestamp(r.accepted_at), expires_at = alertQualityTimestamp(r.expires_at);
    const span = alertQualityTimestampMicros(expires_at) - alertQualityTimestampMicros(accepted_at);
    if (span <= 0 || span > 300_000_000n || alertQualityTimestampMicros(accepted_at) > alertQualityTimestampMicros(read_at)) fail();
    const status = choice(r.status, ["pending", "unconfirmed", "assessment_ready", "proposal_ready", "held"]);
    const recorded = timeOrNull(r.result_recorded_at);
    if ((status === "pending" || status === "unconfirmed") !== (recorded === null)) fail();
    if (recorded !== null && (alertQualityTimestampMicros(recorded) < alertQualityTimestampMicros(accepted_at) || alertQualityTimestampMicros(recorded) > alertQualityTimestampMicros(read_at))) fail();
    const plan = r.plan === null ? null : decodeAlertQualityPlan(r.plan);
    if ((status === "proposal_ready") !== (plan !== null) || (plan !== null && plan.scope_ref !== scope)) fail();
    if (r.detail !== null && plan === null) fail();
    const projection = r.detail === null || plan === null ? null : detail(r.detail, plan);
    if (projection !== null && (recorded === null || alertQualityTimestampMicros(projection.recorded_at) > alertQualityTimestampMicros(recorded))) fail();
    return { request_ref: ref(r.request_ref), request_key: r.request_key,
      operation: choice(r.operation, ["alert_noise.assess", "alert_noise.propose"]), accepted_at, expires_at, status,
      reason: r.reason === null ? null : ref(r.reason), result_recorded_at: recorded, plan, detail: projection };
  });
  if (new Set(requests.map((r) => r.request_ref)).size !== requests.length) fail();
  return { source: "alert-noise-requests", scope_ref: scope, read_at, requests, truncated: bool(h.truncated) };
}
