import { OperatorApiError } from "../api";
import {
  panelArray,
  panelBoolean,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelNullableString,
  panelRecord,
  panelStringArray,
} from "./panel-decode";

const SCHEDULING_STATES = ["one_shot", "local_loop", "container_apps_job"] as const;
const METRIC_ACCESS_STATES = ["available", "unavailable", "unverified"] as const;
const EVENT_PUBLICATION_STATES = ["verified", "unavailable", "unverified"] as const;
const EVALUATION_STATES = [
  "evaluated_no_finding",
  "finding",
  "evaluation_error",
  "unsupported",
] as const;
const COVERAGE_PUBLICATION_STATES = [
  "published",
  "published_receipt_unrecorded",
  "duplicate_suppressed",
  "reconciled_duplicate",
  "publish_uncertain",
  "awaiting_reconciliation",
  "failed",
] as const;

type SchedulingState = typeof SCHEDULING_STATES[number];
type MetricAccessState = typeof METRIC_ACCESS_STATES[number];
type EventPublicationState = typeof EVENT_PUBLICATION_STATES[number];
export type AnalyzerEvaluationState = typeof EVALUATION_STATES[number];
export type AnalyzerCoveragePublicationState =
  typeof COVERAGE_PUBLICATION_STATES[number];

type PublicationCounts = Readonly<Record<AnalyzerCoveragePublicationState, number>>;

/** Reconciled counts for one canonical resource type in the latest attempt. */
export interface AnalyzerCoverageResourceTypeView {
  readonly resource_type: string;
  readonly candidate_count: number;
  readonly selected_count: number;
  readonly evaluated_count: number;
  readonly held_count: number;
  readonly held_reason_counts: Readonly<Record<string, number>>;
  readonly finding_count: number;
  readonly unsupported_count: number;
  readonly error_count: number;
  readonly error_codes: readonly string[];
  readonly publication_counts: PublicationCounts;
}

/** Evaluation and exact finding-delivery counts for one selected resource. */
export interface AnalyzerCoverageResourceView {
  readonly resource_ref: string;
  readonly resource_type: string;
  readonly resource_kind: string;
  readonly evaluation_state: AnalyzerEvaluationState;
  readonly finding_count: number;
  readonly unsupported_count: number;
  readonly error_count: number;
  readonly error_codes: readonly string[];
  readonly publication_counts: PublicationCounts;
}

/** Strict latest-attempt coverage, or a named section-local unavailable state. */
export type AnalyzerCoverageView =
  | {
      readonly status: "unavailable";
      readonly unavailable_reason: string;
      readonly source: string;
      readonly recorded_at: string | null;
      readonly run_attempt_id: string | null;
      readonly cause_claim_supported: false;
      readonly execution_authority: false;
    }
  | {
      readonly status: "available";
      readonly unavailable_reason: null;
      readonly source: string;
      readonly recorded_at: string;
      readonly run_attempt_id: string;
      readonly candidate_count: number;
      readonly selected_count: number;
      readonly evaluated_count: number;
      readonly held_count: number;
      readonly finding_count: number;
      readonly unsupported_count: number;
      readonly error_count: number;
      readonly unattributed_error_count: number;
      readonly unattributed_error_codes: readonly string[];
      readonly publication_counts: PublicationCounts;
      readonly resource_types: readonly AnalyzerCoverageResourceTypeView[];
      readonly resources: readonly AnalyzerCoverageResourceView[];
      readonly cause_claim_supported: false;
      readonly execution_authority: false;
    };

export interface AnalyzerRunView {
  readonly source: string;
  readonly recorded_at: string;
  readonly targets: number;
  readonly findings: number;
  readonly published: number;
  readonly duplicates_suppressed: number;
  readonly uncertain: number;
  readonly configured_targets: number;
  readonly discovered_targets: number;
  readonly candidate_count: number | null;
  readonly inventory_consulted: boolean;
  readonly source_complete: boolean;
  readonly truncated: boolean;
  readonly skipped_reasons: readonly string[];
  readonly skipped_reason_counts: Readonly<Record<string, number>> | null;
  readonly held_count: number | null;
  readonly unsupported_target_count: number;
  readonly analyzer_error_count: number;
  readonly publish_error_count: number;
  readonly receipt_error_count: number;
  readonly scheduling: SchedulingState;
  readonly metric_access: MetricAccessState;
  readonly event_publication: EventPublicationState;
}

export function decodeAnalyzerRun(value: unknown): AnalyzerRunView | null {
  if (value === undefined || value === null) return null;
  const run = panelRecord(value, "analyzer run");
  if (panelBoolean(run, "execution_authority", "analyzer run")) {
    throw invalid("analyzer run widened its read-only boundary");
  }
  const recordedAt = panelNonEmptyString(run, "recorded_at", "analyzer run");
  if (!hasTimezone(recordedAt) || Number.isNaN(Date.parse(recordedAt))) {
    throw invalid("analyzer run recorded_at is malformed");
  }
  const targets = panelNonNegativeInteger(run, "targets", "analyzer run");
  const configuredTargets = panelNonNegativeInteger(run, "configured_targets", "analyzer run");
  const discoveredTargets = panelNonNegativeInteger(run, "discovered_targets", "analyzer run");
  const candidateCount = run["candidate_count"] === null
    ? null
    : panelNonNegativeInteger(run, "candidate_count", "analyzer run");
  const skippedReasons = panelStringArray(
    run["skipped_reasons"],
    "analyzer run skipped reasons",
  );
  if (
    skippedReasons.length > 16
    || new Set(skippedReasons).size !== skippedReasons.length
    || skippedReasons.some((reason) => reason.length > 128)
  ) {
    throw invalid("analyzer run skipped reasons are malformed");
  }
  const skippedReasonCounts = decodeSkippedReasonCounts(run["skipped_reason_counts"]);
  if (
    targets !== configuredTargets + discoveredTargets
    || (candidateCount !== null && candidateCount < discoveredTargets)
    || (
      skippedReasonCounts !== null
      && !sameMembers(Object.keys(skippedReasonCounts), skippedReasons)
    )
  ) {
    throw invalid("analyzer run target totals do not reconcile");
  }
  return {
    source: panelNonEmptyString(run, "source", "analyzer run"),
    recorded_at: recordedAt,
    targets,
    findings: panelNonNegativeInteger(run, "findings", "analyzer run"),
    published: panelNonNegativeInteger(run, "published", "analyzer run"),
    duplicates_suppressed: panelNonNegativeInteger(
      run,
      "duplicates_suppressed",
      "analyzer run",
    ),
    uncertain: panelNonNegativeInteger(run, "uncertain", "analyzer run"),
    configured_targets: configuredTargets,
    discovered_targets: discoveredTargets,
    candidate_count: candidateCount,
    inventory_consulted: panelBoolean(run, "inventory_consulted", "analyzer run"),
    source_complete: panelBoolean(run, "source_complete", "analyzer run"),
    truncated: panelBoolean(run, "truncated", "analyzer run"),
    skipped_reasons: skippedReasons,
    skipped_reason_counts: skippedReasonCounts,
    held_count: skippedReasonCounts === null
      ? null
      : Object.values(skippedReasonCounts).reduce((total, count) => total + count, 0),
    unsupported_target_count: panelNonNegativeInteger(
      run,
      "unsupported_target_count",
      "analyzer run",
    ),
    analyzer_error_count: panelNonNegativeInteger(run, "analyzer_error_count", "analyzer run"),
    publish_error_count: panelNonNegativeInteger(run, "publish_error_count", "analyzer run"),
    receipt_error_count: panelNonNegativeInteger(run, "receipt_error_count", "analyzer run"),
    scheduling: member(
      panelNonEmptyString(run, "scheduling", "analyzer run"),
      SCHEDULING_STATES,
      "scheduling",
    ),
    metric_access: member(
      panelNonEmptyString(run, "metric_access", "analyzer run"),
      METRIC_ACCESS_STATES,
      "metric access",
    ),
    event_publication: member(
      panelNonEmptyString(run, "event_publication", "analyzer run"),
      EVENT_PUBLICATION_STATES,
      "event publication",
    ),
  };
}

/** Validate one no-authority cross-resource analyzer coverage projection. */
export function decodeAnalyzerCoverage(value: unknown): AnalyzerCoverageView {
  if (value === undefined || value === null) {
    return unavailableCoverage("section_absent", null, null);
  }
  const root = panelRecord(value, "analyzer coverage");
  if (
    panelBoolean(root, "cause_claim_supported", "analyzer coverage")
    || panelBoolean(root, "execution_authority", "analyzer coverage")
  ) {
    throw invalid("analyzer coverage widened its read-only boundary");
  }
  if (root["schema_version"] !== "1.1.0") {
    return unavailableCoverage("schema_unsupported", null, null);
  }
  const source = panelNonEmptyString(root, "source", "analyzer coverage");
  const recordedAt = panelNullableString(root, "recorded_at", "analyzer coverage");
  const runAttemptId = panelNullableString(
    root,
    "run_attempt_id",
    "analyzer coverage",
  );
  const status = panelNonEmptyString(root, "status", "analyzer coverage");
  const reason = panelNullableString(root, "unavailable_reason", "analyzer coverage");
  if (status === "unavailable") {
    if (reason === null) throw invalid("analyzer coverage unavailable reason is missing");
    return unavailableCoverage(reason, source, recordedAt, runAttemptId);
  }
  if (
    status !== "available"
    || reason !== null
    || recordedAt === null
    || runAttemptId === null
    || !hasTimezone(recordedAt)
    || Number.isNaN(Date.parse(recordedAt))
  ) {
    throw invalid("analyzer coverage availability is malformed");
  }

  const resourceTypes = panelArray(
    root["resource_types"],
    "analyzer coverage resource types",
  ).map((item, index) => decodeCoverageResourceType(item, index));
  const resources = panelArray(
    root["resources"],
    "analyzer coverage resources",
  ).map((item, index) => decodeCoverageResource(item, index));
  if (
    resourceTypes.length > 32
    || resources.length > 1_000
    || new Set(resourceTypes.map((item) => item.resource_type)).size
      !== resourceTypes.length
    || new Set(resources.map((item) => item.resource_ref)).size !== resources.length
  ) {
    throw invalid("analyzer coverage row identity is malformed");
  }

  const coverage: AnalyzerCoverageView = {
    status: "available",
    unavailable_reason: null,
    source,
    recorded_at: recordedAt,
    run_attempt_id: runAttemptId,
    candidate_count: panelNonNegativeInteger(
      root,
      "candidate_count",
      "analyzer coverage",
    ),
    selected_count: panelNonNegativeInteger(
      root,
      "selected_count",
      "analyzer coverage",
    ),
    evaluated_count: panelNonNegativeInteger(
      root,
      "evaluated_count",
      "analyzer coverage",
    ),
    held_count: panelNonNegativeInteger(root, "held_count", "analyzer coverage"),
    finding_count: panelNonNegativeInteger(
      root,
      "finding_count",
      "analyzer coverage",
    ),
    unsupported_count: panelNonNegativeInteger(
      root,
      "unsupported_count",
      "analyzer coverage",
    ),
    error_count: panelNonNegativeInteger(root, "error_count", "analyzer coverage"),
    unattributed_error_count: panelNonNegativeInteger(
      root,
      "unattributed_error_count",
      "analyzer coverage",
    ),
    unattributed_error_codes: boundedStringList(
      root["unattributed_error_codes"],
      "analyzer coverage unattributed error codes",
    ),
    publication_counts: decodePublicationCounts(
      root["publication_counts"],
      "analyzer coverage publication counts",
    ),
    resource_types: resourceTypes,
    resources,
    cause_claim_supported: false,
    execution_authority: false,
  };
  reconcileCoverage(coverage);
  return coverage;
}

function unavailableCoverage(
  reason: string,
  source: string | null,
  recordedAt: string | null,
  runAttemptId: string | null = null,
): AnalyzerCoverageView {
  return {
    status: "unavailable",
    unavailable_reason: reason,
    source: source ?? "postgresql:state_kv:analyzer-tick-receipt",
    recorded_at: recordedAt,
    run_attempt_id: runAttemptId,
    cause_claim_supported: false,
    execution_authority: false,
  };
}

function decodeCoverageResourceType(
  value: unknown,
  index: number,
): AnalyzerCoverageResourceTypeView {
  const label = `analyzer coverage resource types[${index}]`;
  const row = panelRecord(value, label);
  const candidateCount = panelNonNegativeInteger(row, "candidate_count", label);
  const selectedCount = panelNonNegativeInteger(row, "selected_count", label);
  const heldCount = panelNonNegativeInteger(row, "held_count", label);
  const errorCount = panelNonNegativeInteger(row, "error_count", label);
  const errorCodes = boundedStringList(row["error_codes"], `${label}.error_codes`);
  const heldReasonCounts = decodePositiveCountMapping(
    row["held_reason_counts"],
    `${label}.held_reason_counts`,
  );
  if (candidateCount !== selectedCount + heldCount) {
    throw invalid("analyzer coverage resource type totals do not reconcile");
  }
  if (sumCounts(heldReasonCounts) !== heldCount) {
    throw invalid("analyzer coverage held reason totals do not reconcile");
  }
  if ((errorCount === 0) !== (errorCodes.length === 0)) {
    throw invalid("analyzer coverage resource type error codes are inconsistent");
  }
  return {
    resource_type: boundedText(row, "resource_type", label),
    candidate_count: candidateCount,
    selected_count: selectedCount,
    evaluated_count: panelNonNegativeInteger(row, "evaluated_count", label),
    held_count: heldCount,
    held_reason_counts: heldReasonCounts,
    finding_count: panelNonNegativeInteger(row, "finding_count", label),
    unsupported_count: panelNonNegativeInteger(row, "unsupported_count", label),
    error_count: errorCount,
    error_codes: errorCodes,
    publication_counts: decodePublicationCounts(
      row["publication_counts"],
      `${label}.publication_counts`,
    ),
  };
}

function decodeCoverageResource(
  value: unknown,
  index: number,
): AnalyzerCoverageResourceView {
  const label = `analyzer coverage resources[${index}]`;
  const row = panelRecord(value, label);
  const evaluationState = member(
    panelNonEmptyString(row, "evaluation_state", label),
    EVALUATION_STATES,
    "coverage evaluation state",
  );
  const findingCount = panelNonNegativeInteger(row, "finding_count", label);
  const unsupportedCount = panelNonNegativeInteger(row, "unsupported_count", label);
  const errorCount = panelNonNegativeInteger(row, "error_count", label);
  const errorCodes = boundedStringList(row["error_codes"], `${label}.error_codes`);
  const publicationCounts = decodePublicationCounts(
    row["publication_counts"],
    `${label}.publication_counts`,
  );
  if (
    sumCounts(publicationCounts) !== findingCount
    || (evaluationState === "evaluated_no_finding"
      && (findingCount !== 0 || errorCount !== 0 || unsupportedCount !== 0))
    || (evaluationState === "finding" && findingCount === 0)
    || (evaluationState === "evaluation_error" && errorCount === 0)
    || (evaluationState === "unsupported" && unsupportedCount === 0)
    || ((errorCount === 0) !== (errorCodes.length === 0))
  ) {
    throw invalid("analyzer coverage resource state is inconsistent");
  }
  return {
    resource_ref: boundedText(row, "resource_ref", label, 512),
    resource_type: boundedText(row, "resource_type", label),
    resource_kind: boundedText(row, "resource_kind", label),
    evaluation_state: evaluationState,
    finding_count: findingCount,
    unsupported_count: unsupportedCount,
    error_count: errorCount,
    error_codes: errorCodes,
    publication_counts: publicationCounts,
  };
}

function decodePublicationCounts(value: unknown, label: string): PublicationCounts {
  const root = panelRecord(value, label);
  if (
    Object.keys(root).length !== COVERAGE_PUBLICATION_STATES.length
    || COVERAGE_PUBLICATION_STATES.some((state) => !(state in root))
  ) {
    throw invalid("analyzer coverage publication count keys are malformed");
  }
  return Object.fromEntries(
    COVERAGE_PUBLICATION_STATES.map((state) => [
      state,
      panelNonNegativeInteger(root, state, label),
    ]),
  ) as Record<AnalyzerCoveragePublicationState, number>;
}

function reconcileCoverage(
  coverage: Extract<AnalyzerCoverageView, { readonly status: "available" }>,
): void {
  const byType = new Map(
    coverage.resource_types.map((row) => [row.resource_type, row]),
  );
  const resourcesByType = new Map<string, AnalyzerCoverageResourceView[]>();
  for (const resource of coverage.resources) {
    if (!byType.has(resource.resource_type)) {
      throw invalid("analyzer coverage resource type row is missing");
    }
    resourcesByType.set(
      resource.resource_type,
      [...(resourcesByType.get(resource.resource_type) ?? []), resource],
    );
  }
  for (const row of coverage.resource_types) {
    const resources = resourcesByType.get(row.resource_type) ?? [];
    const evaluated = resources.filter((resource) =>
      ["evaluated_no_finding", "finding"].includes(resource.evaluation_state)
    ).length;
    if (
      row.selected_count !== resources.length
      || row.evaluated_count !== evaluated
      || row.finding_count !== resources.reduce(
        (total, resource) => total + resource.finding_count,
        0,
      )
      || row.unsupported_count !== resources.reduce(
        (total, resource) => total + resource.unsupported_count,
        0,
      )
      || row.error_count !== resources.reduce(
        (total, resource) => total + resource.error_count,
        0,
      )
      || !sameMembers(
        row.error_codes,
        [...new Set(resources.flatMap((resource) => resource.error_codes))],
      )
      || COVERAGE_PUBLICATION_STATES.some((state) =>
        row.publication_counts[state] !== resources.reduce(
          (total, resource) => total + resource.publication_counts[state],
          0,
        )
      )
    ) {
      throw invalid("analyzer coverage resource type totals do not reconcile");
    }
  }
  const sumTypes = (key: keyof AnalyzerCoverageResourceTypeView) =>
    coverage.resource_types.reduce((total, row) => {
      const value = row[key];
      return total + (typeof value === "number" ? value : 0);
    }, 0);
  if (
    coverage.candidate_count !== coverage.selected_count + coverage.held_count
    || coverage.candidate_count !== sumTypes("candidate_count")
    || coverage.selected_count !== coverage.resources.length
    || coverage.selected_count !== sumTypes("selected_count")
    || coverage.evaluated_count !== sumTypes("evaluated_count")
    || coverage.held_count !== sumTypes("held_count")
    || coverage.finding_count !== sumTypes("finding_count")
    || coverage.unsupported_count !== sumTypes("unsupported_count")
    || coverage.error_count !== (
      sumTypes("error_count") + coverage.unattributed_error_count
    )
    || ((coverage.unattributed_error_count === 0)
      !== (coverage.unattributed_error_codes.length === 0))
    || COVERAGE_PUBLICATION_STATES.some((state) =>
      coverage.publication_counts[state] !== coverage.resource_types.reduce(
        (total, row) => total + row.publication_counts[state],
        0,
      )
    )
  ) {
    throw invalid("analyzer coverage global totals do not reconcile");
  }
}

function boundedText(
  row: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
  maximum = 128,
): string {
  const value = panelNonEmptyString(row, key, label);
  if (value.length > maximum) throw invalid(`${label}.${key} is too long`);
  return value;
}

function boundedStringList(value: unknown, label: string): readonly string[] {
  const values = panelStringArray(value, label);
  if (
    values.length > 8
    || new Set(values).size !== values.length
    || values.some((item) => item.length > 128)
  ) {
    throw invalid(`${label} is malformed`);
  }
  return [...values].sort();
}

function decodePositiveCountMapping(
  value: unknown,
  label: string,
): Readonly<Record<string, number>> {
  const root = panelRecord(value, label);
  if (Object.keys(root).length > 16) throw invalid(`${label} is malformed`);
  return Object.fromEntries(Object.keys(root).sort().map((key) => {
    if (!key || key.length > 128) throw invalid(`${label} is malformed`);
    const count = panelNonNegativeInteger(root, key, label);
    if (count === 0) throw invalid(`${label} is malformed`);
    return [key, count];
  }));
}

function sumCounts(counts: Readonly<Record<string, number>>): number {
  return Object.values(counts).reduce((total, count) => total + count, 0);
}

function decodeSkippedReasonCounts(
  value: unknown,
): Readonly<Record<string, number>> | null {
  if (value === null) return null;
  const counts = panelRecord(value, "analyzer run skipped reason counts");
  const entries = Object.keys(counts);
  if (entries.length > 16 || entries.some((reason) => !reason || reason.length > 128)) {
    throw invalid("analyzer run skipped reason counts are malformed");
  }
  return Object.fromEntries(entries.map((reason) => [
    reason,
    panelNonNegativeInteger(counts, reason, "analyzer run skipped reason counts"),
  ]));
}

function sameMembers(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((value) => right.includes(value));
}

function hasTimezone(value: string): boolean {
  return /(?:Z|[+-]\d{2}:\d{2})$/i.test(value);
}

function member<T extends string>(
  value: string,
  values: readonly T[],
  label: string,
): T {
  if (!values.includes(value as T)) {
    throw invalid(`analyzer run ${label} is unsupported`);
  }
  return value as T;
}

function invalid(message: string): OperatorApiError {
  return new OperatorApiError(502, `invalid Operator API response: ${message}`);
}
