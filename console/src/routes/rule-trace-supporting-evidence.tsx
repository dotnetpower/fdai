import {
  DataTable,
  StatusPill,
  type Column,
  type PillKind,
} from "../components/ui";
import { routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import { presentationLabel, t } from "./i18n/evidence";
import type {
  TraceActionLifecycle,
  TraceStep,
} from "./rule-trace";

export function TraceActionLifecycleSection({
  lifecycles,
}: {
  readonly lifecycles: readonly TraceActionLifecycle[];
}) {
  return (
    <section class="trace-lifecycle-section" aria-labelledby="trace-action-lifecycle-title">
      <span class="trace-section-label">{t("evidence.trace.readOnlyHint")}</span>
      <h3 id="trace-action-lifecycle-title">{t("evidence.trace.lifecycle.title")}</h3>
      <p>{t("evidence.trace.lifecycle.body")}</p>
      {lifecycles.length === 0 ? (
        <p class="state-block">{t("evidence.trace.lifecycle.noActionIdentity")}</p>
      ) : lifecycles.map((lifecycle) => (
        <article
          class="trace-action-lifecycle-group"
          key={`${lifecycle.actionId}:${lifecycle.attempt ?? "unknown"}`}
        >
          <h4>
            <code>{lifecycle.actionId}</code>
            <span>{lifecycle.attempt === null
              ? t("evidence.trace.lifecycle.attemptUnknown")
              : t("evidence.trace.lifecycle.attempt", { attempt: lifecycle.attempt })}</span>
          </h4>
          <ol class="approval-lifecycle trace-action-lifecycle">
            {lifecycle.stages.map((item, index) => (
              <li
                key={item.id}
                data-state={item.state === "recorded"
                  ? "complete"
                  : item.state === "not_attempted"
                    ? "not-started"
                    : item.state}
                aria-current={item.state === "pending" ? "step" : undefined}
              >
                <span aria-hidden="true">{index + 1}</span>
                <strong>{t(`evidence.trace.lifecycle.${item.id}`)}</strong>
                <small>
                  {item.evidence === null
                    ? t("evidence.trace.lifecycle.notRecorded")
                    : t("evidence.trace.lifecycle.evidence", {
                      sequence: item.evidence.seq,
                      kind: item.evidence.action_kind,
                      state: t(`evidence.trace.lifecycle.state.${item.state}`),
                    })}
                </small>
              </li>
            ))}
          </ol>
        </article>
      ))}
    </section>
  );
}

export function TraceTimeline({
  correlationId,
  steps,
}: {
  readonly correlationId: string;
  readonly steps: readonly TraceStep[];
}) {
  const columns: readonly Column<TraceStep>[] = [
    {
      key: "n",
      header: "#",
      render: (step) => (
        <a href={routeHref("audit", {
          params: { correlation: correlationId, entry: step.seq },
        })}>
          {step.seq}
        </a>
      ),
      cellClass: "num",
      headerClass: "num",
    },
    {
      key: "at",
      header: t("evidence.trace.column.recordedAt"),
      render: (step) => (
        <time dateTime={step.recorded_at} title={step.recorded_at}>
          {formatConsoleTimestamp(step.recorded_at)}
        </time>
      ),
      cellClass: "mono",
    },
    {
      key: "stage",
      header: t("evidence.trace.column.stage"),
      render: (step) => step.stage === null
        ? <span class="muted">{traceStageLabel(null)}</span>
        : <span title={step.stage}>{traceStageLabel(step.stage)}</span>,
      cellClass: "mono",
    },
    {
      key: "kind",
      header: t("evidence.trace.column.actionKind"),
      render: (step) => step.action_kind,
      cellClass: "mono",
    },
    {
      key: "decision",
      header: t("evidence.trace.column.decision"),
      render: (step) => step.decision === null
        ? <span class="muted">-</span>
        : <StatusPill
            kind={decisionPill(step.decision)}
            label={presentationLabel("status", step.decision)}
          />,
    },
    {
      key: "reason",
      header: t("evidence.trace.column.reason"),
      render: (step) => step.reason ?? <span class="muted">-</span>,
    },
    {
      key: "mode",
      header: t("evidence.trace.column.mode"),
      render: (step) => (
        <StatusPill
          kind={modePill(step.mode)}
          label={presentationLabel("status", step.mode)}
        />
      ),
    },
  ];
  return (
    <DataTable
      columns={columns}
      rows={steps}
      keyOf={(step) => step.seq}
      empty={t("evidence.trace.empty")}
    />
  );
}

export function latestRecordedDecision(steps: readonly TraceStep[]): string | null {
  for (let index = steps.length - 1; index >= 0; index -= 1) {
    const decision = steps[index]?.decision;
    if (decision !== null && decision !== undefined) return decision;
  }
  return null;
}

export function traceOffset(first: TraceStep, step: TraceStep): string {
  const elapsed = Date.parse(step.recorded_at) - Date.parse(first.recorded_at);
  const sign = elapsed < 0 ? "-" : "+";
  const absolute = Math.abs(elapsed);
  if (absolute < 1_000) return `${sign}${absolute} ms`;
  const seconds = absolute / 1_000;
  return `${sign}${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} s`;
}

export function traceStageLabel(stage: string | null): string {
  if (stage === null) return t("evidence.trace.unnamed");
  return presentationLabel("traceStage", stage);
}

export function traceActionLabel(actionKind: string): string {
  switch (actionKind) {
    case "measurement.control_loop.v1":
      return t("evidence.trace.action.controlLoopMeasurement");
    case "control_loop.compliant":
      return t("evidence.trace.action.controlLoopCompliant");
    case "action.proposal.recorded":
      return t("evidence.trace.action.proposalRecorded");
    case "risk_gate.unified":
      return t("evidence.trace.action.riskGateDecision");
    case "hil.approved.execution_pending":
      return t("evidence.trace.action.approvalRecorded");
    case "executor.remote.awaiting_effect_evidence":
      return t("evidence.trace.action.effectEvidencePending");
    case "effect_observation.recorded":
      return t("evidence.trace.action.effectObserved");
    case "t2.proposer.route.rolled_back":
      return t("evidence.trace.action.rollbackRecorded");
    default:
      return actionKind;
  }
}

export function traceStepPill(step: TraceStep): PillKind {
  if (step.outcome !== null) {
    const outcome = step.outcome.toLowerCase();
    if (/(fail|denied|stopped|expired)/.test(outcome)) return "danger";
    if (/(pending|awaiting|timeout|unknown)/.test(outcome)) return "hil";
    if (/(succeeded|verified|observed|rolled_back)/.test(outcome)) return "success";
    return "info";
  }
  return step.decision === null ? modePill(step.mode) : decisionPill(step.decision);
}

function decisionPill(decision: string): PillKind {
  const value = decision.toLowerCase();
  if (value === "auto") return "auto";
  if (value === "hil") return "hil";
  if (value === "deny" || value === "failed") return "danger";
  if (value === "done" || value === "ok") return "success";
  if (value === "abstain") return "neutral";
  return "info";
}

function modePill(mode: string): PillKind {
  if (mode === "enforce") return "enforce";
  if (mode === "shadow") return "shadow";
  return "neutral";
}
