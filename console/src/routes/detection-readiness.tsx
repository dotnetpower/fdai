import { useEffect, useState } from "preact/hooks";

import { isOptionalOperatorApiUnavailable, OperatorApiError, type OperatorApiClient } from "../api";
import {
  AsyncBoundary,
  DataTable,
  EmptyState,
  KpiCard,
  KpiGrid,
  PageHeader,
  StatusPill,
  UnavailableState,
  type AsyncState,
  type Column,
  type PillKind,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import {
  pushRouteState,
  replaceRouteState,
  routeHref,
  ROUTE_STATE_EVENT,
} from "../router";
import { formatConsoleTimestamp } from "../time-format";
import {
  CoverageOverview,
  CoverageResources,
} from "./detection-coverage-view";
import {
  coverageResourceHref,
  filterCoverageResources,
  parseCoverageResourceControls,
  type CoverageResourceControls,
} from "./detection-coverage-state";
import {
  decodeAnalyzerCoverage,
  decodeAnalyzerRun,
  type AnalyzerCoverageResourceView,
  type AnalyzerCoverageView,
  type AnalyzerRunView,
} from "./detection-readiness.analyzer-run";
import { t } from "./i18n/detection-readiness";
import {
  panelArray,
  panelBoolean,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelNonNegativeNumber,
  panelNullableString,
  panelRecord,
  panelStringArray,
} from "./panel-decode";

const DECISIONS = ["ready", "partial", "blocked", "stale", "unauthorized", "unknown"] as const;
const DIMENSIONS = [
  "discovered",
  "collector_configured",
  "telemetry_observed",
  "detector_bound",
  "pipeline_observed",
  "action_governed",
] as const;
const CEILINGS = ["disabled", "deterministic_fallback", "shadow", "human_approval", "deployment"] as const;
const EVIDENCE_STATES = ["complete", "incomplete", "conflicting", "missed"] as const;
const CURRENT_STATES = ["recovered", "failing", "unknown"] as const;
const RECOVERY_STATES = ["verified", "not_verified", "unknown"] as const;
const LIFECYCLE_SIGNALS = [
  "container_restart",
  "pod_replacement",
  "rollout_replacement",
  "insufficient_evidence",
  "conflicting_evidence",
] as const;
const RECOVERY_STATUSES = [
  "restart_observed_recovered",
  "restart_observed_not_recovered",
  "insufficient_evidence",
  "conflicting_evidence",
] as const;
const EVIDENCE_GAPS = [
  "missing_evidence",
  "stale_evidence",
  "incomplete_evidence",
  "conflicting_evidence",
  "unassessed_finding",
  "delivery_uncertain",
  "delivery_failed",
] as const;
const PUBLICATION_STATES = [
  "published",
  "published_receipt_unrecorded",
  "duplicate_suppressed",
  "reconciled_duplicate",
  "publish_uncertain",
  "awaiting_reconciliation",
  "failed",
] as const;
const ANALYZER_RECOVERY_STATES = ["verified", "open", "unknown"] as const;
const COVERAGE_VIEWS = ["coverage", "resources", "findings"] as const;

type Decision = typeof DECISIONS[number];
type Dimension = typeof DIMENSIONS[number];
type AuthorityCeiling = typeof CEILINGS[number];
type EvidenceState = typeof EVIDENCE_STATES[number];
type CurrentState = typeof CURRENT_STATES[number];
type PodRecoveryState = typeof RECOVERY_STATES[number];
type LifecycleSignal = typeof LIFECYCLE_SIGNALS[number];
type RecoveryStatus = typeof RECOVERY_STATUSES[number];
type EvidenceGap = typeof EVIDENCE_GAPS[number];
type PublicationState = typeof PUBLICATION_STATES[number];
type AnalyzerRecoveryState = typeof ANALYZER_RECOVERY_STATES[number];
type DetectionCoverageViewId = typeof COVERAGE_VIEWS[number];

interface DetectionObservationView {
  readonly dimension: Dimension;
  readonly status: string;
}

interface DetectionTargetView {
  readonly resource_ref: string;
  readonly generated_at: string;
  readonly decision: Decision;
  readonly authority_ceiling: AuthorityCeiling;
  readonly observations: readonly DetectionObservationView[];
  readonly missing_dimensions: readonly Dimension[];
  readonly stale_dimensions: readonly Dimension[];
}

interface LifecycleFailureView {
  readonly idempotency_key: string;
  readonly signal: LifecycleSignal;
  readonly occurred_at: string;
  readonly recorded_at: string;
  readonly detection_latency_seconds: number;
  readonly evidence_complete: boolean;
  readonly recovery_closed: boolean | null;
  readonly recovery_status: RecoveryStatus | null;
  readonly publication: PublicationState;
  readonly evidence_refs: readonly string[];
  readonly evidence_gaps: readonly string[];
}

interface LifecycleTargetView {
  readonly resource_ref: string;
  readonly generated_at: string;
  readonly stale: boolean;
  readonly projection_age_seconds: number;
  readonly current_state: CurrentState;
  readonly current_signal: LifecycleSignal | null;
  readonly current_state_observed_at: string | null;
  readonly recovery_state: PodRecoveryState;
  readonly recovery_verified_at: string | null;
  readonly failure_count: number;
  readonly failures: readonly LifecycleFailureView[];
  readonly retained_record_count: number;
  readonly evidence_gaps: readonly EvidenceGap[];
  readonly evidence_gap_details: readonly string[];
  readonly delivery_counts: Readonly<Record<PublicationState, number>>;
}

interface LifecycleView {
  readonly status: "available" | "unavailable";
  readonly unavailable_reason: string | null;
  readonly target_count: number;
  readonly failure_total: number;
  readonly gap_target_count: number;
  readonly counts: Readonly<Record<CurrentState, number>>;
  readonly recovery_counts: Readonly<Record<PodRecoveryState, number>>;
  readonly targets: readonly LifecycleTargetView[];
}

interface DetectionReadinessView {
  readonly source: string;
  readonly observed_at: string | null;
  readonly target_count: number;
  readonly counts: Readonly<Record<Decision, number>>;
  readonly targets: readonly DetectionTargetView[];
  readonly analyzer_coverage: AnalyzerCoverageView;
  readonly analyzer_run: AnalyzerRunView | null;
  readonly lifecycle: DetectionLifecycleView;
  readonly pod_lifecycle: LifecycleView;
}

interface DetectionLifecycleAssessment {
  readonly idempotency_key: string;
  readonly resource_ref: string;
  readonly resource_kind: string;
  readonly signal: string;
  readonly occurred_at: string;
  readonly recorded_at: string;
  readonly current_state: string;
  readonly detection_latency_seconds: number;
  readonly evidence_complete: boolean;
  readonly evidence_state: EvidenceState;
  readonly publication: {
    readonly current: PublicationState;
    readonly attempts: readonly PublicationState[];
    readonly duplicate_observed: boolean;
  };
  readonly recovery_state: AnalyzerRecoveryState;
  readonly evidence_refs: readonly string[];
  readonly cause_claim_supported: false;
  readonly execution_authority: false;
}

interface DetectionLifecycleTarget {
  readonly resource_ref: string;
  readonly current: DetectionLifecycleAssessment;
  readonly history: readonly DetectionLifecycleAssessment[];
}

interface DetectionLifecycleView {
  readonly source: string;
  readonly observed_at: string | null;
  readonly retained_from: string | null;
  readonly receipt_count: number;
  readonly receipt_limit: number;
  readonly target_count: number;
  readonly assessment_count: number;
  readonly evidence_counts: Readonly<Record<EvidenceState, number>>;
  readonly targets: readonly DetectionLifecycleTarget[];
}

export function DetectionReadinessRoute({ client }: { readonly client: OperatorApiClient }) {
  const [state, setState] = useState<AsyncState<DetectionReadinessView>>({ status: "loading" });
  useEffect(() => {
    let active = true;
    void loadDetectionReadinessState(client).then((nextState) => {
      if (active) setState(nextState);
    });
    return () => { active = false; };
  }, [client]);

  return (
    <div class="stack detection-readiness-route">
      <PageHeader title={t("title")} subtitle={t("subtitle")} />
      <AsyncBoundary state={state} resourceLabel={t("resourceLabel")}>
        {(data) => <DetectionReadinessBody data={data} />}
      </AsyncBoundary>
    </div>
  );
}

export async function loadDetectionReadinessState(
  client: OperatorApiClient,
): Promise<AsyncState<DetectionReadinessView>> {
  try {
    const value = await client.panel<unknown>("/detection-coverage");
    return { status: "ready", data: decodeDetectionReadiness(value) };
  } catch (error) {
    return isOptionalOperatorApiUnavailable(error)
      ? { status: "unavailable", message: t("unavailable") }
      : { status: "error", message: error instanceof Error ? error.message : String(error) };
  }
}

export function decodeDetectionReadiness(value: unknown): DetectionReadinessView {
  const root = panelRecord(value, "detection readiness");
  const countsRoot = panelRecord(root["counts"], "detection readiness counts");
  const counts = Object.fromEntries(
    DECISIONS.map((decision) => [
      decision,
      panelNonNegativeInteger(countsRoot, decision, "detection readiness counts"),
    ]),
  ) as Record<Decision, number>;
  const targets = panelArray(root["targets"], "detection readiness targets").map(
    (item, index) => decodeTarget(item, index),
  );
  const targetCount = panelNonNegativeInteger(root, "target_count", "detection readiness");
  if (targets.length !== targetCount || Object.values(counts).reduce((sum, count) => sum + count, 0) !== targetCount) {
    throw new OperatorApiError(502, "invalid Operator API response: detection readiness totals do not reconcile");
  }
  return {
    source: panelNonEmptyString(root, "source", "detection readiness"),
    observed_at: panelNullableString(root, "observed_at", "detection readiness"),
    target_count: targetCount,
    counts,
    targets,
    analyzer_coverage: decodeAnalyzerCoverage(root["analyzer_coverage"]),
    analyzer_run: decodeAnalyzerRun(root["analyzer_run"]),
    lifecycle: decodeAnalyzerLifecycle(root["lifecycle"]),
    pod_lifecycle: decodeLifecycle(root["pod_lifecycle"]),
  };
}

function decodeAnalyzerLifecycle(value: unknown): DetectionLifecycleView {
  const root = panelRecord(value, "detection lifecycle");
  const countsRoot = panelRecord(root["evidence_counts"], "detection lifecycle evidence counts");
  const evidenceCounts = Object.fromEntries(
    EVIDENCE_STATES.map((state) => [
      state,
      panelNonNegativeInteger(countsRoot, state, "detection lifecycle evidence counts"),
    ]),
  ) as Record<EvidenceState, number>;
  const targets = panelArray(root["targets"], "detection lifecycle targets").map((item, index) => {
    const target = panelRecord(item, `detection lifecycle targets[${index}]`);
    const resourceRef = panelNonEmptyString(target, "resource_ref", "detection lifecycle target");
    const current = decodeAssessment(target["current"], `detection lifecycle targets[${index}].current`);
    const history = panelArray(target["history"], "detection lifecycle history").map(
      (assessment, historyIndex) =>
        decodeAssessment(assessment, `detection lifecycle targets[${index}].history[${historyIndex}]`),
    );
    if ([current, ...history].some((assessment) => assessment.resource_ref !== resourceRef)) {
      throw new OperatorApiError(502, "invalid Operator API response: detection lifecycle target identity mismatch");
    }
    return { resource_ref: resourceRef, current, history };
  });
  const targetCount = panelNonNegativeInteger(root, "target_count", "detection lifecycle");
  const assessmentCount = panelNonNegativeInteger(root, "assessment_count", "detection lifecycle");
  const receiptCount = panelNonNegativeInteger(root, "receipt_count", "detection lifecycle");
  const receiptLimit = panelNonNegativeInteger(root, "receipt_limit", "detection lifecycle");
  const renderedAssessmentCount = targets.reduce((count, target) => count + 1 + target.history.length, 0);
  if (
    targets.length !== targetCount
    || renderedAssessmentCount !== assessmentCount
    || Object.values(evidenceCounts).reduce((sum, count) => sum + count, 0) !== assessmentCount
    || receiptCount < assessmentCount
    || receiptCount > receiptLimit
  ) {
    throw new OperatorApiError(502, "invalid Operator API response: detection lifecycle totals do not reconcile");
  }
  return {
    source: panelNonEmptyString(root, "source", "detection lifecycle"),
    observed_at: panelNullableString(root, "observed_at", "detection lifecycle"),
    retained_from: panelNullableString(
      root,
      "retained_from",
      "detection lifecycle",
    ),
    receipt_count: receiptCount,
    receipt_limit: receiptLimit,
    target_count: targetCount,
    assessment_count: assessmentCount,
    evidence_counts: evidenceCounts,
    targets,
  };
}

function decodeAssessment(value: unknown, label: string): DetectionLifecycleAssessment {
  const row = panelRecord(value, label);
  const publication = panelRecord(row["publication"], `${label}.publication`);
  const attempts = panelStringArray(publication["attempts"], `${label}.publication.attempts`).map(
    (item) => member(item, PUBLICATION_STATES, "publication state"),
  );
  const currentPublication = member(
    panelNonEmptyString(publication, "current", `${label}.publication`),
    PUBLICATION_STATES,
    "publication state",
  );
  const duplicateObserved = panelBoolean(publication, "duplicate_observed", `${label}.publication`);
  if (
    attempts.length === 0
    || new Set(attempts).size !== attempts.length
    || attempts.at(-1) !== currentPublication
    || duplicateObserved !== (
      attempts.includes("duplicate_suppressed") || attempts.includes("reconciled_duplicate")
    )
  ) {
    throw new OperatorApiError(502, "invalid Operator API response: detection lifecycle publication history is inconsistent");
  }
  const causeClaimSupported = panelBoolean(row, "cause_claim_supported", label);
  const executionAuthority = panelBoolean(row, "execution_authority", label);
  if (causeClaimSupported || executionAuthority) {
    throw new OperatorApiError(502, "invalid Operator API response: detection lifecycle widened its read-only boundary");
  }
  return {
    idempotency_key: panelNonEmptyString(row, "idempotency_key", label),
    resource_ref: panelNonEmptyString(row, "resource_ref", label),
    resource_kind: panelNonEmptyString(row, "resource_kind", label),
    signal: panelNonEmptyString(row, "signal", label),
    occurred_at: panelNonEmptyString(row, "occurred_at", label),
    recorded_at: panelNonEmptyString(row, "recorded_at", label),
    current_state: panelNonEmptyString(row, "current_state", label),
    detection_latency_seconds: panelNonNegativeNumber(row, "detection_latency_seconds", label),
    evidence_complete: panelBoolean(row, "evidence_complete", label),
    evidence_state: member(
      panelNonEmptyString(row, "evidence_state", label),
      EVIDENCE_STATES,
      "evidence state",
    ),
    publication: {
      current: currentPublication,
      attempts,
      duplicate_observed: duplicateObserved,
    },
    recovery_state: member(
      panelNonEmptyString(row, "recovery_state", label),
      ANALYZER_RECOVERY_STATES,
      "recovery state",
    ),
    evidence_refs: panelStringArray(row["evidence_refs"], `${label}.evidence_refs`),
    cause_claim_supported: false,
    execution_authority: false,
  };
}

export function decodeLifecycle(value: unknown): LifecycleView {
  if (value === undefined || value === null) {
    return unavailableLifecycle("section_absent");
  }
  const root = panelRecord(value, "pod lifecycle detection");
  const status = panelNonEmptyString(root, "status", "pod lifecycle detection");
  if (panelBoolean(root, "cause_claim_supported", "pod lifecycle detection")) {
    throw new OperatorApiError(502, "invalid Operator API response: pod lifecycle projection claims a cause");
  }
  if (panelBoolean(root, "execution_authority", "pod lifecycle detection")) {
    throw new OperatorApiError(502, "invalid Operator API response: pod lifecycle projection claims authority");
  }
  const reason = panelNullableString(root, "unavailable_reason", "pod lifecycle detection");
  if (status === "unavailable") {
    return unavailableLifecycle(reason ?? "unavailable");
  }
  if (status !== "available") {
    throw new OperatorApiError(502, "invalid Operator API response: unknown pod lifecycle status");
  }
  const targets = panelArray(root["targets"], "pod lifecycle targets").map(
    (item, index) => decodeLifecycleTarget(item, index),
  );
  const targetCount = panelNonNegativeInteger(root, "target_count", "pod lifecycle detection");
  const counts = countsOf(root["counts"], CURRENT_STATES, "pod lifecycle counts");
  const recoveryCounts = countsOf(root["recovery_counts"], RECOVERY_STATES, "pod lifecycle recovery counts");
  const failureTotal = panelNonNegativeInteger(root, "failure_total", "pod lifecycle detection");
  const observedFailures = targets.reduce((sum, target) => sum + target.failure_count, 0);
  if (
    targets.length !== targetCount ||
    sum(counts) !== targetCount ||
    sum(recoveryCounts) !== targetCount ||
    observedFailures !== failureTotal
  ) {
    throw new OperatorApiError(502, "invalid Operator API response: pod lifecycle totals do not reconcile");
  }
  return {
    status: "available",
    unavailable_reason: reason,
    target_count: targetCount,
    failure_total: failureTotal,
    gap_target_count: panelNonNegativeInteger(root, "gap_target_count", "pod lifecycle detection"),
    counts,
    recovery_counts: recoveryCounts,
    targets,
  };
}

function unavailableLifecycle(reason: string): LifecycleView {
  return {
    status: "unavailable",
    unavailable_reason: reason,
    target_count: 0,
    failure_total: 0,
    gap_target_count: 0,
    counts: { recovered: 0, failing: 0, unknown: 0 },
    recovery_counts: { verified: 0, not_verified: 0, unknown: 0 },
    targets: [],
  };
}

function decodeLifecycleTarget(value: unknown, index: number): LifecycleTargetView {
  const row = panelRecord(value, `pod lifecycle targets[${index}]`);
  const currentState = member(
    panelNonEmptyString(row, "current_state", "pod lifecycle target"),
    CURRENT_STATES,
    "current state",
  );
  const recoveryState = member(
    panelNonEmptyString(row, "recovery_state", "pod lifecycle target"),
    RECOVERY_STATES,
    "recovery state",
  );
  const recoveryVerifiedAt = panelNullableString(row, "recovery_verified_at", "pod lifecycle target");
  if ((recoveryState === "verified") !== (recoveryVerifiedAt !== null)) {
    throw new OperatorApiError(502, "invalid Operator API response: pod lifecycle recovery time does not match its state");
  }
  if (currentState === "recovered" && recoveryState !== "verified") {
    throw new OperatorApiError(502, "invalid Operator API response: pod lifecycle recovery is not independently verified");
  }
  const currentSignal = panelNullableString(row, "current_signal", "pod lifecycle target");
  const failures = panelArray(row["failures"], "pod lifecycle failures").map(
    (item, position) => decodeLifecycleFailure(item, position),
  );
  const failureCount = panelNonNegativeInteger(row, "failure_count", "pod lifecycle target");
  const retained = panelNonNegativeInteger(row, "retained_record_count", "pod lifecycle target");
  if (failures.length !== failureCount || retained < failureCount) {
    throw new OperatorApiError(502, "invalid Operator API response: pod lifecycle failure history does not reconcile");
  }
  const gaps = panelStringArray(row["evidence_gaps"], "pod lifecycle gaps").map(
    (gap) => member(gap, EVIDENCE_GAPS, "evidence gap"),
  );
  if (new Set(gaps).size !== gaps.length) {
    throw new OperatorApiError(502, "invalid Operator API response: duplicate pod lifecycle evidence gap");
  }
  const stale = panelBoolean(row, "stale", "pod lifecycle target");
  if (stale && !gaps.includes("stale_evidence")) {
    throw new OperatorApiError(502, "invalid Operator API response: stale pod lifecycle target reports no gap");
  }
  if (stale && (currentState !== "unknown" || recoveryState !== "unknown")) {
    throw new OperatorApiError(502, "invalid Operator API response: stale pod lifecycle target still reports a state");
  }
  return {
    resource_ref: panelNonEmptyString(row, "resource_ref", "pod lifecycle target"),
    generated_at: panelNonEmptyString(row, "generated_at", "pod lifecycle target"),
    stale,
    projection_age_seconds: panelNonNegativeNumber(row, "projection_age_seconds", "pod lifecycle target"),
    current_state: currentState,
    current_signal: currentSignal === null ? null : member(currentSignal, LIFECYCLE_SIGNALS, "signal"),
    current_state_observed_at: panelNullableString(row, "current_state_observed_at", "pod lifecycle target"),
    recovery_state: recoveryState,
    recovery_verified_at: recoveryVerifiedAt,
    failure_count: failureCount,
    failures,
    retained_record_count: retained,
    evidence_gaps: gaps,
    evidence_gap_details: panelStringArray(row["evidence_gap_details"], "pod lifecycle gap details"),
    delivery_counts: countsOf(row["delivery_counts"], PUBLICATION_STATES, "pod lifecycle delivery counts"),
  };
}

function decodeLifecycleFailure(value: unknown, index: number): LifecycleFailureView {
  const row = panelRecord(value, `pod lifecycle failures[${index}]`);
  const evidenceComplete = panelBoolean(row, "evidence_complete", "pod lifecycle failure");
  const recoveryClosedValue = row["recovery_closed"];
  if (recoveryClosedValue !== null && typeof recoveryClosedValue !== "boolean") {
    throw new OperatorApiError(502, "invalid Operator API response: pod lifecycle recovery closure is malformed");
  }
  if (recoveryClosedValue === true && !evidenceComplete) {
    throw new OperatorApiError(502, "invalid Operator API response: pod lifecycle closes recovery on incomplete evidence");
  }
  const recoveryStatus = panelNullableString(row, "recovery_status", "pod lifecycle failure");
  return {
    idempotency_key: panelNonEmptyString(row, "idempotency_key", "pod lifecycle failure"),
    signal: member(panelNonEmptyString(row, "signal", "pod lifecycle failure"), LIFECYCLE_SIGNALS, "signal"),
    occurred_at: panelNonEmptyString(row, "occurred_at", "pod lifecycle failure"),
    recorded_at: panelNonEmptyString(row, "recorded_at", "pod lifecycle failure"),
    detection_latency_seconds: panelNonNegativeNumber(row, "detection_latency_seconds", "pod lifecycle failure"),
    evidence_complete: evidenceComplete,
    recovery_closed: recoveryClosedValue,
    recovery_status: recoveryStatus === null ? null : member(recoveryStatus, RECOVERY_STATUSES, "recovery status"),
    publication: member(
      panelNonEmptyString(row, "publication", "pod lifecycle failure"),
      PUBLICATION_STATES,
      "publication state",
    ),
    evidence_refs: panelStringArray(row["evidence_refs"], "pod lifecycle evidence refs"),
    evidence_gaps: panelStringArray(row["evidence_gaps"], "pod lifecycle failure gaps"),
  };
}

function countsOf<T extends string>(
  value: unknown,
  keys: readonly T[],
  label: string,
): Readonly<Record<T, number>> {
  const root = panelRecord(value, label);
  return Object.fromEntries(
    keys.map((key) => [key, panelNonNegativeInteger(root, key, label)]),
  ) as Record<T, number>;
}

function sum(counts: Readonly<Record<string, number>>): number {
  return Object.values(counts).reduce((total, count) => total + count, 0);
}

function decodeTarget(value: unknown, index: number): DetectionTargetView {
  const row = panelRecord(value, `detection readiness targets[${index}]`);
  const decision = member(panelNonEmptyString(row, "decision", "detection target"), DECISIONS, "decision");
  const ceiling = member(panelNonEmptyString(row, "authority_ceiling", "detection target"), CEILINGS, "authority ceiling");
  const observations = panelArray(row["observations"], "detection observations").map((item) => {
    const observation = panelRecord(item, "detection observation");
    return {
      dimension: member(panelNonEmptyString(observation, "dimension", "detection observation"), DIMENSIONS, "dimension"),
      status: panelNonEmptyString(observation, "status", "detection observation"),
    };
  });
  const dimensions = observations.map((item) => item.dimension);
  if (new Set(dimensions).size !== dimensions.length) {
    throw new OperatorApiError(502, "invalid Operator API response: duplicate detection readiness dimension");
  }
  return {
    resource_ref: panelNonEmptyString(row, "resource_ref", "detection target"),
    generated_at: panelNonEmptyString(row, "generated_at", "detection target"),
    decision,
    authority_ceiling: ceiling,
    observations,
    missing_dimensions: dimensionsOf(panelStringArray(row["missing_dimensions"], "missing dimensions")),
    stale_dimensions: dimensionsOf(panelStringArray(row["stale_dimensions"], "stale dimensions")),
  };
}

function member<T extends string>(value: string, values: readonly T[], label: string): T {
  if (!values.includes(value as T)) {
    throw new OperatorApiError(502, `invalid Operator API response: unknown detection readiness ${label}`);
  }
  return value as T;
}

function dimensionsOf(values: readonly string[]): readonly Dimension[] {
  return values.map((value) => member(value, DIMENSIONS, "dimension"));
}

/** Resolve canonical and legacy anchors to the owning Detection coverage view. */
export function detectionCoverageViewFromHash(hash: string): DetectionCoverageViewId {
  if (
    hash.startsWith("#detection-resources")
    || hash.startsWith("#detection-targets")
    || hash.startsWith("#pod-detection-lifecycle")
  ) return "resources";
  if (
    hash.startsWith("#detection-findings")
    || hash.startsWith("#detection-lifecycle")
  ) return "findings";
  return "coverage";
}

/** Return the tab reached by one keyboard navigation direction. */
export function adjacentDetectionCoverageView(
  view: DetectionCoverageViewId,
  direction: "next" | "previous" | "first" | "last",
): DetectionCoverageViewId {
  if (direction === "first") return COVERAGE_VIEWS[0]!;
  if (direction === "last") return COVERAGE_VIEWS[COVERAGE_VIEWS.length - 1]!;
  const offset = direction === "next" ? 1 : -1;
  return COVERAGE_VIEWS[
    (COVERAGE_VIEWS.indexOf(view) + offset + COVERAGE_VIEWS.length)
      % COVERAGE_VIEWS.length
  ]!;
}

function DetectionReadinessBody({ data }: { readonly data: DetectionReadinessView }) {
  const [activeView, setActiveView] = useState<DetectionCoverageViewId>(() =>
    detectionCoverageViewFromHash(
      typeof window === "undefined" ? "" : window.location.hash,
    ),
  );
  const coverage = data.analyzer_coverage;
  const coverageAvailable = coverage.status === "available";
  const [resourceControls, setResourceControls] = useState<CoverageResourceControls>(() => {
    const parsed = parseCoverageResourceControls(
      typeof window === "undefined"
        ? new URLSearchParams()
        : new URLSearchParams(window.location.search),
    );
    return {
      ...parsed,
      selectedRef: parsed.selectedRef
        ?? (coverageAvailable
          ? filterCoverageResources(coverage.resources, parsed)[0]?.resource_ref ?? null
          : null),
    };
  });
  const routeSearch = typeof window === "undefined"
    ? new URLSearchParams()
    : new URLSearchParams(window.location.search);
  const resourcesHref = coverageResourceHref(
    routeHref("detection-readiness"),
    routeSearch,
    resourceControls,
    "detection-resources",
  );
  const findingsHref = coverageResourceHref(
    routeHref("detection-readiness"),
    routeSearch,
    resourceControls,
    "detection-findings",
  );
  const selectedResource = coverageAvailable
    ? coverage.resources.find(
        (resource) => resource.resource_ref === resourceControls.selectedRef,
      ) ?? null
    : null;
  useEffect(() => {
    const syncRouteState = () => {
      setActiveView(detectionCoverageViewFromHash(window.location.hash));
      const parsed = parseCoverageResourceControls(
        new URLSearchParams(window.location.search),
      );
      setResourceControls({
        ...parsed,
        selectedRef: parsed.selectedRef
          ?? (coverageAvailable
            ? filterCoverageResources(coverage.resources, parsed)[0]?.resource_ref ?? null
            : null),
      });
    };
    window.addEventListener("hashchange", syncRouteState);
    window.addEventListener("popstate", syncRouteState);
    window.addEventListener(ROUTE_STATE_EVENT, syncRouteState);
    return () => {
      window.removeEventListener("hashchange", syncRouteState);
      window.removeEventListener("popstate", syncRouteState);
      window.removeEventListener(ROUTE_STATE_EVENT, syncRouteState);
    };
  }, [coverage, coverageAvailable]);
  usePublishViewContext(
    () => ({
      routeId: "detection-readiness",
      routeLabel: t("title"),
      purpose: t("contextPurpose"),
      glossary: composeGlossary([TERMS.detectionReadiness, TERMS.mode]),
      headline: coverageAvailable
        ? selectedResource !== null && activeView === "resources"
          ? t("resources.contextHeadline", {
              resource: selectedResource.resource_ref,
              state: t(`resources.state.${selectedResource.evaluation_state}`),
            })
          : t("contextHeadline", {
              evaluated: coverage.evaluated_count,
              candidates: coverage.candidate_count,
            })
        : t("coverage.unavailable"),
      capturedAt: coverage.recorded_at ?? data.observed_at ?? new Date().toISOString(),
      facts: [
        { key: "coverage_status", value: coverage.status, group: "coverage" },
        ...(coverageAvailable ? [
          { key: "candidate_count", value: coverage.candidate_count, group: "coverage" },
          { key: "selected_count", value: coverage.selected_count, group: "coverage" },
          { key: "evaluated_count", value: coverage.evaluated_count, group: "coverage" },
          { key: "held_count", value: coverage.held_count, group: "coverage" },
          { key: "finding_count", value: coverage.finding_count, group: "coverage" },
          { key: "error_count", value: coverage.error_count, group: "coverage" },
        ] : []),
        ...(data.analyzer_run === null ? [] : [
          {
            key: "latest_successful_recorded_at",
            value: data.analyzer_run.recorded_at,
            group: "latest_successful_run",
          },
          {
            key: "latest_successful_targets",
            value: data.analyzer_run.targets,
            group: "latest_successful_run",
          },
        ]),
        { key: "kubernetes_readiness_targets", value: data.target_count, group: "kubernetes" },
        { key: "retained_finding_targets", value: data.lifecycle.target_count, group: "findings" },
        ...(selectedResource === null ? [] : [
          { key: "selected_resource", value: selectedResource.resource_ref, group: "selection" },
          { key: "selected_resource_type", value: selectedResource.resource_type, group: "selection" },
          { key: "selected_evaluation_state", value: selectedResource.evaluation_state, group: "selection" },
        ]),
        { key: "resource_type_filter", value: resourceControls.resourceType, group: "filters" },
        { key: "evaluation_filter", value: resourceControls.evaluation, group: "filters" },
      ],
      records: {
        resource_coverage: coverageAvailable
          ? coverage.resources.map((resource) => ({ ...resource }))
          : [],
        resource_type_coverage: coverageAvailable
          ? coverage.resource_types.map((resourceType) => ({ ...resourceType }))
          : [],
        retained_findings: data.lifecycle.targets.map((target) => ({ ...target })),
        kubernetes_readiness: data.targets.map((target) => ({ ...target })),
      },
      ...(selectedResource === null ? {} : {
        explanations: {
          selection: {
            entity_kind: "Resource",
            entity_id: selectedResource.resource_ref,
            label: selectedResource.resource_ref,
          },
        },
      }),
    }),
    [
      activeView,
      coverage,
      coverageAvailable,
      data,
      resourceControls.evaluation,
      resourceControls.resourceType,
      selectedResource,
    ],
  );
  const updateResourceControls = (
    next: CoverageResourceControls,
    historyMode: "push" | "replace" = "push",
  ) => {
    setResourceControls(next);
    setActiveView("resources");
    const href = coverageResourceHref(
      window.location.pathname,
      new URLSearchParams(window.location.search),
      next,
    );
    if (historyMode === "push") pushRouteState(href);
    else replaceRouteState(href);
  };
  const openResourceType = (resourceType: string) => {
    const firstMatch = coverageAvailable
      ? coverage.resources.find((resource) => resource.resource_type === resourceType)
      : undefined;
    updateResourceControls(
      {
        ...resourceControls,
        resourceType,
        selectedRef: firstMatch?.resource_ref ?? null,
      },
      "push",
    );
  };
  const selectView = (view: DetectionCoverageViewId) => {
    setActiveView(view);
    const hash = view === "coverage"
      ? "#detection-coverage-summary"
      : view === "resources"
        ? "#detection-resources"
        : "#detection-findings";
    pushRouteState(coverageResourceHref(
      window.location.pathname,
      new URLSearchParams(window.location.search),
      resourceControls,
      hash.slice(1),
    ));
  };
  return (
    <div class="stack">
      <DetectionCoverageTabs activeView={activeView} onSelect={selectView} />
      <div class="governance-readonly-banner">
        <strong>{t("bannerTitle")}</strong>
        <span>{t("bannerBody")}</span>
      </div>
      <div
        id="detection-readiness-panel-coverage"
        class="stack detection-readiness-panel"
        role="tabpanel"
        aria-labelledby="detection-readiness-tab-coverage"
        hidden={activeView !== "coverage"}
      >
        <CoverageOverview
          coverage={coverage}
          successfulRun={data.analyzer_run}
          resourcesHref={resourcesHref}
          findingsHref={findingsHref}
          onOpenResources={() => selectView("resources")}
          onOpenFindings={() => selectView("findings")}
          onSelectResourceType={openResourceType}
        />
      </div>
      <div
        id="detection-readiness-panel-resources"
        class="stack detection-readiness-panel"
        role="tabpanel"
        aria-labelledby="detection-readiness-tab-resources"
        hidden={activeView !== "resources"}
      >
        <CoverageResources
          coverage={coverage}
          controls={resourceControls}
          onControlsChange={updateResourceControls}
          renderResourceDetail={(resource) => (
            resource.resource_type === "kubernetes-cluster" ? (
              <KubernetesCoverageDetail
                resource={resource}
                readiness={data.targets}
              />
            ) : null
          )}
          renderScopeDetail={(resource) => (
            resource.resource_type === "kubernetes-cluster" ? (
              <KubernetesPodScopeDetail lifecycle={data.pod_lifecycle} />
            ) : null
          )}
        />
      </div>
      <div
        id="detection-readiness-panel-findings"
        class="stack detection-readiness-panel"
        role="tabpanel"
        aria-labelledby="detection-readiness-tab-findings"
        hidden={activeView !== "findings"}
      >
        <DetectionLifecycle lifecycle={data.lifecycle} />
      </div>
    </div>
  );
}

function DetectionCoverageTabs({
  activeView,
  onSelect,
}: {
  readonly activeView: DetectionCoverageViewId;
  readonly onSelect: (view: DetectionCoverageViewId) => void;
}) {
  return (
    <div class="detection-readiness-tabs" role="tablist" aria-label={t("view.label")}>
      {COVERAGE_VIEWS.map((view) => (
        <button
          key={view}
          id={`detection-readiness-tab-${view}`}
          type="button"
          role="tab"
          aria-selected={activeView === view}
          aria-controls={`detection-readiness-panel-${view}`}
          tabIndex={activeView === view ? 0 : -1}
          onClick={() => onSelect(view)}
          onKeyDown={(event) => {
            const direction = event.key === "ArrowRight"
              ? "next"
              : event.key === "ArrowLeft"
                ? "previous"
                : event.key === "Home"
                  ? "first"
                  : event.key === "End"
                    ? "last"
                    : null;
            if (direction === null) return;
            event.preventDefault();
            const next = adjacentDetectionCoverageView(view, direction);
            onSelect(next);
            queueMicrotask(() => document.getElementById(`detection-readiness-tab-${next}`)?.focus());
          }}
        >
          {t(`view.${view}`)}
        </button>
      ))}
    </div>
  );
}

function KubernetesCoverageDetail({
  resource,
  readiness,
}: {
  readonly resource: AnalyzerCoverageResourceView;
  readonly readiness: readonly DetectionTargetView[];
}) {
  const snapshot = readiness.find((target) => target.resource_ref === resource.resource_ref);
  return (
    <section class="stack-section detection-kubernetes-extension" aria-labelledby="kubernetes-readiness-title">
      <h4 id="kubernetes-readiness-title" class="section-title">
        {t("resources.kubernetes.readinessTitle")}
      </h4>
      <p class="muted small">{t("resources.kubernetes.axisBoundary")}</p>
      {snapshot === undefined ? (
        <UnavailableState
          message={t("resources.kubernetes.readinessUnavailable")}
          evidenceState="not-measured"
        />
      ) : (
        <>
          <dl class="details-list">
            <div>
              <dt>{t("column.decision")}</dt>
              <dd><StatusPill kind={decisionKind(snapshot.decision)} label={t(`decision.${snapshot.decision}`)} /></dd>
            </div>
            <div><dt>{t("column.evidence")}</dt><dd>{snapshot.observations.length}/{DIMENSIONS.length}</dd></div>
            <div><dt>{t("column.gaps")}</dt><dd>{t("gapSummary", { missing: snapshot.missing_dimensions.length, stale: snapshot.stale_dimensions.length })}</dd></div>
            <div><dt>{t("column.ceiling")}</dt><dd>{t(`ceiling.${snapshot.authority_ceiling}`)}</dd></div>
          </dl>
          <ul class="detection-coverage-axes">
            {DIMENSIONS.map((dimension) => {
              const observation = snapshot.observations.find(
                (item) => item.dimension === dimension,
              );
              const stale = snapshot.stale_dimensions.includes(dimension);
              return (
                <li key={dimension}>
                  <span>{t(`dimension.${dimension}`)}</span>
                  <StatusPill
                    kind={observation === undefined || stale ? "warning" : "success"}
                    label={stale
                      ? t("decision.stale")
                      : observation === undefined
                        ? t("resources.kubernetes.missing")
                        : observationLabel(observation.status)}
                  />
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}

function KubernetesPodScopeDetail({ lifecycle }: { readonly lifecycle: LifecycleView }) {
  return (
    <section class="detection-pod-scope" aria-labelledby="pod-scope-title">
      <details>
        <summary id="pod-scope-title">{t("resources.kubernetes.podScopeTitle")}</summary>
        <p class="state-block state-unavailable">
          {t("resources.kubernetes.podScopeBoundary")}
        </p>
        <PodLifecycleSection lifecycle={lifecycle} />
      </details>
    </section>
  );
}

function DetectionLifecycle({ lifecycle }: { readonly lifecycle: DetectionLifecycleView }) {
  const [selectedRef, setSelectedRef] = useState<string | null>(
    lifecycle.targets[0]?.resource_ref ?? null,
  );
  const [query, setQuery] = useState("");
  const [evidence, setEvidence] = useState<"all" | EvidenceState>("all");
  const [delivery, setDelivery] = useState<"all" | PublicationState>("all");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const filteredTargets = lifecycle.targets.filter((target) =>
    [target.current, ...target.history].some((assessment) =>
      findingMatches(assessment, { query, evidence, delivery, fromDate, toDate })
    )
  );
  const selected = filteredTargets.find((target) => target.resource_ref === selectedRef)
    ?? filteredTargets[0]
    ?? null;
  return (
    <section class="stack-section detection-lifecycle" aria-labelledby="detection-lifecycle-title">
      <div class="section-heading-row">
        <div>
          <h3 id="detection-lifecycle-title" class="section-title">{t("analyzerLifecycle.title")}</h3>
          <p class="section-description">{t("analyzerLifecycle.description")}</p>
        </div>
        <span class="muted small">
          {lifecycle.observed_at
            ? t("analyzerLifecycle.observedAt", { at: formatConsoleTimestamp(lifecycle.observed_at) })
            : t("notObserved")}
        </span>
      </div>
      <div class="detection-retention-summary">
        <span>{t("analyzerLifecycle.retainedReceipts", {
          count: lifecycle.receipt_count,
          limit: lifecycle.receipt_limit,
        })}</span>
        <span>{lifecycle.retained_from
          ? t("analyzerLifecycle.retainedFrom", {
              at: formatConsoleTimestamp(lifecycle.retained_from),
            })
          : t("analyzerLifecycle.noRetainedFrom")}</span>
      </div>
      <KpiGrid>
        <KpiCard href="#detection-lifecycle-records" label={t("analyzerLifecycle.assessments")} value={lifecycle.assessment_count} />
        <KpiCard
          href="#detection-lifecycle-records"
          label={t("analyzerLifecycle.incomplete")}
          value={lifecycle.evidence_counts.incomplete + lifecycle.evidence_counts.missed}
          tone={lifecycle.evidence_counts.incomplete + lifecycle.evidence_counts.missed > 0 ? "warning" : "positive"}
        />
        <KpiCard
          href="#detection-lifecycle-records"
          label={t("analyzerLifecycle.conflicting")}
          value={lifecycle.evidence_counts.conflicting}
          tone={lifecycle.evidence_counts.conflicting > 0 ? "danger" : "positive"}
        />
      </KpiGrid>
      <div class="detection-finding-toolbar" role="group" aria-label={t("analyzerLifecycle.filters")}>
        <label>
          <span>{t("analyzerLifecycle.search")}</span>
          <input
            class="form-input"
            type="search"
            aria-label={t("analyzerLifecycle.search")}
            value={query}
            placeholder={t("analyzerLifecycle.searchPlaceholder")}
            onInput={(event) => setQuery(event.currentTarget.value)}
          />
        </label>
        <label>
          <span>{t("analyzerLifecycle.evidenceFilter")}</span>
          <select
            class="form-input"
            aria-label={t("analyzerLifecycle.evidenceFilter")}
            value={evidence}
            onChange={(event) => setEvidence(event.currentTarget.value as "all" | EvidenceState)}
          >
            <option value="all">{t("analyzerLifecycle.allEvidence")}</option>
            {EVIDENCE_STATES.map((state) => (
              <option key={state} value={state}>{t(`analyzerLifecycle.evidence.${state}`)}</option>
            ))}
          </select>
        </label>
        <label>
          <span>{t("analyzerLifecycle.deliveryFilter")}</span>
          <select
            class="form-input"
            aria-label={t("analyzerLifecycle.deliveryFilter")}
            value={delivery}
            onChange={(event) => setDelivery(event.currentTarget.value as "all" | PublicationState)}
          >
            <option value="all">{t("analyzerLifecycle.allDelivery")}</option>
            {PUBLICATION_STATES.map((state) => (
              <option key={state} value={state}>{t(`analyzerLifecycle.publication.${state}`)}</option>
            ))}
          </select>
        </label>
        <label>
          <span>{t("analyzerLifecycle.fromDate")}</span>
          <input
            class="form-input"
            type="date"
            aria-label={t("analyzerLifecycle.fromDate")}
            value={fromDate}
            onInput={(event) => setFromDate(event.currentTarget.value)}
          />
        </label>
        <label>
          <span>{t("analyzerLifecycle.toDate")}</span>
          <input
            class="form-input"
            type="date"
            aria-label={t("analyzerLifecycle.toDate")}
            value={toDate}
            onInput={(event) => setToDate(event.currentTarget.value)}
          />
        </label>
        <button
          type="button"
          class="secondary"
          onClick={() => {
            setQuery("");
            setEvidence("all");
            setDelivery("all");
            setFromDate("");
            setToDate("");
          }}
        >
          {t("analyzerLifecycle.clearFilters")}
        </button>
      </div>
      <p class="filter-summary">
        <span>
          {t("analyzerLifecycle.resultCount", {
            filtered: filteredTargets.length,
            total: lifecycle.target_count,
          })}
        </span>
      </p>
      {selected === null ? (
        <EmptyState
          title={lifecycle.targets.length === 0
            ? t("analyzerLifecycle.emptyTitle")
            : t("analyzerLifecycle.noMatches")}
          body={lifecycle.targets.length === 0
            ? t("analyzerLifecycle.emptyBody")
            : t("analyzerLifecycle.noMatchesBody")}
        />
      ) : (
        <div id="detection-lifecycle-records" class="detection-record-workspace">
          <aside class="detection-record-list" aria-label={t("analyzerLifecycle.title")}>
            <h4>{t("analyzerLifecycle.targets")}</h4>
            <ul>
              {filteredTargets.map((target) => (
                <li key={target.resource_ref}>
                  <button
                    type="button"
                    aria-pressed={selected.resource_ref === target.resource_ref}
                    aria-controls="detection-lifecycle-detail"
                    onClick={() => setSelectedRef(target.resource_ref)}
                  >
                    <strong class="mono">{target.resource_ref}</strong>
                    <span>
                      {currentStateLabel(target.current.current_state)}
                      {" / "}
                      {t(`analyzerLifecycle.evidence.${target.current.evidence_state}`)}
                      {target.current.resource_kind === "kubernetes_pod"
                        ? ` / ${t(`analyzerLifecycle.recovery.${target.current.recovery_state}`)}`
                        : ""}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </aside>
          <article
            id="detection-lifecycle-detail"
            class="detection-record-detail"
          >
            <h4 class="panel-title mono">{selected.resource_ref}</h4>
            <section
              class="detection-lifecycle-current"
              aria-label={t("analyzerLifecycle.currentRegion", { target: selected.resource_ref })}
            >
              <h5>{t("analyzerLifecycle.current")}</h5>
              <LifecycleAssessment assessment={selected.current} />
            </section>
            <details class="detection-lifecycle-history">
              <summary>{t("analyzerLifecycle.history", { count: selected.history.length })}</summary>
              {selected.history.length === 0 ? (
                <p class="muted small">{t("analyzerLifecycle.noHistory")}</p>
              ) : (
                <ol>
                  {selected.history.map((assessment) => (
                    <li key={assessment.idempotency_key}>
                      <LifecycleAssessment assessment={assessment} />
                    </li>
                  ))}
                </ol>
              )}
            </details>
          </article>
        </div>
      )}
      <span class="sr-only" role="status" aria-live="polite">
        {selected ? t("analyzerLifecycle.selectionChanged", {
          resource: selected.resource_ref,
        }) : ""}
      </span>
      <p class="muted footnote">
        {t("analyzerLifecycle.boundary", { source: lifecycle.source })}
      </p>
    </section>
  );
}

function PodLifecycleSection({ lifecycle }: { readonly lifecycle: LifecycleView }) {
  const anchor = `${routeHref("detection-readiness")}${
    typeof window === "undefined" ? "" : window.location.search
  }#pod-detection-lifecycle`;
  const [selectedRef, setSelectedRef] = useState<string | null>(
    lifecycle.targets[0]?.resource_ref ?? null,
  );
  const selected = lifecycle.targets.find((target) => target.resource_ref === selectedRef)
    ?? lifecycle.targets[0]
    ?? null;
  const failureColumns: readonly Column<LifecycleFailureView>[] = [
    {
      key: "occurred",
      header: t("lifecycle.column.occurred"),
      render: (failure) => formatConsoleTimestamp(failure.occurred_at),
    },
    {
      key: "signal",
      header: t("lifecycle.column.signal"),
      render: (failure) => <code>{failure.signal}</code>,
    },
    {
      key: "recovery",
      header: t("lifecycle.column.recovery"),
      render: (failure) => (failure.recovery_status === null ? t("lifecycle.unassessed") : <code>{failure.recovery_status}</code>),
    },
    {
      key: "delivery",
      header: t("lifecycle.column.delivery"),
      render: (failure) => <code>{failure.publication}</code>,
    },
    {
      key: "evidence",
      header: t("lifecycle.column.evidence"),
      render: (failure) => (failure.evidence_complete ? t("lifecycle.evidenceComplete") : t("lifecycle.evidenceIncomplete")),
    },
  ];
  return (
    <section id="pod-detection-lifecycle" class="stack-section" aria-labelledby="pod-detection-lifecycle-title">
      <h3 id="pod-detection-lifecycle-title" class="section-title">{t("lifecycle.title")}</h3>
      <p class="muted small">{t("lifecycle.note")}</p>
      {lifecycle.status === "unavailable" ? (
        <UnavailableState
          message={t("lifecycle.unavailable", { reason: lifecycle.unavailable_reason ?? "unavailable" })}
          evidenceState="not-measured"
        />
      ) : lifecycle.targets.length === 0 ? (
        <EmptyState title={t("lifecycle.emptyTitle")} body={t("lifecycle.emptyBody")} />
      ) : (
        <div class="stack">
          <KpiGrid>
            <KpiCard href={anchor} label={t("lifecycle.failing")} value={lifecycle.counts.failing} tone={lifecycle.counts.failing > 0 ? "warning" : "positive"} />
            <KpiCard href={anchor} label={t("lifecycle.recoveredVerified")} value={lifecycle.recovery_counts.verified} tone={lifecycle.recovery_counts.verified > 0 ? "positive" : "default"} />
            <KpiCard href={anchor} label={t("lifecycle.failureTotal")} value={lifecycle.failure_total} />
            <KpiCard
              href={anchor}
              label={t("lifecycle.gapTargets")}
              value={lifecycle.gap_target_count}
              tone={lifecycle.gap_target_count > 0 ? "warning" : "positive"}
              evidenceState={lifecycle.gap_target_count > 0 ? "insufficient-sample" : "measured"}
            />
          </KpiGrid>
          {selected ? (
            <div class="detection-record-workspace">
              <aside class="detection-record-list" aria-label={t("lifecycle.title")}>
                <h4>{t("targets")}</h4>
                <ul>
                  {lifecycle.targets.map((target) => (
                    <li key={target.resource_ref}>
                      <button
                        type="button"
                        aria-pressed={selected.resource_ref === target.resource_ref}
                        aria-controls="pod-detection-lifecycle-detail"
                        onClick={() => setSelectedRef(target.resource_ref)}
                      >
                        <strong class="mono">{target.resource_ref}</strong>
                        <span>
                          {t(`lifecycle.state.${target.current_state}`)}
                          {" / "}
                          {t(`lifecycle.recovery.${target.recovery_state}`)}
                          {" / "}
                          {t("lifecycle.failureCount", { count: target.failure_count })}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </aside>
              <article
                id="pod-detection-lifecycle-detail"
                class="detection-record-detail"
              >
                <h4 class="panel-title mono">{selected.resource_ref}</h4>
                <div class="detection-lifecycle-status">
                  <StatusPill kind={currentStateKind(selected.current_state)} label={t(`lifecycle.state.${selected.current_state}`)} />
                  <StatusPill kind={podRecoveryKind(selected.recovery_state)} label={t(`lifecycle.recovery.${selected.recovery_state}`)} />
                  <span class="small">{t("lifecycle.failureCount", { count: selected.failure_count })}</span>
                </div>
                <dl class="details-list">
                  <div>
                    <dt>{t("lifecycle.currentSignal")}</dt>
                    <dd>{selected.current_signal ? <code>{selected.current_signal}</code> : t("lifecycle.noSignal")}</dd>
                  </div>
                  <div>
                    <dt>{t("lifecycle.currentObservedAt")}</dt>
                    <dd>{selected.current_state_observed_at ? formatConsoleTimestamp(selected.current_state_observed_at) : t("notObserved")}</dd>
                  </div>
                  <div>
                    <dt>{t("lifecycle.recoveryVerifiedAt")}</dt>
                    <dd>{selected.recovery_verified_at ? formatConsoleTimestamp(selected.recovery_verified_at) : t("lifecycle.recoveryNotVerified")}</dd>
                  </div>
                  <div>
                    <dt>{t("lifecycle.retained")}</dt>
                    <dd>{t("lifecycle.retainedValue", { retained: selected.retained_record_count, failures: selected.failure_count })}</dd>
                  </div>
                </dl>
                <h4 class="detection-lifecycle-subtitle">{t("lifecycle.historyTitle")}</h4>
                {selected.failures.length === 0 ? (
                  <p class="small">{t("lifecycle.noHistory")}</p>
                ) : (
                  <DataTable
                    columns={failureColumns}
                    rows={selected.failures}
                    keyOf={(failure) => failure.idempotency_key}
                    empty={t("lifecycle.noHistory")}
                  />
                )}
                <h4 class="detection-lifecycle-subtitle">{t("lifecycle.gapsTitle")}</h4>
                {selected.evidence_gaps.length === 0 ? (
                  <p class="small">{t("lifecycle.noGaps")}</p>
                ) : (
                  <ul class="detection-lifecycle-gaps">
                    {selected.evidence_gaps.map((gap) => (
                      <li key={gap}>
                        <StatusPill kind="warning" label={t(`lifecycle.gap.${gap}`)} />
                      </li>
                    ))}
                  </ul>
                )}
                {selected.evidence_gap_details.length > 0 ? (
                  <ul class="detection-lifecycle-gap-details small mono">
                    {selected.evidence_gap_details.map((detail) => (
                      <li key={detail}>{detail}</li>
                    ))}
                  </ul>
                ) : null}
              </article>
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}

function LifecycleAssessment({ assessment }: { readonly assessment: DetectionLifecycleAssessment }) {
  const recoveryCapable = assessment.resource_kind === "kubernetes_pod";
  return (
    <div class="detection-lifecycle-assessment">
      <div class="detection-lifecycle-status">
        <StatusPill kind={evidenceKind(assessment.evidence_state)} label={t(`analyzerLifecycle.evidence.${assessment.evidence_state}`)} />
        {recoveryCapable ? (
          <StatusPill kind={analyzerRecoveryKind(assessment.recovery_state)} label={t(`analyzerLifecycle.recovery.${assessment.recovery_state}`)} />
        ) : null}
        <StatusPill kind={publicationKind(assessment.publication.current)} label={t(`analyzerLifecycle.publication.${assessment.publication.current}`)} />
      </div>
      <dl class="details-list detection-lifecycle-facts">
        <div><dt>{t("analyzerLifecycle.currentState")}</dt><dd>{currentStateLabel(assessment.current_state)}</dd></div>
        <div>
          <dt>{t("analyzerLifecycle.event")}</dt>
          <dd>
            {signalLabel(assessment.signal)}
            <code class="technical-token">{assessment.signal}</code>
          </dd>
        </div>
        <div><dt>{t("analyzerLifecycle.occurredAt")}</dt><dd>{formatConsoleTimestamp(assessment.occurred_at)}</dd></div>
        <div><dt>{t("analyzerLifecycle.latency")}</dt><dd>{t("analyzerLifecycle.seconds", { value: assessment.detection_latency_seconds })}</dd></div>
      </dl>
      <div class="detection-lifecycle-evidence">
        <span class="label">{t("analyzerLifecycle.evidenceRefs")}</span>
        <ul>
          {assessment.evidence_refs.map((reference) => <li class="mono small" key={reference}>{reference}</li>)}
        </ul>
      </div>
      {assessment.publication.duplicate_observed ? (
        <p class="muted small">{t("analyzerLifecycle.duplicateObserved")}</p>
      ) : null}
    </div>
  );
}

function findingMatches(
  assessment: DetectionLifecycleAssessment,
  filters: {
    readonly query: string;
    readonly evidence: "all" | EvidenceState;
    readonly delivery: "all" | PublicationState;
    readonly fromDate: string;
    readonly toDate: string;
  },
): boolean {
  const query = filters.query.trim().toLocaleLowerCase();
  const occurredDate = assessment.occurred_at.slice(0, 10);
  return (filters.evidence === "all" || assessment.evidence_state === filters.evidence)
    && (filters.delivery === "all" || assessment.publication.current === filters.delivery)
    && (!filters.fromDate || occurredDate >= filters.fromDate)
    && (!filters.toDate || occurredDate <= filters.toDate)
    && (
      !query
      || [
        assessment.resource_ref,
        assessment.resource_kind,
        assessment.signal,
        assessment.current_state,
        ...assessment.evidence_refs,
      ].some((value) => value.toLocaleLowerCase().includes(query))
    );
}

function currentStateLabel(state: string): string {
  return ["running", "failed", "unknown"].includes(state)
    ? t(`analyzerLifecycle.currentStateValue.${state}`)
    : state;
}

function signalLabel(signal: string): string {
  return ["container_restart", "pod_replacement", "insufficient_evidence", "conflicting_evidence"].includes(signal)
    ? t(`analyzerLifecycle.signal.${signal}`)
    : signal;
}

function observationLabel(status: string): string {
  return ["passed", "failed", "unavailable", "unauthorized"].includes(status)
    ? t(`observation.${status}`)
    : status;
}

function evidenceKind(state: EvidenceState): PillKind {
  if (state === "complete") return "success";
  if (state === "conflicting") return "danger";
  return "warning";
}

function currentStateKind(state: CurrentState): PillKind {
  if (state === "recovered") return "success";
  if (state === "failing") return "danger";
  return "neutral";
}

function analyzerRecoveryKind(state: AnalyzerRecoveryState): PillKind {
  if (state === "verified") return "success";
  if (state === "open") return "warning";
  return "neutral";
}

function publicationKind(state: PublicationState): PillKind {
  if (state === "published" || state === "duplicate_suppressed" || state === "reconciled_duplicate") return "success";
  if (state === "failed" || state === "published_receipt_unrecorded") return "danger";
  if (state === "publish_uncertain" || state === "awaiting_reconciliation") return "warning";
  return "neutral";
}

function podRecoveryKind(state: PodRecoveryState): PillKind {
  if (state === "verified") return "success";
  if (state === "not_verified") return "warning";
  return "neutral";
}

function decisionKind(decision: Decision): PillKind {
  if (decision === "ready") return "success";
  if (decision === "blocked" || decision === "unauthorized") return "danger";
  if (decision === "partial" || decision === "stale") return "warning";
  return "neutral";
}
