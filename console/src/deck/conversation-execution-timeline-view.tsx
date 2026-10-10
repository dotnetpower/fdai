import { t } from "../i18n";
import { consoleDateTimeLocale } from "../time-format";
import type { ConversationTrajectory } from "./conversation-trajectory";
import { phaseStateLabel } from "./conversation-trajectory-decision-context";
import {
  buildExecutionTimeline,
  executionTimelineWindow,
  type ExecutionTimelineFact,
  type ExecutionTimelineItem,
  type ExecutionTimelineRecord,
} from "./conversation-execution-timeline";
import { JsonCodeBlock } from "./json-code-block";

/** The observed execution timeline on the conversation layer's run roles: one row per observed
 *  event with its kind, label, position in the turn, duration, and outcome, opening in place to the
 *  observed detail, facts, payloads, and evidence references. */
export function ConversationExecutionTimelineView({
  trajectory,
  includeModelCalls,
}: {
  readonly trajectory: ConversationTrajectory;
  readonly includeModelCalls: boolean;
}) {
  const items = buildExecutionTimeline(trajectory, { includeModelCalls });
  if (items.length === 0) return null;
  const window = executionTimelineWindow(items)!;
  const titleId = `execution-timeline-${trajectory.answer.id}`;
  return (
    <section class="cs-run-timeline" aria-labelledby={titleId}>
      <header class="cs-run-timeline-head">
        <h4 class="cs-run-timeline-title" id={titleId}>{t("deck.trajectory.executionTimeline")}</h4>
        <span class="cs-run-timeline-count">
          {t("deck.trajectory.observedEventCount", { count: items.length })}
        </span>
      </header>
      <div class="cs-run-axis" aria-hidden="true">
        <div class="cs-run-axis-range">
          <time>{formatExecutionTimelineAxisClock(window.startedAt)}</time>
          <span>{formatDuration(window.durationMs)}</span>
          <time>{formatExecutionTimelineAxisClock(window.completedAt)}</time>
        </div>
      </div>
      <ol class="cs-run-events">
        {items.map((item) => (
          <li key={item.id} class="cs-run-event" data-kind={item.kind} data-state={item.state}>
            <details>
              <summary class="cs-run-event-summary">
                <span class="cs-run-event-kind">{t(`deck.trajectory.executionKind.${item.kind}`)}</span>
                <strong class="cs-run-event-label">{executionLabel(item)}</strong>
                <RunTrack leftPct={item.leftPct} widthPct={item.widthPct} />
                <span class="cs-run-event-duration">{formatDuration(item.durationMs)}</span>
                <span class="cs-run-event-outcome">{phaseStateLabel(item.state)}</span>
                <span class="cs-run-chevron" aria-hidden="true" />
              </summary>
              <div class="cs-run-event-detail">
                {item.details.summary ? (
                  <p class="cs-run-observed">
                    <span>{t("deck.trajectory.observedDetail")}</span>
                    {item.details.summary}
                  </p>
                ) : null}
                <dl class="cs-run-facts">
                  <div><dt>{t("deck.trajectory.status")}</dt><dd>{executionDetail(item)}</dd></div>
                  <div><dt>{t("deck.investigation.startedAt")}</dt><dd><time dateTime={item.startedAt}>{formatExecutionTimelineClock(item.startedAt)}</time></dd></div>
                  <div><dt>{t("deck.investigation.completedAt")}</dt><dd><time dateTime={item.completedAt}>{formatExecutionTimelineClock(item.completedAt)}</time></dd></div>
                  {item.details.facts.map((fact) => (
                    <div key={`${fact.key}-${fact.value}`}>
                      <dt>{executionFactLabel(fact)}</dt>
                      <dd>{executionFactValue(fact)}</dd>
                    </div>
                  ))}
                </dl>
                {item.details.records?.map((record) => (
                  <ExecutionRecord key={`${record.key}-${record.value}`} record={record} />
                ))}
                {item.details.evidenceRefs.length > 0 ? (
                  <section class="cs-run-payload">
                    <strong>{t("deck.trajectory.references")}</strong>
                    <ul class="cs-run-references">
                      {item.details.evidenceRefs.map((reference) => (
                        <li key={reference}><code>{reference}</code></li>
                      ))}
                    </ul>
                  </section>
                ) : null}
              </div>
            </details>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** A bar placed on the turn's time span; the layer's track keeps a minimum visible width. */
export function RunTrack({ leftPct, widthPct }: { readonly leftPct: number; readonly widthPct: number }) {
  return (
    <span class="cs-run-track" aria-hidden="true">
      <span
        class="cs-run-bar"
        style={`--cs-run-start: ${leftPct.toFixed(2)}; --cs-run-width: ${widthPct.toFixed(2)}`}
      />
    </span>
  );
}

function ExecutionRecord({ record }: { readonly record: ExecutionTimelineRecord }) {
  return (
    <section class="cs-run-payload">
      <strong>{t(`deck.trajectory.detailRecord.${record.key}`)}</strong>
      <JsonCodeBlock value={record.value} />
    </section>
  );
}

function executionFactLabel(fact: ExecutionTimelineFact): string {
  return t(`deck.trajectory.detailFact.${fact.key}`);
}

function executionFactValue(fact: ExecutionTimelineFact): string {
  if ((fact.key === "response" || fact.key === "modelCalls") &&
      (fact.value === "recorded" || fact.value === "notRecorded")) {
    return t(`deck.trajectory.${fact.value}`);
  }
  if ((fact.key === "requestMessages" || fact.key === "response") &&
      fact.value === "contentOmitted") {
    return t("deck.modelTrace.contentNotRetained");
  }
  return fact.value;
}

function executionLabel(item: ExecutionTimelineItem): string {
  if (item.displayLabel) return item.displayLabel;
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

export function formatExecutionTimelineClock(value: string): string {
  return new Date(value).toLocaleTimeString(consoleDateTimeLocale(), {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    fractionalSecondDigits: 3,
  });
}

export function formatExecutionTimelineAxisClock(value: string): string {
  return new Date(value).toLocaleTimeString(consoleDateTimeLocale(), {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatDuration(durationMs: number): string {
  if (durationMs === 0) return "0 ms";
  if (durationMs < 1000) return `${durationMs} ms`;
  return `${(durationMs / 1000).toFixed(2)} s`;
}
