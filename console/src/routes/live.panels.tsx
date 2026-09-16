import { Tooltip } from "../components/tooltip";
import { PageHeader } from "../components/ui";
import type { LiveConnectionStatus } from "../hooks/use-live-stream";
import type { AgentOperationalActivityMessage } from "../agent-operational-activity";
import {
  observationSourceLabel,
  type ObservationSource,
} from "../hooks/observation-source";
import { useContentUpdatePulse } from "../hooks/use-content-update-pulse";
import { t as appT } from "../i18n";
import { routeHref } from "../router";
import { t } from "./i18n/live";
import {
  type FilterKind,
  type LiveSelectionState,
  type LiveState,
  type TileState,
} from "./live.model";
import {
  DetailPanel,
  Sparkline,
} from "./live.tiles";
import type { LiveViewModel } from "./live.view-model";
import {
  LiveObservationDetailPanel,
  type LiveObservationLoadState,
} from "./live.observations";
import { LiveCoverage, type LiveCoverageState } from "./live.coverage";
import {
  LiveActivityWorkspace,
  type LiveViewMode,
} from "./live.activity";

export type { LiveViewMode } from "./live.activity";

export interface LiveRouteUpdate {
  readonly eventId?: string | null;
  readonly filter?: FilterKind;
  readonly view?: LiveViewMode;
}

const SAMPLE_SCENARIO_STEPS = [
  "question",
  "evidence",
  "approval",
  "dispatch",
  "observation",
  "reconciliation",
] as const;

function SampleScenario({ onInspect }: { readonly onInspect: () => void }) {
  return (
    <section class="live-sample-scenario" aria-labelledby="live-sample-scenario-title">
      <header>
        <div>
          <span class="live-eyebrow">{t("live.scenario.eyebrow")}</span>
          <h2 id="live-sample-scenario-title">{t("live.scenario.title")}</h2>
          <p>{t("live.scenario.summary")}</p>
        </div>
        <div class="live-sample-scenario-result">
          <span>{t("live.scenario.resultLabel")}</span>
          <strong>{t("live.scenario.result")}</strong>
        </div>
      </header>
      <dl class="live-sample-scenario-facts">
        <div>
          <dt>{t("live.scenario.actionLabel")}</dt>
          <dd><code>ops.start-vm@1.0.0</code></dd>
        </div>
        <div>
          <dt>{t("live.scenario.targetLabel")}</dt>
          <dd>{t("live.scenario.target")}</dd>
        </div>
        <div>
          <dt>{t("live.scenario.authorityLabel")}</dt>
          <dd>A3-H - {t("live.scenario.authority")}</dd>
        </div>
      </dl>
      <ol class="live-sample-scenario-steps">
        {SAMPLE_SCENARIO_STEPS.map((step, index) => (
          <li key={step}>
            <span aria-hidden="true">{index + 1}</span>
            <div>
              <strong>{t(`live.scenario.steps.${step}.title`)}</strong>
              <small>{t(`live.scenario.steps.${step}.detail`)}</small>
            </div>
          </li>
        ))}
      </ol>
      <footer>
        <span>{t("live.scenario.boundary")}</span>
        <button type="button" class="btn" onClick={onInspect}>
          {t("live.scenario.inspect")}
        </button>
      </footer>
    </section>
  );
}

export function LivePanels({
  state,
  view,
  status,
  lastSignalAt,
  lastError,
  streamSource,
  tickerPaused,
  restartSample,
  frozenObserved,
  droppedFrames,
  cursorReset,
  observations,
  observationLoadState,
  observationStreamStatus,
  observationStreamSource,
  observationError,
  coverage,
  viewMode,
  selectionState,
  selectedTile,
  selectedObservationId,
  selectedObservation,
  togglePause,
  updateRoute,
  selectEvent,
  selectObservation,
}: {
  readonly state: LiveState;
  readonly view: LiveViewModel;
  readonly status: LiveConnectionStatus;
  readonly lastSignalAt: number | null;
  readonly lastError: string | null;
  readonly streamSource: ObservationSource;
  readonly tickerPaused: boolean;
  readonly restartSample: (() => void) | undefined;
  readonly frozenObserved: number;
  readonly droppedFrames: number;
  readonly cursorReset: boolean;
  readonly observations: readonly AgentOperationalActivityMessage[];
  readonly observationLoadState: LiveObservationLoadState;
  readonly observationStreamStatus: LiveConnectionStatus;
  readonly observationStreamSource: ObservationSource;
  readonly observationError: string | null;
  readonly coverage: LiveCoverageState;
  readonly viewMode: LiveViewMode;
  readonly selectionState: LiveSelectionState;
  readonly selectedTile: TileState | null;
  readonly selectedObservationId: string | null;
  readonly selectedObservation: AgentOperationalActivityMessage | null;
  readonly togglePause: () => void;
  readonly updateRoute: (update: LiveRouteUpdate) => void;
  readonly selectEvent: (eventId: string | null) => void;
  readonly selectObservation: (activityId: string | null) => void;
}) {
  const { metrics } = view;
  const epsUpdated = useContentUpdatePulse([
    view.eps,
    metrics.control,
    metrics.source,
  ].join("|"));
  const gateUpdated = useContentUpdatePulse([
    view.autoShare,
    metrics.gateCounts.auto,
    metrics.gateCounts.hil,
    metrics.gateCounts.abstain,
    metrics.gateCounts.deny,
  ].join("|"));
  const tierUpdated = useContentUpdatePulse([
    metrics.tierCounts.t0,
    metrics.tierCounts.t1,
    metrics.tierCounts.t2,
  ].join("|"));
  const displayStatus = status === "open" && !view.streamOpen
    ? "awaitingSource"
    : status === "open"
      ? "open"
      : status;
  const gateKeys = ["auto", "hil", "abstain", "deny"] as const;
  const gateTotal = Math.max(1, view.gateTotal);
  const isSample = streamSource === "synthetic-dev";
  const statusLabel = isSample ? t("live.status.sample") : t(`live.status.${displayStatus}`);
  const signalAt = isSample ? view.lastEventAt : lastSignalAt;
  const lastSignalLabel = signalAt === null || signalAt === 0
    ? t("live.health.notObserved")
    : t("live.spark.secondsAgo", {
        count: Math.max(0, Math.floor((state.now - signalAt) / 1_000)),
      });
  return (
    <div class="live" data-filter={state.filter}>
      <PageHeader
        title={appT("nav.panel.live")}
        subtitle={t("live.lead")}
        actions={<div class="live-header-right">
          {restartSample ? (
            <Tooltip content={t("live.sample.restartHelp")}>
              <button type="button" class="live-sample-restart" onClick={restartSample}>
                {t("live.sample.restart")}
              </button>
            </Tooltip>
          ) : null}
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
          <span
            class={`live-context live-status-${
              displayStatus === "awaitingSource" ? "awaiting-source" : displayStatus
            }`}
          >
            <strong>{observationSourceLabel(streamSource)}</strong>
            <span>{t("live.scope.readOnly")}</span>
            <span>60s</span>
            <span class="live-connection">
              <i aria-hidden="true" />
              {statusLabel}
              {lastError ? ` · ${lastError}` : ""}
            </span>
          </span>
        </div>}
      />

      <section class="live-scope-strip" aria-label={t("live.scope.label")}>
        <span><strong>{t("live.scope.mode")}</strong>{t("live.scope.readOnly")}</span>
        <span>
          <strong>{t("live.scope.transport")}</strong>
          <code>{isSample ? t("live.scope.syntheticTransport") : "SSE /live/stream"}</code>
        </span>
        <span><strong>{t("live.scope.evidence")}</strong>{observationSourceLabel(streamSource)}</span>
        <span
          class={`live-scope-boundary ${
            isSample
              ? "is-sample"
              : view.streamOpen
                ? "is-observed"
                : "is-unavailable"
          }`}
        >
          {isSample
            ? t("live.scope.sample")
            : view.streamOpen
              ? t("live.scope.observed")
              : t("live.scope.notReady")}
        </span>
      </section>

      <div class="live-status-rail">
        <section class="live-health" aria-label={t("live.health.label")}>
          <div>
            <span>{t("live.health.lastSignal")}</span>
            <strong>{lastSignalLabel}</strong>
          </div>
          <div>
            <span>{t("live.health.backlog")}</span>
            <strong class={droppedFrames > 0 ? "live-health-warn" : "live-health-ok"}>
              {droppedFrames > 0
                ? t("live.health.dropped", { count: droppedFrames })
                : cursorReset
                  ? t("live.health.cursorReset")
                  : t("live.health.complete")}
            </strong>
          </div>
          <div>
            <span>{t("live.health.sourceCoverage")}</span>
            <strong class={`live-health-${view.streamOpen ? "ok" : "warn"}`}>
              {observationSourceLabel(streamSource)}
            </strong>
          </div>
          <div>
            <span>{t("live.health.presentation")}</span>
            <strong>
              {tickerPaused
                ? t("live.health.frozen", { count: frozenObserved })
                : t("live.health.following")}
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
              {view.attention.hil > 0 ? (
                <a href={routeHref("hil-queue")}>{t("live.attention.openApprovals")}</a>
              ) : null}
            </>
          ) : (
            <span class="live-attention-calm-text">
              <i class={`live-attention-dot ${view.streamOpen ? "" : "unavailable"}`} />
              {view.streamOpen ? t("live.attention.none") : t("live.attention.unavailable")}
            </span>
          )}
        </section>
      </div>

      {isSample ? (
        <SampleScenario onInspect={() => selectEvent("sample-event-001")} />
      ) : (
        <LiveCoverage coverage={coverage} sample={false} />
      )}

      {!isSample ? <section class="grid live-kpis">
        <a class={`card kpi live-kpi live-kpi-eps${epsUpdated ? " is-content-updated" : ""}`} href={routeHref("agent-activity")}>
          <span class="label">{t("live.kpi.events")}</span>
          <DrilldownCue />
          <span class="live-kpi-value">
            {view.eps}<small>{t("live.kpi.average")}</small>
          </span>
          <Sparkline series={[
            { label: t("live.filter.control"), values: metrics.controlBuckets, className: "live-spark-t0" },
            { label: t("live.filter.source"), values: metrics.sourceBuckets, className: "live-spark-t1" },
          ]} />
          <div class="live-spark-legend">
            <span class="live-spark-key t0"><i />{t("live.filter.control")} <b>{metrics.control}</b></span>
            <span class="live-spark-key t1"><i />{t("live.filter.source")} <b>{metrics.source}</b></span>
          </div>
          <span class="live-kpi-meta">{t(metrics.partial ? "live.kpi.partial" : "live.kpi.messagesHelp")}</span>
        </a>
        <a class={`card kpi live-kpi${gateUpdated ? " is-content-updated" : ""}`} href={routeHref("audit")}>
          <span class="label">{t("live.kpi.gateMix")}</span>
          <DrilldownCue />
          {view.gateTotal === 0 ? (
            <div class="live-kpi-unavailable">
              <strong>{t("live.kpi.noGate")}</strong>
              <small>{t("live.kpi.controlOnly")}</small>
            </div>
          ) : <div class="live-gate-viz">
            <div class="live-gate-donut">
              <svg viewBox="0 0 64 64" aria-hidden="true">
                <circle class="live-gate-track" cx="32" cy="32" r="26" />
                {gateKeys.map((key, index) => {
                  const share = metrics.gateCounts[key] / gateTotal * 100;
                  const offset = gateKeys.slice(0, index).reduce(
                    (sum, previous) => sum + metrics.gateCounts[previous], 0,
                  ) / gateTotal * 100;
                  return <circle key={key} class={`live-gate-segment is-${key}`}
                    cx="32" cy="32" r="26" pathLength="100"
                    stroke-dasharray={`${share} ${100 - share}`} stroke-dashoffset={-offset} />;
                })}
              </svg>
              <span><strong>{view.autoShare}%</strong><small>{t("live.kpi.auto")}</small></span>
            </div>
            <div class="live-mix-legend">
            {gateKeys.map((key) => (
              <span key={key} class={`live-mix-key ${key}`}>
                <i />{t(`live.decision.${key}`)} <b>{metrics.gateCounts[key]}</b>
              </span>
            ))}
            </div>
          </div>}
          <span class="live-kpi-meta">{t(metrics.partial ? "live.kpi.partial" : "live.kpi.finalized", { count: view.gateTotal })}</span>
        </a>
        <a class={`card kpi live-kpi${tierUpdated ? " is-content-updated" : ""}`} href={routeHref("trust-routing")}>
          <span class="label">{t("live.kpi.tierMix")}</span>
          <DrilldownCue />
          {view.tierTotal === 0 ? (
            <div class="live-kpi-unavailable">
              <strong>{t("live.kpi.noTier")}</strong>
              <small>{t("live.kpi.controlOnly")}</small>
            </div>
          ) : <div class="live-tier-plot">
            {(["t0", "t1", "t2"] as const).map((key) => (
              <div key={key} class={`live-tier-row live-tier-row-${key}`}>
                <span><b>{key.toUpperCase()}</b><small>{t(`live.kpi.tierLabel.${key}`)}</small></span>
                <i><i style={{ width: `${view.tierTotal > 0 ? (metrics.tierCounts[key] / view.tierTotal) * 100 : 0}%` }} /></i>
                <strong>{view.tierTotal > 0 ? Math.round((metrics.tierCounts[key] / view.tierTotal) * 100) : 0}%</strong>
              </div>
            ))}
            <div class="live-tier-axis"><span>0</span><span>50</span><span>100%</span></div>
          </div>}
          <span class="live-kpi-meta">{t(metrics.partial ? "live.kpi.partial" : "live.kpi.routed", { count: view.tierTotal })}</span>
        </a>
      </section> : null}

      <LiveActivityWorkspace
        tiles={view.populatedTiles}
        observations={observations}
        observationLoadState={observationLoadState}
        observationStreamStatus={observationStreamStatus}
        observationStreamSource={observationStreamSource}
        observationError={observationError}
        sample={isSample}
        filter={state.filter}
        viewMode={viewMode}
        now={state.now}
        controlEmptyState={view.emptyState}
        selectedEventId={state.selectedEventId}
        selectedObservationId={selectedObservationId}
        onFilter={(filter) => updateRoute({ filter })}
        onViewMode={(view) => updateRoute({ view })}
        onSelectEvent={selectEvent}
        onSelectObservation={selectObservation}
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
        <DetailPanel tile={selectedTile} now={state.now} sample={isSample} onClose={() => selectEvent(null)} />
      ) : null}
      {selectedObservation ? (
        <LiveObservationDetailPanel
          item={selectedObservation}
          onClose={() => selectObservation(null)}
        />
      ) : null}
    </div>
  );
}

function DrilldownCue() {
  return (
    <svg class="live-kpi-detail-cue" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M5 3 H13 V11 M13 3 L4 12" />
    </svg>
  );
}
