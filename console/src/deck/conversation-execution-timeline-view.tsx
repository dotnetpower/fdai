import { t } from "../i18n";
import type { ConversationTrajectory } from "./conversation-trajectory";
import { phaseStateLabel } from "./conversation-trajectory-decision-context";
import {
  buildExecutionTimeline,
  type ExecutionTimelineItem,
} from "./conversation-execution-timeline";

export function ConversationExecutionTimelineView({
  trajectory,
  includeModelCalls,
}: {
  readonly trajectory: ConversationTrajectory;
  readonly includeModelCalls: boolean;
}) {
  const items = buildExecutionTimeline(trajectory, { includeModelCalls });
  if (items.length === 0) return null;
  return (
    <section class="deck-execution-timeline" aria-labelledby={`execution-timeline-${trajectory.answer.id}`}>
      <header>
        <h4 id={`execution-timeline-${trajectory.answer.id}`}>{t("deck.trajectory.executionTimeline")}</h4>
        <span>{t("deck.trajectory.observedEventCount", { count: items.length })}</span>
      </header>
      <ol>
        {items.map((item) => (
          <li key={item.id} data-kind={item.kind} data-state={item.state}>
            <details>
              <summary>
                <span class="deck-execution-kind">{t(`deck.trajectory.executionKind.${item.kind}`)}</span>
                <strong class="deck-execution-label">{executionLabel(item)}</strong>
                <span class="deck-execution-track" aria-hidden="true">
                  <span style={{ left: `${item.leftPct}%`, width: `${item.widthPct}%` }} />
                </span>
                <span class="deck-execution-duration">{formatDuration(item.durationMs)}</span>
                <span class="deck-execution-outcome">{phaseStateLabel(item.state)}</span>
                <span class="deck-execution-chevron" aria-hidden="true" />
              </summary>
              <div class="deck-execution-detail">
                <dl class="deck-execution-facts">
                  <div><dt>{t("deck.trajectory.status")}</dt><dd>{executionDetail(item)}</dd></div>
                  <div><dt>{t("deck.investigation.startedAt")}</dt><dd><time dateTime={item.startedAt}>{formatClock(item.startedAt)}</time></dd></div>
                  <div><dt>{t("deck.investigation.completedAt")}</dt><dd><time dateTime={item.completedAt}>{formatClock(item.completedAt)}</time></dd></div>
                </dl>
              </div>
            </details>
          </li>
        ))}
      </ol>
    </section>
  );
}

function executionLabel(item: ExecutionTimelineItem): string {
  if (item.kind === "turn") return t(`deck.trajectory.phase.${item.label}`);
  if (item.kind === "phase") return t(`deck.trajectory.timingPhase.${item.label}`);
  if (item.kind === "evidence") return t(`deck.investigation.kind.${item.label}`);
  return t("deck.trajectory.modelProviderCall");
}

function executionDetail(item: ExecutionTimelineItem): string {
  if (item.kind === "model") return `${item.detail} / ${item.label}`;
  if (item.kind === "evidence") return t(`deck.investigation.${item.detail}`);
  return phaseStateLabel(item.state);
}

function formatClock(value: string): string {
  return new Date(value).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    fractionalSecondDigits: 3,
  });
}

function formatDuration(durationMs: number): string {
  if (durationMs === 0) return "0 ms";
  if (durationMs < 1000) return `${durationMs} ms`;
  return `${(durationMs / 1000).toFixed(2)} s`;
}
