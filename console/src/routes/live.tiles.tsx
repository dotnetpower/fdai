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
import type { LiveStageName } from "../hooks/use-live-stream";
import {
  AGENT_ROLE,
  STAGE_LABEL,
  STAGE_ORDER,
  formatAge,
  matchesFilter,
  type FilterKind,
  type RateBuckets,
  type TileState,
} from "./live.model";

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
  const dimmed = matchesFilter(tile, filter) ? "" : " dimmed";
  const failed = tile.failed ? "1" : "0";
  const done = tile.completed ? "1" : "0";
  const ageMs = Math.max(0, now - tile.first_seen_at);
  const heading =
    tile.action_type ??
    (tile.completed && !tile.gate_decision ? "no rule matched" : "routing...");
  const tierLabel = tier === "abstain" ? "N/A" : tier.toUpperCase();
  // Abstain-and-done tiles carry zero operational information. Mark
  // them so CSS can quiet them into a background pattern rather than
  // stealing visual weight from remediation tiles.
  const abstain = tile.completed && !tile.gate_decision && !tile.action_type ? "1" : "0";

  return (
    <button
      type="button"
      class={`live-tile live-tile-vertical-${vertical} live-tile-gate-${gate}${dimmed}`}
      data-empty="0"
      data-failed={failed}
      data-done={done}
      data-abstain={abstain}
      data-selected={selected ? "1" : "0"}
      onClick={onClick}
      aria-label={`${tile.action_type ?? "(routing)"} on ${tile.resource_type ?? "unknown"}`}
    >
      <StageDots
        completed={tile.stages_completed}
        last_stage={tile.last_stage}
        stage_agents={tile.stage_agents}
      />
      <div class="live-tile-top">
        <span class="live-tile-action" title={tile.rule ?? tile.action_type}>
          {heading}
        </span>
        <span class={`live-tier live-tier-${tier}`}>{tierLabel}</span>
      </div>
      <div class="live-tile-target">
        <span>{tile.resource_type ?? "-"}</span>
        <span class="muted">{tile.scope ? ` · ${tile.scope}` : ""}</span>
      </div>
      <div class="live-tile-foot">
        {tile.last_agent ? (
          <span
            class="live-tile-agent"
            title={
              AGENT_ROLE[tile.last_agent]
                ? `${tile.last_agent} - ${AGENT_ROLE[tile.last_agent]}`
                : tile.last_agent
            }
          >
            {tile.last_agent}
          </span>
        ) : null}
        {gate ? (
          <span class={`live-gate live-gate-${gate}`}>{gate}</span>
        ) : (
          <span class="muted">…</span>
        )}
        {tile.stages_completed.has("execute") ? (
          <span class="live-tile-mode" title="Action executed in shadow mode - a remediation PR, not an enforce write">
            shadow
          </span>
        ) : null}
        <span class="muted live-tile-age">{formatAge(ageMs)}</span>
      </div>
      {gate === "hil" ? <span class="live-tile-badge">needs approval</span> : null}
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
    <div class="live-tile-progress" aria-label="agent relay">
      {STAGE_ORDER.map((stage) => {
        const relayAgent = stage_agents.get(stage);
        const tip = relayAgent
          ? `${STAGE_LABEL[stage]} - ${relayAgent}${AGENT_ROLE[relayAgent] ? ` (${AGENT_ROLE[relayAgent]})` : ""}`
          : STAGE_LABEL[stage];
        return (
          <span
            key={stage}
            class={`live-tile-dot ${completed.has(stage) ? "done" : ""} ${last_stage === stage ? "current" : ""}`}
            title={tip}
          />
        );
      })}
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
        ? "no completions"
        : avg < 1
          ? "avg <1ms"
          : avg >= 1000
            ? `avg ${(avg / 1000).toFixed(1)}s`
            : `avg ${Math.round(avg)}ms`;
    tip = {
      leftPct: n > 1 ? (hover / (n - 1)) * 100 : 50,
      label: secAgo === 0 ? "last full second" : `${secAgo}s ago`,
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
}: {
  readonly entries: readonly StackEntry[];
  readonly total: number;
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
      <div class="live-stackbar-legend">
        {entries.map((e) => (
          <span key={e.key} class={e.className}>
            {e.label} {total > 0 ? Math.round((e.value / total) * 100) : 0}%
          </span>
        ))}
      </div>
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
  return (
    <div class="live-detail-backdrop" onClick={onClose}>
      <aside class="live-detail-panel" onClick={(e) => e.stopPropagation()}>
        <header>
          <h3>{tile.action_type ?? "(pending)"}</h3>
          <button type="button" class="live-detail-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </header>
        <dl class="live-detail-list">
          <dt>Event id</dt>
          <dd><code>{tile.event_id}</code></dd>
          <dt>Rule</dt>
          <dd>{tile.rule ?? "-"}</dd>
          <dt>ActionType</dt>
          <dd>{tile.action_type ?? "-"}</dd>
          <dt>Vertical</dt>
          <dd>{tile.vertical ?? "-"}</dd>
          <dt>Resource type</dt>
          <dd>{tile.resource_type ?? "-"}</dd>
          <dt>Scope</dt>
          <dd>{tile.scope ?? "-"}</dd>
          <dt>Tier</dt>
          <dd>
            {tile.tier ? (
              <span class={`live-tier live-tier-${tile.tier}`}>{tile.tier.toUpperCase()}</span>
            ) : (
              "-"
            )}
          </dd>
          <dt>Gate decision</dt>
          <dd>
            {tile.gate_decision ? (
              <span class={`live-gate live-gate-${tile.gate_decision}`}>{tile.gate_decision}</span>
            ) : (
              "-"
            )}
          </dd>
          <dt>Stages completed</dt>
          <dd>
            {STAGE_ORDER.filter((s) => tile.stages_completed.has(s)).join(" · ") || "-"}
          </dd>
          <dt>Failed</dt>
          <dd>{tile.failed ? "yes" : "no"}</dd>
          <dt>Age</dt>
          <dd>{formatAge(Math.max(0, now - tile.first_seen_at))}</dd>
          <dt>Outcome</dt>
          <dd>{tile.outcome ?? "-"}</dd>
        </dl>
        <h4 class="live-detail-subhead">Safety invariants (executor guarantees)</h4>
        <ul class="live-detail-safety">
          <li>stop-condition on the ActionType</li>
          <li>tested rollback path</li>
          <li>blast-radius cap enforced</li>
          <li>audit-log entry per terminal outcome</li>
        </ul>
        <p class="muted live-detail-note">
          This panel is read-only. Approvals happen in ChatOps or via a remediation PR.
        </p>
      </aside>
    </div>
  );
}
