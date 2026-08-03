import { t } from "../i18n";
import type { ConversationTrajectory } from "./conversation-trajectory";
import { phaseStateLabel } from "./conversation-trajectory-decision-context";
import {
  buildExecutionTimeline,
  executionTimelineWindow,
  type ExecutionTimelineFact,
  type ExecutionTimelineItem,
  type ExecutionTimelineRecord,
} from "./conversation-execution-timeline";
import { formatJsonValue } from "./json-code-block";

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
  return (
    <section class="deck-execution-timeline" aria-labelledby={`execution-timeline-${trajectory.answer.id}`}>
      <header>
        <h4 id={`execution-timeline-${trajectory.answer.id}`}>{t("deck.trajectory.executionTimeline")}</h4>
        <span>{t("deck.trajectory.observedEventCount", { count: items.length })}</span>
      </header>
      <div class="deck-execution-axis" aria-hidden="true">
        <div class="deck-execution-axis-range">
          <time>{formatAxisClock(window.startedAt)}</time>
          <span>{formatDuration(window.durationMs)}</span>
          <time>{formatAxisClock(window.completedAt)}</time>
        </div>
      </div>
      <ol>
        {items.map((item) => (
          <li key={item.id} data-kind={item.kind} data-state={item.state}>
            <details>
              <summary>
                <span class="deck-execution-kind">{t(`deck.trajectory.executionKind.${item.kind}`)}</span>
                <span class="deck-execution-label-wrap">
                  <span class="deck-execution-flow-mark" aria-hidden="true" />
                  <strong class="deck-execution-label">{executionLabel(item)}</strong>
                </span>
                <span
                  class={`deck-execution-track${item.durationMs === 0 ? " is-point" : ""}`}
                  aria-hidden="true"
                >
                  {item.gapWidthPct > 0 ? (
                    <span
                      class="deck-execution-gap"
                      style={{ left: `${item.gapLeftPct}%`, width: `${item.gapWidthPct}%` }}
                    />
                  ) : null}
                  <span
                    class="deck-execution-bar"
                    style={{ left: `${item.leftPct}%`, width: `${item.widthPct}%` }}
                  />
                </span>
                <span class="deck-execution-duration">{formatDuration(item.durationMs)}</span>
                <span class="deck-execution-outcome">{phaseStateLabel(item.state)}</span>
                <span class="deck-execution-chevron" aria-hidden="true" />
              </summary>
              <div class="deck-execution-detail">
                {item.details.summary ? (
                  <p class="deck-execution-summary">
                    <span>{t("deck.trajectory.observedDetail")}</span>
                    {item.details.summary}
                  </p>
                ) : null}
                <dl class="deck-execution-facts">
                  <div><dt>{t("deck.trajectory.status")}</dt><dd>{executionDetail(item)}</dd></div>
                  <div><dt>{t("deck.investigation.startedAt")}</dt><dd><time dateTime={item.startedAt}>{formatClock(item.startedAt)}</time></dd></div>
                  <div><dt>{t("deck.investigation.completedAt")}</dt><dd><time dateTime={item.completedAt}>{formatClock(item.completedAt)}</time></dd></div>
                  {item.details.facts.map((fact) => (
                    <div key={`${fact.key}-${fact.value}`}>
                      <dt>{executionFactLabel(fact)}</dt>
                      <dd>{executionFactValue(fact)}</dd>
                    </div>
                  ))}
                </dl>
                {item.details.records && item.details.records.length > 0 ? (
                  <div class="deck-execution-records">
                    {item.details.records.map((record) => (
                      <ExecutionRecord
                        key={`${record.key}-${record.value}`}
                        record={record}
                      />
                    ))}
                  </div>
                ) : null}
                {item.details.evidenceRefs.length > 0 ? (
                  <div class="deck-execution-references">
                    <strong>{t("deck.trajectory.references")}</strong>
                    <ul>
                      {item.details.evidenceRefs.map((reference) => (
                        <li key={reference}><code>{reference}</code></li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            </details>
          </li>
        ))}
      </ol>
    </section>
  );
}

function ExecutionRecord({ record }: { readonly record: ExecutionTimelineRecord }) {
  const formatted = formatJsonValue(record.value);
  return (
    <section class="deck-execution-record">
      <strong>{t(`deck.trajectory.detailRecord.${record.key}`)}</strong>
      <pre><code data-format={formatted.isJson ? "json" : "text"}>{formatted.text}</code></pre>
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

function formatClock(value: string): string {
  return new Date(value).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    fractionalSecondDigits: 3,
  });
}

function formatAxisClock(value: string): string {
  return new Date(value).toLocaleTimeString([], {
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
