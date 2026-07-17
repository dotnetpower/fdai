import { Tooltip } from "../components/tooltip";
import type {
  LiveConnectionStatus,
  LiveStageEvent,
} from "../hooks/use-live-stream";
import {
  observationSourceLabel,
  type ObservationSource,
} from "../hooks/observation-source";
import { routeHref } from "../router";
import { t } from "./i18n/live";
import {
  sumBuckets,
  type FilterKind,
  type LiveSelectionState,
  type LiveState,
  type TileState,
} from "./live.model";
import { LiveTicker } from "./live.ticker";
import { DetailPanel, LiveQueue, LiveTile, Sparkline, StackBar } from "./live.tiles";
import type { LiveViewModel } from "./live.view-model";

export type LiveViewMode = "queue" | "flow";

export interface LiveRouteUpdate {
  readonly eventId?: string | null;
  readonly filter?: FilterKind;
  readonly view?: LiveViewMode;
}

export function LivePanels({
  state,
  view,
  status,
  lastError,
  streamSource,
  tickerPaused,
  tickerCollapsed,
  frozenObserved,
  displayedTicker,
  viewMode,
  selectionState,
  selectedTile,
  togglePause,
  toggleCollapse,
  updateRoute,
  selectEvent,
}: {
  readonly state: LiveState;
  readonly view: LiveViewModel;
  readonly status: LiveConnectionStatus;
  readonly lastError: string | null;
  readonly streamSource: ObservationSource;
  readonly tickerPaused: boolean;
  readonly tickerCollapsed: boolean;
  readonly frozenObserved: number;
  readonly displayedTicker: readonly LiveStageEvent[];
  readonly viewMode: LiveViewMode;
  readonly selectionState: LiveSelectionState;
  readonly selectedTile: TileState | null;
  readonly togglePause: () => void;
  readonly toggleCollapse: () => void;
  readonly updateRoute: (update: LiveRouteUpdate) => void;
  readonly selectEvent: (eventId: string | null) => void;
}) {
  return (
    <div class="live" data-filter={state.filter} data-ticker-collapsed={tickerCollapsed ? "1" : "0"}>
      <section class="live-header">
        <div>
          <span class="live-eyebrow">{t("live.eyebrow")}</span>
          <h2>
            {t("live.title")}
            <span class={`live-heartbeat ${view.streamOpen ? "is-live" : ""}`} aria-hidden="true" />
          </h2>
        </div>
        <div class="live-header-right">
          <Tooltip content={tickerPaused ? t("live.resumeTitle") : t("live.freezeTitle")}>
            <button
              type="button"
              class="live-control-btn"
              onClick={togglePause}
              aria-pressed={tickerPaused}
            >
              {tickerPaused ? (
                <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
                  <path d="M3 2 L10 6 L3 10 Z" fill="currentColor" />
                </svg>
              ) : (
                <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
                  <rect x="3" y="2" width="2.5" height="8" fill="currentColor" />
                  <rect x="6.5" y="2" width="2.5" height="8" fill="currentColor" />
                </svg>
              )}
              {tickerPaused ? t("live.resume") : t("live.freeze")}
            </button>
          </Tooltip>
          <span class="live-env-badge">
            {observationSourceLabel(streamSource)}
          </span>
          <span class="live-context-tag">
            {t("live.context.source")} <code>GET /live/stream</code>
          </span>
          <span class="live-context-tag">
            {t("live.context.window")} <strong>60s</strong>
          </span>
          <div class={`live-status live-status-${status}`}>
            <span class="live-status-dot" />
            <span>{t(`live.status.${status === "open" ? "open" : status}`)}</span>
            {lastError ? <span class="muted"> · {lastError}</span> : null}
          </div>
        </div>
      </section>

      <p class="live-lead">
        {t("live.lead")}
      </p>

      <section class="live-health" aria-label={t("live.health.label")}>
        <div>
          <span>{t("live.health.stream")}</span>
          <strong class={`live-health-${view.streamOpen ? "ok" : "warn"}`}>{t(`live.status.${status === "open" ? "open" : status}`)}</strong>
        </div>
        <div>
          <span>{t("live.health.lastEvent")}</span>
          <strong>{view.lastEventLabel}</strong>
        </div>
        <div>
          <span>{t("live.health.environment")}</span>
          <strong>{observationSourceLabel(streamSource)}</strong>
        </div>
        <div>
          <span>{t("live.health.presentation")}</span>
          <strong>{tickerPaused ? t("live.health.frozen", { count: frozenObserved }) : t("live.health.following")}</strong>
        </div>
      </section>

      <section
        class={`live-attention ${view.streamOpen && view.attentionTotal > 0 ? "live-attention-active" : view.streamOpen ? "live-attention-calm" : "live-attention-unavailable"}`}
        aria-label={t("live.attention.ariaLabel")}
      >
        {view.streamOpen && view.attentionTotal > 0 ? (
          <>
            <span class="live-attention-label">{t("live.attention.label")}</span>
            {view.attention.hil > 0 ? (
              <Tooltip content={t("live.attention.approvalTitle")}>
                <button
                  type="button"
                  class="live-attention-chip live-attention-hil"
                  onClick={() => updateRoute({ filter: "hil" })}
                >
                  {t("live.attention.approvals", { count: view.attention.hil })}
                </button>
              </Tooltip>
            ) : null}
            {view.attention.deny > 0 ? (
              <Tooltip content={t("live.attention.deniedTitle")}>
                <button
                  type="button"
                  class="live-attention-chip live-attention-deny"
                  onClick={() => updateRoute({ filter: "deny" })}
                >
                  {t("live.attention.denied", { count: view.attention.deny })}
                </button>
              </Tooltip>
            ) : null}
            {view.attention.failed > 0 ? (
              <Tooltip content={t("live.attention.failedTitle")}>
                <button
                  type="button"
                  class="live-attention-chip live-attention-failed"
                  onClick={() => updateRoute({ filter: "failed" })}
                >
                  {t("live.attention.failed", { count: view.attention.failed })}
                </button>
              </Tooltip>
            ) : null}
            {view.attention.stuck > 0 ? (
              <Tooltip content={t("live.attention.stuckTitle")}>
                <button
                  type="button"
                  class="live-attention-chip live-attention-stuck"
                  onClick={() => updateRoute({ filter: "stuck" })}
                >
                  {t("live.attention.stuck", { count: view.attention.stuck })}
                </button>
              </Tooltip>
            ) : null}
            {view.attention.hil > 0 ? <a href={routeHref("hil-queue")}>{t("live.attention.openApprovals")}</a> : null}
          </>
        ) : (
          <span class="live-attention-calm-text">
            <i class={`live-attention-dot ${view.streamOpen ? "" : "unavailable"}`} />
            {view.streamOpen ? t("live.attention.none") : t("live.attention.unavailable")}
          </span>
        )}
      </section>

      <section class="grid live-kpis">
        <div class="card kpi live-kpi live-kpi-eps">
          <span class="label">{t("live.kpi.events")}</span>
          <span class="live-kpi-value">
            {view.eps}<small>{t("live.kpi.average")}</small>
          </span>
          <Sparkline buckets={state.rateBuckets} latSum={state.latSum} latCount={state.latCount} />
          <div class="live-spark-legend" aria-hidden="true">
            <span class="live-spark-key t0"><i />T0 <b>{sumBuckets(state.rateBuckets.t0)}</b></span>
            <span class="live-spark-key t1"><i />T1 <b>{sumBuckets(state.rateBuckets.t1)}</b></span>
            <span class="live-spark-key t2"><i />T2 <b>{sumBuckets(state.rateBuckets.t2)}</b></span>
          </div>
        </div>
        <div class="card kpi live-kpi">
          <span class="label">{t("live.kpi.gateMix")}</span>
          <span class="live-kpi-value">
            {view.autoShare}% <small>{t("live.kpi.auto")}</small>
          </span>
          <StackBar
            entries={(["auto", "hil", "abstain", "deny"] as const).map((key) => ({
              key,
              label: t(`live.decision.${key}`),
              value: state.gateCounts[key] ?? 0,
              className: `live-gate live-gate-${key}`,
            }))}
            total={view.gateTotal}
            showLegend={false}
          />
          <div class="live-mix-legend">
            {(["auto", "hil", "abstain", "deny"] as const).map((key) => (
              <span key={key} class={`live-mix-key ${key}`}>
                <i />{t(`live.decision.${key}`)} <b>{state.gateCounts[key] ?? 0}</b>
              </span>
            ))}
          </div>
        </div>
        <div class="card kpi live-kpi">
          <span class="label">{t("live.kpi.tierMix")}</span>
          <div class="live-tier-summary">
            {(["t0", "t1", "t2"] as const).map((key) => (
              <span key={key} class={`live-tier live-tier-${key}`}>
                {key.toUpperCase()} {view.tierTotal > 0 ? Math.round(((state.tierCounts[key] ?? 0) / view.tierTotal) * 100) : 0}%
              </span>
            ))}
          </div>
          <StackBar
            entries={(["t0", "t1", "t2"] as const).map((key) => ({
              key,
              label: key.toUpperCase(),
              value: state.tierCounts[key] ?? 0,
              className: `live-tier live-tier-${key}`,
            }))}
            total={view.tierTotal}
            showLegend={false}
          />
        </div>
      </section>

      <section class="live-work-header">
        <div>
          <span class="live-eyebrow">{t("live.work.eyebrow")}</span>
          <h3>{t("live.work.title")}</h3>
        </div>
        <div class="segmented-control" role="group" aria-label={t("live.work.viewModeLabel")}>
          {(["queue", "flow"] as const).map((mode) => (
            <button type="button" class={viewMode === mode ? "active" : undefined} aria-pressed={viewMode === mode} onClick={() => updateRoute({ view: mode })}>
              {mode === "queue" ? t("live.work.queue") : t("live.work.flow")}
            </button>
          ))}
        </div>
      </section>

      <section class="live-filterbar" aria-label={t("live.work.filtersLabel")}>
        {(["all", "hil", "deny", "failed", "stuck"] as const).map((filter, index) => (
          <Tooltip
            key={filter}
            content={t("live.work.filterTitle", { filter: t(`live.filter.${filter}`), key: index + 1 })}
          >
            <button
              type="button"
              class={`live-filter-chip ${state.filter === filter ? "active" : ""}`}
              onClick={() => updateRoute({ filter })}
              aria-keyshortcuts={`${index + 1}`}
            >
              {t(`live.filter.${filter}`)}
              <span class="live-filter-count">{view.filterCounts[filter]}</span>
            </button>
          </Tooltip>
        ))}
        <span class="muted live-filterbar-note">{t("live.work.filterNote")}</span>
      </section>

      {viewMode === "queue" ? (
        <section aria-label={t("live.work.queueLabel")}>
          <LiveQueue
            tiles={view.populatedTiles}
            filter={state.filter}
            selectedEventId={state.selectedEventId}
            now={state.now}
            onSelect={selectEvent}
          />
        </section>
      ) : (
        <section class="live-swarm" aria-label={t("live.work.flowLabel")}>
          {view.activeTileCount === 0 ? (
            <div class="live-swarm-empty" role="status">
              <strong>{view.streamOpen ? t("live.empty.connectedTitle") : t("live.empty.disconnectedTitle")}</strong>
              <span>{view.emptyState}</span>
            </div>
          ) : null}
          {state.tiles.map((tile, index) => (
            <LiveTile
              key={index}
              tile={tile}
              filter={state.filter}
              selected={tile?.event_id === state.selectedEventId}
              now={state.now}
              onClick={
                tile
                  ? () => selectEvent(tile.event_id === state.selectedEventId ? null : tile.event_id)
                  : undefined
              }
            />
          ))}
        </section>
      )}

      <LiveTicker
        events={displayedTicker}
        collapsed={tickerCollapsed}
        paused={tickerPaused}
        onToggleCollapse={toggleCollapse}
      />

      {selectionState === "waiting" && state.selectedEventId ? (
        <div class="state-block state-unavailable" role="status">
          {t("live.selectionWaiting", { event: state.selectedEventId })}
        </div>
      ) : selectionState === "unavailable" && state.selectedEventId ? (
        <div class="state-block state-unavailable" role="alert">
          <span>{t("live.selectionUnavailable", { event: state.selectedEventId })}</span>
          <a href={routeHref("audit")}>{t("live.selectionOpenAudit")}</a>
        </div>
      ) : null}

      {selectedTile ? (
        <DetailPanel tile={selectedTile} now={state.now} onClose={() => selectEvent(null)} />
      ) : null}
    </div>
  );
}
