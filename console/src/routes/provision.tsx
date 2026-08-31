/**
 * Provisioning route (surface B) - a read-only view of an in-flight
 * re-provision, driven by the `GET /provision/stream` SSE endpoint.
 *
 * This is the in-console counterpart of the immersive Day-1 "Genesis"
 * bootstrap screen (`mocks/ui-webgl/provision-genesis.html`): the same
 * `provision.*` event contract, rendered here as a calm, utilitarian
 * progress view fit for the operator console shell. It never executes
 * provisioning - it renders progress and, on `provision.done`, surfaces a
 * link to the resulting console URL (app-shape.instructions.md § Operator
 * console: the console is a read surface).
 *
 * The heavy cinematic (WebGL nebula, word-by-word narration) stays in the
 * mock as the design reference; in-product re-provisioning wants legibility
 * over spectacle.
 */

import { useEffect, useMemo, useReducer, useState } from "preact/hooks";
import { sourceForRoute, type OperatorApiClient, type ReadDataSourcesPayload } from "../api";
import { PageHeader, StatusPill } from "../components/ui";
import { loadConfig } from "../config";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import type {
  ProvisionConnectionStatus,
  ProvisionEvent,
  ProvisionInventoryProgress,
  ProvisionReadiness,
  ProvisionStage,
} from "../hooks/use-provision-stream";
import { useProvisionStream } from "../hooks/use-provision-stream";
import { t } from "./i18n/provision";
import "./provision.css";

interface Props {
  readonly client: OperatorApiClient;
}

interface ProvisionSourceState {
  readonly status: "loading" | "ready" | "unavailable";
  readonly reason: string | null;
}

interface ProvisionState {
  readonly observed: boolean;
  readonly fraction: number;
  readonly waiting: string | null;
  readonly waitingReason: string | null;
  readonly failed: string | null;
  readonly failedReason: string | null;
  readonly cancelled: boolean;
  readonly ready: boolean;
  readonly consoleUrl: string | null;
  readonly runId: string | null;
  readonly sequence: number;
  readonly attempt: number | null;
  readonly runState: string | null;
  readonly currentStage: string | null;
  readonly stagesCompleted: number | null;
  readonly stagesTotal: number | null;
  readonly checkpointsCompleted: number | null;
  readonly checkpointsTotal: number | null;
  readonly lastProgressAt: string | null;
  readonly readiness: ProvisionReadiness | null;
  readonly stages: readonly ProvisionStage[];
  readonly inventory: ProvisionInventoryProgress | null;
  /** Recent nodes that finished, newest first (bounded). */
  readonly recent: readonly string[];
}

export const INITIAL: ProvisionState = {
  observed: false,
  fraction: 0,
  waiting: null,
  waitingReason: null,
  failed: null,
  failedReason: null,
  cancelled: false,
  ready: false,
  consoleUrl: null,
  runId: null,
  sequence: 0,
  attempt: null,
  runState: null,
  currentStage: null,
  stagesCompleted: null,
  stagesTotal: null,
  checkpointsCompleted: null,
  checkpointsTotal: null,
  lastProgressAt: null,
  readiness: null,
  stages: [],
  inventory: null,
  recent: [],
};

const RECENT_CAP = 6;

export function provisionSourceState(payload: ReadDataSourcesPayload): ProvisionSourceState {
  const source = sourceForRoute(payload, "/provision/stream");
  if (source === null) {
    return {
      status: "unavailable",
      reason: "The provisioning stream has no declared read-source owner.",
    };
  }
  if (source.availability === "unavailable" || !source.authoritative) {
    return {
      status: "unavailable",
      reason: source.reason ?? "No authoritative provisioning stream relay is configured.",
    };
  }
  return { status: "ready", reason: null };
}

/**
 * Return `url` only when it is an absolute `http(s)` URL, else `null`.
 *
 * `console_url` arrives over the SSE wire from the provisioning producer
 * (Terraform outputs / an in-product relay). Rendering it straight into an
 * anchor `href` would let a `javascript:` or `data:` URI execute on click
 * (DOM-based XSS / untrusted redirect, OWASP A03). The link is only shown
 * when the value parses as an absolute http/https URL.
 */
export function safeHttpUrl(url: string | null): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    const supported = parsed.protocol === "http:" || parsed.protocol === "https:";
    return supported && !parsed.username && !parsed.password ? parsed.href : null;
  } catch {
    return null;
  }
}

export function reducer(state: ProvisionState, ev: ProvisionEvent): ProvisionState {
  if ((state.ready || state.cancelled) && ev.phase !== "snapshot") return state;
  const observedState = state.observed ? state : { ...state, observed: true };
  switch (ev.phase) {
    case "snapshot":
      if (
        ev.sequence === undefined ||
        ev.run_id === undefined ||
        ev.ready === undefined ||
        ev.stages_completed === undefined ||
        ev.stages_total === undefined ||
        ev.current_stage === undefined ||
        ev.state === undefined ||
        ev.attempt === undefined ||
        ev.last_progress_at === undefined ||
        ev.readiness === undefined ||
        ev.stages === undefined
      ) return state;
      if (state.runId === ev.run_id && ev.sequence <= state.sequence) return state;
      const snapshotBase =
        state.runId === null || state.runId === ev.run_id
          ? observedState
          : { ...INITIAL, observed: true };
      return {
        ...snapshotBase,
        runId: ev.run_id,
        sequence: ev.sequence,
        attempt: ev.attempt,
        runState: ev.state,
        currentStage: ev.current_stage,
        stagesCompleted: ev.stages_completed,
        stagesTotal: ev.stages_total,
        checkpointsCompleted: ev.checkpoints_completed ?? null,
        checkpointsTotal: ev.checkpoints_total ?? null,
        lastProgressAt: ev.last_progress_at,
        readiness: ev.readiness,
        stages: ev.stages,
        inventory: ev.inventory ?? null,
        ready: ev.ready,
        waiting: ev.state === "waiting" ? ev.current_stage : null,
        waitingReason: ev.state === "waiting" ? ev.reason_code ?? null : null,
        failed: ["blocked", "failed", "incomplete"].includes(ev.state)
          ? ev.current_stage
          : null,
        failedReason: ["blocked", "failed", "incomplete"].includes(ev.state)
          ? ev.reason_code ?? null
          : null,
        cancelled: ev.state === "cancelled",
      };
    case "progress": {
      // Newest-first, unique: a repeat completion (reconnect replay / retry)
      // must not create a duplicate `key` in the recent list.
      const recent = ev.node
        ? [ev.node, ...state.recent.filter((n) => n !== ev.node)].slice(0, RECENT_CAP)
        : state.recent;
      return {
        ...observedState,
        // A progress bar never regresses: keep the high-water mark even if a
        // reconnect replays an earlier (lower) fraction.
        fraction: Math.max(
          state.fraction,
          Number.isFinite(ev.fraction) ? Math.max(0, Math.min(1, ev.fraction!)) : state.fraction,
        ),
        // Do NOT clear `waiting` here: progress for an unrelated resource must
        // not hide the "waiting on X" banner. The bridge emits `resumed` when
        // the waiting resource itself completes (see below).
        recent,
      };
    }
    case "waiting":
      return {
        ...observedState,
        waiting: ev.node ?? "a resource",
        waitingReason: ev.reason ?? null,
      };
    case "resumed":
      // Only clear when the currently-displayed waiter is the one that
      // resumed. Otherwise a concurrent waiter (A waits, B waits, A resumes)
      // would falsely hide B's banner when A's RESUMED arrives. Single-slot
      // display keeps the shape simple; identity check keeps it honest.
      return ev.node && state.waiting !== ev.node
        ? state
        : { ...observedState, waiting: null, waitingReason: null };
    case "done":
      return {
        ...observedState,
        waiting: null,
        waitingReason: null,
        consoleUrl: ev.console_url ?? state.consoleUrl,
      };
    case "failed":
      return {
        ...observedState,
        // The waiting resource resolving into a failure clears the hold.
        waiting: null,
        waitingReason: null,
        failed: ev.node ?? "a resource",
        failedReason: ev.reason ?? null,
      };
    default:
      return observedState;
  }
}

function statusLabel(status: ProvisionConnectionStatus): string {
  switch (status) {
    case "open":
      return t("provision.status.streaming");
    case "connecting":
      return t("provision.status.connecting");
    case "closed":
      return t("provision.status.disconnected");
    case "idle":
      return t("provision.status.idle");
    case "unsupported":
      return t("provision.status.unsupported");
    default:
      return status;
  }
}

export function ProvisionRoute({ client }: Props) {
  const [state, dispatch] = useReducer(reducer, INITIAL);
  const [source, setSource] = useState<ProvisionSourceState>({
    status: "loading",
    reason: null,
  });

  useEffect(() => {
    let cancelled = false;
    client.dataSources()
      .then((payload) => {
        if (!cancelled) setSource(provisionSourceState(payload));
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setSource({
            status: "unavailable",
            reason: error instanceof Error ? error.message : String(error),
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [client]);

  const url = useMemo(() => {
    const cfg = loadConfig();
    const base =
      cfg.operatorApiBaseUrl || (typeof window !== "undefined" ? window.location.origin : "");
    return `${base.replace(/\/$/, "")}/provision/stream`;
  }, []);

  const { status, lastError } = useProvisionStream({
    url,
    enabled: source.status === "ready",
    getAuthorizationHeader: client.authorizationHeader,
    onEvent: (event) => dispatch(event),
  });

  const stageFraction =
    state.stagesCompleted !== null && state.stagesTotal
      ? state.stagesCompleted / state.stagesTotal
      : state.fraction;
  const pct = state.ready
    ? 100
    : Math.max(0, Math.min(99.9, Math.round(stageFraction * 1000) / 10));
  const consoleUrl = safeHttpUrl(state.consoleUrl);

  usePublishViewContext(
    () => ({
      routeId: "provision",
      routeLabel: t("nav.panel.provision"),
      purpose: t("provision.viewPurpose"),
      glossary: composeGlossary([TERMS.shadowMode]),
      headline: state.ready
        ? t("provision.ready")
        : state.failed
        ? t("provision.failed", { resource: state.failed, reason: state.failedReason ?? t("provision.reasonUnavailable") })
        : state.cancelled
        ? t("provision.cancelled")
        : t("provision.viewHeadline", { percent: pct.toFixed(1), status: statusLabel(status) }),
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "connection_status", value: status, group: "stream" },
        { key: "source_status", value: source.status, group: "stream" },
        { key: "source_reason", value: source.reason, group: "stream" },
        { key: "observed", value: state.observed, group: "run" },
        { key: "progress_percent", value: pct, group: "run" },
        { key: "waiting_resource", value: state.waiting, group: "run" },
        { key: "failed_resource", value: state.failed, group: "run" },
        { key: "cancelled", value: state.cancelled, group: "run" },
        { key: "ready", value: state.ready, group: "run" },
        { key: "run_id", value: state.runId, group: "run" },
        { key: "current_stage", value: state.currentStage, group: "run" },
        { key: "stages_completed", value: state.stagesCompleted, group: "run" },
        { key: "stages_total", value: state.stagesTotal, group: "run" },
        { key: "resources_observed", value: state.inventory?.resources_observed ?? null, group: "inventory" },
        { key: "resources_expected", value: state.inventory?.resources_expected ?? null, group: "inventory" },
        { key: "recent_resource_count", value: state.recent.length, group: "run" },
        { key: "stream_error", value: lastError, group: "stream" },
      ],
      records: {
        recent_resources: state.recent.map((resource) => ({ resource })),
      },
    }),
    [lastError, pct, source, state, status],
  );

  return (
    <div class="provision">
      <PageHeader
        title={t("nav.panel.provision")}
        subtitle={t("provision.subtitle")}
        actions={<StatusPill kind={status === "open" ? "success" : status === "closed" ? "danger" : "neutral"} label={statusLabel(status)} />}
      />

      <p class="provision-sub">
        {t("provision.readOnlyPrefix")} <code>GET /provision/stream</code>. {t("provision.readOnlySuffix")}
      </p>

      {source.status === "unavailable" ? (
        <div class="state-block state-unavailable" role="status">
          {t("provision.unavailable")}
        </div>
      ) : state.observed ? (
        <>
          <div
            class={`provision-meter${state.failed ? " is-failed" : ""}${
              state.ready ? " is-done" : ""
            }`}
            role="progressbar"
            aria-label={t("provision.progressLabel")}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={pct}
          >
            <div class="provision-meter-fill" style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} />
          </div>
          <div class="provision-pct">{pct.toFixed(1)}%</div>
        </>
      ) : (
        <div class="state-block state-unavailable" role="status">
          {t("provision.notObserved")}
        </div>
      )}

      {/* Live region: state transitions (waiting / failed / done) are
          announced to assistive tech, which a purely visual meter cannot do. */}
      <div class="provision-status" role="status" aria-live="polite">
        {state.waiting && (
          <p class="provision-line provision-line--waiting">
            {t("provision.waitingOn")} <code>{state.waiting}</code>
            {state.waitingReason ? ` - ${state.waitingReason}` : ""}. {t("provision.waitingSuffix")}
          </p>
        )}

        {state.failed && (
          <p class="provision-line provision-line--failed">
            {t("provision.failedOn")} <code>{state.failed}</code>
            {state.failedReason ? ` - ${state.failedReason}` : ""}.
          </p>
        )}

        {state.cancelled && (
          <p class="provision-line provision-line--cancelled">{t("provision.cancelled")}</p>
        )}

        {state.ready && (
          <div class="provision-done">
            <p class="provision-line provision-line--done">{t("provision.ready")}</p>
            {consoleUrl && (
              <a class="provision-enter" href={consoleUrl} rel="noopener noreferrer">
                {t("provision.enter")}
              </a>
            )}
          </div>
        )}
      </div>

      {state.stages.length > 0 && (
        <section class="provision-section" aria-labelledby="provision-stages-title">
          <div class="provision-section-head">
            <div>
              <h2 id="provision-stages-title">{t("provision.stages")}</h2>
              <p>{t("provision.stagesSummary", {
                completed: state.stagesCompleted ?? 0,
                total: state.stagesTotal ?? state.stages.length,
              })}</p>
            </div>
            {state.runId ? <code>{state.runId}</code> : null}
          </div>
          <ol class="provision-stages">
            {state.stages.map((stage) => (
              <li
                key={stage.id}
                class={`provision-stage provision-stage--${stage.status}`}
                aria-current={stage.id === state.currentStage ? "step" : undefined}
              >
                <span class="provision-stage-marker" aria-hidden="true" />
                <code>{stage.id}</code>
                <span>{t(`provision.stageStatus.${stage.status}`)}</span>
              </li>
            ))}
          </ol>
        </section>
      )}

      {state.readiness && (
        <section class="provision-section" aria-labelledby="provision-readiness-title">
          <div class="provision-section-head">
            <div>
              <h2 id="provision-readiness-title">{t("provision.readinessTitle")}</h2>
              <p>{t("provision.readinessDescription")}</p>
            </div>
          </div>
          <dl class="provision-readiness">
            {Object.entries(state.readiness).map(([key, ready]) => (
              <div key={key}>
                <dt>{t(`provision.readiness.${key}`)}</dt>
                <dd><StatusPill kind={ready ? "success" : "neutral"} label={t(ready ? "provision.verified" : "provision.pending")} /></dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      {state.inventory && (
        <section class="provision-section" aria-labelledby="provision-inventory-title">
          <div class="provision-section-head">
            <div>
              <h2 id="provision-inventory-title">{t("provision.inventoryTitle")}</h2>
              <p>{t("provision.inventoryEstimate")}</p>
            </div>
          </div>
          <dl class="provision-inventory">
            <div>
              <dt>{t("provision.resources")}</dt>
              <dd>{progressPair(state.inventory.resources_observed, state.inventory.resources_expected)}</dd>
            </div>
            <div>
              <dt>{t("provision.pages")}</dt>
              <dd>{progressPair(state.inventory.pages_completed, state.inventory.pages_expected)}</dd>
            </div>
            <div>
              <dt>{t("provision.completeness")}</dt>
              <dd>{state.readiness?.inventory ? t("provision.independentlyVerified") : t("provision.awaitingVerification")}</dd>
            </div>
          </dl>
        </section>
      )}

      {state.recent.length > 0 && (
        <ul class="provision-recent" aria-label={t("provision.recentLabel")}>
          {state.recent.map((node) => (
            <li key={node} class="provision-recent-item">
              <code>{node}</code>
            </li>
          ))}
        </ul>
      )}

      {status === "idle" && !state.ready && (
        <p class="provision-idle">
          {t("provision.idlePrefix")} <code>provision.*</code> {t("provision.idleSuffix")}
        </p>
      )}

      {lastError && <p class="provision-error mono" role="alert">{lastError}</p>}
    </div>
  );
}

function progressPair(completed: number | null, expected: number | null): string {
  if (completed === null || expected === null) return t("provision.notMeasured");
  return t("provision.progressPair", { completed, expected });
}
