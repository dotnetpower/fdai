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

import { useEffect, useRef, useState } from "preact/hooks";
import { architectureHref } from "../components/architecture-map.model";
import { Tooltip } from "../components/tooltip";
import type { LiveStageName } from "../hooks/use-live-stream";
import { routeHref } from "../router";
import { t } from "./i18n/live";
import {
  STAGE_ORDER,
  formatAge,
  isTileStuck,
  matchesFilter,
  type FilterKind,
  type RateBuckets,
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

function actionHeading(tile: TileState): string {
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

// ---------------------------------------------------------------------------
// Tile + stage dots
// ---------------------------------------------------------------------------

export interface TileProps {
  readonly tile: TileState | null;
  readonly filter: FilterKind;
  readonly selected: boolean;
  readonly now: number;
  readonly onClick: (() => void) | undefined;
}

export function LiveTile({ tile, filter, selected, now, onClick }: TileProps) {
  if (!tile) {
    return <div class="live-tile live-tile-empty" data-empty="1" aria-hidden="true" />;
  }

  const vertical = tile.vertical ?? "unknown";
  const tier = tile.tier ?? "abstain";
  const gate = tile.gate_decision ?? "";
  const dimmed = matchesFilter(tile, filter, now) ? "" : " dimmed";
  const failed = tile.failed ? "1" : "0";
  const done = tile.completed ? "1" : "0";
  const ageMs = Math.max(0, now - tile.first_seen_at);
  const heading = actionHeading(tile);
  const tierLabel = tier === "abstain" ? "N/A" : tier.toUpperCase();
  // Abstain-and-done tiles carry zero operational information. Mark
  // them so CSS can quiet them into a background pattern rather than
  // stealing visual weight from remediation tiles.
  const abstain = tile.completed && !tile.gate_decision && tile.action_types.size === 0 ? "1" : "0";

  return (
    <button
      type="button"
      class={`live-tile live-tile-gate-${gate}${dimmed}`}
      data-empty="0"
      data-failed={failed}
      data-done={done}
      data-abstain={abstain}
      data-selected={selected ? "1" : "0"}
      onClick={onClick}
      aria-label={t("live.work.itemLabel", {
        action: heading,
        resource: tile.resource_type ?? t("live.work.unknownResource"),
      })}
    >
      <StageDots
        completed={tile.stages_completed}
        last_stage={tile.last_stage}
        stage_agents={tile.stage_agents}
      />
      <div class="live-tile-top">
        <Tooltip content={tile.rule ?? [...tile.action_types].join(", ")}>
          <span class="live-tile-action">{heading}</span>
        </Tooltip>
        <span class={`live-tier live-tier-${tier}`}>{tierLabel}</span>
      </div>
      <div class="live-tile-target">
        <span>{tile.resource_type ?? "-"}</span>
        <span class="muted">{tile.scope ? ` · ${tile.scope}` : ""}</span>
      </div>
      <div class="live-tile-foot">
        {tile.last_agent ? (
          <Tooltip content={`${tile.last_agent} - ${agentRole(tile.last_agent)}`}>
            <span class="live-tile-agent">{tile.last_agent}</span>
          </Tooltip>
        ) : null}
        {gate ? (
          <span class={`live-gate live-gate-${gate}`}>{decisionLabel(gate)}</span>
        ) : (
          <span class="muted">…</span>
        )}
        {tile.mode ? (
          <Tooltip content={t("live.work.executionMode", { mode: tile.mode })}>
            <span class="live-tile-mode">{tile.mode}</span>
          </Tooltip>
        ) : null}
        <span class="muted live-tile-age">{formatAge(ageMs)}</span>
      </div>
      {gate === "hil" ? <span class="live-tile-badge">{t("live.work.needsApproval")}</span> : null}
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

export function tileAttentionRank(tile: TileState, now: number): number {
  if (tile.failed) return 0;
  if (isTileStuck(tile, now)) return 1;
  if (tile.gate_decision === "hil") return 2;
  if (tile.gate_decision === "deny") return 3;
  if (!tile.completed) return 4;
  return 5;
}

export function LiveQueue({
  tiles,
  filter,
  selectedEventId,
  now,
  onSelect,
}: {
  readonly tiles: readonly TileState[];
  readonly filter: FilterKind;
  readonly selectedEventId: string | null;
  readonly now: number;
  readonly onSelect: (eventId: string) => void;
}) {
  const visible = [...tiles.filter((tile) => matchesFilter(tile, filter, now))]
    .sort((left, right) => {
      const rank = tileAttentionRank(left, now) - tileAttentionRank(right, now);
      return rank !== 0 ? rank : right.last_seen_at - left.last_seen_at;
    });

  if (visible.length === 0) {
    return <div class="live-queue-empty" role="status">{t("live.work.noMatch")}</div>;
  }

  return (
    <div class="live-queue-wrap">
      <table class="live-queue">
        <thead>
          <tr>
            <th scope="col">{t("live.work.columns.controlLoop")}</th>
            <th scope="col">{t("live.work.columns.stage")}</th>
            <th scope="col">{t("live.work.columns.age")}</th>
            <th scope="col">{t("live.work.columns.tier")}</th>
            <th scope="col">{t("live.work.columns.mode")}</th>
            <th scope="col">{t("live.work.columns.decision")}</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((tile) => {
            const stuck = isTileStuck(tile, now);
            const status = tile.failed
              ? "failed"
              : stuck
                ? "stuck"
                : tile.gate_decision === "hil"
                  ? "approval"
                  : tile.completed
                    ? "completed"
                    : "active";
            return (
              <tr
                key={tile.event_id}
                data-status={status}
                data-selected={tile.event_id === selectedEventId ? "1" : "0"}
              >
                <td data-label={t("live.work.columns.controlLoop")}>
                  <button type="button" onClick={() => onSelect(tile.event_id)}>
                    <strong>{actionHeading(tile)}</strong>
                    <span>{tile.resource_type ?? t("live.work.unknownResource")}</span>
                    <code>{tile.correlation_id}</code>
                  </button>
                </td>
                <td data-label={t("live.work.columns.stage")}>
                  <span class="live-queue-stage">{stageLabel(tile.last_stage)}</span>
                  {tile.last_agent ? <small>{tile.last_agent}</small> : null}
                </td>
                <td class="live-queue-age" data-label={t("live.work.columns.age")}>
                  {formatAge(Math.max(0, now - tile.first_seen_at))}
                  {stuck ? <small>{t("live.work.overBudget")}</small> : null}
                </td>
                <td data-label={t("live.work.columns.tier")}>
                  <span class={`live-tier live-tier-${tile.tier ?? "unknown"}`}>
                    {tile.tier?.toUpperCase() ?? "N/A"}
                  </span>
                </td>
                <td data-label={t("live.work.columns.mode")}>{tile.mode ? <span class="live-tile-mode">{tile.mode}</span> : "-"}</td>
                <td data-label={t("live.work.columns.decision")}>
                  {tile.gate_decision ? (
                    <span class={`live-gate live-gate-${tile.gate_decision}`}>
                      {decisionLabel(tile.gate_decision)}
                    </span>
                  ) : (
                    <span class="muted">{t("live.work.pending")}</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sparkline (per-tier events/sec, 60s window)
// ---------------------------------------------------------------------------

export function Sparkline({
  buckets,
  latSum,
  latCount,
}: {
  readonly buckets: RateBuckets;
  readonly latSum: readonly number[];
  readonly latCount: readonly number[];
}) {
  const width = 240;
  const height = 44;
  const pad = 3;
  // Drop the trailing bucket: it is the current, still-accumulating second.
  // Plotting it makes the right edge sawtooth down to zero on every 1s roll
  // (events refill it from 0 each second). Rendering only completed seconds
  // keeps the right edge stable - it is the last fully-elapsed second.
  const t0 = buckets.t0.slice(0, -1);
  const t1 = buckets.t1.slice(0, -1);
  const t2 = buckets.t2.slice(0, -1);
  const sampleTotal = [...t0, ...t1, ...t2].reduce((sum, value) => sum + value, 0);
  const series = [t0, t1, t2];
  const n = t0.length;
  // Shared scale so the three tiers stay comparable; a small headroom keeps
  // the dominant T0 line off the top edge for a calmer read.
  const max = Math.max(1, ...t0, ...t1, ...t2) * 1.15;
  const stepX = width / (n - 1 || 1);
  const base = height - pad;
  const span = height - pad * 2;
  const cls = ["live-spark-t0", "live-spark-t1", "live-spark-t2"] as const;
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

  // Hover: map the cursor x to a completed-second bucket and surface that
  // second's tier counts plus the average pipeline latency (ms).
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
    const cnt = latCount[hover] ?? 0;
    const avg = cnt > 0 ? (latSum[hover] ?? 0) / cnt : null;
    const secAgo = n - 1 - hover;
    const latText =
      avg === null
        ? t("live.spark.noCompletions")
        : avg < 1
          ? t("live.spark.averageUnderMs")
          : avg >= 1000
            ? t("live.spark.averageSeconds", { value: (avg / 1000).toFixed(1) })
            : t("live.spark.averageMs", { value: Math.round(avg) });
    tip = {
      leftPct: n > 1 ? (hover / (n - 1)) * 100 : 50,
      label: secAgo === 0 ? t("live.spark.lastSecond") : t("live.spark.secondsAgo", { count: secAgo }),
      counts: `T0 ${t0[hover] ?? 0}  T1 ${t1[hover] ?? 0}  T2 ${t2[hover] ?? 0}`,
      lat: latText,
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
        {series.map((arr, i) => {
          const d = linePath(arr);
          if (!d) return null;
          return (
            <g key={cls[i]}>
              <path d={`${d} L${lastX.toFixed(1)},${height} L0,${height} Z`} class={`live-spark-area ${cls[i]}-area`} />
              <path
                d={d}
                fill="none"
                class={cls[i]}
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
}: {
  readonly tile: TileState;
  readonly now: number;
  readonly onClose: () => void;
}) {
  const panelRef = useRef<HTMLElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    document.body.classList.add("scroll-locked");
    closeRef.current?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = [...(panelRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ) ?? [])];
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown, true);
    return () => {
      document.removeEventListener("keydown", handleKeyDown, true);
      document.body.classList.remove("scroll-locked");
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  }, []);

  const heading = actionHeading(tile);

  return (
    <div class="live-detail-backdrop" onClick={onClose}>
      <aside
        ref={panelRef}
        class="live-detail-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="live-detail-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header>
          <h3 id="live-detail-title">{heading}</h3>
          <button ref={closeRef} type="button" class="live-detail-close" onClick={onClose} aria-label={t("live.detail.close")}>
            ×
          </button>
        </header>
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
        <dl class="live-detail-list">
          <dt>{t("live.detail.eventId")}</dt>
          <dd><code>{tile.event_id}</code></dd>
          <dt>{t("live.detail.correlationId")}</dt>
          <dd><code>{tile.correlation_id}</code></dd>
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
          <dt>{t("live.detail.stagesCompleted")}</dt>
          <dd>
            {STAGE_ORDER.filter((stage) => tile.stages_completed.has(stage)).map(stageLabel).join(" · ") || "-"}
          </dd>
          <dt>{t("live.detail.failed")}</dt>
          <dd>{tile.failed ? t("live.detail.yes") : t("live.detail.no")}</dd>
          <dt>{t("live.detail.age")}</dt>
          <dd>{formatAge(Math.max(0, now - tile.first_seen_at))}</dd>
          <dt>{t("live.detail.outcome")}</dt>
          <dd>{tile.outcome ?? "-"}</dd>
        </dl>
        <h4 class="live-detail-subhead">{t("live.detail.safety")}</h4>
        <ul class="live-detail-safety">
          <li>{t("live.detail.stopCondition")}</li>
          <li>{t("live.detail.rollback")}</li>
          <li>{t("live.detail.blastRadius")}</li>
          <li>{t("live.detail.auditEntry")}</li>
        </ul>
        <p class="muted live-detail-note">
          {t("live.detail.readOnly")}
        </p>
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
      </aside>
    </div>
  );
}
