import { t } from "../i18n";
import type { ConversationTrajectory } from "./conversation-trajectory";
import type {
  TrajectoryPhase,
  TrajectoryPhaseState,
} from "./conversation-trajectory-presentation";

export function TrajectoryDecisionContext({
  trajectory,
  collaborationState,
}: {
  readonly trajectory: ConversationTrajectory;
  readonly collaborationState: TrajectoryPhaseState;
}) {
  const { answer } = trajectory;
  if (!answer.answerPlan && !answer.answerPlanning && !answer.delegation) return null;
  const contributors = uniqueStrings([
    ...(answer.delegation?.contributors ?? []),
    ...(answer.answerPlanning?.consulted_agents ?? []),
  ]);
  return (
    <section class="deck-trajectory-context" aria-labelledby={`trajectory-context-${answer.id}`}>
      <h4 id={`trajectory-context-${answer.id}`}>{t("deck.trajectory.decisionContext")}</h4>
      <div class="deck-trajectory-context-grid">
        {answer.answerPlan ? (
          <details class="deck-trajectory-context-item">
            <summary>
              <strong>{t("deck.trajectory.responsePlan")}</strong>
              <span>{t("deck.trajectory.phaseState.completed")}</span>
            </summary>
            <dl class="deck-trajectory-facts">
              <dt>{t("deck.trajectory.intent")}</dt>
              <dd>{t(`deck.answerPlan.intent.${answer.answerPlan.intent}`)}</dd>
              <dt>{t("deck.trajectory.format")}</dt>
              <dd>{t(`deck.answerPlan.format.${answer.answerPlan.format}`)}</dd>
              <dt>{t("deck.trajectory.detailLevel")}</dt>
              <dd>{t(`deck.answerPlan.detail.${answer.answerPlan.detail_level}`)}</dd>
              <dt>{t("deck.trajectory.evidenceRequirement")}</dt>
              <dd>{answer.answerPlan.evidence_requirement}</dd>
              <dt>{t("deck.trajectory.sections")}</dt>
              <dd>{answer.answerPlan.sections.join(", ") || t("deck.trajectory.none")}</dd>
            </dl>
          </details>
        ) : null}
        {answer.answerPlanning || answer.delegation ? (
          <details class="deck-trajectory-context-item">
            <summary>
              <strong>{t("deck.trajectory.collaborationContext")}</strong>
              <span>{phaseStateLabel(collaborationState)}</span>
            </summary>
            <dl class="deck-trajectory-facts">
              <dt>{t("deck.trajectory.primaryAgent")}</dt>
              <dd>{answer.delegation?.primary_agent
                ?? answer.answerPlanning?.primary_agent
                ?? t("deck.trajectory.none")}</dd>
              <dt>{t("deck.trajectory.contributors")}</dt>
              <dd>{contributors.join(", ") || t("deck.trajectory.none")}</dd>
              {answer.answerPlanning ? (
                <>
                  <dt>{t("deck.trajectory.planningStatus")}</dt>
                  <dd>{phaseStateLabel(collaborationState)}</dd>
                  <dt>{t("deck.trajectory.duration")}</dt>
                  <dd>{formatDuration(answer.answerPlanning.elapsed_ms)}</dd>
                </>
              ) : null}
            </dl>
          </details>
        ) : null}
      </div>
    </section>
  );
}

export function TrajectoryCoverage({
  phaseStates,
}: {
  readonly phaseStates: Readonly<Record<TrajectoryPhase, TrajectoryPhaseState>>;
}) {
  const missing = (Object.entries(phaseStates) as [TrajectoryPhase, TrajectoryPhaseState][])
    .filter(([, state]) => state === "not_observed")
    .map(([phase]) => phase);
  if (missing.length === 0) return null;
  return (
    <details class="deck-trajectory-coverage">
      <summary>{t("deck.trajectory.observationCoverage", { count: missing.length })}</summary>
      <p>{t("deck.trajectory.coverageGap")}</p>
      <ul>
        {missing.map((phase) => <li key={phase}>{t(`deck.trajectory.phase.${phase}`)}</li>)}
      </ul>
    </details>
  );
}

export function phaseStateLabel(state: TrajectoryPhaseState): string {
  return t(`deck.trajectory.phaseState.${state}`);
}

function formatDuration(durationMs: number): string {
  return durationMs < 1000 ? `${Math.round(durationMs)} ms` : `${(durationMs / 1000).toFixed(1)} s`;
}

function uniqueStrings(values: readonly string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}
