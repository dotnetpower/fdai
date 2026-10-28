import { useEffect, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { loadCurrentFindings, type CurrentFinding } from "../findings";

export function useCurrentFindings(
  client: OperatorApiClient,
  enabled = true,
  principalId?: string | null,
) {
  const [findings, setFindings] = useState<readonly CurrentFinding[]>([]);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [owner, setOwner] = useState(principalId);
  const [clientOwner, setClientOwner] = useState(client);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    setFindings([]);
    setLoading(enabled);
    setError(false);
    setOwner(principalId);
    setClientOwner(client);
    if (!enabled) return;
    const poll = async () => {
      try {
        const next = await loadCurrentFindings(client);
        if (active) { setFindings(next); setError(false); }
      } catch {
        if (active) setError(true);
      } finally {
        if (active) {
          setLoading(false);
          timer = setTimeout(() => { void poll(); }, 15_000);
        }
      }
    };
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [client, enabled, principalId]);
  const current = enabled && owner === principalId && clientOwner === client;
  return {
    findings: current ? findings : [],
    error: current && error,
    loading: enabled && (!current || loading),
  };
}
