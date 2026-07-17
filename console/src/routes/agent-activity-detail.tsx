import type { ComponentChildren } from "preact";
import { Tooltip } from "../components/tooltip";
import { StatusPill } from "../components/ui";
import { t } from "../i18n";
import { routeHref } from "../router";
import type { AuditItem } from "../types";
import {
  agentOf,
  clockMs,
  entryConversation,
  entryMap,
  entryNum,
  entryStr,
  fmtDur,
  layerOf,
  lifecycleOf,
  modePill,
  otherEntryFields,
  outcomeOf,
  outcomePill,
  summaryOf,
  tierOf,
} from "./agent-activity-semantics";

export function StepDetail({
  item,
  onClose,
}: {
  readonly item: AuditItem;
  readonly onClose: () => void;
}) {
  const agent = agentOf(item);
  const layer = layerOf(agent);
  const tier = tierOf(item);
  const outcome = outcomeOf(item);
  const summary = summaryOf(item);
  const detail = entryStr(item, "detail");
  const decision = entryStr(item, "decision");
  const reason = entryStr(item, "reason");
  const stage = entryStr(item, "pipeline_stage");
  const durationMs = entryNum(item, "duration_ms");
  const queueMs = entryNum(item, "queue_ms");
  const inputs = entryMap(item, "inputs");
  const outputs = entryMap(item, "outputs");
  const conversation = entryConversation(item);
  const phases = lifecycleOf(item);
  const otherFields = otherEntryFields(item);

  const record: readonly (readonly [string, ComponentChildren])[] = [
    ["Tier", tier ? <span class="mono">{tier}</span> : null],
    ["Mode", <StatusPill kind={modePill(item.mode)} label={item.mode} />],
    ["Outcome", outcome ? <StatusPill kind={outcomePill(outcome)} label={outcome} /> : null],
    ["Decision", decision ? <span class="mono">{decision}</span> : null],
    ["Pipeline stage", stage ? <span class="mono">{stage}</span> : null],
    ["Reason", reason],
    [
      "Correlation",
      item.correlation_id ? (
        <Tooltip content={t("tooltip.openTrace")}>
          <a
            class="mono"
            href={routeHref("trace", { params: { correlation: item.correlation_id } })}
          >
            {item.correlation_id}
          </a>
        </Tooltip>
      ) : null,
    ],
    ["Seq", <span class="mono">{item.seq}</span>],
    ["Event id", <span class="mono waterfall-hash">{item.event_id}</span>],
    ["Entry hash", <span class="mono waterfall-hash">{item.entry_hash}</span>],
    ["Prev hash", <span class="mono waterfall-hash">{item.previous_hash}</span>],
  ];

  return (
    <aside class="waterfall-detail" aria-label="Step detail">
      <header class="waterfall-detail-head">
        <span class="waterfall-detail-title">
          <span class="agent-dot agent-dot-lg" data-layer={layer} aria-hidden="true" />
          <span class="waterfall-detail-agent" data-layer={layer}>{agent}</span>
          <span class="waterfall-detail-action mono">{item.action_kind}</span>
          {tier ? <span class="timeline-tier mono">{tier}</span> : null}
          <StatusPill kind={modePill(item.mode)} label={item.mode} />
          {outcome ? <StatusPill kind={outcomePill(outcome)} label={outcome} /> : null}
        </span>
        <button type="button" class="waterfall-detail-close" onClick={onClose} aria-label="Close detail">
          ×
        </button>
      </header>

      {summary ? <p class="waterfall-detail-summary">{summary}</p> : null}

      <section class="waterfall-section">
        <h3 class="waterfall-section-title">Lifecycle</h3>
        <ol class="waterfall-life">
          {phases.map((phase) => (
            <li class="waterfall-life-step" key={phase.key}>
              <span class="waterfall-life-dot" data-layer={layer} aria-hidden="true" />
              <span class="waterfall-life-body">
                <span class="waterfall-life-label">{phase.label}</span>
                {phase.iso ? <span class="waterfall-life-time mono">{clockMs(phase.iso)}</span> : null}
              </span>
              {phase.gapLabel ? <span class="waterfall-life-gap mono">{phase.gapLabel}</span> : null}
            </li>
          ))}
        </ol>
        <p class="waterfall-life-note muted">
          {durationMs !== null ? <>Worked <strong>{fmtDur(durationMs)}</strong></> : null}
          {durationMs !== null && queueMs !== null ? " · " : null}
          {queueMs !== null ? <>queued <strong>{fmtDur(queueMs)}</strong></> : null}
        </p>
      </section>

      {detail ? (
        <section class="waterfall-section">
          <h3 class="waterfall-section-title">What it did</h3>
          <p class="waterfall-detail-text">{detail}</p>
        </section>
      ) : null}

      {conversation ? (
        <section class="waterfall-section">
          <h3 class="waterfall-section-title">
            Agent conversation
            <span class="waterfall-conv-count">{conversation.length}</span>
          </h3>
          <ol class="waterfall-chat">
            {conversation.map((turn, index) => (
              <li class="waterfall-chat-turn" key={index} data-layer={layerOf(turn.from)}>
                <div class="waterfall-chat-meta">
                  <span class="waterfall-chat-from" data-layer={layerOf(turn.from)}>
                    {turn.from}
                  </span>
                  <span class="waterfall-chat-arrow" aria-hidden="true">-&gt;</span>
                  <span class="waterfall-chat-to" data-layer={layerOf(turn.to)}>
                    {turn.to}
                  </span>
                </div>
                <p class="waterfall-chat-text">{turn.text}</p>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      {inputs || outputs ? (
        <div class="waterfall-io">
          {inputs ? (
            <section class="waterfall-section">
              <h3 class="waterfall-section-title">Inputs</h3>
              <dl class="waterfall-kv">
                {inputs.map(([key, value]) => (
                  <div class="waterfall-kv-row" key={key}>
                    <dt class="mono">{key}</dt>
                    <dd class="mono">{value}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ) : null}
          {outputs ? (
            <section class="waterfall-section">
              <h3 class="waterfall-section-title">Outputs</h3>
              <dl class="waterfall-kv">
                {outputs.map(([key, value]) => (
                  <div class="waterfall-kv-row" key={key}>
                    <dt class="mono">{key}</dt>
                    <dd class="mono">{value}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ) : null}
        </div>
      ) : null}

      <section class="waterfall-section">
        <h3 class="waterfall-section-title">Record</h3>
        <dl class="waterfall-detail-grid">
          {record.map(([label, value]) =>
            value === null || value === undefined ? null : (
              <div class="waterfall-detail-row" key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ),
          )}
        </dl>
      </section>

      {otherFields.length > 0 ? (
        <section class="waterfall-section">
          <h3 class="waterfall-section-title">Other recorded fields</h3>
          <dl class="waterfall-detail-grid">
            {otherFields.map(([key, value]) => (
              <div class="waterfall-detail-row" key={key}>
                <dt class="mono">{key}</dt>
                <dd class="mono">{value}</dd>
              </div>
            ))}
          </dl>
        </section>
      ) : null}
    </aside>
  );
}
