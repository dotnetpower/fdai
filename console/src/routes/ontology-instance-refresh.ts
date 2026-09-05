export const ONTOLOGY_INSTANCE_REFRESH_INTERVAL_MS = 15_000;

export type OntologyInstanceRefreshTrigger =
  | "initial"
  | "periodic"
  | "focus"
  | "online"
  | "visible";

export interface OntologyInstanceRefreshHost {
  setInterval(callback: () => void, intervalMs: number): unknown;
  clearInterval(handle: unknown): void;
  addWindowListener(type: "focus" | "online", listener: () => void): void;
  removeWindowListener(type: "focus" | "online", listener: () => void): void;
  addDocumentListener(type: "visibilitychange", listener: () => void): void;
  removeDocumentListener(type: "visibilitychange", listener: () => void): void;
  isVisible(): boolean;
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
): () => void {
  let stopped = false;
  let inFlight: Promise<void> | null = null;

  const requestRefresh = (trigger: OntologyInstanceRefreshTrigger): void => {
    if (
      stopped
      || inFlight !== null
      || (trigger !== "initial" && !host.isVisible())
    ) return;
    inFlight = refresh(trigger);
    void inFlight.then(
      () => { inFlight = null; },
      () => { inFlight = null; },
    );
  };
  const onFocus = () => requestRefresh("focus");
  const onOnline = () => requestRefresh("online");
  const onVisible = () => requestRefresh("visible");
  const interval = host.setInterval(
    () => requestRefresh("periodic"),
    ONTOLOGY_INSTANCE_REFRESH_INTERVAL_MS,
  );

  host.addWindowListener("focus", onFocus);
  host.addWindowListener("online", onOnline);
  host.addDocumentListener("visibilitychange", onVisible);
  requestRefresh("initial");

  return () => {
    stopped = true;
    host.clearInterval(interval);
    host.removeWindowListener("focus", onFocus);
    host.removeWindowListener("online", onOnline);
    host.removeDocumentListener("visibilitychange", onVisible);
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
  };
}
