import { useEffect, useState } from "preact/hooks";
import { probeBackend, type BackendHealth } from "./backend";
import { installBackendHealthRefresh } from "./backend-health-refresh";

/** Keeps launcher readiness and refreshes the shared health projection while the Deck is open. */
export function useDeckBackendHealth(open: boolean): BackendHealth | null {
  const [health, setHealth] = useState<BackendHealth | null>(null);

  useEffect(() => {
    if (document.visibilityState !== "visible" || navigator.onLine === false) return;
    let cancelled = false;
    void probeBackend().then((result) => {
      if (!cancelled) setHealth(result);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    return installBackendHealthRefresh(probeBackend, setHealth);
  }, [open]);

  return health;
}
