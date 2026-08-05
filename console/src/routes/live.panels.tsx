import { Tooltip } from "../components/tooltip";
import { PageHeader } from "../components/ui";
import type { LiveConnectionStatus } from "../hooks/use-live-stream";
import {
  observationSourceLabel,
  type ObservationSource,
} from "../hooks/observation-source";
import { useContentUpdatePulse } from "../hooks/use-content-update-pulse";
import { t as appT } from "../i18n";
import { routeHref } from "../router";
import { t } from "./i18n/live";
import {
  sumBuckets,
  type FilterKind,
  type LiveSelectionState,
  type LiveState,
  type TileState,
} from "./live.model";
import {
  compareLiveTiles,
  DetailPanel,
  LiveQueue,
  LiveTile,
  Sparkline,
  StackBar,
} from "./live.tiles";
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
  frozenObserved,
  droppedFrames,
  viewMode,
  selectionState,
  selectedTile,
  togglePause,
  updateRoute,
  selectEvent,
}: {
  readonly state: LiveState;
  readonly view: LiveViewModel;
  readonly status: LiveConnectionStatus;
  readonly lastError: string | null;
  readonly streamSource: ObservationSource;
  readonly tickerPaused: boolean;
  readonly frozenObserved: number;
  readonly droppedFrames: number;
  readonly viewMode: LiveViewMode;
  readonly selectionState: LiveSelectionState;
  readonly selectedTile: TileState | null;
  readonly togglePause: () => void;
  readonly updateRoute: (update: LiveRouteUpdate) => void;
  readonly selectEvent: (eventId: string | null) => void;
}) {
  const epsUpdated = useContentUpdatePulse([
    view.eps,
    state.rateBuckets.t0.join(","),
    state.rateBuckets.t1.join(","),
    state.rateBuckets.t2.join(","),
  ].join("|"));
  const gateUpdated = useContentUpdatePulse([
    view.autoShare,
    state.gateCounts.auto ?? 0,
    state.gateCounts.hil ?? 0,
    state.gateCounts.abstain ?? 0,
    state.gateCounts.deny ?? 0,
  ].join("|"));
  const tierUpdated = useContentUpdatePulse([
    state.tierCounts.t0 ?? 0,
    state.tierCounts.t1 ?? 0,
    state.tierCounts.t2 ?? 0,
  ].join("|"));
  const displayStatus = status === "open" && !view.streamOpen
    ? "awaitingSource"
    : status === "open"
      ? "open"
      : status;
  const gateKeys = ["auto", "hil", "abstain", "deny"] as const;
  const gateTotal = Math.max(1, view.gateTotal);
  const gateAutoEnd = ((state.gateCounts.auto ?? 0) / gateTotal) * 100;
  const gateHilEnd = gateAutoEnd + ((state.gateCounts.hil ?? 0) / gateTotal) * 100;
  const gateAbstainEnd = gateHilEnd + ((state.gateCounts.abstain ?? 0) / gateTotal) * 100;
  const gateGradient = view.gateTotal > 0
    ? `conic-gradient(var(--gate-auto) 0 ${gateAutoEnd}%, var(--gate-hil) ${gateAutoEnd}% ${gateHilEnd}%, var(--gate-abstain) ${gateHilEnd}% ${gateAbstainEnd}%, var(--gate-deny) ${gateAbstainEnd}% 100%)`
    : "var(--bg)";

  return (
    <div class="live" data-filter={state.filter}>
      <PageHeader
        title={appT("nav.panel.live")}
        subtitle={t("live.lead")}
        actions={<div class="live-header-right">
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
          <div class={`live-status live-status-${displayStatus === "awaitingSource" ? "awaiting-source" : displayStatus}`}>
            <span class="live-status-dot" />
            <span>{t(`live.status.${displayStatus}`)}</span>
            {lastError ? <span class="muted"> · {lastError}</span> : null}
          </div>
        </div>}
      />

      <section class="live-scope-strip" aria-label={t("live.scope.label")}>
        <span><strong>{t("live.scope.mode")}</strong>{t("live.scope.readOnly")}</span>
        <span><strong>{t("live.scope.source")}</strong><code>GET /live/stream</code></span>
        <span><strong>{t("live.scope.evidence")}</strong>{observationSourceLabel(streamSource)}</span>
        <span class="live-scope-warning">
          {view.streamOpen ? t("live.scope.observed") : t("live.scope.notReady")}
        </span>
      </section>

      <section class="live-health" aria-label={t("live.health.label")}>
        <div>
          <span>{t("live.health.stream")}</span>
          <strong class={`live-health-${view.streamOpen ? "ok" : "warn"}`}>{t(`live.status.${displayStatus}`)}</strong>
        </div>
        <div>
          <span>{t("live.health.lastEvent")}</span>
          <strong>{view.lastEventLabel}</strong>
        </div>
        <div>
          <span>{t("live.health.presentation")}</span>
          <strong>{tickerPaused ? t("live.health.frozen", { count: frozenObserved }) : t("live.health.following")}</strong>
        </div>
        <div>
          <span>{t("live.health.backlog")}</span>
          <strong class={droppedFrames > 0 ? "live-health-warn" : "live-health-ok"}>
            {droppedFrames > 0
              ? t("live.health.dropped", { count: droppedFrames })
              : t("live.health.complete")}
          </strong>
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
        <a class={`card kpi live-kpi live-kpi-eps${epsUpdated ? " is-content-updated" : ""}`} href={routeHref("audit")}>
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
        </a>
        <a class={`card kpi live-kpi${gateUpdated ? " is-content-updated" : ""}`} href={routeHref("audit")}>
          <span class="label">{t("live.kpi.gateMix")}</span>
          <div class="live-gate-viz">
            <div class="live-gate-donut" style={{ background: gateGradient }}>
              <span><strong>{view.autoShare}%</strong><small>{t("live.kpi.auto")}</small></span>
            </div>
            <div class="live-mix-legend">
            {gateKeys.map((key) => (
              <span key={key} class={`live-mix-key ${key}`}>
                <i />{t(`live.decision.${key}`)} <b>{state.gateCounts[key] ?? 0}</b>
              </span>
            ))}
            </div>
          </div>
          <span class="live-kpi-meta">{t("live.kpi.finalized", { count: view.gateTotal })}</span>
        </a>
        <a class={`card kpi live-kpi${tierUpdated ? " is-content-updated" : ""}`} href={routeHref("trust-routing")}>
          <span class="label">{t("live.kpi.tierMix")}</span>
          <div class="live-tier-plot">
            {(["t0", "t1", "t2"] as const).map((key) => (
              <div key={key} class={`live-tier-row live-tier-row-${key}`}>
                <span><b>{key.toUpperCase()}</b><small>{t(`live.kpi.tierLabel.${key}`)}</small></span>
                <i><i style={{ width: `${view.tierTotal > 0 ? ((state.tierCounts[key] ?? 0) / view.tierTotal) * 100 : 0}%` }} /></i>
                <strong>{view.tierTotal > 0 ? Math.round(((state.tierCounts[key] ?? 0) / view.tierTotal) * 100) : 0}%</strong>
              </div>
            ))}
            <div class="live-tier-axis"><span>0</span><span>50</span><span>100%</span></div>
          </div>
          <span class="live-kpi-meta">{t("live.kpi.routed", { count: view.tierTotal })}</span>
        </a>
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
          {[...view.populatedTiles]
            .sort((left, right) => compareLiveTiles(left, right, state.now))
            .map((tile) => (
            <LiveTile
              key={tile.event_id}
              tile={tile}
              filter={state.filter}
              selected={tile.event_id === state.selectedEventId}
              now={state.now}
              onClick={() => selectEvent(tile.event_id === state.selectedEventId ? null : tile.event_id)}
            />
          ))}
        </section>
      )}

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
