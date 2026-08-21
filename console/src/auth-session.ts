export const AUTH_SESSION_REFRESH_INTERVAL_MS = 30 * 60 * 1_000;

export type AuthSessionRefreshTrigger = "startup" | "periodic" | "focus" | "online" | "visible";

export interface AuthSessionHost {
  setInterval(callback: () => void, intervalMs: number): unknown;
  clearInterval(handle: unknown): void;
  addWindowListener(type: "focus" | "online", listener: () => void): void;
  removeWindowListener(type: "focus" | "online", listener: () => void): void;
  addDocumentListener(type: "visibilitychange", listener: () => void): void;
  removeDocumentListener(type: "visibilitychange", listener: () => void): void;
  isVisible(): boolean;
}

export function msalCacheLocationForOrigin(
  origin: string,
): "localStorage" | "sessionStorage" {
  const hostname = new URL(origin).hostname;
  return hostname === "localhost" || hostname === "127.0.0.1" ||
      hostname === "::1" || hostname === "[::1]"
    ? "localStorage"
    : "sessionStorage";
}

export function installAuthSessionKeeper(
  refresh: (trigger: AuthSessionRefreshTrigger) => Promise<void>,
  host: AuthSessionHost = browserSessionHost(),
): () => void {
  let stopped = false;
  let inFlight: Promise<void> | null = null;

  const requestRefresh = (trigger: AuthSessionRefreshTrigger) => {
    if (stopped || inFlight !== null) return;
    inFlight = refresh(trigger)
      .catch(() => undefined)
      .finally(() => {
        inFlight = null;
      });
  };
  const onFocus = () => requestRefresh("focus");
  const onOnline = () => requestRefresh("online");
  const onVisible = () => {
    if (host.isVisible()) requestRefresh("visible");
  };
  const interval = host.setInterval(
    () => requestRefresh("periodic"),
    AUTH_SESSION_REFRESH_INTERVAL_MS,
  );

  host.addWindowListener("focus", onFocus);
  host.addWindowListener("online", onOnline);
  host.addDocumentListener("visibilitychange", onVisible);
  requestRefresh("startup");

  return () => {
    stopped = true;
    host.clearInterval(interval);
    host.removeWindowListener("focus", onFocus);
    host.removeWindowListener("online", onOnline);
    host.removeDocumentListener("visibilitychange", onVisible);
  };
}

function browserSessionHost(): AuthSessionHost {
  return {
    setInterval: (callback, intervalMs) => window.setInterval(callback, intervalMs),
    clearInterval: (handle) => window.clearInterval(handle as number),
    addWindowListener: (type, listener) => window.addEventListener(type, listener),
    removeWindowListener: (type, listener) => window.removeEventListener(type, listener),
    addDocumentListener: (type, listener) => document.addEventListener(type, listener),
    removeDocumentListener: (type, listener) => document.removeEventListener(type, listener),
    isVisible: () => document.visibilityState === "visible",
  };
}
