import { BACKEND_HEALTH_REFRESH_MS, OFFLINE_HEALTH } from "./backend-health";
import type { BackendHealth } from "./backend-types";

/** Browser scheduling seam for the open Deck's read-only health refresh. */
export interface BackendHealthRefreshHost {
  setTimeout(callback: () => void, delay: number): unknown;
  clearTimeout(handle: unknown): void;
  addWindowListener(type: "online" | "offline", listener: () => void): void;
  removeWindowListener(type: "online" | "offline", listener: () => void): void;
  addVisibilityListener(listener: () => void): void;
  removeVisibilityListener(listener: () => void): void;
  canRefresh(): boolean;
  isOnline(): boolean;
}

/**
 * Reads initial readiness even when an embedded browser reports the open Deck as hidden.
 * Later refreshes require a visible, online tab; all reads share the coalesced health cache.
 * The interval starts after settlement so cache completion time cannot halve the refresh rate.
 * Disposal prevents pending results and timers from updating a closed or unmounted Deck.
 */
export function installBackendHealthRefresh(
  probe: () => Promise<BackendHealth>,
  onHealth: (health: BackendHealth) => void,
  host: BackendHealthRefreshHost = browserHost(),
): () => void {
  let stopped = false;
  let inFlight = false;
  let timer: unknown = null;

  const clearTimer = () => {
    if (timer !== null) host.clearTimeout(timer);
    timer = null;
  };
  const settled = (health: BackendHealth) => {
    inFlight = false;
    if (stopped) return;
    onHealth(health);
    if (host.canRefresh()) timer = host.setTimeout(refresh, BACKEND_HEALTH_REFRESH_MS);
  };
  const requestRefresh = (initial: boolean) => {
    clearTimer();
    if (stopped || inFlight || !host.isOnline() || (!initial && !host.canRefresh())) return;
    inFlight = true;
    void probe().then(settled, () => settled(OFFLINE_HEALTH));
  };
  const refresh = () => requestRefresh(false);

  host.addWindowListener("online", refresh);
  host.addWindowListener("offline", refresh);
  host.addVisibilityListener(refresh);
  requestRefresh(true);
  return () => {
    stopped = true;
    clearTimer();
    host.removeWindowListener("online", refresh);
    host.removeWindowListener("offline", refresh);
    host.removeVisibilityListener(refresh);
  };
}

function browserHost(): BackendHealthRefreshHost {
  return {
    setTimeout: (callback, delay) => window.setTimeout(callback, delay),
    clearTimeout: (handle) => window.clearTimeout(handle as number),
    addWindowListener: (type, listener) => window.addEventListener(type, listener),
    removeWindowListener: (type, listener) => window.removeEventListener(type, listener),
    addVisibilityListener: (listener) => document.addEventListener("visibilitychange", listener),
    removeVisibilityListener: (listener) => document.removeEventListener("visibilitychange", listener),
    canRefresh: () => document.visibilityState === "visible" && navigator.onLine !== false,
    isOnline: () => navigator.onLine !== false,
  };
}
