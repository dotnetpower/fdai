import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDeckBackendHealth } from "./use-deck-backend-health";

const fixture = vi.hoisted(() => ({
  effects: [] as Array<() => void | (() => void)>,
  probe: vi.fn(),
  setHealth: vi.fn(),
  install: vi.fn(),
  stop: vi.fn(),
}));
vi.mock("preact/hooks", () => ({
  useState: () => [null, fixture.setHealth],
  useEffect: (effect: () => void | (() => void)) => { fixture.effects.push(effect); },
}));
vi.mock("./backend", () => ({ probeBackend: fixture.probe }));
vi.mock("./backend-health-refresh", () => ({ installBackendHealthRefresh: fixture.install }));

beforeEach(() => {
  fixture.effects.length = 0;
  vi.clearAllMocks();
  fixture.probe.mockResolvedValue({ available: true, model: "example-mini" });
  fixture.install.mockReturnValue(fixture.stop);
  vi.stubGlobal("document", { visibilityState: "visible" });
  vi.stubGlobal("navigator", { onLine: true });
});
afterEach(() => { vi.unstubAllGlobals(); });

describe("Deck backend health lifecycle", () => {
  it("reads launcher readiness once but does not install a periodic refresh while closed", async () => {
    useDeckBackendHealth(false);
    const cleanup = fixture.effects[0]?.();
    fixture.effects[1]?.();
    await Promise.resolve();
    expect(fixture.probe).toHaveBeenCalledTimes(1);
    expect(fixture.install).not.toHaveBeenCalled();
    if (typeof cleanup === "function") cleanup();
  });

  it("binds open-state refresh to the existing cached probe and returns its disposer", () => {
    useDeckBackendHealth(true);
    const cleanup = fixture.effects[1]?.();
    expect(fixture.install).toHaveBeenCalledWith(fixture.probe, fixture.setHealth);
    if (typeof cleanup === "function") cleanup();
    expect(fixture.stop).toHaveBeenCalledTimes(1);
  });

  it("does not issue the initial launcher read from a hidden or offline tab", () => {
    for (const state of [
      { visibilityState: "hidden", onLine: true },
      { visibilityState: "visible", onLine: false },
    ]) {
      vi.stubGlobal("document", { visibilityState: state.visibilityState });
      vi.stubGlobal("navigator", { onLine: state.onLine });
      fixture.effects.length = 0;
      useDeckBackendHealth(false);
      fixture.effects[0]?.();
    }
    expect(fixture.probe).not.toHaveBeenCalled();
  });

  it("does not update launcher state when an initial read resolves after unmount", async () => {
    useDeckBackendHealth(false);
    const cleanup = fixture.effects[0]?.();
    if (typeof cleanup === "function") cleanup();
    await Promise.resolve();
    expect(fixture.setHealth).not.toHaveBeenCalled();
  });
});
