import type { ComponentChildren } from "preact";
import { useState } from "preact/hooks";

import { t } from "../i18n";
import type { EvidenceBranch, InvestigationActivity } from "./backend";
import type { ConversationTrajectory } from "./conversation-trajectory";

const PHASES = ["input", "plan", "collaboration", "evidence", "verification", "answer"] as const;
type Phase = typeof PHASES[number];

export function ConversationTrajectoryView({ trajectory }: { readonly trajectory: ConversationTrajectory }) {
  const [open, setOpen] = useState(false);
  const { answer, activities, branches } = trajectory;
  const milestones = trajectory.observedTurns.filter(
    (turn) => turn.kind === "message" && turn.source === "investigation",
  );
  const evidenceRefs = uniqueStrings([
    ...branches.flatMap((branch) => branch.evidenceRefs),
    ...(answer.verification?.evidence_refs ?? []),
  ]);
  const recorded = recordedPhases(trajectory, milestones.length, evidenceRefs.length);
  const observedSteps = recorded.size + activities.length + branches.length + milestones.length;

  return (
    <details class="deck-trajectory" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary class="deck-trajectory-summary">
        <span class="deck-trajectory-title">
          <span class="deck-trajectory-glyph" aria-hidden="true" />
          {t("deck.trajectory.title")}
        </span>
        <span class="deck-trajectory-stats">
          {t("deck.trajectory.summary", { steps: observedSteps, evidence: evidenceRefs.length })}
        </span>
        <span class="deck-trajectory-duration">
          {trajectory.durationMs === undefined
            ? t("deck.trajectory.sequenceOnly")
            : formatDuration(trajectory.durationMs)}
        </span>
      </summary>
      {open ? (
        <div class="deck-trajectory-body">
          <PhaseStrip recorded={recorded} />
          <div class="deck-trajectory-window">
            <span>{formatTimestamp(trajectory.startedAt, trajectory.question.at)}</span>
            <span aria-hidden="true" />
            <span>{formatTimestamp(trajectory.completedAt, trajectory.answer.at)}</span>
          </div>
          <ol class="deck-trajectory-events">
            <TrajectoryPhase index="01" phase="input" title={t("deck.trajectory.phase.input")}
              summary={trajectory.question.text} time={formatTimestamp(trajectory.startedAt, trajectory.question.at)}>
              <p class="deck-trajectory-prose">{trajectory.question.text}</p>
            </TrajectoryPhase>
            <PlanPhase trajectory={trajectory} />
            <CollaborationPhase trajectory={trajectory} />
            <TrajectoryPhase index="04" phase="evidence" title={t("deck.trajectory.phase.evidence")}
              summary={t("deck.trajectory.evidenceSummary", {
                branches: branches.length,
                activities: activities.length,
                references: evidenceRefs.length,
              })}
              recorded={recorded.has("evidence")}>
              {recorded.has("evidence") ? (
                <EvidenceTimeline trajectory={trajectory} activities={activities} branches={branches}
                  milestones={milestones} evidenceRefs={evidenceRefs} />
              ) : <CoverageGap />}
            </TrajectoryPhase>
            <VerificationPhase trajectory={trajectory} />
            <AnswerPhase trajectory={trajectory} />
          </ol>
        </div>
      ) : null}
    </details>
  );
}

function PhaseStrip({ recorded }: { readonly recorded: ReadonlySet<Phase> }) {
  return (
    <ol class="deck-trajectory-phase-strip" aria-label={t("deck.trajectory.phaseLabel")}>
      {PHASES.map((phase, index) => (
        <li key={phase} data-recorded={recorded.has(phase) ? "true" : "false"}>
          <span>{String(index + 1).padStart(2, "0")}</span>
          <strong>{t(`deck.trajectory.phase.${phase}`)}</strong>
        </li>
      ))}
    </ol>
  );
}

function PlanPhase({ trajectory }: { readonly trajectory: ConversationTrajectory }) {
  const plan = trajectory.answer.answerPlan;
  return (
    <TrajectoryPhase index="02" phase="plan" title={t("deck.trajectory.phase.plan")}
      summary={plan
        ? `${t(`deck.answerPlan.intent.${plan.intent}`)} / ${t(`deck.answerPlan.format.${plan.format}`)}`
        : t("deck.trajectory.notRecorded")}
      recorded={plan !== undefined}>
      {plan ? (
        <dl class="deck-trajectory-facts">
          <dt>{t("deck.trajectory.intent")}</dt><dd>{t(`deck.answerPlan.intent.${plan.intent}`)}</dd>
          <dt>{t("deck.trajectory.format")}</dt><dd>{t(`deck.answerPlan.format.${plan.format}`)}</dd>
          <dt>{t("deck.trajectory.detailLevel")}</dt><dd>{t(`deck.answerPlan.detail.${plan.detail_level}`)}</dd>
          <dt>{t("deck.trajectory.evidenceRequirement")}</dt><dd>{plan.evidence_requirement}</dd>
          <dt>{t("deck.trajectory.sections")}</dt><dd>{plan.sections.join(", ") || t("deck.trajectory.none")}</dd>
        </dl>
      ) : <CoverageGap />}
    </TrajectoryPhase>
  );
}

function CollaborationPhase({ trajectory }: { readonly trajectory: ConversationTrajectory }) {
  const { answer } = trajectory;
  const recorded = answer.answerPlanning !== undefined || answer.delegation !== undefined;
  const contributors = uniqueStrings([
    ...(answer.delegation?.contributors ?? []),
    ...(answer.answerPlanning?.consulted_agents ?? []),
  ]);
  return (
    <TrajectoryPhase index="03" phase="collaboration" title={t("deck.trajectory.phase.collaboration")}
      summary={collaborationSummary(trajectory)} recorded={recorded}
      {...(answer.answerPlanning ? { time: formatDuration(answer.answerPlanning.elapsed_ms) } : {})}>
      {recorded ? (
        <>
          <dl class="deck-trajectory-facts">
            <dt>{t("deck.trajectory.primaryAgent")}</dt>
            <dd>{answer.delegation?.primary_agent ?? answer.answerPlanning?.primary_agent ?? t("deck.trajectory.none")}</dd>
            <dt>{t("deck.trajectory.contributors")}</dt><dd>{contributors.join(", ") || t("deck.trajectory.none")}</dd>
            {answer.answerPlanning ? (
              <><dt>{t("deck.trajectory.planningStatus")}</dt><dd>{answer.answerPlanning.status}</dd></>
            ) : null}
          </dl>
          {answer.answerPlanning?.contributions.length ? (
            <ul class="deck-trajectory-detail-list">
              {answer.answerPlanning.contributions.map((contribution) => (
                <li key={contribution.agent}>
                  <strong>{contribution.agent}</strong>
                  <span>{t("deck.trajectory.confidence", { value: Math.round(contribution.confidence * 100) })}</span>
                  <small>{contribution.suggested_sections.join(", ")}</small>
                  <ReferenceList refs={contribution.evidence_refs} />
                </li>
              ))}
            </ul>
          ) : null}
        </>
      ) : <CoverageGap />}
    </TrajectoryPhase>
  );
}

function VerificationPhase({ trajectory }: { readonly trajectory: ConversationTrajectory }) {
  const verification = trajectory.answer.verification;
  return (
    <TrajectoryPhase index="05" phase="verification" title={t("deck.trajectory.phase.verification")}
      summary={verification
        ? `${t(`deck.grounded.verificationStatus.${verification.status}`)} / ${verification.checks_completed}/${verification.checks_total}`
        : t("deck.trajectory.notRecorded")}
      recorded={verification !== undefined}>
      {verification ? (
        <>
          <dl class="deck-trajectory-facts">
            <dt>{t("deck.trajectory.status")}</dt><dd>{t(`deck.grounded.verificationStatus.${verification.status}`)}</dd>
            <dt>{t("deck.trajectory.authority")}</dt><dd>{verification.authority}</dd>
            <dt>{t("deck.trajectory.checks")}</dt><dd>{verification.checks_completed}/{verification.checks_total}</dd>
            <dt>{t("deck.trajectory.reason")}</dt><dd>{verification.reason_code ?? t("deck.trajectory.none")}</dd>
          </dl>
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
        </>
      ) : <CoverageGap />}
    </TrajectoryPhase>
  );
}

function AnswerPhase({ trajectory }: { readonly trajectory: ConversationTrajectory }) {
  const { answer } = trajectory;
  return (
    <TrajectoryPhase index="06" phase="answer" title={t("deck.trajectory.phase.answer")}
      summary={answer.source ?? answer.agent ?? t("deck.trajectory.recorded")}
      time={formatTimestamp(trajectory.completedAt, answer.at)}>
      <dl class="deck-trajectory-facts">
        <dt>{t("deck.trajectory.agent")}</dt><dd>{answer.agent ?? t("deck.trajectory.none")}</dd>
        <dt>{t("deck.trajectory.source")}</dt><dd>{answer.source ?? t("deck.trajectory.none")}</dd>
        {answer.resourceContext ? (
          <><dt>{t("deck.trajectory.resource")}</dt><dd>{answer.resourceContext.name} ({answer.resourceContext.resource_type})</dd></>
        ) : null}
      </dl>
      <p class="deck-trajectory-prose">{answer.text}</p>
      {answer.codeArtifacts?.map((artifact) => (
        <details key={artifact.artifact_ref} class="deck-trajectory-nested">
          <summary>{artifact.language} / {t(`deck.codeEvidence.status.${artifact.validation_status}`)}</summary>
          <code>{artifact.artifact_ref}</code><pre><code>{artifact.content}</code></pre>
        </details>
      ))}
      {answer.actionDraft ? (
        <details class="deck-trajectory-nested">
          <summary>{t("deck.actionDraft.title")}: {answer.actionDraft.actionType}</summary>
          <pre><code>{JSON.stringify(answer.actionDraft.arguments, null, 2)}</code></pre>
        </details>
      ) : null}
    </TrajectoryPhase>
  );
}

function TrajectoryPhase({ index, phase, title, summary, time, recorded = true, children }: {
  readonly index: string; readonly phase: Phase; readonly title: string; readonly summary: string;
  readonly time?: string; readonly recorded?: boolean; readonly children: ComponentChildren;
}) {
  return (
    <li class="deck-trajectory-event" data-phase={phase} data-recorded={recorded ? "true" : "false"}>
      <span class="deck-trajectory-event-index" aria-hidden="true">{index}</span>
      <details>
        <summary><span><strong>{title}</strong><small>{summary}</small></span>
          <time>{time ?? (recorded ? t("deck.trajectory.recorded") : t("deck.trajectory.notRecorded"))}</time></summary>
        <div class="deck-trajectory-event-detail">{children}</div>
      </details>
    </li>
  );
}

function EvidenceTimeline({ trajectory, activities, branches, milestones, evidenceRefs }: {
  readonly trajectory: ConversationTrajectory; readonly activities: readonly InvestigationActivity[];
  readonly branches: readonly EvidenceBranch[]; readonly milestones: ConversationTrajectory["observedTurns"];
  readonly evidenceRefs: readonly string[];
}) {
  return (
    <>
      <ReferenceList refs={evidenceRefs} />
      <ol class="deck-trajectory-evidence">
        {branches.map((branch) => (
        <li key={branch.branchId} data-status={branch.status}>
          <TimedBar trajectory={trajectory} start={branch.startedAt}
            {...(branch.completedAt ? { end: branch.completedAt } : {})}
            {...(branch.durationMs !== undefined ? { durationMs: branch.durationMs } : {})} />
          <details><summary><span class={`deck-trajectory-kind is-${branch.kind}`}>{branch.kind}</span>
            <strong>{branch.summary}</strong><time>{formatTimestamp(branch.startedAt)}{branch.durationMs !== undefined ? ` / ${formatDuration(branch.durationMs)}` : ""}</time></summary>
            <ReferenceList refs={branch.evidenceRefs} /></details>
        </li>
        ))}
        {activities.map((activity) => (
        <li key={activity.activityId} data-status={activity.status}>
          <TimedBar trajectory={trajectory}
            {...(activity.execution?.startedAt || activity.observedAt
              ? { start: activity.execution?.startedAt ?? activity.observedAt }
              : {})}
            {...(activity.execution?.completedAt ? { end: activity.execution.completedAt } : {})}
            {...(activity.execution?.durationMs !== undefined
              ? { durationMs: activity.execution.durationMs }
              : {})} />
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
        <li key={milestone.id} data-status="completed"><span class="deck-trajectory-milestone" aria-hidden="true" />
          <div class="deck-trajectory-milestone-copy"><span class="deck-trajectory-kind is-milestone">{t("deck.trajectory.milestone")}</span>
            <strong>{milestone.text}</strong><time>{formatTimestamp(milestone.recordedAt, milestone.at)}</time></div></li>
        ))}
      </ol>
    </>
  );
}

function ExecutionDetail({ activity }: { readonly activity: InvestigationActivity }) {
  const execution = activity.execution;
  if (!execution) return null;
  return (
    <><pre><code>{execution.command}</code></pre>
      {execution.output !== undefined ? (
        <details class="deck-trajectory-nested"><summary>{execution.inputKind === "query"
          ? t("deck.investigation.queryResult") : t("deck.investigation.outputLogs")}</summary>
          <pre><code>{execution.output}</code></pre></details>
      ) : null}</>
  );
}

function TimedBar({ trajectory, start, end, durationMs }: {
  readonly trajectory: ConversationTrajectory; readonly start?: string; readonly end?: string; readonly durationMs?: number;
}) {
  const style = barStyle(trajectory, start, end, durationMs);
  return style ? <span class="deck-trajectory-timebar"><span style={style} /></span> : null;
}

function CoverageGap() { return <p class="deck-trajectory-gap">{t("deck.trajectory.coverageGap")}</p>; }

function ReferenceList({ refs }: { readonly refs: readonly string[] }) {
  return refs.length === 0 ? null : (
    <ul class="deck-trajectory-refs" aria-label={t("deck.trajectory.references")}>
      {refs.map((ref) => <li key={ref}><code>{ref}</code></li>)}
    </ul>
  );
}

function recordedPhases(
  trajectory: ConversationTrajectory,
  milestoneCount: number,
  evidenceRefCount: number,
): Set<Phase> {
  const recorded = new Set<Phase>(["input", "answer"]);
  if (trajectory.answer.answerPlan) recorded.add("plan");
  if (trajectory.answer.answerPlanning || trajectory.answer.delegation) recorded.add("collaboration");
  if (trajectory.activities.length || trajectory.branches.length || milestoneCount || evidenceRefCount) {
    recorded.add("evidence");
  }
  if (trajectory.answer.verification) recorded.add("verification");
  return recorded;
}

function collaborationSummary({ answer }: ConversationTrajectory): string {
  return uniqueStrings([answer.delegation?.primary_agent ?? "", ...(answer.delegation?.contributors ?? []),
    ...(answer.answerPlanning?.consulted_agents ?? [])]).filter(Boolean).join(" -> ") || t("deck.trajectory.notRecorded");
}

function barStyle(trajectory: ConversationTrajectory, start: string | undefined, end: string | undefined,
  durationMs: number | undefined): Record<string, string> | undefined {
  if (!trajectory.startedAt || !trajectory.completedAt || !validTimestamp(start)) return undefined;
  const windowStart = Date.parse(trajectory.startedAt);
  const total = Date.parse(trajectory.completedAt) - windowStart;
  if (total <= 0) return undefined;
  const eventStart = Date.parse(start);
  const eventEnd = validTimestamp(end) ? Date.parse(end) : eventStart + (durationMs ?? 0);
  const left = clamp(((eventStart - windowStart) / total) * 100, 0, 100);
  const width = clamp(((Math.max(eventStart, eventEnd) - eventStart) / total) * 100, 1.5, 100 - left);
  return { left: `${left}%`, width: `${width}%` };
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
function clamp(value: number, minimum: number, maximum: number): number { return Math.max(minimum, Math.min(maximum, value)); }
