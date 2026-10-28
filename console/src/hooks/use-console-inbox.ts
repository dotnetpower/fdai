import { useEffect, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { loadConsoleInbox, type ConsoleInboxItem } from "../console-inbox";

export function useConsoleInbox(client: OperatorApiClient, enabled = true) {
  const [items, setItems] = useState<readonly ConsoleInboxItem[]>([]);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    setItems([]);
    setLoading(enabled);
    setError(false);
    if (!enabled) return;
    const poll = async () => {
      try {
        const next = await loadConsoleInbox(client);
        if (active) { setItems(next); setError(false); }
      } catch {
        if (active) setError(true);
      } finally {
        if (active) {
          setLoading(false);
          timer = setTimeout(() => { void poll(); }, 30_000);
        }
      }
    };
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [client, enabled]);
  return { items, error, loading: enabled && loading };
}
