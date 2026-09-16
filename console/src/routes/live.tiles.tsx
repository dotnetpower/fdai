/**
 * Presentational sub-components for the Live cockpit route.
 *
 * SRP: pure UI. `LiveTile`, `StageDots`, `Sparkline`, `StackBar`, and
 * `DetailPanel` all receive their state as props and never mutate; the
 * SSE wiring, reducer plumbing, and layout live in `live.tsx`.
 *
 * Extracted from `live.tsx` so the ~450 lines of tile / chart / drawer
 * markup live away from the SSE / lifecycle code.
 */

import { useState } from "preact/hooks";
import { architectureHref } from "../components/architecture-map.model";
import { Tooltip } from "../components/tooltip";
import type { LiveStageName } from "../hooks/use-live-stream";
import { useContentUpdatePulse } from "../hooks/use-content-update-pulse";
import { routeHref } from "../router";
import { t } from "./i18n/live";
import { LiveDetailShell } from "./live.detail-shell";
import { liveSampleStory } from "./operations.sample-live-stories";
import {
  STAGE_ORDER,
  formatAge,
  matchesFilter,
  type FilterKind,
  type TileState,
} from "./live.model";

function stageLabel(stage: LiveStageName): string {
  return t(`live.stage.${stage}`);
}

function agentRole(agent: string): string {
  return t(`live.role.${agent}`) === `live.role.${agent}`
    ? t("live.role.unknown")
    : t(`live.role.${agent}`);
}

function actionHeading(tile: TileState, sample = false): string {
  const story = sample ? liveSampleStory(tile.rule) : undefined;
  if (story) return t(`live.sample.title.${story.key}`);
  if (tile.action_types.size > 1) {
    return t("live.work.actions", { count: tile.action_types.size });
  }
  return tile.action_type ??
    (tile.completed && !tile.gate_decision ? t("live.work.noRule") : t("live.work.routing"));
}

function decisionLabel(decision: string): string {
  const key = `live.decision.${decision}`;
  const label = t(key);
  return label === key ? decision : label;
}

function outcomeLabel(outcome: string | undefined): string {
  if (!outcome) return t("live.control.notObserved");
  const key = `live.outcome.${outcome}`;
  const label = t(key);
  return label === key ? outcome : label;
}

type EvidenceCategory =
  | "approval"
  | "provider"
  | "observation"
  | "reconciliation"
  | "recovery";

export function evidenceStatusLabel(
  category: EvidenceCategory,
  value: string | undefined,
): string {
  const status = value ?? "not_observed";
  const key = `live.evidence.${category}.${status}`;
  const label = t(key);
  return label === key ? status : label;
}

function tierHelp(tier: string): string {
  const key = `live.help.tier.${tier}`;
  const value = t(key);
  return value === key ? t("live.help.tier.unknown") : value;
}

function normalizedAutonomy(value: string | undefined): string | null {
  if (!value) return null;
  const normalized = value.trim().toUpperCase().replace("AUTONOMY.", "").replace("_", "-");
  return ["A0", "A1", "A2", "A3-H", "A3-E", "A4"].includes(normalized)
    ? normalized
    : null;
}

export function authorityModeLabel(tile: TileState): string {
  const autonomy = normalizedAutonomy(tile.autonomy);
  const mode = tile.mode?.trim().toUpperCase();
  return [autonomy, mode].filter(Boolean).join(" · ") || t("live.work.pending");
}

export function authorityModeHelp(tile: TileState): string {
  const autonomy = normalizedAutonomy(tile.autonomy);
  const autonomyKey = autonomy ? `live.help.autonomy.${autonomy.replace("-", "_")}` : "live.help.autonomy.guide";
  const mode = tile.mode?.trim().toLowerCase();
  const modeKey = mode && ["shadow", "enforce", "gated"].includes(mode)
    ? `live.help.mode.${mode}`
    : "live.help.mode.pending";
  return `${t(autonomyKey)} ${t(modeKey)}`;
}

export interface LiveControlState {
  readonly policy: string;
  readonly authority: string;
  readonly execution: string;
  readonly effect: string;
}

export function liveControlState(tile: TileState): LiveControlState {
  const blocked =
    tile.gate_decision === "deny" ||
    tile.gate_decision === "hil" && tile.approval_status !== "approved";
  const execution = tile.failed
    ? t("live.control.executionFailed")
    : tile.mode === "shadow"
      ? t("live.control.simulated")
      : blocked
        ? t("live.control.notDispatched")
        : tile.stages_completed.has("execute")
          ? t("live.control.completed")
          : tile.last_stage === "execute"
            ? t("live.control.inProgress")
            : t("live.control.notStarted");
  return {
    policy: tile.gate_decision ? decisionLabel(tile.gate_decision) : t("live.work.pending"),
    authority: normalizedAutonomy(tile.autonomy) ?? t("live.control.notObserved"),
    execution,
    effect: outcomeLabel(tile.outcome),
  };
}

function targetLabel(tile: TileState): string {
  return tile.target ?? tile.resource_type ?? t("live.work.unknownResource");
}

// ---------------------------------------------------------------------------
// Tile + stage dots
// ---------------------------------------------------------------------------

export interface TileProps {
  readonly tile: TileState | null;
  readonly filter: FilterKind;
  readonly selected: boolean;
  readonly now: number;
  readonly onClick: (() => void) | undefined;
  readonly sample?: boolean;
}

export function liveTileUpdateKey(tile: TileState | null): string | null {
  if (!tile) return null;
  return [
    tile.event_id,
    tile.last_stage,
    [...tile.stages_completed].sort().join(","),
    [...tile.stage_agents.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([stage, agent]) => `${stage}:${agent}`)
      .join(","),
    tile.tier ?? "",
    tile.gate_decision ?? "",
    tile.failed,
    tile.completed,
    tile.resource_type ?? "",
    tile.scope ?? "",
    tile.target ?? "",
    tile.reason ?? "",
    tile.autonomy ?? "",
    tile.outcome ?? "",
    tile.last_agent ?? "",
    tile.mode ?? "",
    [...tile.action_types].sort().join(","),
  ].join("|");
}

export function LiveTile({ tile, filter, selected, now, onClick, sample = false }: TileProps) {
  const contentUpdated = useContentUpdatePulse(liveTileUpdateKey(tile));
  if (!tile) {
    return <div class="live-tile live-tile-empty" data-empty="1" aria-hidden="true" />;
  }

  const tier = tile.tier ?? "abstain";
  const gate = tile.gate_decision ?? "";
  const dimmed = matchesFilter(tile, filter, now) ? "" : " dimmed";
  const failed = tile.failed ? "1" : "0";
  const done = tile.completed ? "1" : "0";
  const heading = actionHeading(tile, sample);
  const story = sample ? liveSampleStory(tile.rule) : undefined;
  const tierLabel = tier === "abstain" ? "N/A" : tier.toUpperCase();
  const modeLabel = authorityModeLabel(tile);
  const stageProgress = ((STAGE_ORDER.indexOf(tile.last_stage) + 1) / STAGE_ORDER.length) * 100;
  const statusLabel = tile.failed
    ? t("live.control.executionFailed")
    : tile.completed && tile.gate_decision
      ? decisionLabel(tile.gate_decision)
      : stageLabel(tile.last_stage);
  const abstain = tile.completed && !tile.gate_decision && tile.action_types.size === 0 ? "1" : "0";

  return (
    <button
      type="button"
      class={`live-tile live-work-card live-tile-gate-${gate}${dimmed}${contentUpdated ? " is-content-updated" : ""}`}
      data-empty="0"
      data-event-id={tile.event_id}
      data-tier={tier}
      data-stage={tile.last_stage}
      data-failed={failed}
      data-done={done}
      data-abstain={abstain}
      data-selected={selected ? "1" : "0"}
      aria-expanded={selected}
      aria-haspopup="dialog"
      aria-controls="live-detail-panel"
      onClick={onClick}
      aria-label={t("live.work.itemLabel", {
        action: heading,
        resource: tile.resource_type ?? t("live.work.unknownResource"),
      })}
    >
      <div class="live-tile-top">
        <Tooltip content={tierHelp(tier)}>
          <span class={`live-tier live-tier-${tier}`}>{tierLabel}</span>
        </Tooltip>
        <Tooltip content={authorityModeHelp(tile)}>
          <span class={`live-tile-mode live-tile-mode-${tile.mode ?? "pending"}`}>{modeLabel}</span>
        </Tooltip>
        <span class="live-tile-stage">{statusLabel}</span>
      </div>
      <Tooltip content={tile.rule ?? [...tile.action_types].join(", ")}>
        <span class="live-tile-action">{heading}</span>
      </Tooltip>
      <div class="live-tile-target">
        <span>{story ? t(`live.sample.target.${story.key}`) : targetLabel(tile)}</span>
      </div>
      <div class="live-tile-reason">
        {t("live.work.why", { reason: story ? t(`live.sample.reason.${story.key}`) : tile.reason ?? t("live.control.notObserved") })}
      </div>
      <div class="live-tile-foot">
        <span class="live-tile-owner">
          {tile.last_agent ? `${tile.last_agent} · ${stageLabel(tile.last_stage)}` : stageLabel(tile.last_stage)}
        </span>
        <span class="live-tile-scope">{tile.scope ?? t("live.control.notObserved")}</span>
      </div>
      <span class="live-tile-bar" role="meter" aria-label={t("live.work.progress")}
        aria-valuemin={0} aria-valuemax={STAGE_ORDER.length}
        aria-valuenow={STAGE_ORDER.indexOf(tile.last_stage) + 1}
        aria-valuetext={`${stageLabel(tile.last_stage)} - ${statusLabel}`}>
        <span style={{ width: `${stageProgress}%` }} />
      </span>
    </button>
  );
}

export function StageDots({
  completed,
  last_stage,
  stage_agents,
}: {
  readonly completed: ReadonlySet<LiveStageName>;
  readonly last_stage: LiveStageName;
  readonly stage_agents: ReadonlyMap<LiveStageName, string>;
}) {
  return (
    <div class="live-tile-progress" aria-label={t("live.work.agentRelay")}>
      {STAGE_ORDER.map((stage) => {
        const relayAgent = stage_agents.get(stage);
        const tip = relayAgent
          ? `${stageLabel(stage)} - ${relayAgent} (${agentRole(relayAgent)})`
          : stageLabel(stage);
        return (
          <Tooltip key={stage} content={tip}>
            <span
              class={`live-tile-dot ${completed.has(stage) ? "done" : ""} ${last_stage === stage ? "current" : ""}`}
            />
          </Tooltip>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sparkline (business messages by lane, 60s window)
// ---------------------------------------------------------------------------

export function Sparkline({
  series,
}: {
  readonly series: readonly {
    readonly label: string;
    readonly values: readonly number[];
    readonly className: string;
  }[];
}) {
  const width = 240;
  const height = 44;
  const pad = 3;
  // Drop the trailing bucket: it is the current, still-accumulating second.
  // Plotting it makes the right edge sawtooth down to zero on every 1s roll
  // (events refill it from 0 each second). Rendering only completed seconds
  // keeps the right edge stable - it is the last fully-elapsed second.
  const completed = series.map(entry => ({ ...entry, values: entry.values.slice(0, -1) }));
  const sampleTotal = completed.flatMap(entry => entry.values).reduce((sum, value) => sum + value, 0);
  const n = completed[0]?.values.length ?? 0;
  // Shared scale so the message lanes stay comparable; a small headroom keeps
  // the dominant T0 line off the top edge for a calmer read.
  const max = Math.max(1, ...completed.flatMap(entry => entry.values)) * 1.15;
  const stepX = width / (n - 1 || 1);
  const base = height - pad;
  const span = height - pad * 2;
  // Smooth the line (quadratic through bucket midpoints) so a low, noisy
  // per-second rate reads as a calm curve instead of a jagged staircase.
  const linePath = (arr: readonly number[]): string => {
    const pts = arr.map((v, i) => [i * stepX, base - (v / max) * span] as const);
    const first = pts[0];
    if (!first) return "";
    let d = `M${first[0].toFixed(1)},${first[1].toFixed(1)}`;
    for (let j = 0; j < pts.length - 1; j++) {
      const a = pts[j];
      const b = pts[j + 1];
      if (!a || !b) continue;
      const mx = (a[0] + b[0]) / 2;
      const my = (a[1] + b[1]) / 2;
      d += ` Q${a[0].toFixed(1)},${a[1].toFixed(1)} ${mx.toFixed(1)},${my.toFixed(1)}`;
    }
    const last = pts[pts.length - 1];
    if (last) d += ` L${last[0].toFixed(1)},${last[1].toFixed(1)}`;
    return d;
  };
  const lastX = (n - 1) * stepX;

  // Only complete seconds appear in the plot and its hover counts.
  const [hover, setHover] = useState<number | null>(null);
  const onMove = (e: MouseEvent) => {
    const el = e.currentTarget as HTMLElement | null;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const frac = rect.width > 0 ? (e.clientX - rect.left) / rect.width : 0;
    setHover(Math.max(0, Math.min(n - 1, Math.round(frac * (n - 1)))));
  };
  const onLeave = () => setHover(null);

  let tip: { leftPct: number; label: string; counts: string; lat: string } | null = null;
  if (hover !== null) {
    const secAgo = n - 1 - hover;
    tip = {
      leftPct: n > 1 ? (hover / (n - 1)) * 100 : 50,
      label: secAgo === 0 ? t("live.spark.lastSecond") : t("live.spark.secondsAgo", { count: secAgo }),
      counts: completed.map(entry => `${entry.label} ${entry.values[hover] ?? 0}`).join("  "),
      lat: t("live.kpi.messagesHelp"),
    };
  }

  return (
    <div class="live-spark-wrap" onMouseMove={onMove} onMouseLeave={onLeave}>
      <svg
        class="live-spark"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        {[0.25, 0.5, 0.75].map((ratio) => (
          <line
            key={ratio}
            class="live-spark-grid"
            x1="0"
            y1={(height * ratio).toFixed(1)}
            x2={width}
            y2={(height * ratio).toFixed(1)}
          />
        ))}
        {completed.map((entry) => {
          const d = linePath(entry.values);
          if (!d) return null;
          return (
            <g key={entry.className}>
              <path d={`${d} L${lastX.toFixed(1)},${height} L0,${height} Z`} class={`live-spark-area ${entry.className}-area`} />
              <path
                d={d}
                fill="none"
                class={entry.className}
                stroke-width="1.6"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </g>
          );
        })}
        {hover !== null ? (
          <line
            class="live-spark-cursor"
            x1={(hover * stepX).toFixed(1)}
            y1="0"
            x2={(hover * stepX).toFixed(1)}
            y2={height}
          />
        ) : null}
      </svg>
      {sampleTotal === 0 ? <span class="live-spark-empty">{t("live.spark.awaiting")}</span> : null}
      {tip ? (
        <div class="live-spark-tip" style={`left:${tip.leftPct.toFixed(1)}%`}>
          <div class="live-spark-tip-h">{tip.label}</div>
          <div class="live-spark-tip-counts">{tip.counts}</div>
          <div class="live-spark-tip-lat">{tip.lat}</div>
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stack bar (tier / gate mix as a horizontal 100% bar)
// ---------------------------------------------------------------------------

export interface StackEntry {
  readonly key: string;
  readonly label: string;
  readonly value: number;
  readonly className: string;
}

export function StackBar({
  entries,
  total,
  showLegend = true,
}: {
  readonly entries: readonly StackEntry[];
  readonly total: number;
  readonly showLegend?: boolean;
}) {
  return (
    <div class="live-stackbar">
      <div class="live-stackbar-bar" aria-hidden="true">
        {entries.map((e) => (
          <span
            key={e.key}
            class={`live-stackbar-seg ${e.className}`}
            style={{ width: `${total > 0 ? (e.value / total) * 100 : 0}%` }}
          />
        ))}
      </div>
      {showLegend ? (
        <div class="live-stackbar-legend">
          {entries.map((e) => (
            <span key={e.key} class={e.className}>
              {e.label} {total > 0 ? Math.round((e.value / total) * 100) : 0}%
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Detail panel (right drawer for the selected tile)
// ---------------------------------------------------------------------------

export function DetailPanel({
  tile,
  now,
  onClose,
  sample = false,
}: {
  readonly tile: TileState;
  readonly now: number;
  readonly onClose: () => void;
  readonly sample?: boolean;
}) {
  const heading = actionHeading(tile, sample);
  const control = liveControlState(tile);

  return (
    <LiveDetailShell
      panelId="live-detail-panel"
      titleId="live-detail-title"
      heading={heading}
      closeLabel={t("live.detail.close")}
      onClose={onClose}
    >
        <p class="live-detail-boundary">
          <strong>{t("live.detail.boundaryTitle")}</strong>
          <span>{t("live.detail.readOnly")}</span>
        </p>
        <ol class="live-detail-trace" aria-label={t("live.detail.traceLabel")}>
          {STAGE_ORDER.map((stage) => {
            const complete = tile.stages_completed.has(stage);
            const current = tile.last_stage === stage;
            const agent = tile.stage_agents.get(stage);
            return (
              <li class={complete ? "done" : current ? "current" : undefined}>
                <span class="live-detail-trace-dot" aria-hidden="true" />
                <div>
                  <strong>{stageLabel(stage)}</strong>
                  <small>
                    {agent
                      ? `${agent} - ${agentRole(agent)}`
                      : current
                        ? t("live.detail.inProgress")
                        : t("live.detail.notObserved")}
                  </small>
                </div>
              </li>
            );
          })}
        </ol>
        <section class="live-detail-section" aria-labelledby="live-control-state-heading">
          <h3 id="live-control-state-heading">{t("live.detail.controlState")}</h3>
          <div class="live-detail-control-state">
            <div>
              <span>{t("live.detail.policyDecision")}</span>
              <strong>{control.policy}</strong>
            </div>
            <div>
              <span>{t("live.detail.authority")}</span>
              <strong>{control.authority}</strong>
            </div>
            <div>
              <span>{t("live.detail.execution")}</span>
              <strong>{control.execution}</strong>
            </div>
            <div>
              <span>{t("live.detail.effect")}</span>
              <strong>{control.effect}</strong>
            </div>
          </div>
        </section>
        <section class="live-detail-section" aria-labelledby="live-work-summary-heading">
          <h3 id="live-work-summary-heading">{t("live.detail.workSummary")}</h3>
          <dl class="live-detail-list">
          <dt>{t("live.detail.reason")}</dt>
          <dd>{tile.reason ?? t("live.control.notObserved")}</dd>
          <dt>{t("live.detail.target")}</dt>
          <dd>{targetLabel(tile)}</dd>
          <dt>{t("live.detail.rule")}</dt>
          <dd>{tile.rule ?? "-"}</dd>
          <dt>{tile.action_types.size > 1 ? t("live.detail.actionTypes") : t("live.detail.actionType")}</dt>
          <dd>{tile.action_types.size > 0 ? [...tile.action_types].join(", ") : "-"}</dd>
          <dt>{t("live.detail.mode")}</dt>
          <dd>{tile.mode ?? "-"}</dd>
          <dt>{t("live.detail.vertical")}</dt>
          <dd>{tile.vertical ?? "-"}</dd>
          <dt>{t("live.detail.resourceType")}</dt>
          <dd>{tile.resource_type ?? "-"}</dd>
          <dt>{t("live.detail.scope")}</dt>
          <dd>{tile.scope ?? "-"}</dd>
          <dt>{t("live.detail.tier")}</dt>
          <dd>
            {tile.tier ? (
              <span class={`live-tier live-tier-${tile.tier}`}>{tile.tier.toUpperCase()}</span>
            ) : (
              "-"
            )}
          </dd>
          <dt>{t("live.detail.gateDecision")}</dt>
          <dd>
            {tile.gate_decision ? (
              <span class={`live-gate live-gate-${tile.gate_decision}`}>{decisionLabel(tile.gate_decision)}</span>
            ) : (
              "-"
            )}
          </dd>
          <dt>{t("live.detail.age")}</dt>
          <dd>{formatAge(Math.max(0, now - tile.first_seen_at))}</dd>
          <dt>{t("live.detail.outcome")}</dt>
          <dd>{tile.outcome ? outcomeLabel(tile.outcome) : "-"}</dd>
          </dl>
        </section>
        {tile.approval_status || tile.provider_status || tile.observation_status ? (
          <section class="live-detail-section" aria-labelledby="live-effect-evidence-heading">
            <h3 id="live-effect-evidence-heading">{t("live.detail.effectEvidence")}</h3>
            <dl class="live-detail-list live-detail-evidence">
              <dt>{t("live.detail.approvalStatus")}</dt>
              <dd>{evidenceStatusLabel("approval", tile.approval_status)}</dd>
              <dt>{t("live.detail.providerStatus")}</dt>
              <dd>{evidenceStatusLabel("provider", tile.provider_status)}</dd>
              <dt>{t("live.detail.observationStatus")}</dt>
              <dd>{evidenceStatusLabel("observation", tile.observation_status)}</dd>
              <dt>{t("live.detail.reconciliationStatus")}</dt>
              <dd>{evidenceStatusLabel("reconciliation", tile.reconciliation_status)}</dd>
              <dt>{t("live.detail.recoveryStatus")}</dt>
              <dd>{evidenceStatusLabel("recovery", tile.recovery_status)}</dd>
            </dl>
          </section>
        ) : null}
        <h4 class="live-detail-subhead">{t("live.detail.safety")}</h4>
        <ul class="live-detail-safety">
          <li>{t("live.detail.stopCondition")}</li>
          <li>{t("live.detail.rollback")}</li>
          <li>{t("live.detail.blastRadius")}</li>
          <li>{t("live.detail.auditEntry")}</li>
        </ul>
        <details class="live-detail-technical">
          <summary>{t("live.detail.technicalDetails")}</summary>
          <dl class="live-detail-list">
            <dt>{t("live.detail.eventId")}</dt>
            <dd><code>{tile.event_id}</code></dd>
            <dt>{t("live.detail.correlationId")}</dt>
            <dd><code>{tile.correlation_id}</code></dd>
            <dt>{t("live.detail.stagesCompleted")}</dt>
            <dd>
              {STAGE_ORDER.filter((stage) => tile.stages_completed.has(stage)).map(stageLabel).join(" · ") || "-"}
            </dd>
            <dt>{t("live.detail.failed")}</dt>
            <dd>{tile.failed ? t("live.detail.yes") : t("live.detail.no")}</dd>
          </dl>
        </details>
        <div class="live-detail-actions">
          <a class="btn" href={routeHref("trace", { params: { correlation: tile.correlation_id } })}>
            {t("live.detail.openTrace")}
          </a>
          <a class="btn" href={routeHref("audit", { params: { correlation: tile.correlation_id } })}>
            {t("live.detail.openAudit")}
          </a>
          <a class="btn" href={architectureHref(tile.scope ?? undefined)}>
            {t("live.detail.architecture")}
          </a>
        </div>
    </LiveDetailShell>
  );
}
