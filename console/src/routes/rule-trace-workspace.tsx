import type { ComponentChildren } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
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
  latestRecordedDecision,
  traceActionLabel,
  traceOffset,
  traceStageLabel,
  traceStepPill,
  TraceActionLifecycleSection,
  TraceTimeline,
} from "./rule-trace-supporting-evidence";
import { TraceFact, TraceMetric } from "./rule-trace-layout";

interface Props {
  readonly data: TraceResponse;
  readonly lifecycles: readonly TraceActionLifecycle[];
  readonly summary: TraceOperationalSummary;
  readonly toolbar: ComponentChildren;
}

export function RuleTraceWorkspace({
  data,
  lifecycles,
  summary,
  toolbar,
}: Props) {
  const [selectedSequence, setSelectedSequence] = useState(
    data.steps.at(-1)?.seq ?? null,
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

  const selectedStep = data.steps.find((step) => step.seq === selectedSequence)
    ?? data.steps.at(-1)
    ?? null;
  const latestDecision = latestRecordedDecision(data.steps);
  const auditHref = routeHref("audit", {
    params: { correlation: data.correlation_id },
  });

  return (
    <div class="trace-ready-workspace">
      <section class="trace-metrics" aria-label={t("evidence.trace.summaryLabel")}>
        <TraceMetric
          href={auditHref}
          label={t("evidence.trace.summary.decision")}
          value={latestDecision === null
            ? t("evidence.trace.summary.notRecorded")
            : presentationLabel("status", latestDecision)}
          hint={summary.notificationEscalation
            ? t("evidence.trace.summary.notificationEscalation")
            : summary.decisionRecorded
              ? t("evidence.trace.summary.decisionRecorded")
              : t("evidence.trace.summary.activityOnly")}
        />
        <TraceMetric
          href={routeHref("rca", { params: { correlation: data.correlation_id } })}
          label={t("evidence.trace.summary.rootCause")}
          value={summary.rcaRecorded
            ? t("evidence.trace.summary.recorded")
            : t("evidence.trace.summary.notRecorded")}
          hint={t("evidence.trace.readOnlyHint")}
        />
        <TraceMetric
          href={auditHref}
          label={t("evidence.trace.summary.pipelineStages")}
          value={summary.namedStageCount}
          hint={t("evidence.trace.terminalHint", {
            stage: data.terminal_stage === null
              ? t("evidence.trace.noValue")
              : traceStageLabel(data.terminal_stage),
          })}
        />
        <TraceMetric
          href={auditHref}
          label={t("evidence.trace.steps")}
          value={data.step_count}
          hint={t("evidence.trace.actionAttemptsHint", { count: lifecycles.length })}
        />
      </section>

      {toolbar}

      {selectedStep === null ? (
        <p class="state-block">{t("evidence.trace.empty")}</p>
      ) : (
        <section
          class="trace-workbench"
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
                const stateLabel = presentationLabel(
                  "status",
                  step.outcome ?? step.decision ?? step.mode,
                );
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
                        <strong>{traceStageLabel(step.stage)}</strong>
                        <small title={`${step.action_kind} / ${traceOffset(data.steps[0]!, step)}`}>
                          <code>{step.action_kind}</code>
                          <span aria-hidden="true"> / </span>
                          {traceOffset(data.steps[0]!, step)}
                          <span class="sr-only">
                            {t("evidence.trace.auditSequence", { sequence: step.seq })}
                          </span>
                        </small>
                      </span>
                      <span class="trace-stage-state" title={stateLabel}>
                        {stateLabel}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ol>
          </aside>

          <TraceStepDetail
            correlationId={data.correlation_id}
            step={selectedStep}
            steps={data.steps}
          />
        </section>
      )}

      <TraceActionLifecycleSection lifecycles={lifecycles} />

      <details class="trace-timeline-details">
        <summary>{t("evidence.trace.timelineDetails")}</summary>
        <TraceTimeline correlationId={data.correlation_id} steps={data.steps} />
      </details>
    </div>
  );
}

function TraceStepDetail({
  correlationId,
  step,
  steps,
}: {
  readonly correlationId: string;
  readonly step: TraceStep;
  readonly steps: readonly TraceStep[];
}) {
  const status = step.outcome ?? step.decision ?? step.mode;
  return (
    <div class="trace-step-detail" id="trace-selected-stage-detail">
      <header class="trace-step-head">
        <div>
          <span class="trace-step-kicker">
            {t("evidence.trace.stageKicker", {
              sequence: step.seq,
              stage: traceStageLabel(step.stage),
            })}
          </span>
          <h3>{traceActionLabel(step.action_kind)}</h3>
          <p>{step.reason ?? t("evidence.trace.noReason")}</p>
        </div>
        <StatusPill kind={traceStepPill(step)} label={presentationLabel("status", status)} />
      </header>

      <dl class="trace-step-facts">
        <TraceFact
          label={t("evidence.trace.column.recordedAt")}
          value={(
            <time dateTime={step.recorded_at} title={step.recorded_at}>
              {formatConsoleTimestamp(step.recorded_at)}
            </time>
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
          value={step.attempt ?? t("evidence.trace.noValue")}
        />
      </dl>

      <div class="trace-step-grid">
        <section>
          <h4>{t("evidence.trace.recordedEvidence")}</h4>
          <dl class="trace-evidence-grid">
            <TraceEvidenceDatum
              label={t("evidence.trace.actionId")}
              value={step.action_id}
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
        </section>
        <aside>
          <h4>{t("evidence.trace.integrityEvidence")}</h4>
          <dl class="trace-integrity-list">
            <TraceEvidenceDatum
              label={t("evidence.trace.entryHash")}
              value={step.entry_hash}
            />
            <TraceEvidenceDatum
              label={t("evidence.trace.correlationId")}
              value={correlationId}
            />
          </dl>
        </aside>
      </div>

      <div class="trace-path" aria-label={t("evidence.trace.completePath")}>
        {steps.map((item) => (
          <span class={item.seq === step.seq ? "is-current" : undefined} key={item.seq}>
            {item.stage === null ? `#${item.seq}` : traceStageLabel(item.stage)}
          </span>
        ))}
      </div>
    </div>
  );
}

function TraceEvidenceDatum({
  label,
  value,
}: {
  readonly label: string;
  readonly value: string | null;
}) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value === null ? t("evidence.trace.noValue") : <code>{value}</code>}</dd>
    </div>
  );
}
