import {
  panelArray,
  panelBoolean,
  panelNonEmptyString,
  panelNumber,
  panelRecord,
  panelString,
  panelStringArray,
} from "./routes/panel-decode";

export type AksCommerceStatus =
  | "catalog_unavailable"
  | "dead_letter_growth"
  | "dependency_pressure"
  | "deployment_regression"
  | "healthy"
  | "held"
  | "order_backlog"
  | "recovered";

export type AksCommerceEvidenceState =
  | "complete"
  | "conflicting"
  | "stale"
  | "unavailable";

export interface AksCommerceMetric {
  readonly name: string;
  readonly unit: string;
  readonly current: number | null;
  readonly previous: number | null;
  readonly source_ref: string;
  readonly observed_at: string;
  readonly state: AksCommerceEvidenceState;
  readonly synthetic: boolean;
}

export interface AksCommerceSlo {
  readonly slo_id: string;
  readonly objective_ratio: number;
  readonly observed_ratio: number | null;
  readonly budget_remaining_ratio: number | null;
  readonly breached: boolean | null;
  readonly state: AksCommerceEvidenceState;
  readonly source_ref: string;
}

export interface AksCommerceWorkload {
  readonly workload_id: string;
  readonly display_name: string;
  readonly resource_ref: string | null;
  readonly ready: boolean | null;
  readonly revision: string | null;
  readonly evidence_state: AksCommerceEvidenceState;
}

export interface AksCommerceAction {
  readonly action_type: string;
  readonly state: string;
  readonly target_ref: string;
  readonly action_run_ref: string | null;
  readonly execution_authority: false;
  readonly effect_verified: boolean | null;
  readonly effect_evidence_ref: string | null;
}

export interface AksCommerceProjection {
  readonly assessment_id: string;
  readonly service_id: "catalog-browse" | "order-fulfillment";
  readonly status: AksCommerceStatus;
  readonly summary: string;
  readonly observed_at: string;
  readonly window_start: string;
  readonly window_end: string;
  readonly complete: boolean;
  readonly synthetic: boolean;
  readonly affected_workload_ids: readonly string[];
  readonly dependency_path: readonly string[];
  readonly workloads: readonly AksCommerceWorkload[];
  readonly metrics: readonly AksCommerceMetric[];
  readonly slos: readonly AksCommerceSlo[];
  readonly evidence_gaps: readonly string[];
  readonly evidence_refs: readonly string[];
  readonly proposed_action: AksCommerceAction | null;
  readonly owner_agent: "Forseti";
  readonly observer_agent: "Heimdall";
  readonly execution_authority: false;
}

const STATUSES = new Set<AksCommerceStatus>([
  "catalog_unavailable",
  "dead_letter_growth",
  "dependency_pressure",
  "deployment_regression",
  "healthy",
  "held",
  "order_backlog",
  "recovered",
]);
const EVIDENCE_STATES = new Set<AksCommerceEvidenceState>([
  "complete",
  "conflicting",
  "stale",
  "unavailable",
]);

export function decodeAksCommerceProjection(value: unknown): AksCommerceProjection {
  const record = panelRecord(value, "AKS commerce projection");
  const status = enumValue(
    panelString(record, "status", "AKS commerce projection"),
    STATUSES,
    "status",
  );
  const serviceId = panelString(record, "service_id", "AKS commerce projection");
  if (serviceId !== "catalog-browse" && serviceId !== "order-fulfillment") {
    throw new Error("Invalid AKS commerce service_id");
  }
  return {
    assessment_id: panelNonEmptyString(record, "assessment_id", "AKS commerce projection"),
    service_id: serviceId,
    status,
    summary: panelNonEmptyString(record, "summary", "AKS commerce projection"),
    observed_at: panelNonEmptyString(record, "observed_at", "AKS commerce projection"),
    window_start: panelNonEmptyString(record, "window_start", "AKS commerce projection"),
    window_end: panelNonEmptyString(record, "window_end", "AKS commerce projection"),
    complete: panelBoolean(record, "complete", "AKS commerce projection"),
    synthetic: panelBoolean(record, "synthetic", "AKS commerce projection"),
    affected_workload_ids: panelStringArray(
      record["affected_workload_ids"],
      "affected_workload_ids",
    ),
    dependency_path: panelStringArray(record["dependency_path"], "dependency_path"),
    workloads: panelArray(record["workloads"], "workloads").map(decodeWorkload),
    metrics: panelArray(record["metrics"], "metrics").map(decodeMetric),
    slos: panelArray(record["slos"], "slos").map(decodeSlo),
    evidence_gaps: panelStringArray(record["evidence_gaps"], "evidence_gaps"),
    evidence_refs: panelStringArray(record["evidence_refs"], "evidence_refs"),
    proposed_action: record["proposed_action"] === null
      ? null
      : decodeAction(record["proposed_action"]),
    owner_agent: literal(record, "owner_agent", "Forseti"),
    observer_agent: literal(record, "observer_agent", "Heimdall"),
    execution_authority: literal(record, "execution_authority", false),
  };
}

function decodeMetric(value: unknown): AksCommerceMetric {
  const record = panelRecord(value, "AKS commerce metric");
  return {
    name: panelNonEmptyString(record, "name", "AKS commerce metric"),
    unit: panelNonEmptyString(record, "unit", "AKS commerce metric"),
    current: nullableNumber(record, "current", "AKS commerce metric"),
    previous: nullableNumber(record, "previous", "AKS commerce metric"),
    source_ref: panelNonEmptyString(record, "source_ref", "AKS commerce metric"),
    observed_at: panelNonEmptyString(record, "observed_at", "AKS commerce metric"),
    state: enumValue(
      panelString(record, "state", "AKS commerce metric"),
      EVIDENCE_STATES,
      "metric state",
    ),
    synthetic: panelBoolean(record, "synthetic", "AKS commerce metric"),
  };
}

function decodeSlo(value: unknown): AksCommerceSlo {
  const record = panelRecord(value, "AKS commerce SLO");
  return {
    slo_id: panelNonEmptyString(record, "slo_id", "AKS commerce SLO"),
    objective_ratio: panelNumber(record, "objective_ratio", "AKS commerce SLO"),
    observed_ratio: nullableNumber(record, "observed_ratio", "AKS commerce SLO"),
    budget_remaining_ratio: nullableNumber(
      record,
      "budget_remaining_ratio",
      "AKS commerce SLO",
    ),
    breached: nullableBoolean(record, "breached", "AKS commerce SLO"),
    state: enumValue(
      panelString(record, "state", "AKS commerce SLO"),
      EVIDENCE_STATES,
      "SLO state",
    ),
    source_ref: panelNonEmptyString(record, "source_ref", "AKS commerce SLO"),
  };
}

function decodeWorkload(value: unknown): AksCommerceWorkload {
  const record = panelRecord(value, "AKS commerce workload");
  return {
    workload_id: panelNonEmptyString(record, "workload_id", "AKS commerce workload"),
    display_name: panelNonEmptyString(record, "display_name", "AKS commerce workload"),
    resource_ref: nullableString(record, "resource_ref", "AKS commerce workload"),
    ready: nullableBoolean(record, "ready", "AKS commerce workload"),
    revision: nullableString(record, "revision", "AKS commerce workload"),
    evidence_state: enumValue(
      panelString(record, "evidence_state", "AKS commerce workload"),
      EVIDENCE_STATES,
      "workload state",
    ),
  };
}

function decodeAction(value: unknown): AksCommerceAction {
  const record = panelRecord(value, "AKS commerce action");
  return {
    action_type: panelNonEmptyString(record, "action_type", "AKS commerce action"),
    state: panelNonEmptyString(record, "state", "AKS commerce action"),
    target_ref: panelNonEmptyString(record, "target_ref", "AKS commerce action"),
    action_run_ref: nullableString(record, "action_run_ref", "AKS commerce action"),
    execution_authority: literal(record, "execution_authority", false),
    effect_verified: nullableBoolean(record, "effect_verified", "AKS commerce action"),
    effect_evidence_ref: nullableString(
      record,
      "effect_evidence_ref",
      "AKS commerce action",
    ),
  };
}

function nullableNumber(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): number | null {
  return record[key] === null ? null : panelNumber(record, key, label);
}

function nullableBoolean(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): boolean | null {
  return record[key] === null ? null : panelBoolean(record, key, label);
}

function nullableString(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): string | null {
  return record[key] === null ? null : panelString(record, key, label);
}

function enumValue<T extends string>(
  value: string,
  allowed: ReadonlySet<T>,
  label: string,
): T {
  if (!allowed.has(value as T)) throw new Error(`Invalid AKS commerce ${label}`);
  return value as T;
}

function literal<T extends string | boolean>(
  record: Readonly<Record<string, unknown>>,
  key: string,
  expected: T,
): T {
  if (record[key] !== expected) throw new Error(`Invalid AKS commerce ${key}`);
  return expected;
}
