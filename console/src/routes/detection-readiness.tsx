import { useEffect, useState } from "preact/hooks";

import { isOptionalOperatorApiUnavailable, OperatorApiError, type OperatorApiClient } from "../api";
import { architectureHref } from "../components/architecture-map.model";
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
import { routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
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

type Decision = typeof DECISIONS[number];
type Dimension = typeof DIMENSIONS[number];
type AuthorityCeiling = typeof CEILINGS[number];
type CurrentState = typeof CURRENT_STATES[number];
type RecoveryState = typeof RECOVERY_STATES[number];
type LifecycleSignal = typeof LIFECYCLE_SIGNALS[number];
type RecoveryStatus = typeof RECOVERY_STATUSES[number];
type EvidenceGap = typeof EVIDENCE_GAPS[number];
type PublicationState = typeof PUBLICATION_STATES[number];

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
  readonly recovery_state: RecoveryState;
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
  readonly recovery_counts: Readonly<Record<RecoveryState, number>>;
  readonly targets: readonly LifecycleTargetView[];
}

interface DetectionReadinessView {
  readonly source: string;
  readonly observed_at: string | null;
  readonly target_count: number;
  readonly counts: Readonly<Record<Decision, number>>;
  readonly targets: readonly DetectionTargetView[];
  readonly lifecycle: LifecycleView;
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
    const value = await client.panel<unknown>("/detection-readiness");
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
    lifecycle: decodeLifecycle(root["lifecycle"]),
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

function DetectionReadinessBody({ data }: { readonly data: DetectionReadinessView }) {
  const attention = data.target_count - data.counts.ready;
  const shadowLimited = data.targets.filter((target) =>
    ["disabled", "deterministic_fallback", "shadow"].includes(target.authority_ceiling),
  ).length;
  const anchor = `${routeHref("detection-readiness")}#detection-targets`;
  usePublishViewContext(
    () => ({
      routeId: "detection-readiness",
      routeLabel: t("title"),
      purpose: t("contextPurpose"),
      glossary: composeGlossary([TERMS.detectionReadiness, TERMS.mode]),
      headline: t("contextHeadline", { targets: data.target_count, ready: data.counts.ready }),
      capturedAt: data.observed_at ?? new Date().toISOString(),
      facts: [
        { key: "target_count", value: data.target_count, group: "readiness" },
        { key: "ready_count", value: data.counts.ready, group: "readiness" },
        { key: "attention_count", value: attention, group: "readiness" },
        { key: "source", value: data.source, group: "provenance" },
        { key: "lifecycle_status", value: data.lifecycle.status, group: "lifecycle" },
        { key: "lifecycle_failing", value: data.lifecycle.counts.failing, group: "lifecycle" },
        { key: "lifecycle_failure_total", value: data.lifecycle.failure_total, group: "lifecycle" },
        { key: "lifecycle_recovery_verified", value: data.lifecycle.recovery_counts.verified, group: "lifecycle" },
        { key: "lifecycle_gap_targets", value: data.lifecycle.gap_target_count, group: "lifecycle" },
      ],
      records: {
        targets: data.targets.map((target) => ({ ...target })),
        pod_lifecycle: data.lifecycle.targets.map((target) => ({ ...target })),
      },
    }),
    [attention, data],
  );
  const columns: readonly Column<DetectionTargetView>[] = [
    {
      key: "target",
      header: t("column.target"),
      render: (target) => <a class="mono small" href={architectureHref(target.resource_ref)}>{target.resource_ref}</a>,
    },
    {
      key: "decision",
      header: t("column.decision"),
      render: (target) => <StatusPill kind={decisionKind(target.decision)} label={t(`decision.${target.decision}`)} />,
    },
    {
      key: "evidence",
      header: t("column.evidence"),
      render: (target) => `${target.observations.length}/${DIMENSIONS.length}`,
      cellClass: "num",
    },
    {
      key: "gaps",
      header: t("column.gaps"),
      render: (target) => t("gapSummary", {
        missing: target.missing_dimensions.length,
        stale: target.stale_dimensions.length,
      }),
    },
    {
      key: "ceiling",
      header: t("column.ceiling"),
      render: (target) => <code>{target.authority_ceiling}</code>,
    },
  ];
  return (
    <div class="stack">
      <div class="governance-readonly-banner">
        <strong>{t("bannerTitle")}</strong>
        <span>{t("bannerBody")}</span>
      </div>
      <KpiGrid>
        <KpiCard href={anchor} label={t("targets")} value={data.target_count} />
        <KpiCard href={anchor} label={t("ready")} value={data.counts.ready} tone={data.counts.ready === data.target_count && data.target_count > 0 ? "positive" : "default"} />
        <KpiCard href={anchor} label={t("attention")} value={attention} tone={attention > 0 ? "warning" : "positive"} />
        <KpiCard href={routeHref("promotion-gates")} label={t("shadowLimited")} value={shadowLimited} tone={shadowLimited > 0 ? "warning" : "default"} />
      </KpiGrid>
      <section class="stack-section" aria-labelledby="detection-provenance">
        <h3 id="detection-provenance" class="section-title">{t("provenance")}</h3>
        <dl class="details-list">
          <div><dt>{t("source")}</dt><dd><code>{data.source}</code></dd></div>
          <div><dt>{t("observedAt")}</dt><dd>{data.observed_at ? formatConsoleTimestamp(data.observed_at) : t("notObserved")}</dd></div>
        </dl>
      </section>
      <section id="detection-targets" class="stack-section">
        <h3 class="section-title">{t("targetTitle")}</h3>
        {data.targets.length === 0 ? (
          <EmptyState title={t("emptyTitle")} body={t("emptyBody")} />
        ) : (
          <DataTable columns={columns} rows={data.targets} keyOf={(target) => target.resource_ref} empty={t("emptyTitle")} />
        )}
      </section>
      <PodLifecycleSection lifecycle={data.lifecycle} />
    </div>
  );
}

function PodLifecycleSection({ lifecycle }: { readonly lifecycle: LifecycleView }) {
  const anchor = `${routeHref("detection-readiness")}#detection-lifecycle`;
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
    <section id="detection-lifecycle" class="stack-section" aria-labelledby="detection-lifecycle-title">
      <h3 id="detection-lifecycle-title" class="section-title">{t("lifecycle.title")}</h3>
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
          <ul class="detection-lifecycle-list">
            {lifecycle.targets.map((target) => (
              <li key={target.resource_ref} class="detection-lifecycle-target">
                <details>
                  <summary class="detection-lifecycle-summary">
                    <span class="mono small detection-lifecycle-ref">{target.resource_ref}</span>
                    <StatusPill kind={currentStateKind(target.current_state)} label={t(`lifecycle.state.${target.current_state}`)} />
                    <StatusPill kind={recoveryKind(target.recovery_state)} label={t(`lifecycle.recovery.${target.recovery_state}`)} />
                    <span class="small">{t("lifecycle.failureCount", { count: target.failure_count })}</span>
                  </summary>
                  <dl class="details-list">
                    <div>
                      <dt>{t("lifecycle.currentSignal")}</dt>
                      <dd>{target.current_signal ? <code>{target.current_signal}</code> : t("lifecycle.noSignal")}</dd>
                    </div>
                    <div>
                      <dt>{t("lifecycle.currentObservedAt")}</dt>
                      <dd>{target.current_state_observed_at ? formatConsoleTimestamp(target.current_state_observed_at) : t("notObserved")}</dd>
                    </div>
                    <div>
                      <dt>{t("lifecycle.recoveryVerifiedAt")}</dt>
                      <dd>{target.recovery_verified_at ? formatConsoleTimestamp(target.recovery_verified_at) : t("lifecycle.recoveryNotVerified")}</dd>
                    </div>
                    <div>
                      <dt>{t("lifecycle.retained")}</dt>
                      <dd>{t("lifecycle.retainedValue", { retained: target.retained_record_count, failures: target.failure_count })}</dd>
                    </div>
                  </dl>
                  <h4 class="detection-lifecycle-subtitle">{t("lifecycle.historyTitle")}</h4>
                  {target.failures.length === 0 ? (
                    <p class="small">{t("lifecycle.noHistory")}</p>
                  ) : (
                    <DataTable
                      columns={failureColumns}
                      rows={target.failures}
                      keyOf={(failure) => failure.idempotency_key}
                      empty={t("lifecycle.noHistory")}
                    />
                  )}
                  <h4 class="detection-lifecycle-subtitle">{t("lifecycle.gapsTitle")}</h4>
                  {target.evidence_gaps.length === 0 ? (
                    <p class="small">{t("lifecycle.noGaps")}</p>
                  ) : (
                    <ul class="detection-lifecycle-gaps">
                      {target.evidence_gaps.map((gap) => (
                        <li key={gap}>
                          <StatusPill kind="warning" label={t(`lifecycle.gap.${gap}`)} />
                        </li>
                      ))}
                    </ul>
                  )}
                  {target.evidence_gap_details.length > 0 ? (
                    <ul class="detection-lifecycle-gap-details small mono">
                      {target.evidence_gap_details.map((detail) => (
                        <li key={detail}>{detail}</li>
                      ))}
                    </ul>
                  ) : null}
                </details>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function currentStateKind(state: CurrentState): PillKind {
  if (state === "recovered") return "success";
  if (state === "failing") return "danger";
  return "neutral";
}

function recoveryKind(state: RecoveryState): PillKind {
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
