import type { ComponentChildren } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import { Tooltip } from "../components/tooltip";
import { StatusPill } from "../components/ui";
import { routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import { presentationLabel, t } from "./i18n/evidence";
import type {
  TraceActionLifecycle,
  TraceOperationalSummary,
  TraceResponse,
  TraceStep,
} from "./rule-trace";
import {
  traceActionLabel,
  traceActorLabel,
  traceOffset,
  traceStageLabel,
  traceStepPill,
  TraceActionLifecycleSection,
  TraceTimeline,
} from "./rule-trace-supporting-evidence";
import { TraceFact, TraceMetric } from "./rule-trace-layout";
import { TraceCopyButton } from "./rule-trace-copy";

interface Props {
  readonly data: TraceResponse;
  readonly lifecycles: readonly TraceActionLifecycle[];
  readonly loadedAt: string | null;
  readonly summary: TraceOperationalSummary;
  readonly toolbar: ComponentChildren;
}

export function RuleTraceWorkspace({
  data,
  lifecycles,
  loadedAt,
  summary,
  toolbar,
}: Props) {
  const [selectedSequence, setSelectedSequence] = useState(
    data.steps.at(-1)?.seq ?? null,
  );
  const [contextExpanded, setContextExpanded] = useState(
    () => !isNarrowTraceViewport(),
  );
  const stageListRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    setSelectedSequence(data.steps.at(-1)?.seq ?? null);
  }, [data.correlation_id, data.steps]);

  useEffect(() => {
    const list = stageListRef.current;
    const selected = list?.querySelector<HTMLElement>('[aria-pressed="true"]');
    if (list === null || selected === null || selected === undefined) return;
    list.scrollTop = Math.max(
      0,
      selected.offsetTop - list.offsetTop - (list.clientHeight - selected.clientHeight) / 2,
    );
  }, [data.correlation_id, selectedSequence]);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 600px)");
    const sync = () => setContextExpanded(!media.matches);
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);

  const selectedStep = data.steps.find((step) => step.seq === selectedSequence)
    ?? data.steps.at(-1)
    ?? null;
  const auditHref = routeHref("audit", {
    params: { correlation: data.correlation_id },
  });

  return (
    <div class="trace-ready-workspace">
      <section class="trace-metrics" aria-label={t("evidence.trace.summaryLabel")}>
        <TraceMetric
          href={auditHref}
          label={t("evidence.trace.summary.decision")}
          value={data.latest_decision === null
            ? t("evidence.trace.summary.notRecorded")
            : presentationLabel("status", data.latest_decision)}
          hint={summary.notificationEscalation
            ? t("evidence.trace.summary.notificationEscalation")
            : summary.decisionRecorded
              ? t("evidence.trace.summary.decisionRecorded")
              : t("evidence.trace.summary.activityOnly")}
          primary
        />
        <TraceMetric
          href={auditHref}
          label={t("evidence.trace.operationalEffect")}
          value={effectSummary(data).value}
          hint={effectSummary(data).hint}
          primary
        />
        <TraceMetric
          href={auditHref}
          label={t("evidence.trace.completeness")}
          value={data.complete
            ? t("evidence.trace.complete")
            : t("evidence.trace.recentSample")}
          hint={t(
            data.metadata_source === "server"
              ? "evidence.trace.serverMetadata"
              : "evidence.trace.legacyMetadata",
          )}
        />
        <TraceMetric
          href={auditHref}
          label={t("evidence.trace.terminalAndLatest")}
          value={data.terminal_stage === null
            ? t("evidence.trace.noNamedTerminal")
            : traceStageLabel(data.terminal_stage)}
          hint={t("evidence.trace.latestActivityHint", {
            activity: data.latest_activity_stage === null
              ? traceActionLabel(data.latest_action_kind)
              : traceStageLabel(data.latest_activity_stage),
          })}
        />
      </section>

      <details
        class="trace-context-details"
        open={contextExpanded}
        onToggle={(event) => setContextExpanded(event.currentTarget.open)}
      >
        <summary>{t("evidence.trace.contextSummary", {
          kind: t(`evidence.trace.discovery.kind.${data.trace_kind}`),
          records: data.step_count,
        })}</summary>
        <dl class="trace-context-strip">
          <TraceContext
            label={t("evidence.trace.traceKind")}
            value={t(`evidence.trace.discovery.kind.${data.trace_kind}`)}
          />
          <TraceContext
            label={t("evidence.trace.target")}
            value={data.target_resource_ref
              ?? (data.target_count === 0
                ? t("evidence.trace.notRecorded")
                : t("evidence.trace.targetCount", { count: data.target_count }))}
          />
          <TraceContext
            label={t("evidence.trace.evidenceWindow")}
            value={t("evidence.trace.timeRange", {
              from: formatConsoleTimestamp(data.first_recorded_at),
              to: formatConsoleTimestamp(data.last_recorded_at),
              duration: traceOffset(data.steps[0]!, data.steps.at(-1)!),
            })}
          />
          <TraceContext
            label={t("evidence.trace.records")}
            value={t(
              data.action_attempt_count === 1
                ? "evidence.trace.recordSummaryOneAttempt"
                : "evidence.trace.recordSummary",
              {
              records: data.step_count,
              stages: summary.namedStageCount,
              attempts: data.action_attempt_count,
              },
            )}
          />
          <TraceContext
            label={t("evidence.trace.source")}
            value={t(
              data.source_authority === "operator-audit-log"
                ? "evidence.trace.sourceAuthority.operatorAuditLog"
                : "evidence.trace.sourceAuthority.legacy",
            )}
          />
          <TraceContext
            label={t("evidence.trace.lastUpdated")}
            value={loadedAt === null
              ? t("evidence.trace.notRecorded")
              : formatConsoleTimestamp(loadedAt)}
          />
        </dl>
      </details>

      {toolbar}

      {selectedStep === null ? (
        <p class="state-block">{t("evidence.trace.empty")}</p>
      ) : (
        <section
          class={`trace-workbench${data.steps.length <= 4 ? " is-compact" : ""}`}
          aria-label={t("evidence.trace.workbenchLabel")}
        >
          <aside class="trace-stage-rail">
            <header class="trace-pane-head">
              <div>
                <h3>{t("evidence.trace.recordedStages")}</h3>
                <p>{t("evidence.trace.recordedOrder")}</p>
              </div>
              <span>{t("evidence.trace.stageCount", { count: data.step_count })}</span>
            </header>
            <ol class="trace-stage-list" ref={stageListRef}>
              {data.steps.map((step, index) => {
                const selected = step.seq === selectedStep.seq;
                const state = stageState(step);
                return (
                  <li key={step.seq}>
                    <button
                      type="button"
                      class="trace-stage-select"
                      aria-pressed={selected}
                      aria-controls="trace-selected-stage-detail"
                      onClick={() => setSelectedSequence(step.seq)}
                      onKeyDown={(event) => {
                        const keyTarget = event.key === "Home"
                          ? 0
                          : event.key === "End"
                            ? data.steps.length - 1
                            : event.key === "ArrowUp"
                              ? Math.max(0, index - 1)
                              : event.key === "ArrowDown"
                                ? Math.min(data.steps.length - 1, index + 1)
                                : null;
                        if (keyTarget === null || keyTarget === index) return;
                        event.preventDefault();
                        const target = data.steps[keyTarget];
                        if (target === undefined) return;
                        setSelectedSequence(target.seq);
                        stageListRef.current
                          ?.querySelectorAll<HTMLButtonElement>(".trace-stage-select")
                          .item(keyTarget)
                          .focus();
                      }}
                    >
                      <span class="trace-stage-index" aria-hidden="true">{index + 1}</span>
                      <span class="trace-stage-copy">
                        <strong>
                          {step.stage === null
                            ? traceActionLabel(step.action_kind)
                            : traceStageLabel(step.stage)}
                        </strong>
                        <small>
                          <span>{traceActorLabel(step.actor)}</span>
                          <span aria-hidden="true"> / </span>
                          {traceOffset(data.steps[0]!, step)}
                          <span class="sr-only">
                            {t("evidence.trace.auditSequence", { sequence: step.seq })}
                          </span>
                        </small>
                      </span>
                      <span class="trace-stage-state">
                        <small>{state.label}</small>
                        <strong>{state.value}</strong>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ol>
          </aside>

          <TraceStepDetail
            correlationId={data.correlation_id}
            latestSequence={data.latest_sequence}
            step={selectedStep}
            steps={data.steps}
          />
        </section>
      )}

      <TraceActionLifecycleSection lifecycles={lifecycles} />

      <details class="trace-timeline-details">
        <summary>{t("evidence.trace.timelineDetailsCount", { count: data.step_count })}</summary>
        <TraceTimeline correlationId={data.correlation_id} steps={data.steps} />
      </details>
    </div>
  );
}

function TraceStepDetail({
  correlationId,
  latestSequence,
  step,
  steps,
}: {
  readonly correlationId: string;
  readonly latestSequence: number;
  readonly step: TraceStep;
  readonly steps: readonly TraceStep[];
}) {
  const status = step.outcome ?? step.decision ?? step.mode;
  return (
    <div class="trace-step-detail" id="trace-selected-stage-detail">
      <header class="trace-step-head">
        <div>
          <span class="trace-step-kicker">
            {step.seq === latestSequence
              ? t("evidence.trace.latestActivity")
              : t("evidence.trace.recordedActivity")}
            <span aria-hidden="true"> / </span>
            {t("evidence.trace.stageKicker", {
              sequence: step.seq,
              stage: traceStageLabel(step.stage),
            })}
          </span>
          <h3>{traceActionLabel(step.action_kind)}</h3>
          {step.reason === null ? (
            <p class="trace-no-reason">
              {t("evidence.trace.noReasonGuidance")}
              <a href={routeHref("audit", {
                params: { correlation: correlationId, entry: step.seq },
              })}>
                {t("evidence.trace.openRawEntry")}
              </a>
            </p>
          ) : <p>{step.reason}</p>}
        </div>
        <StatusPill kind={traceStepPill(step)} label={presentationLabel("status", status)} />
      </header>

      <dl class="trace-step-facts">
        <TraceFact
          label={t("evidence.trace.column.recordedAt")}
          value={(
            <Tooltip content={step.recorded_at}>
              <time dateTime={step.recorded_at}>
                {formatConsoleTimestamp(step.recorded_at)}
              </time>
            </Tooltip>
          )}
        />
        <TraceFact
          label={t("evidence.trace.column.decision")}
          value={step.decision === null
            ? t("evidence.trace.noValue")
            : presentationLabel("status", step.decision)}
        />
        <TraceFact
          label={t("evidence.trace.column.mode")}
          value={presentationLabel("status", step.mode)}
        />
        <TraceFact
          label={t("evidence.trace.attemptLabel")}
          value={step.action_id === null
            ? t("evidence.trace.notApplicable")
            : step.attempt ?? t("evidence.trace.noValue")}
        />
      </dl>

      <div class="trace-step-grid">
        <section>
          <h4>{t("evidence.trace.recordedEvidence")}</h4>
          {step.action_id === null
            && step.execution_path === null
            && step.outcome === null ? (
              <div class="trace-no-action">
                <strong>{t("evidence.trace.noActionPath")}</strong>
                <p>{t("evidence.trace.noActionPathBody")}</p>
                <code>{step.action_kind}</code>
              </div>
            ) : (
              <dl class="trace-evidence-grid">
                <TraceEvidenceDatum
                  label={t("evidence.trace.actionId")}
                  value={step.action_id}
                  copyable
                />
                <TraceEvidenceDatum
                  label={t("evidence.trace.column.actionKind")}
                  value={step.action_kind}
                />
                <TraceEvidenceDatum
                  label={t("evidence.trace.executionPath")}
                  value={step.execution_path}
                />
                <TraceEvidenceDatum
                  label={t("evidence.trace.outcome")}
                  value={step.outcome}
                />
              </dl>
            )}
        </section>
        <aside>
          <h4>{t("evidence.trace.auditReferences")}</h4>
          <p class="trace-integrity-note">{t("evidence.trace.chainNotVerified")}</p>
          <dl class="trace-integrity-list">
            <TraceEvidenceDatum
              label={t("evidence.trace.eventId")}
              value={step.event_id}
              copyable
            />
            <TraceEvidenceDatum
              label={t("evidence.trace.actor")}
              value={step.actor}
            />
            <TraceEvidenceDatum
              label={t("evidence.trace.sourceCorrelationId")}
              value={step.source_correlation_id}
              copyable
            />
            <TraceEvidenceDatum
              label={t("evidence.trace.entryHash")}
              value={step.entry_hash}
              copyable
            />
            <TraceEvidenceDatum
              label={t("evidence.trace.previousHash")}
              value={step.previous_hash}
              copyable
            />
            <TraceEvidenceDatum
              label={t("evidence.trace.correlationId")}
              value={correlationId}
              copyable
            />
          </dl>
          <p class="trace-join-note">
            {step.source_correlation_id === correlationId
              ? t("evidence.trace.directCorrelation")
              : t("evidence.trace.eventJoinedCorrelation")}
          </p>
        </aside>
      </div>

      <div class="trace-path" aria-label={t("evidence.trace.completePath")}>
        {steps.map((item) => (
          <span class={item.seq === step.seq ? "is-current" : undefined} key={item.seq}>
            {item.stage === null
              ? traceActionLabel(item.action_kind)
              : traceStageLabel(item.stage)}
          </span>
        ))}
      </div>
    </div>
  );
}

function TraceContext({
  label,
  value,
}: {
  readonly label: string;
  readonly value: ComponentChildren;
}) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function effectSummary(data: TraceResponse): {
  readonly value: string;
  readonly hint: string;
} {
  if (data.effect_observation_count > 0) {
    return {
      value: t("evidence.trace.effect.observed"),
      hint: t(
        data.effect_observation_count === 1
          ? "evidence.trace.effect.observedHintOne"
          : "evidence.trace.effect.observedHint",
        { count: data.effect_observation_count },
      ),
    };
  }
  if (data.action_attempt_count === 0) {
    return {
      value: t("evidence.trace.notApplicable"),
      hint: t("evidence.trace.effect.noAction"),
    };
  }
  const outcome = data.latest_outcome?.toLowerCase() ?? "";
  if (/(pending|awaiting|timeout|unknown)/.test(outcome)) {
    return {
      value: t("evidence.trace.effect.pending"),
      hint: data.latest_outcome === null
        ? t("evidence.trace.effect.notRecorded")
        : presentationLabel("status", data.latest_outcome),
    };
  }
  if (/(failed|denied|stopped|expired)/.test(outcome)) {
    return {
      value: t("evidence.trace.effect.failed"),
      hint: presentationLabel("status", data.latest_outcome ?? "failed"),
    };
  }
  return {
    value: t("evidence.trace.effect.notRecorded"),
    hint: t("evidence.trace.effect.noObservation"),
  };
}

function stageState(step: TraceStep): {
  readonly label: string;
  readonly value: string;
} {
  if (step.outcome !== null) {
    return {
      label: t("evidence.trace.outcome"),
      value: presentationLabel("status", step.outcome),
    };
  }
  if (step.decision !== null) {
    return {
      label: t("evidence.trace.column.decision"),
      value: presentationLabel("status", step.decision),
    };
  }
  return {
    label: t("evidence.trace.column.mode"),
    value: presentationLabel("status", step.mode),
  };
}

function TraceEvidenceDatum({
  copyable = false,
  label,
  value,
}: {
  readonly copyable?: boolean;
  readonly label: string;
  readonly value: string | null;
}) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        {value === null ? t("evidence.trace.noValue") : (
          <>
            <code>{value}</code>
            {copyable ? (
              <TraceCopyButton
                text={value}
                label={t("evidence.trace.copyValue", { label })}
              />
            ) : null}
          </>
        )}
      </dd>
    </div>
  );
}

function isNarrowTraceViewport(): boolean {
  return typeof window !== "undefined"
    && window.matchMedia("(max-width: 600px)").matches;
}
