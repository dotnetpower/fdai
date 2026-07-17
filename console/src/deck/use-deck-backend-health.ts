import { useEffect, useState } from "preact/hooks";
import { probeBackend, type BackendHealth } from "./backend";

export function useDeckBackendHealth(open: boolean): BackendHealth | null {
  const [health, setHealth] = useState<BackendHealth | null>(null);

  useEffect(() => {
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
    let cancelled = false;
    void probeBackend().then((result) => {
      if (!cancelled) setHealth(result);
    });
    return () => {
      cancelled = true;
    };
  }, [open]);

  return health;
}
