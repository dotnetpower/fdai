/**
 * Isolated test for the FE view-context builder that ships alongside every
 * chat request. Exercises the wiring - `_user` from getDeckUser() and
 * `_route_actions` from ROUTE_ACTION_HINTS - without going through fetch.
 * We import the module and read the wire the sole way that keeps things
 * unit-testable: via mocked fetch that captures the request body.
 */
import { describe, expect, test, vi, afterEach, beforeEach } from "vitest";
import type { ViewSnapshot } from "./context";

async function callAskAndCaptureBody(snap: ViewSnapshot | null) {
  const capture: { body?: string } = {};
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
    capture.body = String(init?.body ?? "");
    return new Response(
      JSON.stringify({ answer: "ok", model: "m", latency_ms: 1 }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  const mod = await import("./backend");
  await mod.askBackend("hi", snap, []);
  return capture.body ? (JSON.parse(capture.body) as { view_context?: Record<string, unknown> }) : null;
}

function liveSnap(): ViewSnapshot {
  return {
    routeId: "live",
    routeLabel: "Live cockpit",
    headline: "60 tiles",
    capturedAt: "2026-07-06T11:00:00+00:00",
    facts: [],
    records: {},
  };
}

describe("viewContextWithUser wiring", () => {
  beforeEach(() => {
    vi.resetModules();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("attaches _route_actions for a known route", async () => {
    const parsed = await callAskAndCaptureBody(liveSnap());
    const ctx = parsed?.view_context ?? {};
    expect(typeof ctx._route_actions).toBe("string");
    expect(String(ctx._route_actions).toLowerCase()).toContain("live cockpit");
  });

  test("omits _route_actions for a route without a hint", async () => {
    const parsed = await callAskAndCaptureBody({
      ...liveSnap(),
      routeId: "no-such-route",
      routeLabel: "Custom",
    });
    const ctx = parsed?.view_context ?? {};
    expect(ctx._route_actions).toBeUndefined();
  });

  test("null snapshot -> no _route_actions", async () => {
    const parsed = await callAskAndCaptureBody(null);
    const ctx = parsed?.view_context ?? {};
    expect(ctx._route_actions).toBeUndefined();
  });

  test("attaches _locale from the active i18n setting", async () => {
    const parsed = await callAskAndCaptureBody(liveSnap());
    const ctx = parsed?.view_context ?? {};
    // Default is 'en' - byte-identical default for English operators.
    expect(ctx._locale).toBe("en");
  });

  test("respects setLocale('ko')", async () => {
    const i18n = await import("../i18n");
    i18n.setLocale("ko");
    try {
      const parsed = await callAskAndCaptureBody(liveSnap());
      const ctx = parsed?.view_context ?? {};
      expect(ctx._locale).toBe("ko");
    } finally {
      i18n.setLocale("en");
    }
  });
});
