/** Read-only provisioning presentation built from durable replay evidence. */

import { useState } from "preact/hooks";
import { PageHeader, StatusPill } from "../components/ui";
import type { ConsoleDataMode } from "../console-data-mode";
import type { ProvisionConnectionStatus } from "../hooks/use-provision-stream";
import { formatConsoleCompactTimestamp } from "../time-format";
import { t } from "./i18n/provision";
import type { ProvisionSourceState, ProvisionState } from "./provision";

type ProvisionViewId = "stages" | "readiness" | "resources";

interface Props {
  readonly consoleUrl: string | null;
  readonly dataMode: ConsoleDataMode;
  readonly embedded?: boolean;
  readonly lastError: string | null;
  readonly percent: number;
  readonly source: ProvisionSourceState;
  readonly state: ProvisionState;
  readonly status: ProvisionConnectionStatus;
}

const PROVISION_VIEWS: readonly ProvisionViewId[] = ["stages", "readiness", "resources"];

/** Resolve keyboard movement within the three-tab provisioning evidence workspace. */
export function nextProvisionView(
  current: ProvisionViewId,
  key: string,
): ProvisionViewId {
  if (key === "Home") return PROVISION_VIEWS[0]!;
  if (key === "End") return PROVISION_VIEWS[PROVISION_VIEWS.length - 1]!;
  if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(key)) return current;
  const direction = key === "ArrowRight" || key === "ArrowDown" ? 1 : -1;
  const index = PROVISION_VIEWS.indexOf(current);
  return PROVISION_VIEWS[(index + direction + PROVISION_VIEWS.length) % PROVISION_VIEWS.length]!;
}

/** Render source state, run progress, and mutually exclusive evidence views. */
export function ProvisionView({
  consoleUrl,
  dataMode,
  embedded = false,
  lastError,
  percent,
  source,
  state,
  status,
}: Props) {
  const [activeView, setActiveView] = useState<ProvisionViewId>("stages");
  const connection = connectionPresentation(source, status, dataMode, lastError);
  const visibleStreamError = provisionStreamError(lastError);

  return (
    <div class="provision">
      {embedded ? (
        <header class="environment-deployment-section-header">
          <div>
            <h2>{t("nav.panel.provision")}</h2>
            <p>{t("provision.subtitle")}</p>
          </div>
          <StatusPill kind={connection.kind} label={connection.label} />
        </header>
      ) : (
        <PageHeader
          title={t("nav.panel.provision")}
          subtitle={t("provision.subtitle")}
          actions={<StatusPill kind={connection.kind} label={connection.label} />}
        />
      )}

      <div class="provision-boundary">
        <strong>{t("provision.readOnlyLabel")}</strong>
        <span>
          {t("provision.readOnlyPrefix")} <code>GET /provision/stream</code>.{" "}
          {t("provision.readOnlySuffix")}
        </span>
      </div>

      {source.status === "loading" ? (
        <ProvisionNotice
          heading={t("provision.sourceLoadingTitle")}
          body={t("provision.sourceLoadingBody")}
        />
      ) : source.status === "unavailable" ? (
        <ProvisionNotice
          heading={t("provision.sourceUnavailableTitle")}
          body={t("provision.unavailable")}
          detail={source.reason}
        />
      ) : !state.observed ? (
        <ProvisionNotice
          heading={visibleStreamError ? t("provision.streamErrorTitle") : t("provision.noRunTitle")}
          body={visibleStreamError ?? t("provision.notObserved")}
          tone={visibleStreamError ? "error" : "neutral"}
        />
      ) : (
        <>
          <ProvisionRunSummary
            consoleUrl={consoleUrl}
            percent={percent}
            state={state}
          />

          {visibleStreamError ? (
            <div class="provision-stream-error" role="alert">
              <strong>{t("provision.streamErrorTitle")}</strong>
              <span>{visibleStreamError}</span>
            </div>
          ) : null}

          <div
            class="settings-tabs provision-tabs"
            role="tablist"
            aria-label={t("provision.viewsLabel")}
            onKeyDown={(event) => {
              const next = nextProvisionView(activeView, event.key);
              if (next === activeView) return;
              event.preventDefault();
              setActiveView(next);
              requestAnimationFrame(() => {
                document.getElementById(`provision-tab-${next}`)?.focus();
              });
            }}
          >
            {PROVISION_VIEWS.map((view) => (
              <button
                key={view}
                id={`provision-tab-${view}`}
                type="button"
                role="tab"
                class={activeView === view ? "is-active" : undefined}
                aria-selected={activeView === view}
                aria-controls={`provision-panel-${view}`}
                tabIndex={activeView === view ? 0 : -1}
                onClick={() => setActiveView(view)}
              >
                {t(`provision.view.${view}`)}
              </button>
            ))}
          </div>

          {activeView === "stages" ? <StagesPanel state={state} /> : null}
          {activeView === "readiness" ? <ReadinessPanel state={state} /> : null}
          {activeView === "resources" ? <ResourcesPanel state={state} /> : null}
        </>
      )}
    </div>
  );
}

function ProvisionNotice({
  heading,
  body,
  detail = null,
  tone = "neutral",
}: {
  readonly heading: string;
  readonly body: string;
  readonly detail?: string | null;
  readonly tone?: "neutral" | "error";
}) {
  return (
    <section
      class={`provision-notice${tone === "error" ? " is-error" : ""}`}
      role={tone === "error" ? "alert" : "status"}
      aria-labelledby="provision-notice-title"
    >
      <span class="provision-notice-marker" aria-hidden="true" />
      <div>
        <h2 id="provision-notice-title">{heading}</h2>
        <p>{body}</p>
        {detail ? (
          <details>
            <summary>{t("provision.sourceDetails")}</summary>
            <p class="mono">{detail}</p>
          </details>
        ) : null}
      </div>
    </section>
  );
}

function ProvisionRunSummary({
  consoleUrl,
  percent,
  state,
}: {
  readonly consoleUrl: string | null;
  readonly percent: number;
  readonly state: ProvisionState;
}) {
  const completed = state.stages.filter((stage) => stage.status === "completed").length;
  const active = state.stages.filter(
    (stage) => stage.status === "active" || stage.status === "waiting",
  ).length;
  const queued = state.stages.filter((stage) => stage.status === "pending").length;
  const stageTotal = state.stagesTotal ?? state.stages.length;
  const currentIndex = state.stages.findIndex((stage) => stage.id === state.currentStage);
  const currentNumber = currentIndex >= 0 ? currentIndex + 1 : Math.min(completed + 1, stageTotal);
  const run = runPresentation(state);

  return (
    <section class="provision-run" aria-labelledby="provision-run-title">
      <div class="provision-run-main">
        <div class="provision-run-state">
          <StatusPill kind={run.kind} label={run.label} />
          <span class="provision-live-indicator">
            <span aria-hidden="true" />
            {t("provision.recordedProjection")}
          </span>
        </div>
        <h2 id="provision-run-title">{t("provision.runTitle")}</h2>
        <p class="provision-current-stage">
          {t("provision.currentStage")}{" "}
          <code>{state.currentStage ?? t("provision.notRecorded")}</code>
        </p>

        <div class="provision-progress">
          <div class="provision-progress-head">
            <span>
              {stageTotal > 0
                ? t("provision.stageProgress", { current: currentNumber, total: stageTotal })
                : t("provision.progressObserved")}
            </span>
            <strong>{percent.toFixed(1)}%</strong>
          </div>
          <div
            class={`provision-meter${state.failed ? " is-failed" : ""}${
              state.ready ? " is-done" : ""
            }`}
            role="progressbar"
            aria-label={t("provision.progressLabel")}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent}
            aria-valuetext={t("provision.stagesSummary", {
              completed,
              total: stageTotal,
            })}
          >
            <div
              class="provision-meter-fill"
              style={{ width: `${Math.max(0, Math.min(100, percent))}%` }}
            />
          </div>
          <div class="provision-progress-facts">
            <span><strong>{completed}</strong> {t("provision.completeCount")}</span>
            <span><strong>{active}</strong> {t("provision.activeCount")}</span>
            <span><strong>{queued}</strong> {t("provision.queuedCount")}</span>
            {state.checkpointsCompleted !== null && state.checkpointsTotal !== null ? (
              <span>
                {t("provision.checkpointProgress", {
                  completed: state.checkpointsCompleted,
                  total: state.checkpointsTotal,
                })}
              </span>
            ) : null}
          </div>
        </div>

        <ProvisionRunMessage consoleUrl={consoleUrl} state={state} />
      </div>

      <dl class="provision-run-meta">
        <div>
          <dt>{t("provision.runId")}</dt>
          <dd><code>{state.runId ?? t("provision.notRecorded")}</code></dd>
        </div>
        <div>
          <dt>{t("provision.attempt")}</dt>
          <dd>{state.attempt ?? t("provision.notRecorded")}</dd>
        </div>
        <div>
          <dt>{t("provision.lastProgress")}</dt>
          <dd>
            {state.lastProgressAt
              ? <time dateTime={state.lastProgressAt}>{formatConsoleCompactTimestamp(state.lastProgressAt)}</time>
              : t("provision.notRecorded")}
          </dd>
        </div>
      </dl>
    </section>
  );
}

function ProvisionRunMessage({
  consoleUrl,
  state,
}: {
  readonly consoleUrl: string | null;
  readonly state: ProvisionState;
}) {
  if (!state.waiting && !state.failed && !state.cancelled && !state.ready) return null;
  return (
    <div class="provision-run-message" role="status" aria-live="polite">
      {state.waiting ? (
        <p>
          {t("provision.waitingOn")} <code>{state.waiting}</code>
          {state.waitingReason ? ` - ${state.waitingReason}` : ""}.{" "}
          {t("provision.waitingSuffix")}
        </p>
      ) : null}
      {state.failed ? (
        <p class="is-error">
          {t("provision.failedOn")} <code>{state.failed}</code>
          {state.failedReason ? ` - ${state.failedReason}` : ""}.
        </p>
      ) : null}
      {state.cancelled ? <p>{t("provision.cancelled")}</p> : null}
      {state.ready ? (
        <div class="provision-ready">
          <p>{t("provision.ready")}</p>
          {consoleUrl ? (
            <a class="provision-enter" href={consoleUrl} rel="noopener noreferrer">
              {t("provision.enter")}
            </a>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function StagesPanel({ state }: { readonly state: ProvisionState }) {
  return (
    <section
      id="provision-panel-stages"
      class="provision-panel"
      role="tabpanel"
      aria-labelledby="provision-tab-stages"
    >
      <div class="provision-section-head">
        <div>
          <span class="provision-label">{t("provision.orderedLifecycle")}</span>
          <h2>{t("provision.stages")}</h2>
          <p>{t("provision.stagesSummary", {
            completed: state.stagesCompleted ?? 0,
            total: state.stagesTotal ?? state.stages.length,
          })}</p>
        </div>
      </div>
      {state.stages.length > 0 ? (
        <ol class="provision-stages">
          {state.stages.map((stage, index) => (
            <li
              key={stage.id}
              class={`provision-stage provision-stage--${stage.status}`}
              aria-current={stage.id === state.currentStage ? "step" : undefined}
            >
              <span class="provision-stage-index">{String(index + 1).padStart(2, "0")}</span>
              <code>{stage.id}</code>
              <span class="provision-stage-state">{t(`provision.stageStatus.${stage.status}`)}</span>
            </li>
          ))}
        </ol>
      ) : <p class="provision-empty">{t("provision.stagesNotRecorded")}</p>}
    </section>
  );
}

function ReadinessPanel({ state }: { readonly state: ProvisionState }) {
  return (
    <section
      id="provision-panel-readiness"
      class="provision-panel"
      role="tabpanel"
      aria-labelledby="provision-tab-readiness"
    >
      <div class="provision-section-head">
        <div>
          <span class="provision-label">{t("provision.independentChecks")}</span>
          <h2>{t("provision.readinessTitle")}</h2>
          <p>{t("provision.readinessDescription")}</p>
        </div>
      </div>
      {state.readiness ? (
        <dl class="provision-readiness">
          {Object.entries(state.readiness).map(([key, ready]) => (
            <div key={key}>
              <dt>{t(`provision.readiness.${key}`)}</dt>
              <dd>
                <StatusPill
                  kind={ready ? "success" : "neutral"}
                  label={t(ready ? "provision.verified" : "provision.pending")}
                />
              </dd>
            </div>
          ))}
        </dl>
      ) : <p class="provision-empty">{t("provision.readinessNotRecorded")}</p>}
    </section>
  );
}

function ResourcesPanel({ state }: { readonly state: ProvisionState }) {
  return (
    <section
      id="provision-panel-resources"
      class="provision-panel"
      role="tabpanel"
      aria-labelledby="provision-tab-resources"
    >
      <div class="provision-section-head">
        <div>
          <span class="provision-label">{t("provision.independentInventory")}</span>
          <h2>{t("provision.inventoryTitle")}</h2>
          <p>{t("provision.inventoryEstimate")}</p>
        </div>
      </div>
      {state.inventory ? (
        <dl class="provision-inventory">
          <div>
            <dt>{t("provision.resources")}</dt>
            <dd>{progressPair(
              state.inventory.resources_observed,
              state.inventory.resources_expected,
            )}</dd>
          </div>
          <div>
            <dt>{t("provision.pages")}</dt>
            <dd>{progressPair(
              state.inventory.pages_completed,
              state.inventory.pages_expected,
            )}</dd>
          </div>
          <div>
            <dt>{t("provision.completeness")}</dt>
            <dd>
              {state.readiness?.inventory
                ? t("provision.independentlyVerified")
                : t("provision.awaitingVerification")}
            </dd>
          </div>
        </dl>
      ) : <p class="provision-empty">{t("provision.inventoryNotRecorded")}</p>}

      <div class="provision-recent-block">
        <h3>{t("provision.recentLabel")}</h3>
        {state.recent.length > 0 ? (
          <ul class="provision-recent">
            {state.recent.map((node) => (
              <li key={node}><code>{node}</code></li>
            ))}
          </ul>
        ) : <p class="provision-empty">{t("provision.noRecentResources")}</p>}
      </div>
    </section>
  );
}

function connectionPresentation(
  source: ProvisionSourceState,
  status: ProvisionConnectionStatus,
  dataMode: ConsoleDataMode,
  lastError: string | null,
): { readonly kind: "neutral" | "success" | "warning" | "danger"; readonly label: string } {
  if (dataMode === "sample") {
    return { kind: "neutral", label: t("provision.status.sample") };
  }
  if (source.status === "loading") {
    return { kind: "neutral", label: t("provision.status.loading") };
  }
  if (source.status === "unavailable") {
    return { kind: "warning", label: t("provision.status.unavailable") };
  }
  switch (status) {
    case "open":
      return { kind: "success", label: t("provision.status.streaming") };
    case "connecting":
      return { kind: "neutral", label: t("provision.status.connecting") };
    case "closed":
      if (lastError === "SSE connection closed") {
        return { kind: "warning", label: t("provision.status.reconnecting") };
      }
      return { kind: "danger", label: t("provision.status.disconnected") };
    case "unsupported":
      return { kind: "warning", label: t("provision.status.unsupported") };
    case "idle":
    default:
      return { kind: "neutral", label: t("provision.status.idle") };
  }
}

/** Suppress only the finite replay EOF that the hook immediately reconnects. */
export function provisionStreamError(lastError: string | null): string | null {
  return lastError === "SSE connection closed" ? null : lastError;
}

function runPresentation(
  state: ProvisionState,
): { readonly kind: "neutral" | "success" | "warning" | "danger"; readonly label: string } {
  if (state.ready) return { kind: "success", label: t("provision.runState.ready") };
  if (state.failed) return { kind: "danger", label: t("provision.runState.failed") };
  if (state.cancelled) return { kind: "neutral", label: t("provision.runState.cancelled") };
  if (state.waiting || state.runState === "waiting") {
    return { kind: "warning", label: t("provision.runState.waiting") };
  }
  const stateKey = state.runState && [
    "planning",
    "applying",
    "verifying",
    "completed",
    "blocked",
    "incomplete",
  ].includes(state.runState)
    ? state.runState
    : "observed";
  const kind = stateKey === "blocked" || stateKey === "incomplete" ? "danger" : "neutral";
  return { kind, label: t(`provision.runState.${stateKey}`) };
}

function progressPair(completed: number | null, expected: number | null): string {
  if (completed === null || expected === null) return t("provision.notMeasured");
  return t("provision.progressPair", { completed, expected });
}
