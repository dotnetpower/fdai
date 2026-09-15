/** Bounded alert-noise read contracts and inert proposal inputs, never authorization. */
import { panelContractError, panelRecord } from "./panel-decode";
import { isRfc3339Timestamp } from "../time-format";

const REF = /^[a-z][a-z0-9_.:-]{0,159}$/;
const DIGEST = /^sha256:[a-f0-9]{64}$/;
const COVERAGE = ["complete", "partial", "unavailable"] as const;
const REASONS = ["storm", "flapping", "overlap", "broad_role", "unowned", "protected", "incomplete"] as const;
const GUIDANCE = ["review-routing", "review-evaluation", "review-ownership", "retain-protected", "collect-evidence"] as const;
const ACTIONS = ["ops.update-alert-routing", "ops.set-alert-notification-window", "ops.tune-alert-evaluation", "ops.restore-alert-configuration"] as const;
export const ALERT_FINDINGS_PAGE_SIZE = 50;
export const ALERT_MAX_PLANS = 32;
export const ALERT_MAX_PROJECTION_BYTES = 1_048_576;
export const ALERT_AUDIENCE_KINDS = ["direct", "group", "role", "channel", "oncall"] as const;

/** The privacy-minimized finding preserves distinct episode, delivery and potential counts. */
export interface AlertNoiseFinding {
  readonly rule_ref: string;
  readonly service_ref: string;
  readonly reason: typeof REASONS[number];
  readonly guidance: typeof GUIDANCE[number];
  readonly source_episodes: number | null;
  readonly observed_deliveries: number | null;
  readonly potential_recipients_lower: number | null;
  readonly potential_recipients_upper: number | null;
  readonly duplicate_paths: number;
  readonly protected: boolean;
  readonly team_refs?: readonly string[] | null;
  readonly audience_kinds?: readonly typeof ALERT_AUDIENCE_KINDS[number][] | null;
}

/** Exact NoiseAssessment 1.0.0 projection; validity is not an observation period. */
export interface AlertNoiseAssessment {
  readonly schema_version: "1.0.0";
  readonly source: "alert-noise-evidence";
  readonly evidence_digest: string;
  readonly policy_digest: string;
  readonly tenant_ref: string;
  readonly scope_ref: string;
  readonly observed_at: string;
  readonly valid_until: string;
  /** Retained v1 records may omit these; current serializers emit both, possibly null. */
  readonly window_start?: string | null;
  readonly window_end?: string | null;
  readonly coverage: typeof COVERAGE[number];
  readonly reasons: readonly string[];
  readonly source_episodes: number | null;
  readonly notification_attempts: number | null;
  readonly confirmed_deliveries: number | null;
  readonly acknowledgements: number | null;
  readonly findings: readonly AlertNoiseFinding[];
  readonly execution_authority: false;
}

/** Only supported finite evaluation semantics cross the read boundary. */
export interface AlertEvaluation {
  readonly metric_ref: string;
  readonly operator: "above" | "below";
  readonly threshold: number;
  readonly window_seconds: number;
  readonly frequency_seconds: number;
  readonly aggregation: "average" | "maximum" | "minimum";
}

/** One treatment axis. Omitted cross-axis fields may be serialized as null, never values. */
export type AlertQualityTreatment =
  | { readonly kind: "routing"; readonly target_ref: string; readonly remove_group_ref: string; readonly replacement_group_ref: string }
  | { readonly kind: "suppression"; readonly target_ref: string; readonly processing_rule_ref: string; readonly starts_at: string; readonly ends_at: string }
  | { readonly kind: "evaluation"; readonly target_ref: string; readonly evaluation: AlertEvaluation };

/** An immutable plan reports required quorum, not fulfilled approval or execution. */
export interface AlertQualityPlan {
  readonly schema_version: "1.0.0";
  readonly action_type: typeof ACTIONS[number];
  readonly tenant_ref: string;
  readonly scope_ref: string;
  readonly requester_ref: string;
  readonly evidence_digest: string;
  readonly policy_digest: string;
  readonly target_revision: string;
  readonly treatment: AlertQualityTreatment;
  readonly service_refs: readonly string[];
  readonly lock_refs: readonly string[];
  readonly created_at: string;
  readonly expires_at: string;
  readonly max_execution_seconds: number;
  readonly max_observation_seconds: number;
  readonly max_recovery_seconds: number;
  readonly rollback_ref: string;
  /** A reference only, not a projected replay result or approval. Absent in retained v1. */
  readonly evaluation_receipt_digest?: string | null;
  readonly execution_path: "pr_manual";
  readonly default_mode: "shadow";
  readonly quorum_required: 2;
  readonly execution_authority: false;
}

/** Runtime availability, preference, and authority remain independent axes. */
export interface AlertQualityPayload {
  readonly source: "alert-noise-governance";
  readonly available: boolean;
  readonly enabled: boolean;
  /** Optional server veto; older producers use available and enabled alone. */
  readonly requestable?: boolean;
  readonly authority: "shadow";
  readonly unavailable_reason: string | null;
  readonly assessment: AlertNoiseAssessment | null;
  readonly plans: readonly AlertQualityPlan[];
}

type RecordValue = Readonly<Record<string, unknown>>;

export { plan as decodeAlertQualityPlan, evaluation as decodeAlertQualityEvaluation };

function exact(value: unknown, keys: string): RecordValue {
  const row = panelRecord(value, "alert quality");
  const allowed = new Set(keys.split(" "));
  if (Object.keys(row).some((key) => !allowed.has(key))) fail("unexpected field");
  return row;
}

function fail(reason: string): never {
  throw panelContractError(`alert quality: ${reason}`);
}

function literal<T extends string | number | boolean>(value: unknown, expected: T): T {
  if (value !== expected) fail("canonical contract value is missing or invalid");
  return expected;
}

function member<T extends string>(value: unknown, choices: readonly T[]): T {
  if (typeof value !== "string" || !choices.includes(value as T)) fail("unsupported enum value");
  return value as T;
}

function boolean(value: unknown): boolean {
  if (typeof value !== "boolean") fail("expected a strict boolean");
  return value;
}

function boundedInteger(value: unknown, max = 10_000_000, min = 0): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < min || value > max) {
    fail("integer is missing or outside its bounds");
  }
  return value;
}

function nullableCount(value: unknown): number | null {
  return value === null ? null : boundedInteger(value);
}

function ref(value: unknown): string {
  if (!isAlertQualityRef(value)) fail("expected an exact opaque reference");
  return value;
}

function digest(value: unknown): string {
  if (typeof value !== "string" || value.length !== 71 || !DIGEST.test(value)) fail("invalid content digest");
  return value;
}

function array(value: unknown, max: number): readonly unknown[] {
  if (!Array.isArray(value) || value.length > max) fail("array is missing or exceeds its bound");
  return value;
}

function refs(value: unknown, max: number, sorted = false): readonly string[] {
  const result = array(value, max).map(ref);
  if (new Set(result).size !== result.length) fail("duplicate references");
  if (sorted && (result.length === 0 || result.some((item, index) => index > 0 && item <= result[index - 1]!))) {
    fail("references must be nonempty, sorted and unique");
  }
  return result;
}

/** Reject naive clocks, impossible dates and unknown offsets before browser date formatting. */
export function alertQualityTimestamp(value: unknown): string {
  if (!isAlertQualityTimestamp(value)) fail("invalid RFC 3339 time");
  return value;
}

/** Form validation uses the same calendar grammar without catching decoder exceptions. */
export function isAlertQualityTimestamp(value: unknown): value is string {
  if (typeof value !== "string" || value.length > 40 || !isRfc3339Timestamp(value)) return false;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$/.exec(value);
  if (!match || match[0] !== value) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  const zone = match[7]!;
  if (year < 1 || month < 1 || month > 12 || day < 1 || day > days[month - 1]!
    || Number(match[4]) > 23 || Number(match[5]) > 59 || Number(match[6]) > 59
    || zone === "-00:00" || (zone !== "Z" && (Number(zone.slice(1, 3)) > 23 || Number(zone.slice(4)) > 59))) {
    return false;
  }
  return true;
}

function interval(start: string, end: string): void {
  if (alertQualityTimestampMicros(start) >= alertQualityTimestampMicros(end)) fail("validity interval must be positive");
}

/** Compare already-validated RFC 3339 values without discarding microseconds. */
export function alertQualityTimestampMicros(value: string): bigint {
  // Date.parse truncates microseconds. Preserve the contract's final three digits for ordering.
  const fraction = /\.(\d{1,6})/.exec(value)?.[1] ?? "";
  return BigInt(Date.parse(value)) * 1_000n + BigInt(fraction.padEnd(6, "0").slice(3));
}

/** Match the service Ref without trimming, case folding or accepting a provider path. */
export function isAlertQualityRef(value: unknown): value is string {
  // JavaScript's dollar anchor also matches before a final newline; require the entire match.
  return typeof value === "string" && value.length <= 160 && REF.exec(value)?.[0] === value;
}

/** Duplicate selectors are ambiguous; an invalid scope never becomes an unscoped read. */
export function alertQualityScope(search: URLSearchParams): string | null {
  const values = search.getAll("scope_ref");
  return values.length === 1 && isAlertQualityRef(values[0]) ? values[0] : null;
}

function finding(value: unknown): AlertNoiseFinding {
  const row = exact(value, "rule_ref service_ref reason guidance source_episodes observed_deliveries potential_recipients_lower potential_recipients_upper duplicate_paths protected team_refs audience_kinds");
  const teams = Object.hasOwn(row, "team_refs") ? { team_refs: row.team_refs === null ? null : refs(row.team_refs, 32, true) } : {};
  const kinds = Object.hasOwn(row, "audience_kinds") ? { audience_kinds: row.audience_kinds === null ? null
    : array(row.audience_kinds, 5).map((kind) => member(kind, ALERT_AUDIENCE_KINDS)) } : {};
  if (kinds.audience_kinds?.some((kind, index, values) => index > 0 && kind <= values[index - 1]!)) fail("audience kinds must be sorted and unique");
  const lower = nullableCount(row.potential_recipients_lower);
  const upper = nullableCount(row.potential_recipients_upper);
  if (lower !== null && upper !== null && lower > upper) fail("recipient bounds are reversed");
  if ((row.reason === "protected" || row.guidance === "retain-protected") && row.protected !== true) {
    fail("protected finding contradicts its protection flag");
  }
  return {
    rule_ref: ref(row.rule_ref), service_ref: ref(row.service_ref),
    reason: member(row.reason, REASONS), guidance: member(row.guidance, GUIDANCE),
    source_episodes: nullableCount(row.source_episodes), observed_deliveries: nullableCount(row.observed_deliveries),
    potential_recipients_lower: lower, potential_recipients_upper: upper,
    duplicate_paths: boundedInteger(row.duplicate_paths), protected: boolean(row.protected),
    ...teams, ...kinds,
  };
}

function assessment(value: unknown): AlertNoiseAssessment {
  const row = exact(value, "schema_version source evidence_digest policy_digest tenant_ref scope_ref observed_at valid_until window_start window_end coverage reasons source_episodes notification_attempts confirmed_deliveries acknowledgements findings execution_authority");
  const observed = alertQualityTimestamp(row.observed_at);
  const until = alertQualityTimestamp(row.valid_until);
  interval(observed, until);
  // Only the two additive v1 fields may be omitted. Explicit undefined is invalid.
  const window = {
    ...(Object.hasOwn(row, "window_start") ? { window_start: row.window_start === null ? null : alertQualityTimestamp(row.window_start) } : {}),
    ...(Object.hasOwn(row, "window_end") ? { window_end: row.window_end === null ? null : alertQualityTimestamp(row.window_end) } : {}),
  };
  if ((window.window_start == null) !== (window.window_end == null)) fail("observation bounds must be supplied together");
  if (window.window_start != null && window.window_end != null) {
    interval(window.window_start, window.window_end);
    if (alertQualityTimestampMicros(window.window_end) > alertQualityTimestampMicros(observed)) {
      fail("observation window must precede the evidence cutoff");
    }
  }
  const findings = array(row.findings, 10_000).map(finding);
  const ruleServices = new Map<string, string>();
  const ruleFacets = new Map<string, string>();
  for (const item of findings) {
    const service = ruleServices.get(item.rule_ref);
    if (service !== undefined && service !== item.service_ref) fail("rule service identity is inconsistent");
    ruleServices.set(item.rule_ref, item.service_ref);
    const facets = JSON.stringify([item.team_refs ?? null, item.audience_kinds ?? null]);
    if (ruleFacets.has(item.rule_ref) && ruleFacets.get(item.rule_ref) !== facets) fail("rule facet identity is inconsistent");
    ruleFacets.set(item.rule_ref, facets);
  }
  return {
    schema_version: literal(row.schema_version, "1.0.0"), source: literal(row.source, "alert-noise-evidence"),
    evidence_digest: digest(row.evidence_digest), policy_digest: digest(row.policy_digest),
    tenant_ref: ref(row.tenant_ref), scope_ref: ref(row.scope_ref), observed_at: observed, valid_until: until,
    ...window, coverage: member(row.coverage, COVERAGE), reasons: refs(row.reasons, 32),
    source_episodes: nullableCount(row.source_episodes), notification_attempts: nullableCount(row.notification_attempts),
    confirmed_deliveries: nullableCount(row.confirmed_deliveries), acknowledgements: nullableCount(row.acknowledgements),
    findings, execution_authority: literal(row.execution_authority, false),
  };
}

function evaluation(value: unknown): AlertEvaluation {
  const row = exact(value, "metric_ref operator threshold window_seconds frequency_seconds aggregation");
  if (typeof row.threshold !== "number" || !Number.isFinite(row.threshold)) fail("threshold must be finite");
  return {
    metric_ref: ref(row.metric_ref), operator: member(row.operator, ["above", "below"]), threshold: row.threshold,
    window_seconds: boundedInteger(row.window_seconds, 86_400, 1),
    frequency_seconds: boundedInteger(row.frequency_seconds, 86_400, 1),
    aggregation: member(row.aggregation, ["average", "maximum", "minimum"]),
  };
}

/** Validate every cross-axis field individually, including incomplete field pairs. */
export function decodeAlertQualityTreatment(value: unknown): AlertQualityTreatment {
  const row = exact(value, "kind target_ref replacement_group_ref remove_group_ref processing_rule_ref starts_at ends_at evaluation");
  const kind = member(row.kind, ["routing", "suppression", "evaluation"]);
  const target_ref = ref(row.target_ref);
  const unused = kind === "routing" ? ["processing_rule_ref", "starts_at", "ends_at", "evaluation"]
    : kind === "suppression" ? ["replacement_group_ref", "remove_group_ref", "evaluation"]
    : ["replacement_group_ref", "remove_group_ref", "processing_rule_ref", "starts_at", "ends_at"];
  if (unused.some((key) => row[key] !== undefined && row[key] !== null)) fail("treatment mixes axes");
  if (kind === "routing") {
    const remove_group_ref = ref(row.remove_group_ref);
    const replacement_group_ref = ref(row.replacement_group_ref);
    if (remove_group_ref === replacement_group_ref) fail("routing replacement must differ");
    return { kind, target_ref, remove_group_ref, replacement_group_ref };
  }
  if (kind === "suppression") {
    const starts_at = alertQualityTimestamp(row.starts_at);
    const ends_at = alertQualityTimestamp(row.ends_at);
    interval(starts_at, ends_at);
    return { kind, target_ref, processing_rule_ref: ref(row.processing_rule_ref), starts_at, ends_at };
  }
  return { kind, target_ref, evaluation: evaluation(row.evaluation) };
}

function plan(value: unknown): AlertQualityPlan {
  const row = exact(value, "schema_version action_type tenant_ref scope_ref requester_ref evidence_digest policy_digest target_revision treatment service_refs lock_refs created_at expires_at max_execution_seconds max_observation_seconds max_recovery_seconds rollback_ref evaluation_receipt_digest execution_path default_mode quorum_required execution_authority");
  const treatment = decodeAlertQualityTreatment(row.treatment);
  const action_type = member(row.action_type, ACTIONS);
  const expected = { routing: ACTIONS[0], suppression: ACTIONS[1], evaluation: ACTIONS[2] } as const;
  if (action_type !== expected[treatment.kind]) fail("action and treatment disagree");
  const created_at = alertQualityTimestamp(row.created_at);
  const expires_at = alertQualityTimestamp(row.expires_at);
  interval(created_at, expires_at);
  return {
    schema_version: literal(row.schema_version, "1.0.0"), action_type,
    tenant_ref: ref(row.tenant_ref), scope_ref: ref(row.scope_ref), requester_ref: ref(row.requester_ref),
    evidence_digest: digest(row.evidence_digest), policy_digest: digest(row.policy_digest), target_revision: digest(row.target_revision),
    treatment, service_refs: refs(row.service_refs, 64, true), lock_refs: refs(row.lock_refs, 256, true), created_at, expires_at,
    max_execution_seconds: boundedInteger(row.max_execution_seconds, 86_400, 1),
    max_observation_seconds: boundedInteger(row.max_observation_seconds, 86_400, 1),
    max_recovery_seconds: boundedInteger(row.max_recovery_seconds, 86_400, 1), rollback_ref: digest(row.rollback_ref),
    ...(Object.hasOwn(row, "evaluation_receipt_digest")
      ? { evaluation_receipt_digest: row.evaluation_receipt_digest === null ? null : digest(row.evaluation_receipt_digest) } : {}),
    execution_path: literal(row.execution_path, "pr_manual"), default_mode: literal(row.default_mode, "shadow"),
    quorum_required: literal(row.quorum_required, 2), execution_authority: literal(row.execution_authority, false),
  };
}

/** Reject malformed or cross-scope projections atomically rather than dropping unsafe rows. */
export function decodeAlertQuality(value: unknown, expectedScope: string): AlertQualityPayload {
  ref(expectedScope);
  const row = exact(value, "source available enabled requestable authority unavailable_reason assessment plans");
  const available = boolean(row.available);
  const reason = row.unavailable_reason;
  if (reason !== null && (typeof reason !== "string" || !reason.trim() || reason.length > 256 || /[\x00-\x1f\x7f]/.test(reason))) fail("invalid unavailable reason");
  if (!available && reason === null) fail("unavailable runtime must explain its reason");
  const report = row.assessment === null ? null : assessment(row.assessment);
  const plans = array(row.plans, ALERT_MAX_PLANS).map(plan);
  // Producer readiness and retained evidence are independent. An expired or missing
  // report must not prevent a fresh assessment when the server is ready to produce it.
  const records = [...(report === null ? [] : [report]), ...plans];
  if (records.some((item) => item.scope_ref !== expectedScope)) fail("scope mismatch");
  if (new Set(records.map((item) => item.tenant_ref)).size > 1) fail("tenant mismatch");
  if (new TextEncoder().encode(JSON.stringify(value)).byteLength > ALERT_MAX_PROJECTION_BYTES) {
    fail("projection exceeds its byte bound");
  }
  return {
    source: literal(row.source, "alert-noise-governance"), available, enabled: boolean(row.enabled),
    ...(Object.hasOwn(row, "requestable") ? { requestable: boolean(row.requestable) } : {}),
    authority: literal(row.authority, "shadow"), unavailable_reason: reason,
    assessment: report, plans,
  };
}

/** Browser time only reduces request eligibility; the server must revalidate every request. */
export function alertQualityFreshness(start: string, end: string, now: number): "current" | "expired" | "future" | "unknown" {
  if (!Number.isSafeInteger(now) || !Number.isFinite(Date.parse(start)) || !Number.isFinite(Date.parse(end))) return "unknown";
  const instant = BigInt(now) * 1_000n;
  return instant < alertQualityTimestampMicros(start) ? "future" : instant >= alertQualityTimestampMicros(end) ? "expired" : "current";
}

/** A routing suggestion is not proof of ownership, approval, replacement coverage or safety. */
export function alertRoutingCandidates(report: AlertNoiseAssessment): readonly string[] {
  return alertTreatmentCandidates(report, "routing");
}

/** Findings narrow input choices only; unsupported native semantics remain server-held. */
export function alertTreatmentCandidates(report: AlertNoiseAssessment, kind: AlertQualityTreatment["kind"]): readonly string[] {
  const candidates = new Set<string>();
  const held = new Set<string>();
  for (const row of report.findings) {
    if (row.guidance === (kind === "evaluation" ? "review-evaluation" : "review-routing")) candidates.add(row.rule_ref);
    if (row.protected || ["protected", "incomplete", "unowned"].includes(row.reason)
      || ["retain-protected", "collect-evidence", "review-ownership"].includes(row.guidance)) held.add(row.rule_ref);
  }
  return [...candidates].filter((rule) => !held.has(rule)).sort();
}

/** No report is required to request one. This is a UI veto, not request authority. */
export function alertQualityRequestable(data: AlertQualityPayload): boolean {
  return data.available && data.enabled && data.authority === "shadow" && data.requestable !== false;
}

/** Build only a report-bound, single-axis routing proposal; no provider target is invented. */
export function buildAlertRoutingProposal(
  data: AlertQualityPayload, scope: string, rule: string, remove: string, replacement: string, now: number,
): { readonly scope_ref: string; readonly evidence_digest: string; readonly treatment: Extract<AlertQualityTreatment, { kind: "routing" }> } | null {
  const report = data.assessment;
  if (!isAlertQualityRef(scope) || !alertQualityRequestable(data)
    || report === null || report.scope_ref !== scope || report.coverage !== "complete" || report.reasons.length !== 0
    || alertQualityFreshness(report.observed_at, report.valid_until, now) !== "current"
    || !alertRoutingCandidates(report).includes(rule) || !isAlertQualityRef(remove)
    || !isAlertQualityRef(replacement) || remove === replacement) return null;
  return {
    scope_ref: scope, evidence_digest: report.evidence_digest,
    treatment: { kind: "routing", target_ref: rule, remove_group_ref: remove, replacement_group_ref: replacement },
  };
}
