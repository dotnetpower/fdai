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

import { useMemo, useReducer } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { loadConfig } from "../config";
import type {
  ProvisionConnectionStatus,
  ProvisionEvent,
} from "../hooks/use-provision-stream";
import { useProvisionStream } from "../hooks/use-provision-stream";

interface Props {
  readonly client: ReadApiClient;
}

interface ProvisionState {
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
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
  } catch {
    return null;
  }
}

export function reducer(state: ProvisionState, ev: ProvisionEvent): ProvisionState {
  switch (ev.phase) {
    case "progress": {
      const recent = ev.node ? [ev.node, ...state.recent].slice(0, RECENT_CAP) : state.recent;
      return {
        ...state,
        // A progress bar never regresses: keep the high-water mark even if a
        // reconnect replays an earlier (lower) fraction.
        fraction: Math.max(state.fraction, ev.fraction ?? state.fraction),
        waiting: null,
        waitingReason: null,
        recent,
      };
    }
    case "waiting":
      return {
        ...state,
        waiting: ev.node ?? "a resource",
        waitingReason: ev.reason ?? null,
      };
    case "resumed":
      return { ...state, waiting: null, waitingReason: null };
    case "done":
      return {
        ...state,
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
        ...state,
        failed: ev.node ?? "a resource",
        failedReason: ev.reason ?? null,
      };
    default:
      return state;
  }
}

function statusLabel(status: ProvisionConnectionStatus): string {
  switch (status) {
    case "open":
      return "Streaming";
    case "connecting":
      return "Connecting";
    case "closed":
      return "Disconnected";
    case "idle":
      return "Idle";
    case "unsupported":
      return "SSE unsupported";
    default:
      return status;
  }
}

export function ProvisionRoute(_props: Props) {
  const [state, dispatch] = useReducer(reducer, INITIAL);

  const url = useMemo(() => {
    const cfg = loadConfig();
    const base =
      cfg.readApiBaseUrl || (typeof window !== "undefined" ? window.location.origin : "");
    return `${base.replace(/\/$/, "")}/provision/stream`;
  }, []);

  const { status, lastError } = useProvisionStream({
    url,
    onEvent: (event) => dispatch(event),
  });

  const pct = Math.max(0, Math.min(100, Math.round(state.fraction * 1000) / 10));
  const consoleUrl = safeHttpUrl(state.consoleUrl);

  return (
    <div class="provision">
      <header class="provision-head">
        <h1 class="provision-title">Provisioning</h1>
        <span class={`provision-conn provision-conn--${status}`}>{statusLabel(status)}</span>
      </header>

      <p class="provision-sub">
        A read-only view of an in-flight re-provision, streamed from{" "}
        <code>GET /provision/stream</code>. This screen renders progress; it never
        executes provisioning.
      </p>

      <div
        class={`provision-meter${state.failed ? " is-failed" : ""}${
          state.done ? " is-done" : ""
        }`}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
      >
        <div class="provision-meter-fill" style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} />
      </div>
      <div class="provision-pct">{pct.toFixed(1)}%</div>

      {state.waiting && (
        <p class="provision-line provision-line--waiting">
          Waiting on <code>{state.waiting}</code>
          {state.waitingReason ? ` - ${state.waitingReason}` : ""}. Holding, honestly.
        </p>
      )}

      {state.failed && (
        <p class="provision-line provision-line--failed">
          Failed on <code>{state.failed}</code>
          {state.failedReason ? ` - ${state.failedReason}` : ""}.
        </p>
      )}

      {state.done && (
        <div class="provision-done">
          <p class="provision-line provision-line--done">Every resource is up.</p>
          {consoleUrl && (
            <a class="provision-enter" href={consoleUrl} rel="noopener noreferrer">
              Enter the control plane
            </a>
          )}
        </div>
      )}

      {state.recent.length > 0 && (
        <ul class="provision-recent" aria-label="Recently provisioned resources">
          {state.recent.map((node) => (
            <li key={node} class="provision-recent-item">
              <code>{node}</code>
            </li>
          ))}
        </ul>
      )}

      {status === "idle" && !state.done && (
        <p class="provision-idle">
          No provisioning in progress. This screen wakes when the stream carries a{" "}
          <code>provision.*</code> event.
        </p>
      )}

      {lastError && <p class="provision-error mono">{lastError}</p>}
    </div>
  );
}
