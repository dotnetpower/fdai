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
            <span class="deck-execution-kind">{t(`deck.trajectory.executionKind.${item.kind}`)}</span>
            <span class="deck-execution-label">
              <strong>{executionLabel(item)}</strong>
              <small>{executionDetail(item)}</small>
            </span>
            <span class="deck-execution-track" aria-hidden="true">
              <span style={{ left: `${item.leftPct}%`, width: `${item.widthPct}%` }} />
            </span>
            <time>{formatClock(item.startedAt)}</time>
            <span class="deck-execution-outcome">
              <strong>{phaseStateLabel(item.state)}</strong>
              <small>{formatDuration(item.durationMs)}</small>
            </span>
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
  if (durationMs === 0) return t("deck.trajectory.pointInTime");
  if (durationMs < 1000) return `${durationMs} ms`;
  return `${(durationMs / 1000).toFixed(2)} s`;
}
