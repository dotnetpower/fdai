import { describe, expect, it, vi } from "vitest";

import {
  formatOntologyRefreshCountdown,
  installOntologyInstanceRefresh,
  ONTOLOGY_INSTANCE_REFRESH_INTERVAL_MS,
  type OntologyInstanceRefreshHost,
  type OntologyInstanceRefreshTrigger,
} from "./ontology-instance-refresh";

function refreshHost(initiallyVisible = true) {
  let visible = initiallyVisible;
  let now = 1_000;
  let interval: (() => void) | undefined;
  const windowListeners = new Map<string, () => void>();
  const documentListeners = new Map<string, () => void>();
  const host: OntologyInstanceRefreshHost = {
    setInterval(callback, intervalMs) {
      expect(intervalMs).toBe(ONTOLOGY_INSTANCE_REFRESH_INTERVAL_MS);
      interval = callback;
      return "interval";
    },
    clearInterval: vi.fn(),
    addWindowListener(type, listener) {
      windowListeners.set(type, listener);
    },
    removeWindowListener: vi.fn(),
    addDocumentListener(type, listener) {
      documentListeners.set(type, listener);
    },
    removeDocumentListener: vi.fn(),
    isVisible: () => visible,
    now: () => now,
  };
  return {
    host,
    setNow: (value: number) => { now = value; },
    setVisible: (value: boolean) => { visible = value; },
    triggerInterval: () => interval?.(),
    triggerWindow: (type: "focus" | "online" | "fdai:ontology-invalidated") =>
      windowListeners.get(type)?.(),
    triggerVisible: () => documentListeners.get("visibilitychange")?.(),
  };
}

async function settleRefresh(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

describe("ontology instance refresh scheduling", () => {
  it("formats a monotonic countdown without negative values", () => {
    expect(formatOntologyRefreshCountdown(15)).toBe("00:15");
    expect(formatOntologyRefreshCountdown(65)).toBe("01:05");
    expect(formatOntologyRefreshCountdown(-1)).toBe("00:00");
  });

  it("refreshes initially, periodically, and when a visible browser resumes", async () => {
    const refresh = vi.fn(async (_trigger: OntologyInstanceRefreshTrigger) => undefined);
    const fixture = refreshHost();
    const deadlines: Array<number | null> = [];
    const stop = installOntologyInstanceRefresh(refresh, fixture.host, {
      onNextPeriodicAt: (deadline) => deadlines.push(deadline),
    });

    expect(refresh).toHaveBeenCalledWith("initial");
    await settleRefresh();
    fixture.triggerInterval();
    await settleRefresh();
    fixture.triggerWindow("focus");
    await settleRefresh();
    fixture.triggerWindow("online");
    await settleRefresh();
    fixture.triggerWindow("fdai:ontology-invalidated");
    await settleRefresh();
    fixture.triggerVisible();
    await settleRefresh();

    expect(refresh.mock.calls.map(([trigger]) => trigger)).toEqual([
      "initial",
      "periodic",
      "focus",
      "online",
      "sse",
      "visible",
    ]);
    expect(deadlines).toEqual([16_000, 16_000]);
    stop();
    fixture.triggerInterval();
    expect(refresh).toHaveBeenCalledTimes(6);
    expect(deadlines.at(-1)).toBeNull();
  });

  it("does not poll a hidden document and refreshes when it becomes visible", async () => {
    const refresh = vi.fn(async (_trigger: OntologyInstanceRefreshTrigger) => undefined);
    const fixture = refreshHost(false);
    const stop = installOntologyInstanceRefresh(refresh, fixture.host);

    await settleRefresh();
    fixture.triggerInterval();
    fixture.triggerWindow("online");
    await settleRefresh();
    expect(refresh).toHaveBeenCalledTimes(1);

    fixture.setVisible(true);
    fixture.setNow(4_000);
    fixture.triggerVisible();
    await settleRefresh();
    expect(refresh).toHaveBeenLastCalledWith("visible");
    stop();
  });

  it("coalesces overlapping triggers and releases the lock after failure", async () => {
    let reject: ((reason?: unknown) => void) | undefined;
    const refresh = vi.fn((_trigger: OntologyInstanceRefreshTrigger) =>
      new Promise<void>((_resolve, rejectPromise) => {
        reject = rejectPromise;
      }));
    const fixture = refreshHost();
    const stop = installOntologyInstanceRefresh(refresh, fixture.host);

    fixture.triggerInterval();
    fixture.triggerWindow("focus");
    expect(refresh).toHaveBeenCalledTimes(1);

    reject?.(new Error("visible refresh failure"));
    await settleRefresh();
    fixture.triggerWindow("focus");
    expect(refresh).toHaveBeenCalledTimes(2);
    stop();
  });

  it("runs one queued SSE refresh after an older request settles", async () => {
    let release: (() => void) | undefined;
    const refresh = vi.fn((_trigger: OntologyInstanceRefreshTrigger) =>
      new Promise<void>((resolve) => {
        release = resolve;
      }));
    const fixture = refreshHost();
    const stop = installOntologyInstanceRefresh(refresh, fixture.host);

    fixture.triggerWindow("fdai:ontology-invalidated");
    fixture.triggerWindow("fdai:ontology-invalidated");
    expect(refresh).toHaveBeenCalledTimes(1);

    release?.();
    await settleRefresh();
    expect(refresh).toHaveBeenNthCalledWith(2, "sse");
    stop();
  });
});
