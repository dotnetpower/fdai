import {
  panelArray,
  panelBoolean,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelNumber,
  panelRecord,
  panelString,
  panelStringArray,
} from "./routes/panel-decode";

export type OutcomeAssuranceReadState = "complete" | "stale" | "unavailable";
export type OutcomeAssuranceUnavailableReason =
  | "source_not_connected"
  | "source_missing"
  | "source_stale"
  | "projection_missing"
  | "projection_malformed"
  | "principal_scope_empty"
  | "insufficient_sample";
export type OutcomeAssuranceMetricState =
  | "measured"
  | "stale"
  | "unavailable"
  | "insufficient_sample"
  | "regressed";

export interface OutcomeAssuranceSource {
  readonly name: string;
  readonly state: "complete" | "stale" | "unavailable";
  readonly reason: OutcomeAssuranceUnavailableReason | null;
  readonly observed_at: string | null;
  readonly expires_at: string | null;
  readonly evidence_refs: readonly string[];
}

export interface OutcomeAssuranceMetric {
  readonly objective_ref: string;
  readonly metric: string;
  readonly state: OutcomeAssuranceMetricState;
  readonly reason: OutcomeAssuranceUnavailableReason | null;
  readonly current_value: number | null;
  readonly baseline_value: number | null;
  readonly target_value: number | null;
  readonly unit: string | null;
  readonly sample_size: number | null;
  readonly source_time: string | null;
  readonly evidence_refs: readonly string[];
}

export interface OutcomeAssuranceReadiness {
  readonly facet: string;
  readonly state: string;
  readonly reason: OutcomeAssuranceUnavailableReason | null;
  readonly evidence_refs: readonly string[];
}

export interface OutcomeAssuranceProjection {
  readonly state: OutcomeAssuranceReadState;
  readonly reason: OutcomeAssuranceUnavailableReason | null;
  readonly scope: {
    readonly scope_ref: string;
    readonly vertical: "resilience" | "change_safety" | "cost_governance" | null;
  };
  readonly window: {
    readonly start: string;
    readonly end: string;
    readonly label: string | null;
  };
  readonly sources: readonly OutcomeAssuranceSource[];
  readonly readiness: readonly OutcomeAssuranceReadiness[];
  readonly alignment: {
    readonly state: string;
    readonly finalized_events: number;
    readonly attributed_events: number;
    readonly unattributed_events: number;
    readonly coverage: number | null;
    readonly reason: OutcomeAssuranceUnavailableReason | null;
  };
  readonly outcomes: readonly OutcomeAssuranceMetric[];
  readonly guards: {
    readonly state: string;
    readonly reason: OutcomeAssuranceUnavailableReason | null;
    readonly policy_escape_count: number;
  };
  readonly provenance: {
    readonly as_of: string;
    readonly generated_at: string;
    readonly source_names: readonly string[];
    readonly synthetic: false;
  };
  readonly principal_scoped: true;
  readonly execution_authority: false;
  readonly approval_authority: false;
  readonly promotion_authority: false;
}

const READ_STATES = new Set<OutcomeAssuranceReadState>([
  "complete",
  "stale",
  "unavailable",
]);
const REASONS = new Set<OutcomeAssuranceUnavailableReason>([
  "source_not_connected",
  "source_missing",
  "source_stale",
  "projection_missing",
  "projection_malformed",
  "principal_scope_empty",
  "insufficient_sample",
]);
const METRIC_STATES = new Set<OutcomeAssuranceMetricState>([
  "measured",
  "stale",
  "unavailable",
  "insufficient_sample",
  "regressed",
]);

export function decodeOutcomeAssuranceProjection(value: unknown): OutcomeAssuranceProjection {
  const record = panelRecord(value, "Outcome Assurance projection");
  const type = panelString(record, "type", "Outcome Assurance projection");
  if (type !== "outcome-assurance.projection") {
    throw new Error("Invalid Outcome Assurance type");
  }
  const schemaVersion = panelString(record, "schema_version", "Outcome Assurance projection");
  if (schemaVersion !== "1.0.0") throw new Error("Invalid Outcome Assurance schema_version");
  const state = enumValue(
    panelString(record, "state", "Outcome Assurance projection"),
    READ_STATES,
    "state",
  );
  return {
    state,
    reason: nullableReason(record, "reason", "Outcome Assurance projection"),
    scope: decodeScope(record["scope"]),
    window: decodeWindow(record["window"]),
    sources: panelArray(record["sources"], "sources").map(decodeSource),
    readiness: panelArray(record["readiness"], "readiness").map(decodeReadiness),
    alignment: decodeAlignment(record["alignment"]),
    outcomes: panelArray(record["outcomes"], "outcomes").map(decodeMetric),
    guards: decodeGuards(record["guards"]),
    provenance: decodeProvenance(record["provenance"]),
    principal_scoped: literal(record, "principal_scoped", true),
    execution_authority: literal(record, "execution_authority", false),
    approval_authority: literal(record, "approval_authority", false),
    promotion_authority: literal(record, "promotion_authority", false),
  };
}

function decodeScope(value: unknown): OutcomeAssuranceProjection["scope"] {
  const record = panelRecord(value, "Outcome Assurance scope");
  const vertical = record["vertical"];
  if (
    vertical !== null
    && vertical !== "resilience"
    && vertical !== "change_safety"
    && vertical !== "cost_governance"
  ) {
    throw new Error("Invalid Outcome Assurance vertical");
  }
  return {
    scope_ref: panelNonEmptyString(record, "scope_ref", "Outcome Assurance scope"),
    vertical,
  };
}

function decodeWindow(value: unknown): OutcomeAssuranceProjection["window"] {
  const record = panelRecord(value, "Outcome Assurance window");
  return {
    start: panelNonEmptyString(record, "start", "Outcome Assurance window"),
    end: panelNonEmptyString(record, "end", "Outcome Assurance window"),
    label: nullableString(record, "label", "Outcome Assurance window"),
  };
}

function decodeSource(value: unknown): OutcomeAssuranceSource {
  const record = panelRecord(value, "Outcome Assurance source");
  const state = panelString(record, "state", "Outcome Assurance source");
  if (state !== "complete" && state !== "stale" && state !== "unavailable") {
    throw new Error("Invalid Outcome Assurance source state");
  }
  return {
    name: panelNonEmptyString(record, "name", "Outcome Assurance source"),
    state,
    reason: nullableReason(record, "reason", "Outcome Assurance source"),
    observed_at: nullableString(record, "observed_at", "Outcome Assurance source"),
    expires_at: nullableString(record, "expires_at", "Outcome Assurance source"),
    evidence_refs: panelStringArray(record["evidence_refs"], "source evidence_refs"),
  };
}

function decodeReadiness(value: unknown): OutcomeAssuranceReadiness {
  const record = panelRecord(value, "Outcome Assurance readiness");
  return {
    facet: panelNonEmptyString(record, "facet", "Outcome Assurance readiness"),
    state: panelNonEmptyString(record, "state", "Outcome Assurance readiness"),
    reason: nullableReason(record, "reason", "Outcome Assurance readiness"),
    evidence_refs: panelStringArray(record["evidence_refs"], "readiness evidence_refs"),
  };
}

function decodeAlignment(value: unknown): OutcomeAssuranceProjection["alignment"] {
  const record = panelRecord(value, "Outcome Assurance alignment");
  return {
    state: panelNonEmptyString(record, "state", "Outcome Assurance alignment"),
    finalized_events: panelNonNegativeInteger(record, "finalized_events", "Outcome Assurance alignment"),
    attributed_events: panelNonNegativeInteger(record, "attributed_events", "Outcome Assurance alignment"),
    unattributed_events: panelNonNegativeInteger(
      record,
      "unattributed_events",
      "Outcome Assurance alignment",
    ),
    coverage: nullableNumber(record, "coverage", "Outcome Assurance alignment"),
    reason: nullableReason(record, "reason", "Outcome Assurance alignment"),
  };
}

function decodeMetric(value: unknown): OutcomeAssuranceMetric {
  const record = panelRecord(value, "Outcome Assurance metric");
  const state = enumValue(
    panelString(record, "state", "Outcome Assurance metric"),
    METRIC_STATES,
    "metric state",
  );
  const metric = {
    objective_ref: panelNonEmptyString(record, "objective_ref", "Outcome Assurance metric"),
    metric: panelNonEmptyString(record, "metric", "Outcome Assurance metric"),
    state,
    reason: nullableReason(record, "reason", "Outcome Assurance metric"),
    current_value: nullableNumber(record, "current_value", "Outcome Assurance metric"),
    baseline_value: nullableNumber(record, "baseline_value", "Outcome Assurance metric"),
    target_value: nullableNumber(record, "target_value", "Outcome Assurance metric"),
    unit: nullableString(record, "unit", "Outcome Assurance metric"),
    sample_size: nullableInteger(record, "sample_size", "Outcome Assurance metric"),
    source_time: nullableString(record, "source_time", "Outcome Assurance metric"),
    evidence_refs: panelStringArray(record["evidence_refs"], "metric evidence_refs"),
  };
  if (metric.state !== "measured" && metric.state !== "regressed") {
    const values = [
      metric.current_value,
      metric.baseline_value,
      metric.target_value,
      metric.unit,
      metric.sample_size,
      metric.source_time,
    ];
    if (values.some((item) => item !== null)) {
      throw new Error("Unavailable Outcome Assurance metric cannot carry values");
    }
  }
  return metric;
}

function decodeGuards(value: unknown): OutcomeAssuranceProjection["guards"] {
  const record = panelRecord(value, "Outcome Assurance guards");
  return {
    state: panelNonEmptyString(record, "state", "Outcome Assurance guards"),
    reason: nullableReason(record, "reason", "Outcome Assurance guards"),
    policy_escape_count: panelNonNegativeInteger(
      record,
      "policy_escape_count",
      "Outcome Assurance guards",
    ),
  };
}

function decodeProvenance(value: unknown): OutcomeAssuranceProjection["provenance"] {
  const record = panelRecord(value, "Outcome Assurance provenance");
  return {
    as_of: panelNonEmptyString(record, "as_of", "Outcome Assurance provenance"),
    generated_at: panelNonEmptyString(record, "generated_at", "Outcome Assurance provenance"),
    source_names: panelStringArray(record["source_names"], "provenance source_names"),
    synthetic: literal(record, "synthetic", false),
  };
}

function nullableReason(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): OutcomeAssuranceUnavailableReason | null {
  if (record[key] === null) return null;
  return enumValue(panelString(record, key, label), REASONS, key);
}

function nullableString(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): string | null {
  return record[key] === null ? null : panelNonEmptyString(record, key, label);
}

function nullableNumber(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): number | null {
  return record[key] === null ? null : panelNumber(record, key, label);
}

function nullableInteger(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): number | null {
  return record[key] === null ? null : panelNonNegativeInteger(record, key, label);
}

function literal<T extends string | boolean>(
  record: Readonly<Record<string, unknown>>,
  key: string,
  expected: T,
): T {
  if (record[key] !== expected) throw new Error(`Invalid Outcome Assurance ${key}`);
  return expected;
}

function enumValue<T extends string>(value: string, allowed: ReadonlySet<T>, label: string): T {
  if (!allowed.has(value as T)) throw new Error(`Invalid Outcome Assurance ${label}`);
  return value as T;
}
