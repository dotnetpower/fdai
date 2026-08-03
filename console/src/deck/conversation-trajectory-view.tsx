import type { ComponentChildren } from "preact";
import { useState } from "preact/hooks";

import { t } from "../i18n";
import type {
  EvidenceBranch,
  IntentGraphEvidence,
  IntentGraphMetadata,
  InvestigationActivity,
} from "./backend";
import type { ConversationTrajectory } from "./conversation-trajectory";
import { ConversationExecutionTimelineView } from "./conversation-execution-timeline-view";
import {
  phaseStateLabel,
  TrajectoryCoverage,
  TrajectoryDecisionContext,
} from "./conversation-trajectory-decision-context";
import { verificationPrimaryLabel } from "./verification-presentation";
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
  const { answer, activities, branches } = trajectory;
  const milestones = trajectory.milestones;
  const evidenceRefs = uniqueStrings([
    ...branches.flatMap((branch) => branch.evidenceRefs),
    ...(answer.verification?.evidence_refs ?? []),
  ]);
  const presentation = buildTrajectoryPresentation(trajectory);
  const [open, setOpen] = useState(presentation.workProgress === "timeline");
  const queryCount = activities.filter(
    (activity) => activity.execution?.inputKind === "query",
  ).length;
  const commandCount = activities.filter(
    (activity) => activity.execution?.inputKind === "command",
  ).length;
  const omittedDetailCount = answer.trajectoryDetail
    ? Object.values(answer.trajectoryDetail.omitted).reduce((total, count) => total + count, 0)
    : 0;
  const timelinePhases: TrajectoryPhase[] = [
    "input",
    ...(answer.intentGraph ? ["plan" as const] : []),
    ...(presentation.evidenceAttemptCount > 0 || milestones.length > 0 ? ["evidence" as const] : []),
    ...(answer.verification ? ["verification" as const] : []),
    "answer",
  ];
  const startedAt = firstValidTimestamp(trajectory.startedAt, trajectory.question.at);
  const completedAt = firstValidTimestamp(trajectory.completedAt, trajectory.answer.at);

  return (
    <div class={`deck-trajectory-cluster is-${presentation.workProgress}`}>
      <div class="deck-trajectory-results" aria-label={t("deck.trajectory.title")}>
        <span data-state="observed">
          {t("deck.trajectory.activitySummary", {
            queries: queryCount,
            commands: commandCount,
          })}
        </span>
        <span data-state={presentation.phaseStates.evidence}>
          {t("deck.trajectory.evidenceSummary", {
            successful: presentation.evidenceCompletedCount,
            attempted: presentation.evidenceAttemptCount,
            references: presentation.evidenceReferenceCount,
          })}
        </span>
        {answer.verification ? (
          <span data-state={presentation.phaseStates.verification}>
            {answer.verification.checks_completed}/{answer.verification.checks_total} {t("deck.trajectory.checks")}
          </span>
        ) : null}
      </div>
      <details
        class="deck-trajectory"
        open={open}
        onToggle={(event) => setOpen(event.currentTarget.open)}
      >
      <summary class="deck-trajectory-summary">
        <span class="deck-trajectory-title">
          <span class="deck-trajectory-glyph" aria-hidden="true" />
          <span class="deck-trajectory-title-copy">
            <small>{t("deck.trajectory.runRecord")}</small>
            <strong>{t("deck.trajectory.title")}</strong>
          </span>
        </span>
        <span class="deck-trajectory-stats">
          {t(!showModelTrace
            ? "deck.trajectory.summaryTraceOff"
            : answer.modelTrace
              ? "deck.trajectory.summary"
              : "deck.trajectory.summaryTraceMissing", {
            models: presentation.modelCallCountIsLowerBound
              ? `${presentation.modelCallCount}+`
              : presentation.modelCallCount,
            successful: presentation.evidenceCompletedCount,
            attempted: presentation.evidenceAttemptCount,
            verification: phaseStateLabel(presentation.phaseStates.verification),
          })}
        </span>
        <span class="deck-trajectory-duration">
          {trajectory.durationMs === undefined
            ? t("deck.trajectory.sequenceOnly")
            : t("deck.trajectory.endToEndDuration", {
                duration: formatDuration(trajectory.durationMs),
              })}
        </span>
        <span class="deck-trajectory-chevron" aria-hidden="true" />
        <span class="deck-trajectory-question">
          <small>{t("deck.trajectory.phase.input")}</small>
          <strong>{trajectory.question.text}</strong>
        </span>
      </summary>
      {open ? (
        <div class="deck-trajectory-body">
          <PhaseStrip phaseStates={presentation.phaseStates} />
          <ConversationExecutionTimelineView trajectory={trajectory}
            includeModelCalls={showModelTrace} />
          <ModelTraceWaterfall
            captureEnabled={showModelTrace}
            {...(showModelTrace && answer.modelTrace ? { trace: answer.modelTrace } : {})}
          />
          <dl class="deck-trajectory-signals">
            <div data-state={presentation.phaseStates.evidence}>
              <dt>{t("deck.trajectory.phase.evidence")}</dt>
              <dd>{t("deck.trajectory.evidenceSummary", {
                successful: presentation.evidenceCompletedCount,
                attempted: presentation.evidenceAttemptCount,
                references: presentation.evidenceReferenceCount,
              })}</dd>
            </div>
            <div data-state={presentation.phaseStates.verification}>
              <dt>{t("deck.trajectory.authority")}</dt>
              <dd>{answer.verification?.authority ?? t("deck.trajectory.none")}</dd>
            </div>
            <div data-state={presentation.phaseStates.answer}>
              <dt>{t("deck.trajectory.source")}</dt>
              <dd>{answer.source ?? answer.agent ?? t("deck.trajectory.none")}</dd>
            </div>
          </dl>
          <details class="deck-trajectory-records">
            <summary>
              <strong>{t("deck.trajectory.executionDetails")}</strong>
              <span>{timelinePhases.length}</span>
            </summary>
            <div class="deck-trajectory-window">
              <Timestamp value={startedAt} />
              <span aria-hidden="true" />
              <Timestamp value={completedAt} />
            </div>
            <TrajectoryDecisionContext trajectory={trajectory}
              collaborationState={presentation.phaseStates.collaboration} />
            <ol class="deck-trajectory-events">
            <TrajectoryPhase index={phaseIndex(timelinePhases, "input")} phase="input"
              state={presentation.phaseStates.input} heading={t("deck.trajectory.phase.input")}
              summary={trajectory.question.text} time={formatTimestamp(startedAt)}
              {...(startedAt ? { dateTime: startedAt } : {})}>
              <p class="deck-trajectory-prose">{trajectory.question.text}</p>
            </TrajectoryPhase>
            {answer.intentGraph ? (
              <IntentGraphPhase
                graph={answer.intentGraph}
                {...(answer.intentGraphEvidence ? { evidence: answer.intentGraphEvidence } : {})}
                index={phaseIndex(timelinePhases, "plan")}
                state={presentation.phaseStates.plan}
              />
            ) : null}
            {timelinePhases.includes("evidence") ? (
              <TrajectoryPhase index={phaseIndex(timelinePhases, "evidence")} phase="evidence"
                state={presentation.phaseStates.evidence} heading={t("deck.trajectory.phase.evidence")}
                summary={t("deck.trajectory.evidenceSummary", {
                  successful: presentation.evidenceCompletedCount,
                  attempted: presentation.evidenceAttemptCount,
                  references: evidenceRefs.length,
                })}>
                <EvidenceTimeline activities={activities} branches={branches} milestones={milestones} />
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
          </details>
        </div>
      ) : null}
      </details>
    </div>
  );
}

function IntentGraphPhase({
  graph,
  evidence,
  index,
  state,
}: {
  readonly graph: IntentGraphMetadata;
  readonly evidence?: IntentGraphEvidence;
  readonly index: string;
  readonly state: TrajectoryPhaseState;
}) {
  const receipts = new Map((evidence?.goals ?? []).map((goal) => [goal.goal_id, goal]));
  const mode = evidence?.evidence_mode ?? "held_for_review";
  return (
    <TrajectoryPhase
      index={index}
      phase="plan"
      state={state}
      heading={t("deck.trajectory.phase.plan")}
      summary={t("deck.trajectory.planSummary", {
        count: graph.goals.length,
        mode: t(`deck.trajectory.evidenceMode.${mode}`),
      })}
    >
      <ol class="deck-trajectory-goals" aria-label={t("deck.trajectory.goalsLabel")}>
        {graph.goals.map((goal, goalIndex) => {
          const receipt = receipts.get(goal.goal_id);
          const status = receipt?.status ?? "planned";
          return (
            <li key={goal.goal_id} data-status={status}>
              <span class="deck-trajectory-goal-index" aria-hidden="true">
                {String(goalIndex + 1).padStart(2, "0")}
              </span>
              <span class="deck-trajectory-goal-copy">
                <strong>{t("deck.trajectory.goalLabel", { index: goalIndex + 1 })}</strong>
                <code>{goal.capability ?? t("deck.trajectory.contextGoal")}</code>
                {goal.depends_on.length > 0 ? (
                  <small>{t("deck.trajectory.dependsOn", {
                    goals: goal.depends_on.join(", "),
                  })}</small>
                ) : null}
              </span>
              <span class={`deck-trajectory-goal-status is-${status}`}>
                {status === "planned"
                  ? t("deck.trajectory.planned")
                  : t(`deck.investigation.${status}`)}
              </span>
            </li>
          );
        })}
      </ol>
    </TrajectoryPhase>
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
          <span aria-hidden="true">{phaseMark(phaseStates[phase], index)}</span>
          <strong>{t(`deck.trajectory.phase.${phase}`)}</strong>
          <small>{phaseStateLabel(phaseStates[phase])}</small>
        </li>
      ))}
    </ol>
  );
}

function phaseMark(state: TrajectoryPhaseState, index: number): string {
  if (state === "completed") return "✓";
  if (state === "corrected") return "R";
  if (state === "degraded" || state === "unverified") return "!";
  if (state === "failed") return "x";
  if (state === "running") return "...";
  return String(index + 1).padStart(2, "0");
}

function VerificationPhase({ trajectory, index, state }: {
  readonly trajectory: ConversationTrajectory;
  readonly index: string;
  readonly state: TrajectoryPhaseState;
}) {
  const verification = trajectory.answer.verification;
  if (!verification) return null;
  const statusLabel = verificationPrimaryLabel(verification);
  return (
    <TrajectoryPhase index={index} phase="verification" state={state}
      heading={t("deck.trajectory.phase.verification")}
      summary={`${statusLabel} / ${verification.checks_completed}/${verification.checks_total}`}>
      <dl class="deck-trajectory-facts">
        <dt>{t("deck.trajectory.status")}</dt><dd>{statusLabel}</dd>
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
      heading={t("deck.trajectory.phase.answer")}
      summary={answer.source ?? answer.agent ?? t("deck.trajectory.recorded")}
      time={formatTimestamp(firstValidTimestamp(trajectory.completedAt, answer.at))}
      {...(firstValidTimestamp(trajectory.completedAt, answer.at)
        ? { dateTime: firstValidTimestamp(trajectory.completedAt, answer.at)! }
        : {})}>
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

function TrajectoryPhase({ index, phase, state, heading, summary, time, dateTime, children }: {
  readonly index: string; readonly phase: TrajectoryPhase; readonly state: TrajectoryPhaseState;
  readonly heading: string; readonly summary: string; readonly time?: string; readonly dateTime?: string;
  readonly children: ComponentChildren;
}) {
  return (
    <li class="deck-trajectory-event" data-phase={phase} data-state={state}>
      <span class="deck-trajectory-event-index" aria-hidden="true">{index}</span>
      <details>
        <summary><span><strong>{heading}</strong><small>{summary}</small></span>
          <span class="deck-trajectory-event-meta">
            {time ? <Timestamp value={dateTime} fallback={time} /> : null}
            <span class="deck-trajectory-state">{phaseStateLabel(state)}</span>
          </span>
        </summary>
        <div class="deck-trajectory-event-detail">{children}</div>
      </details>
    </li>
  );
}

function EvidenceTimeline({ activities, branches, milestones }: {
  readonly activities: readonly InvestigationActivity[];
  readonly branches: readonly EvidenceBranch[]; readonly milestones: ConversationTrajectory["milestones"];
}) {
  return (
      <ol class="deck-trajectory-evidence">
        {branches.map((branch) => {
          const startedAt = firstValidTimestamp(branch.startedAt);
          return (
        <li key={branch.branchId} data-status={branch.status}>
          <details><summary><span class={`deck-trajectory-kind is-${branch.kind}`}>{t(`deck.investigation.kind.${branch.kind}`)}</span>
            <strong>{t(`deck.investigation.${branch.status}`)}</strong>
            <span><Timestamp value={startedAt} />
              {branch.durationMs !== undefined ? ` / ${formatDuration(branch.durationMs)}` : ""}</span></summary>
            <p>{branch.summary}</p><ReferenceList refs={branch.evidenceRefs} /></details>
        </li>
          );
        })}
        {activities.map((activity) => {
          const observedAt = firstValidTimestamp(activity.execution?.startedAt, activity.observedAt);
          return (
        <li key={activity.activityId} data-status={activity.status}>
          <details><summary><span class="deck-trajectory-kind is-activity">{activity.execution?.inputKind ?? activity.kind}</span>
            <strong>{activity.label}</strong><Timestamp value={observedAt} /></summary>
            {activity.detail ? <p>{activity.detail}</p> : null}
            <dl class="deck-trajectory-facts">
              <dt>{t("deck.trajectory.status")}</dt><dd>{t(`deck.investigation.${activity.status}`)}</dd>
              <dt>{t("deck.trajectory.agent")}</dt><dd>{activity.agent ?? t("deck.trajectory.none")}</dd>
              <dt>{t("deck.trajectory.authority")}</dt><dd>{activity.authority ?? t("deck.trajectory.none")}</dd>
            </dl>
            {activity.execution ? <ExecutionDetail activity={activity} /> : null}
          </details>
        </li>
          );
        })}
        {milestones.map((milestone) => {
          const recordedAt = firstValidTimestamp(milestone.recordedAt);
          return (
        <li key={milestone.messageId} data-status="completed"><span class="deck-trajectory-milestone" aria-hidden="true" />
          <div class="deck-trajectory-milestone-copy"><span class="deck-trajectory-kind is-milestone">{t("deck.trajectory.milestone")}</span>
            <strong>{milestone.text}</strong><Timestamp value={recordedAt} /></div></li>
          );
        })}
      </ol>
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

function Timestamp({ value, fallback }: {
  readonly value: string | undefined;
  readonly fallback?: string;
}) {
  const timestamp = firstValidTimestamp(value);
  return timestamp
    ? <time class="deck-trajectory-timestamp" dateTime={timestamp}>{formatTimestamp(timestamp)}</time>
    : <span class="deck-trajectory-timestamp">{fallback ?? t("deck.trajectory.notRecorded")}</span>;
}

function uniqueStrings(values: readonly string[]): string[] { return [...new Set(values.filter(Boolean))]; }
function validTimestamp(value: string | undefined): value is string { return value !== undefined && Number.isFinite(Date.parse(value)); }
function firstValidTimestamp(...values: readonly (string | undefined)[]): string | undefined {
  return values.find(validTimestamp);
}
