import {
  panelArray,
  panelBoolean,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelNonNegativeNumber,
  panelRecord,
  panelString,
  panelStringArray,
} from "./routes/panel-decode";

export type CostGovernanceSurface =
  | "overview"
  | "resource-efficiency"
  | "optimization-cases"
  | "outcomes";

export type CostGovernanceResourceEfficiencyMode =
  | "service_summary"
  | "resource_candidate";

export type CostEvidenceFreshness = "fresh" | "stale" | "unknown";
export type CostEvidenceState = "complete" | "partial" | "unavailable";
export type CostReadinessSurface =
  | "observations"
  | "analytics"
  | "resource-candidates"
  | "decision-cases"
  | "settlements";
export type CostReadinessReason =
  | "no_observations"
  | "observations_partial"
  | "observations_stale"
  | "analytics_run_missing"
  | "analytics_run_failed"
  | "analytics_run_partial"
  | "analytics_disabled"
  | "analytics_stale"
  | "disclosure_insufficient"
  | "resource_candidates_missing"
  | "candidate_evidence_incomplete"
  | "decision_cases_missing"
  | "decision_case_incomplete"
  | "settlements_missing"
  | "settlement_incomplete";

export interface CostDisclosurePolicy {
  readonly granularity: "none" | "summary" | "group" | "resource";
  readonly identity_visibility: "none" | "pseudonymous" | "exact";
  readonly amount_precision: "none" | "band" | "rounded" | "exact";
  readonly small_cell_minimum: number;
  readonly rounding_increment: number;
}

export interface CostEvidenceSourceFacet {
  readonly source_authority: string;
  readonly state: CostEvidenceState;
  readonly window_start_at: string | null;
  readonly window_end_at: string | null;
  readonly latest_source_at: string | null;
  readonly complete_count: number;
  readonly partial_count: number;
  readonly reason: string | null;
}

export interface CostSurfaceReadiness {
  readonly surface: CostReadinessSurface;
  readonly state: CostEvidenceState;
  readonly reason: CostReadinessReason | null;
  readonly record_count: number;
  readonly latest_evidence_at: string | null;
}

export interface CostAnalyticsRunReceipt {
  readonly run_id: string;
  readonly scope_digest: string;
  readonly venue: "local" | "deployed";
  readonly window_start_at: string;
  readonly window_end_at: string;
  readonly started_at: string;
  readonly finished_at: string;
  readonly status: "complete" | "partial" | "failed" | "disabled";
  readonly sources: readonly CostEvidenceSourceFacet[];
  readonly observation_count: number;
  readonly trend_point_count: number;
  readonly budget_count: number;
  readonly recommendation_count: number;
  readonly utilization_count: number;
  readonly limitations: readonly string[];
  readonly failure_reason: string | null;
  readonly snapshot_id: string | null;
}

export interface CostProjectionEvidence {
  readonly window_start_at: string | null;
  readonly window_end_at: string | null;
  readonly latest_source_at: string | null;
  readonly freshness: CostEvidenceFreshness;
  readonly freshness_threshold_seconds: number;
  readonly complete_count: number;
  readonly partial_count: number;
  readonly sources: readonly CostEvidenceSourceFacet[];
  readonly disclosure: CostDisclosurePolicy;
  readonly readiness: readonly CostSurfaceReadiness[];
  readonly latest_analytics_run: CostAnalyticsRunReceipt | null;
}

export interface CostResourceCandidate {
  readonly [key: string]: unknown;
  readonly kind: "resource_candidate";
  readonly recommendation_ref: string;
  readonly resource: string;
  readonly resource_type: string;
  readonly current_configuration: string;
  readonly proposed_configuration: string;
  readonly utilization_metric: string;
  readonly utilization_percent: number;
  readonly projected_monthly_savings: number | null;
  readonly currency: string | null;
  readonly observed_at: string;
  readonly source_authority: string;
}

export interface CostDecisionCase {
  readonly [key: string]: unknown;
  readonly kind: "decision_case";
  readonly case_ref: string;
  readonly revision: number;
  readonly target_refs: readonly string[];
  readonly evidence_cutoff: string;
  readonly decision_frame_digest: string;
  readonly option_ids: readonly string[];
  readonly selected_option_id: string | null;
  readonly verdict: "hold";
  readonly reason: string;
  readonly evidence_refs: readonly string[];
  readonly evidence_sources: readonly string[];
  readonly recovery_steps: readonly string[];
  readonly recorded_at: string;
  readonly source_authority: string;
}

export interface CostSettlementEffect {
  readonly effect_id: string;
  readonly kind: "cost" | "capacity" | "service" | "recovery";
  readonly status: "verified" | "failed" | "censored" | "unscorable";
  readonly reason: string;
  readonly terminal: boolean;
  readonly observation_digest: string | null;
  readonly completeness_digest: string | null;
}

export interface CostSettlementOutcome {
  readonly [key: string]: unknown;
  readonly kind: "settlement_outcome";
  readonly case_ref: string;
  readonly revision: number;
  readonly action_ref?: string | null;
  readonly action_revision?: number | null;
  readonly decision_frame_digest: string;
  readonly terminal: boolean;
  readonly verified_savings: number | null;
  readonly currency: string | null;
  readonly rollback_requested: boolean;
  readonly recovery_observed: boolean;
  readonly effects: readonly CostSettlementEffect[];
  readonly settled_at: string;
}

export interface CostGovernanceTrendPoint {
  readonly observed_on: string;
  readonly amount: number;
  readonly currency: string;
  readonly completeness: number;
}

export interface CostGovernanceBudget {
  readonly budget_ref: string;
  readonly amount: number;
  readonly current_spend: number;
  readonly forecast_spend: number | null;
  readonly currency: string;
  readonly time_grain: string;
}

export interface CostGovernanceRecommendation {
  readonly recommendation_ref: string;
  readonly resource_ref: string | null;
  readonly resource_type: string;
  readonly problem: string;
  readonly solution: string;
  readonly impact: "High" | "Medium" | "Low" | "Unknown";
  readonly monthly_savings: number | null;
  readonly currency: string | null;
  readonly current_sku: string | null;
  readonly target_sku: string | null;
  readonly utilization_percent: number | null;
  readonly utilization_metric: string | null;
  readonly observed_at: string;
  readonly source_authority: string;
}

export interface CostGovernanceAnalytics {
  readonly source_authority: string;
  readonly observed_at: string;
  readonly complete: boolean;
  readonly window_start_at?: string | null;
  readonly window_end_at?: string | null;
  readonly sources?: readonly CostEvidenceSourceFacet[];
  readonly trend: readonly CostGovernanceTrendPoint[];
  readonly budgets: readonly CostGovernanceBudget[];
  readonly recommendations: readonly CostGovernanceRecommendation[];
  readonly limitations: readonly string[];
}

export interface CostGovernanceProjection {
  readonly surface: CostGovernanceSurface;
  readonly complete: boolean;
  readonly source_authority: string;
  readonly items: readonly Readonly<Record<string, unknown>>[];
  readonly suppressed_count: number;
  readonly analytics?: CostGovernanceAnalytics | null;
  readonly generated_at?: string | null;
  readonly disclosure?: CostDisclosurePolicy | null;
  readonly evidence?: CostProjectionEvidence | null;
  readonly resource_efficiency_mode?: CostGovernanceResourceEfficiencyMode | null;
}

export function decodeCostGovernanceProjection(value: unknown): CostGovernanceProjection {
  const record = panelRecord(value, "cost governance projection");
  const surface = panelString(record, "surface", "cost governance projection");
  if (!["overview", "resource-efficiency", "optimization-cases", "outcomes"].includes(surface)) {
    throw new Error("Unknown Cost Governance surface");
  }
  return {
    surface: surface as CostGovernanceSurface,
    complete: panelBoolean(record, "complete", "cost governance projection"),
    source_authority: panelString(record, "source_authority", "cost governance projection"),
    items: panelArray(record["items"], "items").map((item, index) =>
      decodeProjectionItem(item, index)
    ),
    suppressed_count: panelNonNegativeInteger(
      record,
      "suppressed_count",
      "cost governance projection",
    ),
    analytics: record["analytics"] === undefined || record["analytics"] === null
      ? null
      : decodeAnalytics(record["analytics"]),
    generated_at: optionalString(record, "generated_at", "cost governance projection"),
    disclosure: record["disclosure"] === undefined || record["disclosure"] === null
      ? null
      : decodeDisclosure(record["disclosure"], "cost governance projection.disclosure"),
    evidence: record["evidence"] === undefined || record["evidence"] === null
      ? null
      : decodeEvidence(record["evidence"]),
    resource_efficiency_mode: optionalEnum(
      record,
      "resource_efficiency_mode",
      "cost governance projection",
      ["service_summary", "resource_candidate"] as const,
    ),
  };
}

function decodeAnalytics(value: unknown): CostGovernanceAnalytics {
  const record = panelRecord(value, "cost governance analytics");
  return {
    source_authority: panelString(record, "source_authority", "cost governance analytics"),
    observed_at: panelString(record, "observed_at", "cost governance analytics"),
    complete: panelBoolean(record, "complete", "cost governance analytics"),
    window_start_at: optionalString(record, "window_start_at", "cost governance analytics"),
    window_end_at: optionalString(record, "window_end_at", "cost governance analytics"),
    sources: record["sources"] === undefined
      ? []
      : panelArray(record["sources"], "analytics.sources").map((item, index) =>
        decodeSourceFacet(item, `analytics.sources[${index}]`)
      ),
    trend: panelArray(record["trend"], "trend").map((item, index) => {
      const point = panelRecord(item, `trend[${index}]`);
      return {
        observed_on: panelString(point, "observed_on", `trend[${index}]`),
        amount: decimal(point, "amount", `trend[${index}]`),
        currency: panelString(point, "currency", `trend[${index}]`),
        completeness: decimal(point, "completeness", `trend[${index}]`),
      };
    }),
    budgets: panelArray(record["budgets"], "budgets").map((item, index) => {
      const budget = panelRecord(item, `budgets[${index}]`);
      return {
        budget_ref: panelString(budget, "budget_ref", `budgets[${index}]`),
        amount: decimal(budget, "amount", `budgets[${index}]`),
        current_spend: decimal(budget, "current_spend", `budgets[${index}]`),
        forecast_spend: nullableDecimal(budget, "forecast_spend", `budgets[${index}]`),
        currency: panelString(budget, "currency", `budgets[${index}]`),
        time_grain: panelString(budget, "time_grain", `budgets[${index}]`),
      };
    }),
    recommendations: panelArray(record["recommendations"], "recommendations").map(
      (item, index) => decodeRecommendation(item, index),
    ),
    limitations: panelArray(record["limitations"], "limitations").map((item) => {
      if (typeof item !== "string") throw new Error("Invalid Cost Governance limitation");
      return item;
    }),
  };
}

function decodeProjectionItem(
  value: unknown,
  index: number,
): Readonly<Record<string, unknown>> {
  const label = `items[${index}]`;
  const record = panelRecord(value, label);
  if (record["positive_below_rounding_increment"] !== undefined) {
    panelBoolean(record, "positive_below_rounding_increment", label);
  }
  if (record["kind"] === "resource_candidate") {
    return decodeResourceCandidate(record, label);
  }
  if (record["kind"] === "decision_case") {
    return decodeDecisionCase(record, label);
  }
  if (record["kind"] === "settlement_outcome") {
    return decodeSettlementOutcome(record, label);
  }
  return record;
}

function decodeResourceCandidate(
  record: Readonly<Record<string, unknown>>,
  label: string,
): CostResourceCandidate {
  return {
    kind: "resource_candidate",
    recommendation_ref: panelNonEmptyString(record, "recommendation_ref", label),
    resource: panelNonEmptyString(record, "resource", label),
    resource_type: panelNonEmptyString(record, "resource_type", label),
    current_configuration: panelNonEmptyString(record, "current_configuration", label),
    proposed_configuration: panelNonEmptyString(record, "proposed_configuration", label),
    utilization_metric: panelNonEmptyString(record, "utilization_metric", label),
    utilization_percent: boundedDecimal(record, "utilization_percent", label, 100),
    projected_monthly_savings: nullableDecimal(
      record,
      "projected_monthly_savings",
      label,
    ),
    currency: optionalString(record, "currency", label),
    observed_at: panelNonEmptyString(record, "observed_at", label),
    source_authority: panelNonEmptyString(record, "source_authority", label),
  };
}

function decodeDecisionCase(
  record: Readonly<Record<string, unknown>>,
  label: string,
): CostDecisionCase {
  const verdict = panelString(record, "verdict", label);
  if (verdict !== "hold") throw new Error(`${label}.verdict MUST be hold`);
  const revision = panelNonNegativeInteger(record, "revision", label);
  if (revision < 1) throw new Error(`${label}.revision MUST be positive`);
  return {
    kind: "decision_case",
    case_ref: panelNonEmptyString(record, "case_ref", label),
    revision,
    target_refs: nonEmptyStringArray(record["target_refs"], `${label}.target_refs`),
    evidence_cutoff: panelNonEmptyString(record, "evidence_cutoff", label),
    decision_frame_digest: panelNonEmptyString(record, "decision_frame_digest", label),
    option_ids: nonEmptyStringArray(record["option_ids"], `${label}.option_ids`),
    selected_option_id: optionalString(record, "selected_option_id", label),
    verdict: "hold",
    reason: panelNonEmptyString(record, "reason", label),
    evidence_refs: nonEmptyStringArray(record["evidence_refs"], `${label}.evidence_refs`),
    evidence_sources: nonEmptyStringArray(
      record["evidence_sources"],
      `${label}.evidence_sources`,
    ),
    recovery_steps: record["recovery_steps"] === undefined
      ? []
      : panelStringArray(record["recovery_steps"], `${label}.recovery_steps`),
    recorded_at: panelNonEmptyString(record, "recorded_at", label),
    source_authority: panelNonEmptyString(record, "source_authority", label),
  };
}

function decodeSettlementOutcome(
  record: Readonly<Record<string, unknown>>,
  label: string,
): CostSettlementOutcome {
  const revision = panelNonNegativeInteger(record, "revision", label);
  if (revision < 1) throw new Error(`${label}.revision MUST be positive`);
  const effects = panelArray(record["effects"], `${label}.effects`).map((item, effectIndex) =>
    decodeSettlementEffect(item, `${label}.effects[${effectIndex}]`)
  );
  if (effects.length === 0) throw new Error(`${label}.effects MUST NOT be empty`);
  const actionRef = optionalString(record, "action_ref", label);
  const actionRevision = optionalPositiveInteger(record, "action_revision", label);
  if ((actionRef === null) !== (actionRevision === null)) {
    throw new Error(`${label} action_ref and action_revision MUST be reported together`);
  }
  const outcome: CostSettlementOutcome = {
    kind: "settlement_outcome",
    case_ref: panelNonEmptyString(record, "case_ref", label),
    revision,
    action_ref: actionRef,
    action_revision: actionRevision,
    decision_frame_digest: panelNonEmptyString(record, "decision_frame_digest", label),
    terminal: panelBoolean(record, "terminal", label),
    verified_savings: nullableDecimal(record, "verified_savings", label),
    currency: optionalString(record, "currency", label),
    rollback_requested: panelBoolean(record, "rollback_requested", label),
    recovery_observed: panelBoolean(record, "recovery_observed", label),
    effects,
    settled_at: panelNonEmptyString(record, "settled_at", label),
  };
  const independentlyVerified = outcome.terminal
    && !outcome.rollback_requested
    && outcome.effects.every((effect) => effect.terminal && effect.status === "verified");
  if (
    outcome.verified_savings !== null
    && (!independentlyVerified || outcome.currency === null)
  ) {
    throw new Error(
      `${label}.verified_savings requires complete independent settlement and currency`,
    );
  }
  if (outcome.currency !== null && outcome.verified_savings === null) {
    throw new Error(`${label}.currency requires verified_savings`);
  }
  return outcome;
}

function decodeSettlementEffect(value: unknown, label: string): CostSettlementEffect {
  const record = panelRecord(value, label);
  const status = requiredEnum(
    record,
    "status",
    label,
    ["verified", "failed", "censored", "unscorable"] as const,
  );
  const observationDigest = optionalString(record, "observation_digest", label);
  const completenessDigest = optionalString(record, "completeness_digest", label);
  if (
    (status === "verified" || status === "failed")
    && (observationDigest === null || completenessDigest === null)
  ) {
    throw new Error(`${label} scored settlement requires independent evidence digests`);
  }
  return {
    effect_id: panelNonEmptyString(record, "effect_id", label),
    kind: requiredEnum(
      record,
      "kind",
      label,
      ["cost", "capacity", "service", "recovery"] as const,
    ),
    status,
    reason: panelNonEmptyString(record, "reason", label),
    terminal: panelBoolean(record, "terminal", label),
    observation_digest: observationDigest,
    completeness_digest: completenessDigest,
  };
}

function decodeEvidence(value: unknown): CostProjectionEvidence {
  const label = "cost governance evidence";
  const record = panelRecord(value, label);
  const readiness = panelArray(record["readiness"], `${label}.readiness`).map(
    (item, index) => decodeReadiness(item, `${label}.readiness[${index}]`),
  );
  const expectedSurfaces: readonly CostReadinessSurface[] = [
    "observations",
    "analytics",
    "resource-candidates",
    "decision-cases",
    "settlements",
  ];
  if (
    readiness.length !== expectedSurfaces.length
    || expectedSurfaces.some(
      (surface) => readiness.filter((item) => item.surface === surface).length !== 1,
    )
  ) {
    throw new Error(`${label}.readiness MUST cover each evidence surface exactly once`);
  }
  return {
    window_start_at: optionalString(record, "window_start_at", label),
    window_end_at: optionalString(record, "window_end_at", label),
    latest_source_at: optionalString(record, "latest_source_at", label),
    freshness: requiredEnum(
      record,
      "freshness",
      label,
      ["fresh", "stale", "unknown"] as const,
    ),
    freshness_threshold_seconds: positiveInteger(
      record,
      "freshness_threshold_seconds",
      label,
    ),
    complete_count: panelNonNegativeInteger(record, "complete_count", label),
    partial_count: panelNonNegativeInteger(record, "partial_count", label),
    sources: panelArray(record["sources"], `${label}.sources`).map((item, index) =>
      decodeSourceFacet(item, `${label}.sources[${index}]`)
    ),
    disclosure: decodeDisclosure(record["disclosure"], `${label}.disclosure`),
    readiness,
    latest_analytics_run: record["latest_analytics_run"] === undefined
      || record["latest_analytics_run"] === null
      ? null
      : decodeAnalyticsRun(record["latest_analytics_run"]),
  };
}

function decodeSourceFacet(value: unknown, label: string): CostEvidenceSourceFacet {
  const record = panelRecord(value, label);
  return {
    source_authority: panelNonEmptyString(record, "source_authority", label),
    state: requiredEnum(
      record,
      "state",
      label,
      ["complete", "partial", "unavailable"] as const,
    ),
    window_start_at: optionalString(record, "window_start_at", label),
    window_end_at: optionalString(record, "window_end_at", label),
    latest_source_at: optionalString(record, "latest_source_at", label),
    complete_count: panelNonNegativeInteger(record, "complete_count", label),
    partial_count: panelNonNegativeInteger(record, "partial_count", label),
    reason: optionalString(record, "reason", label),
  };
}

function decodeReadiness(value: unknown, label: string): CostSurfaceReadiness {
  const record = panelRecord(value, label);
  return {
    surface: requiredEnum(
      record,
      "surface",
      label,
      [
        "observations",
        "analytics",
        "resource-candidates",
        "decision-cases",
        "settlements",
      ] as const,
    ),
    state: requiredEnum(
      record,
      "state",
      label,
      ["complete", "partial", "unavailable"] as const,
    ),
    reason: optionalEnum(
      record,
      "reason",
      label,
      [
        "no_observations",
        "observations_partial",
        "observations_stale",
        "analytics_run_missing",
        "analytics_run_failed",
        "analytics_run_partial",
        "analytics_disabled",
        "analytics_stale",
        "disclosure_insufficient",
        "resource_candidates_missing",
        "candidate_evidence_incomplete",
        "decision_cases_missing",
        "decision_case_incomplete",
        "settlements_missing",
        "settlement_incomplete",
      ] as const,
    ),
    record_count: panelNonNegativeInteger(record, "record_count", label),
    latest_evidence_at: optionalString(record, "latest_evidence_at", label),
  };
}

function decodeAnalyticsRun(value: unknown): CostAnalyticsRunReceipt {
  const label = "cost governance analytics run";
  const record = panelRecord(value, label);
  return {
    run_id: panelNonEmptyString(record, "run_id", label),
    scope_digest: panelNonEmptyString(record, "scope_digest", label),
    venue: requiredEnum(record, "venue", label, ["local", "deployed"] as const),
    window_start_at: panelNonEmptyString(record, "window_start_at", label),
    window_end_at: panelNonEmptyString(record, "window_end_at", label),
    started_at: panelNonEmptyString(record, "started_at", label),
    finished_at: panelNonEmptyString(record, "finished_at", label),
    status: requiredEnum(
      record,
      "status",
      label,
      ["complete", "partial", "failed", "disabled"] as const,
    ),
    sources: panelArray(record["sources"], `${label}.sources`).map((item, index) =>
      decodeSourceFacet(item, `${label}.sources[${index}]`)
    ),
    observation_count: panelNonNegativeInteger(record, "observation_count", label),
    trend_point_count: panelNonNegativeInteger(record, "trend_point_count", label),
    budget_count: panelNonNegativeInteger(record, "budget_count", label),
    recommendation_count: panelNonNegativeInteger(record, "recommendation_count", label),
    utilization_count: panelNonNegativeInteger(record, "utilization_count", label),
    limitations: panelStringArray(record["limitations"], `${label}.limitations`),
    failure_reason: optionalString(record, "failure_reason", label),
    snapshot_id: optionalString(record, "snapshot_id", label),
  };
}

function decodeDisclosure(value: unknown, label: string): CostDisclosurePolicy {
  const record = panelRecord(value, label);
  return {
    granularity: requiredEnum(
      record,
      "granularity",
      label,
      ["none", "summary", "group", "resource"] as const,
    ),
    identity_visibility: requiredEnum(
      record,
      "identity_visibility",
      label,
      ["none", "pseudonymous", "exact"] as const,
    ),
    amount_precision: requiredEnum(
      record,
      "amount_precision",
      label,
      ["none", "band", "rounded", "exact"] as const,
    ),
    small_cell_minimum: panelNonNegativeInteger(record, "small_cell_minimum", label),
    rounding_increment: decimal(record, "rounding_increment", label),
  };
}

function decodeRecommendation(value: unknown, index: number): CostGovernanceRecommendation {
  const label = `recommendations[${index}]`;
  const record = panelRecord(value, label);
  const impact = panelString(record, "impact", label);
  if (!["High", "Medium", "Low", "Unknown"].includes(impact)) {
    throw new Error("Invalid Cost Governance recommendation impact");
  }
  return {
    recommendation_ref: panelString(record, "recommendation_ref", label),
    resource_ref: nullableString(record, "resource_ref", label),
    resource_type: panelString(record, "resource_type", label),
    problem: panelString(record, "problem", label),
    solution: panelString(record, "solution", label),
    impact: impact as CostGovernanceRecommendation["impact"],
    monthly_savings: nullableDecimal(record, "monthly_savings", label),
    currency: nullableString(record, "currency", label),
    current_sku: nullableString(record, "current_sku", label),
    target_sku: nullableString(record, "target_sku", label),
    utilization_percent: nullableDecimal(record, "utilization_percent", label),
    utilization_metric: nullableString(record, "utilization_metric", label),
    observed_at: panelString(record, "observed_at", label),
    source_authority: panelString(record, "source_authority", label),
  };
}

function decimal(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): number {
  const value = record[key];
  if (typeof value === "number") return panelNonNegativeNumber(record, key, label);
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed) && parsed >= 0) return parsed;
  }
  throw new Error(`${label}.${key} MUST be a non-negative decimal`);
}

function nullableDecimal(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): number | null {
  return record[key] === null || record[key] === undefined
    ? null
    : decimal(record, key, label);
}

function nullableString(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): string | null {
  return record[key] === null || record[key] === undefined
    ? null
    : panelString(record, key, label);
}

function optionalString(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): string | null {
  return record[key] === null || record[key] === undefined
    ? null
    : panelString(record, key, label);
}

function requiredEnum<const Values extends readonly string[]>(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
  values: Values,
): Values[number] {
  const value = panelString(record, key, label);
  if (!values.includes(value)) {
    throw new Error(`${label}.${key} has an unsupported value`);
  }
  return value as Values[number];
}

function optionalEnum<const Values extends readonly string[]>(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
  values: Values,
): Values[number] | null {
  return record[key] === null || record[key] === undefined
    ? null
    : requiredEnum(record, key, label, values);
}

function positiveInteger(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): number {
  const value = panelNonNegativeInteger(record, key, label);
  if (value < 1) throw new Error(`${label}.${key} MUST be positive`);
  return value;
}

function optionalPositiveInteger(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): number | null {
  return record[key] === null || record[key] === undefined
    ? null
    : positiveInteger(record, key, label);
}

function boundedDecimal(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
  maximum: number,
): number {
  const value = decimal(record, key, label);
  if (value > maximum) throw new Error(`${label}.${key} MUST be at most ${maximum}`);
  return value;
}

function nonEmptyStringArray(value: unknown, label: string): readonly string[] {
  const items = panelStringArray(value, label);
  if (items.length === 0 || items.some((item) => item.trim().length === 0)) {
    throw new Error(`${label} MUST contain non-empty strings`);
  }
  return items;
}
