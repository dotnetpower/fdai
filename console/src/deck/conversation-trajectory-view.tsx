import type { ComponentChildren } from "preact";
import { useState } from "preact/hooks";

import { t } from "../i18n";
import type { EvidenceBranch, InvestigationActivity } from "./backend";
import type { ConversationTrajectory } from "./conversation-trajectory";
import { ConversationExecutionTimelineView } from "./conversation-execution-timeline-view";
import {
  phaseStateLabel,
  TrajectoryCoverage,
  TrajectoryDecisionContext,
} from "./conversation-trajectory-decision-context";
import {
  buildTrajectoryPresentation,
  TRAJECTORY_PHASES,
  type TrajectoryPhase,
  type TrajectoryPhaseState,
} from "./conversation-trajectory-presentation";
import { JsonCodeBlock } from "./json-code-block";
import { ModelTraceWaterfall } from "./model-trace-waterfall";

export function ConversationTrajectoryView({
  trajectory,
  showModelTrace,
}: {
  readonly trajectory: ConversationTrajectory;
  readonly showModelTrace: boolean;
}) {
  const [open, setOpen] = useState(false);
  const { answer, activities, branches } = trajectory;
  const milestones = trajectory.milestones;
  const evidenceRefs = uniqueStrings([
    ...branches.flatMap((branch) => branch.evidenceRefs),
    ...(answer.verification?.evidence_refs ?? []),
  ]);
  const presentation = buildTrajectoryPresentation(trajectory);
  const omittedDetailCount = answer.trajectoryDetail
    ? Object.values(answer.trajectoryDetail.omitted).reduce((total, count) => total + count, 0)
    : 0;
  const timelinePhases: TrajectoryPhase[] = [
    "input",
    ...(presentation.evidenceAttemptCount > 0 || milestones.length > 0 ? ["evidence" as const] : []),
    ...(answer.verification ? ["verification" as const] : []),
    "answer",
  ];

  return (
    <details class="deck-trajectory" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary class="deck-trajectory-summary">
        <span class="deck-trajectory-title">
          <span class="deck-trajectory-glyph" aria-hidden="true" />
          {t("deck.trajectory.title")}
        </span>
        <span class="deck-trajectory-stats">
          {t("deck.trajectory.summary", {
            models: showModelTrace ? presentation.modelCallCount : 0,
            successful: presentation.evidenceCompletedCount,
            attempted: presentation.evidenceAttemptCount,
            verification: phaseStateLabel(presentation.phaseStates.verification),
          })}
        </span>
        <span class="deck-trajectory-duration">
          {trajectory.durationMs === undefined
            ? t("deck.trajectory.sequenceOnly")
            : formatDuration(trajectory.durationMs)}
        </span>
      </summary>
      {open ? (
        <div class="deck-trajectory-body">
          <PhaseStrip phaseStates={presentation.phaseStates} />
          <div class="deck-trajectory-window">
            <span>{formatTimestamp(trajectory.startedAt, trajectory.question.at)}</span>
            <span aria-hidden="true" />
            <span>{formatTimestamp(trajectory.completedAt, trajectory.answer.at)}</span>
          </div>
          <TrajectoryDecisionContext trajectory={trajectory}
            collaborationState={presentation.phaseStates.collaboration} />
          <ConversationExecutionTimelineView trajectory={trajectory}
            includeModelCalls={showModelTrace} />
          {showModelTrace ? (
            <ModelTraceWaterfall {...(answer.modelTrace ? { trace: answer.modelTrace } : {})} />
          ) : null}
          <h4 class="deck-trajectory-execution-title">{t("deck.trajectory.executionDetails")}</h4>
          <ol class="deck-trajectory-events">
            <TrajectoryPhase index={phaseIndex(timelinePhases, "input")} phase="input"
              state={presentation.phaseStates.input} title={t("deck.trajectory.phase.input")}
              summary={trajectory.question.text} time={formatTimestamp(trajectory.startedAt, trajectory.question.at)}>
              <p class="deck-trajectory-prose">{trajectory.question.text}</p>
            </TrajectoryPhase>
            {timelinePhases.includes("evidence") ? (
              <TrajectoryPhase index={phaseIndex(timelinePhases, "evidence")} phase="evidence"
                state={presentation.phaseStates.evidence} title={t("deck.trajectory.phase.evidence")}
                summary={t("deck.trajectory.evidenceSummary", {
                  successful: presentation.evidenceCompletedCount,
                  attempted: presentation.evidenceAttemptCount,
                  references: evidenceRefs.length,
                })}>
                <EvidenceTimeline trajectory={trajectory} activities={activities} branches={branches}
                  milestones={milestones} evidenceRefs={evidenceRefs} />
              </TrajectoryPhase>
            ) : null}
            {answer.verification ? (
              <VerificationPhase trajectory={trajectory}
                index={phaseIndex(timelinePhases, "verification")}
                state={presentation.phaseStates.verification} />
            ) : null}
            <AnswerPhase trajectory={trajectory} index={phaseIndex(timelinePhases, "answer")} />
          </ol>
          <TrajectoryCoverage phaseStates={presentation.phaseStates} />
          {answer.trajectoryDetail &&
              (omittedDetailCount > 0 || answer.trajectoryDetail.truncated_outputs > 0) ? (
            <p class="deck-trajectory-gap">
              {t("deck.trajectory.historyDetailBound", {
                omitted: omittedDetailCount,
                truncated: answer.trajectoryDetail.truncated_outputs,
              })}
            </p>
          ) : null}
        </div>
      ) : null}
    </details>
  );
}

function PhaseStrip({
  phaseStates,
}: {
  readonly phaseStates: Readonly<Record<TrajectoryPhase, TrajectoryPhaseState>>;
}) {
  return (
    <ol class="deck-trajectory-phase-strip" aria-label={t("deck.trajectory.phaseLabel")}>
      {TRAJECTORY_PHASES.map((phase, index) => (
        <li key={phase} data-state={phaseStates[phase]}>
          <span>{String(index + 1).padStart(2, "0")}</span>
          <strong>{t(`deck.trajectory.phase.${phase}`)}</strong>
          <small>{phaseStateLabel(phaseStates[phase])}</small>
        </li>
      ))}
    </ol>
  );
}

function VerificationPhase({ trajectory, index, state }: {
  readonly trajectory: ConversationTrajectory;
  readonly index: string;
  readonly state: TrajectoryPhaseState;
}) {
  const verification = trajectory.answer.verification;
  if (!verification) return null;
  return (
    <TrajectoryPhase index={index} phase="verification" state={state}
      title={t("deck.trajectory.phase.verification")}
      summary={`${t(`deck.grounded.verificationStatus.${verification.status}`)} / ${verification.checks_completed}/${verification.checks_total}`}>
      <dl class="deck-trajectory-facts">
        <dt>{t("deck.trajectory.status")}</dt><dd>{t(`deck.grounded.verificationStatus.${verification.status}`)}</dd>
        <dt>{t("deck.trajectory.checks")}</dt><dd>{verification.checks_completed}/{verification.checks_total}</dd>
      </dl>
      <details class="deck-trajectory-nested">
        <summary>{t("deck.trajectory.technicalDetails")}</summary>
        <dl class="deck-trajectory-facts">
          <dt>{t("deck.trajectory.authority")}</dt><dd><code>{verification.authority}</code></dd>
          <dt>{t("deck.trajectory.reason")}</dt><dd><code>{verification.reason_code ?? t("deck.trajectory.none")}</code></dd>
        </dl>
      </details>
          <ReferenceList refs={verification.evidence_refs} />
          {verification.claims?.length ? (
            <ol class="deck-trajectory-claims">
              {verification.claims.map((claim) => (
                <li key={claim.claim_id} data-status={claim.status}>
                  <span>{claim.status}</span><p>{claim.text}</p><ReferenceList refs={claim.evidence_refs} />
                </li>
              ))}
            </ol>
          ) : null}
          {verification.evidence_manifest?.entries.length ? (
            <details class="deck-trajectory-nested">
              <summary>{t("deck.trajectory.manifest", { count: verification.evidence_manifest.entries.length })}</summary>
              <ul class="deck-trajectory-manifest">
                {verification.evidence_manifest.entries.map((entry) => (
                  <li key={entry.ref}><code>{entry.ref}</code><span>{entry.path} / {entry.field}</span><small>{entry.raw_value}</small></li>
                ))}
              </ul>
            </details>
          ) : null}
    </TrajectoryPhase>
  );
}

function AnswerPhase({ trajectory, index }: {
  readonly trajectory: ConversationTrajectory;
  readonly index: string;
}) {
  const { answer } = trajectory;
  return (
    <TrajectoryPhase index={index} phase="answer" state="completed"
      title={t("deck.trajectory.phase.answer")}
      summary={answer.source ?? answer.agent ?? t("deck.trajectory.recorded")}
      time={formatTimestamp(trajectory.completedAt, answer.at)}>
      <dl class="deck-trajectory-facts">
        <dt>{t("deck.trajectory.agent")}</dt><dd>{answer.agent ?? t("deck.trajectory.none")}</dd>
        <dt>{t("deck.trajectory.source")}</dt><dd>{answer.source ?? t("deck.trajectory.none")}</dd>
        {answer.resourceContext ? (
          <><dt>{t("deck.trajectory.resource")}</dt><dd>{answer.resourceContext.name} ({answer.resourceContext.resource_type})</dd></>
        ) : null}
      </dl>
      {answer.codeArtifacts?.map((artifact) => (
        <details key={artifact.artifact_ref} class="deck-trajectory-nested">
          <summary>{artifact.language} / {t(`deck.codeEvidence.status.${artifact.validation_status}`)}</summary>
          <code>{artifact.artifact_ref}</code><pre><code>{artifact.content}</code></pre>
        </details>
      ))}
      {answer.actionDraft ? (
        <details class="deck-trajectory-nested">
          <summary>{t("deck.actionDraft.title")}: {answer.actionDraft.actionType}</summary>
          <JsonCodeBlock value={answer.actionDraft.arguments} />
        </details>
      ) : null}
    </TrajectoryPhase>
  );
}

function TrajectoryPhase({ index, phase, state, title, summary, time, children }: {
  readonly index: string; readonly phase: TrajectoryPhase; readonly state: TrajectoryPhaseState;
  readonly title: string; readonly summary: string; readonly time?: string;
  readonly children: ComponentChildren;
}) {
  return (
    <li class="deck-trajectory-event" data-phase={phase} data-state={state}>
      <span class="deck-trajectory-event-index" aria-hidden="true">{index}</span>
      <details>
        <summary><span><strong>{title}</strong><small>{summary}</small></span>
          <span class="deck-trajectory-event-meta">
            {time ? <time>{time}</time> : null}
            <span class="deck-trajectory-state">{phaseStateLabel(state)}</span>
          </span>
        </summary>
        <div class="deck-trajectory-event-detail">{children}</div>
      </details>
    </li>
  );
}

function EvidenceTimeline({ trajectory, activities, branches, milestones, evidenceRefs }: {
  readonly trajectory: ConversationTrajectory; readonly activities: readonly InvestigationActivity[];
  readonly branches: readonly EvidenceBranch[]; readonly milestones: ConversationTrajectory["milestones"];
  readonly evidenceRefs: readonly string[];
}) {
  return (
    <>
      <ReferenceList refs={evidenceRefs} />
      <ol class="deck-trajectory-evidence">
        {branches.map((branch) => (
        <li key={branch.branchId} data-status={branch.status}>
          <details><summary><span class={`deck-trajectory-kind is-${branch.kind}`}>{t(`deck.investigation.kind.${branch.kind}`)}</span>
            <strong>{t(`deck.investigation.${branch.status}`)}</strong><time>{formatTimestamp(branch.startedAt)}{branch.durationMs !== undefined ? ` / ${formatDuration(branch.durationMs)}` : ""}</time></summary>
            <p>{branch.summary}</p><ReferenceList refs={branch.evidenceRefs} /></details>
        </li>
        ))}
        {activities.map((activity) => (
        <li key={activity.activityId} data-status={activity.status}>
          <details><summary><span class="deck-trajectory-kind is-activity">{activity.execution?.inputKind ?? activity.kind}</span>
            <strong>{activity.label}</strong><time>{formatTimestamp(activity.execution?.startedAt ?? activity.observedAt)}</time></summary>
            {activity.detail ? <p>{activity.detail}</p> : null}
            <dl class="deck-trajectory-facts">
              <dt>{t("deck.trajectory.status")}</dt><dd>{t(`deck.investigation.${activity.status}`)}</dd>
              <dt>{t("deck.trajectory.agent")}</dt><dd>{activity.agent ?? t("deck.trajectory.none")}</dd>
              <dt>{t("deck.trajectory.authority")}</dt><dd>{activity.authority ?? t("deck.trajectory.none")}</dd>
            </dl>
            {activity.execution ? <ExecutionDetail activity={activity} /> : null}
          </details>
        </li>
        ))}
        {milestones.map((milestone) => (
        <li key={milestone.messageId} data-status="completed"><span class="deck-trajectory-milestone" aria-hidden="true" />
          <div class="deck-trajectory-milestone-copy"><span class="deck-trajectory-kind is-milestone">{t("deck.trajectory.milestone")}</span>
            <strong>{milestone.text}</strong><time>{formatTimestamp(milestone.recordedAt)}</time></div></li>
        ))}
      </ol>
    </>
  );
}

function ExecutionDetail({ activity }: { readonly activity: InvestigationActivity }) {
  const execution = activity.execution;
  if (!execution) return null;
  return (
    <><JsonCodeBlock value={execution.command} />
      {execution.output !== undefined ? (
        <details class="deck-trajectory-nested"><summary>{execution.inputKind === "query"
          ? t("deck.investigation.queryResult") : t("deck.investigation.outputLogs")}</summary>
          <JsonCodeBlock value={execution.output} /></details>
      ) : null}</>
  );
}

function ReferenceList({ refs }: { readonly refs: readonly string[] }) {
  return refs.length === 0 ? null : (
    <ul class="deck-trajectory-refs" aria-label={t("deck.trajectory.references")}>
      {refs.map((ref) => <li key={ref}><code>{ref}</code></li>)}
    </ul>
  );
}

function phaseIndex(phases: readonly TrajectoryPhase[], phase: TrajectoryPhase): string {
  return String(phases.indexOf(phase) + 1).padStart(2, "0");
}

function formatDuration(durationMs: number): string {
  if (durationMs < 1000) return `${Math.round(durationMs)} ms`;
  if (durationMs < 60_000) return `${(durationMs / 1000).toFixed(1)} s`;
  return `${Math.floor(durationMs / 60_000)}m ${Math.round((durationMs % 60_000) / 1000)}s`;
}

function formatTimestamp(value: string | undefined, fallback: string = t("deck.trajectory.notRecorded")): string {
  if (!validTimestamp(value)) return fallback;
  return new Date(value).toLocaleTimeString([], {
    hour: "2-digit", minute: "2-digit", second: "2-digit", fractionalSecondDigits: 3,
  });
}

function uniqueStrings(values: readonly string[]): string[] { return [...new Set(values.filter(Boolean))]; }
function validTimestamp(value: string | undefined): value is string { return value !== undefined && Number.isFinite(Date.parse(value)); }
