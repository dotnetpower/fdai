import { useMemo } from "preact/hooks";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import type { LiveConnectionStatus } from "../hooks/use-live-stream";
import { t } from "./i18n/live";
import {
  POOL_SIZE,
  RATE_WINDOW_MS,
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

export function useLiveViewModel(
  state: LiveState,
  status: LiveConnectionStatus,
  selectedTile: TileState | null,
) {
  const eps = (state.ratePings.length / (RATE_WINDOW_MS / 1000)).toFixed(1);
  const gateTotal = Object.values(state.gateCounts).reduce((total, count) => total + count, 0);
  const tierTotal = Object.values(state.tierCounts).reduce((total, count) => total + count, 0);
  const autoShare = gateTotal > 0
    ? Math.round(((state.gateCounts.auto ?? 0) / gateTotal) * 100)
    : 0;
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
  const lastEventLabel = lastEventAt > 0
    ? t("live.spark.secondsAgo", { count: Math.max(0, Math.floor((state.now - lastEventAt) / 1000)) })
    : t("live.health.notObserved");
  const streamOpen = status === "open";
  const emptyState = streamOpen
    ? t("live.empty.connected")
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
          "The real-time cockpit: events flowing through the trust router and " +
          "risk gate right now, one tile per in-flight action, with the T0/T1/T2 " +
          "tier mix and auto/hil/deny gate mix over a rolling 60s window. " +
          "Read-only; streaming is presentation, never a judgment.",
        glossary: composeGlossary([
          TERMS.tier,
          TERMS.gateDecision,
          TERMS.mode,
          TERMS.actionKind,
          TERMS.shadowMode,
        ]),
        headline: `${activeTileCount} tile(s), ${eps} eps, ${attentionTotal} needing attention`,
        capturedAt: new Date().toISOString(),
        facts: [
          { key: "eps", value: eps, group: "throughput" },
          { key: "session.total", value: state.session_total, group: "throughput" },
          { key: "session.duration", value: formatDuration(state.now - state.session_started_at), group: "throughput" },
          { key: "tiles.active", value: activeTileCount, group: "tiles" },
          { key: "tiles.empty", value: POOL_SIZE - activeTileCount, group: "tiles" },
          { key: "tiles.shadow", value: shadowCount, group: "tiles" },
          { key: "tier.t0", value: percent(state.tierCounts.t0 ?? 0, tierTotal), group: "tier" },
          { key: "tier.t1", value: percent(state.tierCounts.t1 ?? 0, tierTotal), group: "tier" },
          { key: "tier.t2", value: percent(state.tierCounts.t2 ?? 0, tierTotal), group: "tier" },
          { key: "gate.auto", value: percent(state.gateCounts.auto ?? 0, gateTotal), group: "gate" },
          { key: "gate.hil", value: percent(state.gateCounts.hil ?? 0, gateTotal), group: "gate" },
          { key: "gate.abstain", value: percent(state.gateCounts.abstain ?? 0, gateTotal), group: "gate" },
          { key: "gate.deny", value: percent(state.gateCounts.deny ?? 0, gateTotal), group: "gate" },
          { key: "attention.total", value: attentionTotal, group: "attention" },
          { key: "attention.hil", value: attention.hil, group: "attention" },
          { key: "attention.deny", value: attention.deny, group: "attention" },
          { key: "attention.failed", value: attention.failed, group: "attention" },
          { key: "attention.stuck", value: attention.stuck, group: "attention" },
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
            gate_decision: tile.gate_decision ?? null,
            vertical: tile.vertical ?? "unknown",
            resource_type: tile.resource_type ?? null,
            scope: tile.scope ?? null,
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
      state.tierCounts,
      state.gateCounts,
      state.session_total,
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
      state.filter,
      state.selectedEventId,
      selectedTile,
    ],
  );

  return {
    eps,
    gateTotal,
    tierTotal,
    autoShare,
    attention,
    attentionTotal,
    activeTileCount,
    filterCounts,
    populatedTiles,
    lastEventLabel,
    streamOpen,
    emptyState,
  };
}

export type LiveViewModel = ReturnType<typeof useLiveViewModel>;
