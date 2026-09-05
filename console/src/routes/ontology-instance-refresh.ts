export const ONTOLOGY_INSTANCE_REFRESH_INTERVAL_MS = 15_000;

export type OntologyInstanceRefreshTrigger =
  | "initial"
  | "periodic"
  | "focus"
  | "online"
  | "visible"
  | "sse";

type OntologyInstanceRefreshWindowEvent = "focus" | "online" | "fdai:ontology-invalidated";

export interface OntologyInstanceRefreshHost {
  setInterval(callback: () => void, intervalMs: number): unknown;
  clearInterval(handle: unknown): void;
  addWindowListener(type: OntologyInstanceRefreshWindowEvent, listener: () => void): void;
  removeWindowListener(type: OntologyInstanceRefreshWindowEvent, listener: () => void): void;
  addDocumentListener(type: "visibilitychange", listener: () => void): void;
  removeDocumentListener(type: "visibilitychange", listener: () => void): void;
  isVisible(): boolean;
  now(): number;
}

export interface OntologyInstanceRefreshOptions {
  readonly onNextPeriodicAt?: (deadlineMs: number | null) => void;
}

export function formatOntologyRefreshCountdown(totalSeconds: number): string {
  const bounded = Math.max(0, Math.floor(totalSeconds));
  const minutes = Math.floor(bounded / 60);
  const seconds = bounded % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

/**
 * Revalidates one selected instance without overlapping requests or polling hidden tabs.
 *
 * The refresh callback owns user-visible failure reporting. A rejected callback releases
 * the in-flight lock but never changes the scheduling contract.
 */
export function installOntologyInstanceRefresh(
  refresh: (trigger: OntologyInstanceRefreshTrigger) => Promise<void>,
  host: OntologyInstanceRefreshHost = browserRefreshHost(),
  options: OntologyInstanceRefreshOptions = {},
): () => void {
  let stopped = false;
  let inFlight: Promise<void> | null = null;
  let pendingSseRefresh = false;

  const requestRefresh = (trigger: OntologyInstanceRefreshTrigger): void => {
    if (stopped || (trigger !== "initial" && !host.isVisible())) return;
    if (inFlight !== null) {
      if (trigger === "sse") pendingSseRefresh = true;
      return;
    }
    inFlight = refresh(trigger);
    const settled = () => {
      inFlight = null;
      if (pendingSseRefresh) {
        pendingSseRefresh = false;
        requestRefresh("sse");
      }
    };
    void inFlight.then(
      settled,
      settled,
    );
  };
  const onFocus = () => requestRefresh("focus");
  const onOnline = () => requestRefresh("online");
  const onVisible = () => requestRefresh("visible");
  const onSseInvalidation = () => requestRefresh("sse");
  const scheduleNextPeriodic = () => {
    options.onNextPeriodicAt?.(host.now() + ONTOLOGY_INSTANCE_REFRESH_INTERVAL_MS);
  };
  scheduleNextPeriodic();
  const interval = host.setInterval(
    () => {
      if (stopped) return;
      scheduleNextPeriodic();
      requestRefresh("periodic");
    },
    ONTOLOGY_INSTANCE_REFRESH_INTERVAL_MS,
  );

  host.addWindowListener("focus", onFocus);
  host.addWindowListener("online", onOnline);
  host.addWindowListener("fdai:ontology-invalidated", onSseInvalidation);
  host.addDocumentListener("visibilitychange", onVisible);
  requestRefresh("initial");

  return () => {
    stopped = true;
    pendingSseRefresh = false;
    host.clearInterval(interval);
    host.removeWindowListener("focus", onFocus);
    host.removeWindowListener("online", onOnline);
    host.removeWindowListener("fdai:ontology-invalidated", onSseInvalidation);
    host.removeDocumentListener("visibilitychange", onVisible);
    options.onNextPeriodicAt?.(null);
  };
}

function browserRefreshHost(): OntologyInstanceRefreshHost {
  return {
    setInterval: (callback, intervalMs) => window.setInterval(callback, intervalMs),
    clearInterval: (handle) => window.clearInterval(handle as number),
    addWindowListener: (type, listener) => window.addEventListener(type, listener),
    removeWindowListener: (type, listener) => window.removeEventListener(type, listener),
    addDocumentListener: (type, listener) => document.addEventListener(type, listener),
    removeDocumentListener: (type, listener) => document.removeEventListener(type, listener),
    isVisible: () => document.visibilityState === "visible",
    now: () => Date.now(),
  };
}
