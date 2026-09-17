/**
 * Provisioning route (surface B) - a read-only view of an in-flight
 * re-provision, driven by the `GET /provision/stream` SSE endpoint.
 *
 * It follows the information hierarchy of `mocks/ui/provision.html` while
 * rendering only evidence present in the durable `provision.*` contract.
 * It never executes provisioning; on `provision.done`, it may surface a safe
 * link to the resulting Console URL.
 */

import { useEffect, useMemo, useReducer, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { sourceForRoute, type ReadDataSourcesPayload } from "../api-data-sources";
import { loadConfig } from "../config";
import type { ConsoleDataMode } from "../console-data-mode";
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
import { OPERATIONS_SAMPLE_PROVISION_EVENTS } from "./operations.sample-events";
import { ProvisionView } from "./provision-view";
import "./provision.css";

interface Props {
  readonly client: OperatorApiClient;
  readonly dataMode: ConsoleDataMode;
  readonly embedded?: boolean;
}

/** Source-manifest state that gates the authenticated provisioning replay. */
export interface ProvisionSourceState {
  readonly status: "loading" | "ready" | "unavailable";
  readonly reason: string | null;
}

/** Reduced, display-safe state for one durable provisioning run. */
export interface ProvisionState {
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

export function ProvisionRoute(props: Props) {
  return <ProvisionRouteSession key={props.dataMode} {...props} />;
}

function ProvisionRouteSession({ client, dataMode, embedded = false }: Props) {
  const [state, dispatch] = useReducer(reducer, INITIAL);
  const [source, setSource] = useState<ProvisionSourceState>({
    status: "loading",
    reason: null,
  });

  useEffect(() => {
    let cancelled = false;
    if (dataMode === "sample") {
      setSource({ status: "ready", reason: null });
      for (const event of OPERATIONS_SAMPLE_PROVISION_EVENTS) dispatch(event);
      return () => {
        cancelled = true;
      };
    }
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
  }, [client, dataMode]);

  const url = useMemo(() => {
    const cfg = loadConfig();
    const base =
      cfg.operatorApiBaseUrl || (typeof window !== "undefined" ? window.location.origin : "");
    return `${base.replace(/\/$/, "")}/provision/stream`;
  }, []);

  const stream = useProvisionStream({
    url,
    enabled: dataMode === "live" && source.status === "ready",
    getAuthorizationHeader: client.authorizationHeader,
    onEvent: (event) => dispatch(event),
  });
  const status = dataMode === "sample" ? "open" : stream.status;
  const lastError = dataMode === "sample" ? null : stream.lastError;

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
    <ProvisionView
      consoleUrl={consoleUrl}
      dataMode={dataMode}
      embedded={embedded}
      lastError={lastError}
      percent={pct}
      source={source}
      state={state}
      status={status}
    />
  );
}
