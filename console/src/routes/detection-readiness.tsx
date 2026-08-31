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
const EVIDENCE_STATES = ["complete", "incomplete", "conflicting", "missed"] as const;
const PUBLICATION_STATES = [
  "published",
  "published_receipt_unrecorded",
  "duplicate_suppressed",
  "failed",
] as const;
const RECOVERY_STATES = ["verified", "open", "unknown"] as const;

type Decision = typeof DECISIONS[number];
type Dimension = typeof DIMENSIONS[number];
type AuthorityCeiling = typeof CEILINGS[number];
type EvidenceState = typeof EVIDENCE_STATES[number];
type PublicationState = typeof PUBLICATION_STATES[number];
type RecoveryState = typeof RECOVERY_STATES[number];

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

interface DetectionReadinessView {
  readonly source: string;
  readonly observed_at: string | null;
  readonly target_count: number;
  readonly counts: Readonly<Record<Decision, number>>;
  readonly targets: readonly DetectionTargetView[];
  readonly lifecycle: DetectionLifecycleView;
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
  readonly recovery_state: RecoveryState;
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

function decodeLifecycle(value: unknown): DetectionLifecycleView {
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
  const renderedAssessmentCount = targets.reduce((count, target) => count + 1 + target.history.length, 0);
  if (
    targets.length !== targetCount
    || renderedAssessmentCount !== assessmentCount
    || Object.values(evidenceCounts).reduce((sum, count) => sum + count, 0) !== assessmentCount
  ) {
    throw new OperatorApiError(502, "invalid Operator API response: detection lifecycle totals do not reconcile");
  }
  return {
    source: panelNonEmptyString(root, "source", "detection lifecycle"),
    observed_at: panelNullableString(root, "observed_at", "detection lifecycle"),
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
    || duplicateObserved !== attempts.includes("duplicate_suppressed")
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
      RECOVERY_STATES,
      "recovery state",
    ),
    evidence_refs: panelStringArray(row["evidence_refs"], `${label}.evidence_refs`),
    cause_claim_supported: false,
    execution_authority: false,
  };
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
      ],
      records: {
        targets: data.targets.map((target) => ({ ...target })),
        lifecycle: data.lifecycle.targets.map((target) => ({ ...target })),
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
      <DetectionLifecycle lifecycle={data.lifecycle} />
      <section id="detection-targets" class="stack-section">
        <h3 class="section-title">{t("targetTitle")}</h3>
        {data.targets.length === 0 ? (
          <EmptyState title={t("emptyTitle")} body={t("emptyBody")} />
        ) : (
          <DataTable columns={columns} rows={data.targets} keyOf={(target) => target.resource_ref} empty={t("emptyTitle")} />
        )}
      </section>
    </div>
  );
}

function DetectionLifecycle({ lifecycle }: { readonly lifecycle: DetectionLifecycleView }) {
  return (
    <section class="stack-section detection-lifecycle" aria-labelledby="detection-lifecycle-title">
      <div class="section-heading-row">
        <div>
          <h3 id="detection-lifecycle-title" class="section-title">{t("lifecycle.title")}</h3>
          <p class="section-description">{t("lifecycle.description")}</p>
        </div>
        <span class="muted small">
          {lifecycle.observed_at
            ? t("lifecycle.observedAt", { at: formatConsoleTimestamp(lifecycle.observed_at) })
            : t("notObserved")}
        </span>
      </div>
      <KpiGrid>
        <KpiCard href="#detection-lifecycle-records" label={t("lifecycle.assessments")} value={lifecycle.assessment_count} />
        <KpiCard
          href="#detection-lifecycle-records"
          label={t("lifecycle.incomplete")}
          value={lifecycle.evidence_counts.incomplete + lifecycle.evidence_counts.missed}
          tone={lifecycle.evidence_counts.incomplete + lifecycle.evidence_counts.missed > 0 ? "warning" : "positive"}
        />
        <KpiCard
          href="#detection-lifecycle-records"
          label={t("lifecycle.conflicting")}
          value={lifecycle.evidence_counts.conflicting}
          tone={lifecycle.evidence_counts.conflicting > 0 ? "danger" : "positive"}
        />
      </KpiGrid>
      <div id="detection-lifecycle-records" class="detection-lifecycle-list">
        {lifecycle.targets.length === 0 ? (
          <EmptyState title={t("lifecycle.emptyTitle")} body={t("lifecycle.emptyBody")} />
        ) : lifecycle.targets.map((target) => (
          <article class="detection-lifecycle-target" key={target.resource_ref}>
            <h4 class="panel-title mono">{target.resource_ref}</h4>
            <section
              class="detection-lifecycle-current"
              aria-label={t("lifecycle.currentRegion", { target: target.resource_ref })}
            >
              <h5>{t("lifecycle.current")}</h5>
              <LifecycleAssessment assessment={target.current} />
            </section>
            <details class="detection-lifecycle-history">
              <summary>{t("lifecycle.history", { count: target.history.length })}</summary>
              {target.history.length === 0 ? (
                <p class="muted small">{t("lifecycle.noHistory")}</p>
              ) : (
                <ol>
                  {target.history.map((assessment) => (
                    <li key={assessment.idempotency_key}>
                      <LifecycleAssessment assessment={assessment} />
                    </li>
                  ))}
                </ol>
              )}
            </details>
          </article>
        ))}
      </div>
      <p class="muted footnote">
        {t("lifecycle.boundary", { source: lifecycle.source })}
      </p>
    </section>
  );
}

function LifecycleAssessment({ assessment }: { readonly assessment: DetectionLifecycleAssessment }) {
  return (
    <div class="detection-lifecycle-assessment">
      <div class="detection-lifecycle-status">
        <StatusPill kind={evidenceKind(assessment.evidence_state)} label={t(`lifecycle.evidence.${assessment.evidence_state}`)} />
        <StatusPill kind={recoveryKind(assessment.recovery_state)} label={t(`lifecycle.recovery.${assessment.recovery_state}`)} />
        <StatusPill kind={publicationKind(assessment.publication.current)} label={t(`lifecycle.publication.${assessment.publication.current}`)} />
      </div>
      <dl class="details-list detection-lifecycle-facts">
        <div><dt>{t("lifecycle.currentState")}</dt><dd>{currentStateLabel(assessment.current_state)}</dd></div>
        <div>
          <dt>{t("lifecycle.event")}</dt>
          <dd>{signalLabel(assessment.signal)} <code>{assessment.signal}</code></dd>
        </div>
        <div><dt>{t("lifecycle.occurredAt")}</dt><dd>{formatConsoleTimestamp(assessment.occurred_at)}</dd></div>
        <div><dt>{t("lifecycle.latency")}</dt><dd>{t("lifecycle.seconds", { value: assessment.detection_latency_seconds })}</dd></div>
      </dl>
      <div class="detection-lifecycle-evidence">
        <span class="label">{t("lifecycle.evidenceRefs")}</span>
        <ul>
          {assessment.evidence_refs.map((reference) => <li class="mono small" key={reference}>{reference}</li>)}
        </ul>
      </div>
      {assessment.publication.duplicate_observed ? (
        <p class="muted small">{t("lifecycle.duplicateObserved")}</p>
      ) : null}
    </div>
  );
}

function currentStateLabel(state: string): string {
  return ["running", "failed", "unknown"].includes(state)
    ? t(`lifecycle.currentStateValue.${state}`)
    : state;
}

function signalLabel(signal: string): string {
  return ["container_restart", "pod_replacement", "insufficient_evidence", "conflicting_evidence"].includes(signal)
    ? t(`lifecycle.signal.${signal}`)
    : signal;
}

function evidenceKind(state: EvidenceState): PillKind {
  if (state === "complete") return "success";
  if (state === "conflicting") return "danger";
  return "warning";
}

function recoveryKind(state: RecoveryState): PillKind {
  if (state === "verified") return "success";
  if (state === "open") return "warning";
  return "neutral";
}

function publicationKind(state: PublicationState): PillKind {
  if (state === "published" || state === "duplicate_suppressed") return "success";
  if (state === "failed" || state === "published_receipt_unrecorded") return "danger";
  return "neutral";
}

function decisionKind(decision: Decision): PillKind {
  if (decision === "ready") return "success";
  if (decision === "blocked" || decision === "unauthorized") return "danger";
  if (decision === "partial" || decision === "stale") return "warning";
  return "neutral";
}
