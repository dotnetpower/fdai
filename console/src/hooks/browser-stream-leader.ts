import { useEffect, useState } from "preact/hooks";

type BrowserLockRequest = (
  name: string,
  callback: () => Promise<void>,
) => Promise<unknown>;

export function browserStreamLockName(
  channel: string,
  principalId: string | null | undefined,
): string {
  return `fdai:${channel}:${principalId?.trim() || "anonymous"}`;
}

export async function holdBrowserStreamLeadership(
  requestLock: BrowserLockRequest,
  name: string,
  signal: AbortSignal,
  onLeadershipChange: (leader: boolean) => void,
): Promise<void> {
  await requestLock(name, async () => {
    if (signal.aborted) return;
    onLeadershipChange(true);
    await new Promise<void>((resolve) => {
      signal.addEventListener("abort", () => resolve(), { once: true });
    });
    onLeadershipChange(false);
  });
}

export function useExclusiveBrowserStreamLeader(
  enabled: boolean,
  channel: string,
  principalId: string | null | undefined,
): boolean {
  const [leader, setLeader] = useState(false);

  useEffect(() => {
    setLeader(false);
    if (!enabled) return undefined;
    const lockManager = typeof navigator === "undefined" ? undefined : navigator.locks;
    if (!lockManager) {
      setLeader(true);
      return () => setLeader(false);
    }
    const controller = new AbortController();
    void holdBrowserStreamLeadership(
      (name, callback) => lockManager.request(name, () => callback()),
      browserStreamLockName(channel, principalId),
      controller.signal,
      setLeader,
    ).catch(() => {
      if (!controller.signal.aborted) setLeader(true);
    });
    return () => controller.abort();
  }, [channel, enabled, principalId]);

  return leader;
}
