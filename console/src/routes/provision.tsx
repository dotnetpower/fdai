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
import { sourceForRoute, type ReadApiClient, type ReadDataSourcesPayload } from "../api";
import { PageHeader, StatusPill } from "../components/ui";
import { loadConfig } from "../config";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import type {
  ProvisionConnectionStatus,
  ProvisionEvent,
} from "../hooks/use-provision-stream";
import { useProvisionStream } from "../hooks/use-provision-stream";
import { t } from "../i18n";

interface Props {
  readonly client: ReadApiClient;
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
  readonly done: boolean;
  readonly consoleUrl: string | null;
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
  done: false,
  consoleUrl: null,
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
  if (state.done) return state;
  const observedState = state.observed ? state : { ...state, observed: true };
  switch (ev.phase) {
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
        done: true,
        fraction: 1,
        waiting: null,
        waitingReason: null,
        // Every resource is up: an earlier transient failure is resolved, so
        // do not render "up" and "failed" side by side.
        failed: null,
        failedReason: null,
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
      cfg.readApiBaseUrl || (typeof window !== "undefined" ? window.location.origin : "");
    return `${base.replace(/\/$/, "")}/provision/stream`;
  }, []);

  const { status, lastError } = useProvisionStream({
    url,
    enabled: source.status === "ready",
    getAuthorizationHeader: client.authorizationHeader,
    onEvent: (event) => dispatch(event),
  });

  const pct = Math.max(0, Math.min(100, Math.round(state.fraction * 1000) / 10));
  const consoleUrl = safeHttpUrl(state.consoleUrl);

  usePublishViewContext(
    () => ({
      routeId: "provision",
      routeLabel: t("nav.panel.provision"),
      purpose: t("provision.viewPurpose"),
      glossary: composeGlossary([TERMS.shadowMode]),
      headline: state.done
        ? t("provision.done")
        : state.failed
        ? t("provision.failed", { resource: state.failed, reason: state.failedReason ?? t("provision.reasonUnavailable") })
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
        { key: "done", value: state.done, group: "run" },
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
              state.done ? " is-done" : ""
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

        {state.done && (
          <div class="provision-done">
            <p class="provision-line provision-line--done">{t("provision.done")}</p>
            {consoleUrl && (
              <a class="provision-enter" href={consoleUrl} rel="noopener noreferrer">
                {t("provision.enter")}
              </a>
            )}
          </div>
        )}
      </div>

      {state.recent.length > 0 && (
        <ul class="provision-recent" aria-label={t("provision.recentLabel")}>
          {state.recent.map((node) => (
            <li key={node} class="provision-recent-item">
              <code>{node}</code>
            </li>
          ))}
        </ul>
      )}

      {status === "idle" && !state.done && (
        <p class="provision-idle">
          {t("provision.idlePrefix")} <code>provision.*</code> {t("provision.idleSuffix")}
        </p>
      )}

      {lastError && <p class="provision-error mono" role="alert">{lastError}</p>}
    </div>
  );
}
