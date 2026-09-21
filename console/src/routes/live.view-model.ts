import { useMemo } from "preact/hooks";
import type { AgentOperationalActivityMessage } from "../agent-operational-activity";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import type { LiveConnectionStatus } from "../hooks/use-live-stream";
import type { ObservationSource } from "../hooks/observation-source";
import { t } from "./i18n/live";
import {
  LIVE_METRIC_GATES,
  LIVE_METRIC_TIERS,
  type LiveMetricSummary,
} from "./live.metrics";
import {
  formatDuration,
  isTileStuck,
  type LiveState,
  type TileState,
} from "./live.model";

export interface LiveAttention {
  hil: number;
  deny: number;
  failed: number;
  stuck: number;
}

export function summarizeCurrentDecisionMix(
  tiles: readonly (TileState | null)[],
) {
  const tierCounts = { t0: 0, t1: 0, t2: 0 };
  const gateCounts = { auto: 0, hil: 0, abstain: 0, deny: 0 };
  for (const tile of tiles) {
    if (tile === null) continue;
    const tier = LIVE_METRIC_TIERS.find((value) => value === tile.tier);
    if (tier) tierCounts[tier] += 1;
    const gate = LIVE_METRIC_GATES.find((value) => value === tile.gate_decision);
    if (gate) gateCounts[gate] += 1;
  }
  const tierTotal = Object.values(tierCounts).reduce((sum, value) => sum + value, 0);
  const gateTotal = Object.values(gateCounts).reduce((sum, value) => sum + value, 0);
  return {
    tierCounts,
    gateCounts,
    tierTotal,
    gateTotal,
    autoShare: gateTotal === 0 ? 0 : Math.round(gateCounts.auto / gateTotal * 100),
  };
}

export function useLiveViewModel(
  state: LiveState,
  metrics: LiveMetricSummary,
  status: LiveConnectionStatus,
  streamSource: ObservationSource,
  selectedTile: TileState | null,
  droppedFrames = 0,
  observations: readonly AgentOperationalActivityMessage[] = [],
) {
  const { eps } = metrics;
  const currentMix = useMemo(
    () => summarizeCurrentDecisionMix(state.tiles),
    [state.tiles],
  );
  const { gateTotal, tierTotal, gateCounts, tierCounts, autoShare } = currentMix;
  const displayMetrics = useMemo(
    () => ({ ...metrics, ...currentMix }),
    [currentMix, metrics],
  );
  const attention = state.tiles.reduce<LiveAttention>(
    (counts, tile) => {
      if (!tile) return counts;
      if (tile.gate_decision === "hil") counts.hil += 1;
      if (tile.gate_decision === "deny") counts.deny += 1;
      if (tile.failed) counts.failed += 1;
      if (isTileStuck(tile, state.now)) counts.stuck += 1;
      return counts;
    },
    { hil: 0, deny: 0, failed: 0, stuck: 0 },
  );
  const attentionTotal = attention.hil + attention.deny + attention.failed + attention.stuck;
  const verticalCounts = useMemo(() => {
    const counts: Record<string, number> = { change: 0, resilience: 0, cost: 0, unknown: 0 };
    for (const tile of state.tiles) {
      if (!tile) continue;
      const vertical = tile.vertical ?? "unknown";
      counts[vertical] = (counts[vertical] ?? 0) + 1;
    }
    return counts;
  }, [state.tiles]);
  const shadowCount = useMemo(
    () => state.tiles.filter((tile) => tile?.mode === "shadow").length,
    [state.tiles],
  );
  const activeTileCount = useMemo(
    () => state.tiles.filter((tile) => tile !== null).length,
    [state.tiles],
  );
  const sourceActivityCount = observations.length;
  const activeSourceActivityCount = observations.filter(
    (activity) => activity.status === "started",
  ).length;
  const degradedSourceActivityCount = observations.filter(
    (activity) => activity.status === "degraded" || activity.status === "failed",
  ).length;
  const filterCounts = useMemo(
    () => ({
      all: activeTileCount,
      hil: state.tiles.filter((tile) => tile?.gate_decision === "hil").length,
      deny: state.tiles.filter((tile) => tile?.gate_decision === "deny").length,
      failed: state.tiles.filter((tile) => tile?.failed === true).length,
      stuck: state.tiles.filter((tile) => tile && isTileStuck(tile, state.now)).length,
    }),
    [activeTileCount, state.now, state.tiles],
  );
  const populatedTiles = useMemo(
    () => state.tiles.filter((tile): tile is TileState => tile !== null),
    [state.tiles],
  );
  const lastEventAt = populatedTiles.reduce(
    (latest, tile) => Math.max(latest, tile.last_seen_at),
    0,
  );
  const streamConnected = status === "open";
  const streamOpen = streamConnected && streamSource !== "unknown";
  const emptyState = streamOpen
    ? t("live.empty.connected")
    : streamConnected
      ? t("live.empty.awaitingSource")
    : status === "connecting"
      ? t("live.empty.connecting")
      : status === "idle"
        ? t("live.empty.idle")
        : t("live.empty.unavailable");

  usePublishViewContext(
    () => {
      const percent = (value: number, total: number) =>
        total === 0 ? "0%" : `${Math.round((value / total) * 100)}%`;
      const stuckSet = new Set<string>();
      for (const tile of state.tiles) {
        if (tile && isTileStuck(tile, state.now)) stuckSet.add(tile.event_id);
      }
      return {
        routeId: "live",
        routeLabel: "Live cockpit",
        purpose:
          "The read-only real-time cockpit: control-loop events and bounded " +
          "source-read activity share one chronological workspace while retaining " +
          "their distinct authority semantics. Streaming is presentation, never a judgment.",
        glossary: composeGlossary([
          TERMS.tier,
          TERMS.gateDecision,
          TERMS.mode,
          TERMS.actionKind,
          TERMS.shadowMode,
        ]),
        headline:
          `${activeTileCount + sourceActivityCount} activity item(s), ` +
          `${activeTileCount} control-loop, ${sourceActivityCount} source-read, ` +
          `${attentionTotal} needing attention`,
        capturedAt: new Date().toISOString(),
        facts: [
          { key: "eps", value: eps, group: "throughput" },
          { key: "session.total", value: state.session_total, group: "throughput" },
          { key: "stream.frames_dropped", value: droppedFrames, group: "throughput" },
          { key: "session.duration", value: formatDuration(state.now - state.session_started_at), group: "throughput" },
          { key: "tiles.active", value: activeTileCount, group: "tiles" },
          { key: "tiles.empty", value: state.tiles.length - activeTileCount, group: "tiles" },
          { key: "tiles.shadow", value: shadowCount, group: "tiles" },
          { key: "tier.t0", value: percent(tierCounts.t0, tierTotal), group: "tier" },
          { key: "tier.t1", value: percent(tierCounts.t1, tierTotal), group: "tier" },
          { key: "tier.t2", value: percent(tierCounts.t2, tierTotal), group: "tier" },
          { key: "gate.auto", value: percent(gateCounts.auto, gateTotal), group: "gate" },
          { key: "gate.hil", value: percent(gateCounts.hil, gateTotal), group: "gate" },
          { key: "gate.abstain", value: percent(gateCounts.abstain, gateTotal), group: "gate" },
          { key: "gate.deny", value: percent(gateCounts.deny, gateTotal), group: "gate" },
          { key: "messages.control", value: metrics.control, group: "throughput" },
          { key: "messages.source", value: metrics.source, group: "throughput" },
          { key: "messages.partial", value: metrics.partial, group: "throughput" },
          { key: "attention.total", value: attentionTotal, group: "attention" },
          { key: "attention.hil", value: attention.hil, group: "attention" },
          { key: "attention.deny", value: attention.deny, group: "attention" },
          { key: "attention.failed", value: attention.failed, group: "attention" },
          { key: "attention.stuck", value: attention.stuck, group: "attention" },
          { key: "source_activity.total", value: sourceActivityCount, group: "source_activity" },
          { key: "source_activity.active", value: activeSourceActivityCount, group: "source_activity" },
          { key: "source_activity.degraded", value: degradedSourceActivityCount, group: "source_activity" },
          { key: "verticals.change", value: verticalCounts.change ?? 0, group: "verticals" },
          { key: "verticals.resilience", value: verticalCounts.resilience ?? 0, group: "verticals" },
          { key: "verticals.cost", value: verticalCounts.cost ?? 0, group: "verticals" },
          { key: "verticals.unknown", value: verticalCounts.unknown ?? 0, group: "verticals" },
          { key: "view.filter", value: state.filter, group: "view" },
          { key: "selected_event", value: state.selectedEventId ?? "(none)", group: "selection" },
          ...(selectedTile ? [
            { key: "selected_action_type", value: selectedTile.action_type ?? "(none)", group: "selection" },
            { key: "selected_tier", value: selectedTile.tier ?? "(none)", group: "selection" },
            { key: "selected_gate", value: selectedTile.gate_decision ?? "(none)", group: "selection" },
            { key: "selected_vertical", value: selectedTile.vertical ?? "unknown", group: "selection" },
            { key: "selected_rule", value: selectedTile.rule ?? "(none)", group: "selection" },
            {
              key: "selected_status",
              value: selectedTile.failed ? "failed" : selectedTile.completed ? "completed" : "in-progress",
              group: "selection",
            },
          ] : []),
        ],
        records: {
          tiles: populatedTiles.map((tile) => ({
            event_id: tile.event_id,
            correlation_id: tile.correlation_id,
            action_type: tile.action_type ?? null,
            action_types: [...tile.action_types],
            rule: tile.rule ?? null,
            tier: tile.tier ?? null,
            mode: tile.mode ?? null,
            autonomy: tile.autonomy ?? null,
            gate_decision: tile.gate_decision ?? null,
            vertical: tile.vertical ?? "unknown",
            resource_type: tile.resource_type ?? null,
            scope: tile.scope ?? null,
            target: tile.target ?? null,
            reason: tile.reason ?? null,
            risk: tile.risk ?? null,
            impact: tile.impact ?? null,
            stages_completed: [...tile.stages_completed],
            completed: tile.completed,
            failed: tile.failed,
            stuck: stuckSet.has(tile.event_id),
            age_ms: state.now - tile.first_seen_at,
          })),
        },
      };
    },
    [
      state.tiles,
      metrics,
      state.session_total,
      droppedFrames,
      state.session_started_at,
      eps,
      gateTotal,
      tierTotal,
      attentionTotal,
      attention.hil,
      attention.deny,
      attention.failed,
      attention.stuck,
      verticalCounts,
      shadowCount,
      activeTileCount,
      activeSourceActivityCount,
      state.filter,
      state.selectedEventId,
      sourceActivityCount,
      degradedSourceActivityCount,
      selectedTile,
    ],
  );

  return {
    metrics: displayMetrics,
    eps,
    gateTotal,
    tierTotal,
    autoShare,
    attention,
    attentionTotal,
    activeTileCount,
    filterCounts,
    populatedTiles,
    lastEventAt,
    streamOpen,
    streamConnected,
    emptyState,
  };
}

export type LiveViewModel = ReturnType<typeof useLiveViewModel>;
