import { describe, expect, it, vi } from "vitest";

import {
  installOntologyInstanceRefresh,
  ONTOLOGY_INSTANCE_REFRESH_INTERVAL_MS,
  type OntologyInstanceRefreshHost,
  type OntologyInstanceRefreshTrigger,
} from "./ontology-instance-refresh";

function refreshHost(initiallyVisible = true) {
  let visible = initiallyVisible;
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
  };
  return {
    host,
    setVisible: (value: boolean) => { visible = value; },
    triggerInterval: () => interval?.(),
    triggerWindow: (type: "focus" | "online") => windowListeners.get(type)?.(),
    triggerVisible: () => documentListeners.get("visibilitychange")?.(),
  };
}

async function settleRefresh(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

describe("ontology instance refresh scheduling", () => {
  it("refreshes initially, periodically, and when a visible browser resumes", async () => {
    const refresh = vi.fn(async (_trigger: OntologyInstanceRefreshTrigger) => undefined);
    const fixture = refreshHost();
    const stop = installOntologyInstanceRefresh(refresh, fixture.host);

    expect(refresh).toHaveBeenCalledWith("initial");
    await settleRefresh();
    fixture.triggerInterval();
    await settleRefresh();
    fixture.triggerWindow("focus");
    await settleRefresh();
    fixture.triggerWindow("online");
    await settleRefresh();
    fixture.triggerVisible();
    await settleRefresh();

    expect(refresh.mock.calls.map(([trigger]) => trigger)).toEqual([
      "initial",
      "periodic",
      "focus",
      "online",
      "visible",
    ]);
    stop();
    fixture.triggerInterval();
    expect(refresh).toHaveBeenCalledTimes(5);
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
});
