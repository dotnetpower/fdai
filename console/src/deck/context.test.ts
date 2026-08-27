import { describe, expect, it } from "vitest";
import {
  buildFallbackViewSnapshot,
  resolveViewSnapshot,
} from "./context";

describe("buildFallbackViewSnapshot", () => {
  it("identifies any registered panel before a detailed route snapshot publishes", () => {
    expect(buildFallbackViewSnapshot({
      routeId: "configuration-baselines",
      routeLabel: "Configuration baselines",
      purpose: "Read-only baseline evidence",
      capturedAt: "2026-08-27T12:00:00.000Z",
    })).toEqual({
      routeId: "configuration-baselines",
      routeLabel: "Configuration baselines",
      purpose: "Read-only baseline evidence",
      headline: "Read-only baseline evidence",
      facts: [],
      capturedAt: "2026-08-27T12:00:00.000Z",
    });
  });

  it("uses the panel label when a fork panel has no subtitle", () => {
    const snapshot = buildFallbackViewSnapshot({
      routeId: "fork-panel",
      routeLabel: "Fork panel",
      capturedAt: "2026-08-27T12:00:00.000Z",
    });

    expect(snapshot.purpose).toBe("Fork panel");
    expect(snapshot.headline).toBe("Fork panel");
  });

  it("uses the fallback while a route has not published and during route transitions", () => {
    const fallback = buildFallbackViewSnapshot({
      routeId: "browser-evidence",
      routeLabel: "Browser evidence",
      capturedAt: "2026-08-27T12:00:00.000Z",
    });
    const detailed = {
      ...fallback,
      headline: "1 browser evidence artifact",
      facts: [{ key: "artifact_count", value: 1 }],
    };

    expect(resolveViewSnapshot("/browser-evidence", "/browser-evidence", null, fallback))
      .toBe(fallback);
    expect(resolveViewSnapshot("/browser-evidence", "/forecast-learning", detailed, fallback))
      .toBe(fallback);
    expect(resolveViewSnapshot("/browser-evidence", "/browser-evidence", detailed, fallback))
      .toBe(detailed);
  });
});
