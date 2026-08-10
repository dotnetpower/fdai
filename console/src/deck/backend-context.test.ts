/**
 * Isolated test for the FE view-context builder that ships alongside every
 * chat request. Exercises the wiring - `_user` from getDeckUser() and
 * `_route_actions` from ROUTE_ACTION_HINTS - without going through fetch.
 * We import the module and read the wire the sole way that keeps things
 * unit-testable: via mocked fetch that captures the request body.
 */
import { afterEach, describe, expect, test, vi } from "vitest";
import type { ViewSnapshot } from "./context";
import { askBackend } from "./backend";
import { healthUrl, requestHeaders } from "./backend-endpoints";
import { createBackendHealthProbe } from "./backend-health";
import { createBackendRequestPayload } from "./backend-context";
import { parseRouter } from "./backend-normalizers";
import { setChatAuth } from "./auth";
import { resetConsolePreferences, setConsolePreference } from "../preferences";

async function callAskAndCaptureBody(
  snap: ViewSnapshot | null,
  sessionId?: string,
  binding?: import("./open-deck").IncidentConversationBinding,
  targetAgent?: string,
) {
  const capture: { body?: string } = {};
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
    capture.body = String(init?.body ?? "");
    return new Response(
      JSON.stringify({ answer: "ok", model: "m", latency_ms: 1 }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  await askBackend("hi", snap, [], sessionId, binding, targetAgent);
  return capture.body
    ? (JSON.parse(capture.body) as {
        view_context?: Record<string, unknown>;
      })
    : null;
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
  afterEach(() => {
    vi.unstubAllGlobals();
    setChatAuth(null);
    resetConsolePreferences();
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

  test("keeps the current screen path when the panel snapshot is unavailable", async () => {
    vi.stubGlobal("window", { location: { pathname: "/workflow-builder" } });
    const parsed = await callAskAndCaptureBody(null);
    const ctx = parsed?.view_context ?? {};
    expect(ctx._screen_path).toBe("/workflow-builder");
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

  test("sends the stable backend session id", async () => {
    const parsed = await callAskAndCaptureBody(liveSnap(), "session-42");
    expect((parsed as Record<string, unknown>).session_id).toBe("session-42");
  });

  test("requests model traces only after the default-off preference is enabled", () => {
    const disabled = createBackendRequestPayload("status", liveSnap(), [], "session-42");
    setConsolePreference("showModelTrace", true);
    const enabled = createBackendRequestPayload("status", liveSnap(), [], "session-42");

    expect(disabled.include_model_trace).toBeUndefined();
    expect(enabled.include_model_trace).toBe(true);
  });

  test("sends the incident binding as structured conversation context", async () => {
    const parsed = await callAskAndCaptureBody(liveSnap(), "session-42", {
      kind: "incident",
      incidentId: "INC-selected",
      correlationId: "corr-selected",
      selectedAgent: "Var",
    });

    expect((parsed as Record<string, unknown>).conversation_context).toEqual({
      kind: "incident",
      incident_id: "INC-selected",
      correlation_id: "corr-selected",
      selected_agent: "Var",
    });
  });

  test("sends the persistent target for a plain agent conversation", async () => {
    const parsed = await callAskAndCaptureBody(
      liveSnap(),
      "session-heimdall",
      undefined,
      "Heimdall",
    );

    expect((parsed as Record<string, unknown>).target_agent).toBe("Heimdall");
  });

  test("sends the latest assistant resource as bounded follow-up context", () => {
    const older = {
      name: "db-old",
      resource_type: "postgresql-server",
      evidence_ref: "inventory:/subscriptions/test/resourceGroups/rg/providers/db/old",
    };
    const current = {
      name: "db-current",
      resource_type: "postgresql-server",
      evidence_ref: "inventory:/subscriptions/test/resourceGroups/rg/providers/db/current",
    };

    const payload = createBackendRequestPayload("언제부터 중지되어 있었어?", liveSnap(), [
      { role: "assistant", content: "old", resourceContext: older },
      { role: "user", content: "중지된 DB 있어?" },
      { role: "assistant", content: "current", resourceContext: current },
    ], "session-42");

    expect(payload.resource_context).toEqual(current);
    expect(payload.history).toEqual([
      { role: "assistant", content: "old" },
      { role: "user", content: "중지된 DB 있어?" },
      { role: "assistant", content: "current" },
    ]);
  });

  test("does not reuse resource context across a later unrelated assistant turn", () => {
    const payload = createBackendRequestPayload("언제부터였어?", liveSnap(), [
      {
        role: "assistant",
        content: "db result",
        resourceContext: {
          name: "db-old",
          resource_type: "postgresql-server",
          evidence_ref: "inventory:/subscriptions/test/resourceGroups/rg/providers/db/old",
        },
      },
      { role: "user", content: "다른 질문" },
      { role: "assistant", content: "unrelated answer" },
    ], "session-42");

    expect(payload.resource_context).toBeUndefined();
  });
});

describe("backend health probing", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    setChatAuth(null);
  });

  test("deduplicates concurrent and repeated probes", async () => {
    const fetchMock = vi.fn(
      async (_url: string, _init?: RequestInit) =>
        new Response(
          JSON.stringify({ available: true, mode: "test", model: "m", endpoint: null }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const probeBackend = createBackendHealthProbe(healthUrl, () => requestHeaders(), parseRouter);

    const [first, second] = await Promise.all([probeBackend(), probeBackend()]);
    const cached = await probeBackend();

    expect(first.available).toBe(true);
    expect(second).toEqual(first);
    expect(cached).toEqual(first);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  test("attaches the current bearer token", async () => {
    const fetchMock = vi.fn(
      async (_url: string, _init?: RequestInit) =>
        new Response(
          JSON.stringify({ available: true, mode: "test", model: "m", endpoint: null }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
    );
    vi.stubGlobal("fetch", fetchMock);
    setChatAuth({
      devMode: false,
      account: null,
      getAuthorizationHeader: async () => "Bearer test-token",
      signIn: async () => undefined,
      signOut: async () => undefined,
    });
    const probeBackend = createBackendHealthProbe(healthUrl, () => requestHeaders(), parseRouter);

    await probeBackend();

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect((init.headers as Record<string, string>).authorization).toBe("Bearer test-token");
  });
});
