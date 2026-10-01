import { afterEach, describe, expect, test, vi } from "vitest";

import type { AuthContext } from "./auth";
import { observeUnauthorizedApiResponses } from "./auth-response";
import type { ConsoleConfig } from "./config";
import {
  isOptionalOperatorApiUnavailable,
  OperatorApiError,
  OperatorApiTransport,
} from "./api-transport";
import { EntitlementStampStore } from "./entitlement-state";

const config: ConsoleConfig = {
  operatorApiBaseUrl: "http://127.0.0.1:8010",
  ingestionApiBaseUrl: "http://127.0.0.1:8011",
  msalClientId: "",
  msalTenantId: "",
  msalApiScope: "",
  authTokenTimeoutMs: 10_000,
  operatorApiRequestTimeoutMs: 100,
  devMode: true,
  localAzureCliAuth: false,
  localLoginPrompt: true,
  workflowCatalogRepo: "",
  workflowCatalogBranch: "main",
};

function auth(overrides: Partial<AuthContext> = {}): AuthContext {
  return {
    devMode: true,
    account: null,
    async getAuthorizationHeader() { return null; },
    async signIn() {},
    async signOut() {},
    ...overrides,
  };
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("Operator API authentication boundary", () => {
  test.each([
    ["ontology_projection_missing", "ontology_projection_missing"],
    ["ontology_release_mismatch", "ontology_release_mismatch"],
    [null, "invalid_recovery_reason"],
    [{ detail: "invalid" }, "invalid_recovery_reason"],
  ])("preserves only bounded error reasons: %j", async (reason, expected) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: { status: 409, message: "ontology_generation_changed", reason },
    }), { status: 409 })));
    await expect(new OperatorApiTransport(config, auth()).getJson("/ontology/instances/states"))
      .rejects.toMatchObject({ status: 409, message: "ontology_generation_changed", reason: expected });
  });

  test("fails closed when a signed-in Entra account has no bearer token", async () => {
    const fetchMock = vi.fn();
    const onUnauthorized = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const transport = new OperatorApiTransport(config, auth({
      account: {
        homeAccountId: "home-1",
        localAccountId: "user-1",
        username: "user@example.com",
      },
    }), { onUnauthorized });

    await expect(transport.getJson("/iam/self")).rejects.toEqual(
      expect.objectContaining<Partial<OperatorApiError>>({ status: 401 }),
    );
    expect(fetchMock).not.toHaveBeenCalled();
    expect(onUnauthorized).toHaveBeenCalledWith(
      expect.objectContaining<Partial<OperatorApiError>>({ status: 401 }),
    );
  });

  describe("Operator API Sample boundary", () => {
    test("serves registered GET fixtures without authentication or fetch", async () => {
      const fetchMock = vi.fn();
      vi.stubGlobal("fetch", fetchMock);
      const transport = new OperatorApiTransport(config, auth({
        getAuthorizationHeader: async () => {
          throw new Error("Sample reads must not acquire a token");
        },
      }), {
        sampleResponse: (path, params) => ({
          path,
          value: params.get("value"),
        }),
      });

      await expect(
        transport.getJson("/sample", new URLSearchParams({ value: "one" })),
      ).resolves.toEqual({ path: "/sample", value: "one" });
      expect(fetchMock).not.toHaveBeenCalled();
    });

    test("rejects unregistered reads and every mutation", async () => {
      const transport = new OperatorApiTransport(config, auth(), {
        sampleResponse: () => undefined,
      });

      await expect(transport.getJson("/missing")).rejects.toMatchObject({ status: 404 });
      await expect(transport.postJson("/write", {}, "sample-key"))
        .rejects.toMatchObject({ status: 405 });
    });
  });

  test("fails closed when silent token acquisition stalls", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const transport = new OperatorApiTransport(config, auth({
      account: {
        homeAccountId: "home-1",
        localAccountId: "user-1",
        username: "user@example.com",
      },
      getAuthorizationHeader: () => new Promise<string | null>(() => {}),
    }));

    const request = transport.getJson("/iam/self");
    const expectation = expect(request).rejects.toEqual(
      expect.objectContaining<Partial<OperatorApiError>>({
        status: 401,
        message: "Authentication token request timed out. Retry or sign in again.",
      }),
    );
    await vi.runAllTimersAsync();

    await expectation;
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test("keeps tokenless requests for explicit anonymous dev bypass", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    const transport = new OperatorApiTransport(config, auth());

    await expect(transport.getJson("/healthz")).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8010/healthz",
      expect.objectContaining({ headers: { accept: "application/json" } }),
    );
  });

  test("keeps tokenless requests for the local Azure CLI projection", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    const transport = new OperatorApiTransport(config, auth({
      localAzureCli: true,
      account: {
        homeAccountId: "cli-1",
        localAccountId: "cli-1",
        username: "operator@example.com",
      },
    }));

    await expect(transport.getJson("/healthz")).resolves.toEqual({ ok: true });
  });

  test.each([
    "authoritative Operator projection is unavailable",
    "authoritative projection is unavailable",
  ])("distinguishes %s from an operational 503", async (message) => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(Response.json(
        { error: { status: 503, message } },
        { status: 503 },
      ))
      .mockResolvedValueOnce(Response.json(
        { error: { status: 503, message: "service unavailable" } },
        { status: 503 },
      ));
    vi.stubGlobal("fetch", fetchMock);
    const transport = new OperatorApiTransport(config, auth());

    const projectionError = await transport.getJson("/optional").catch((error: unknown) => error);
    const serviceError = await transport.getJson("/optional").catch((error: unknown) => error);

    expect(isOptionalOperatorApiUnavailable(projectionError)).toBe(true);
    expect(isOptionalOperatorApiUnavailable(serviceError)).toBe(false);
  });

  test("reports an HTTP 401 once through the shared fetch boundary", async () => {
    const onUnauthorized = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(
      { error: { status: 401, message: "Authorization header missing" } },
      { status: 401 },
    )));
    const stopObserving = observeUnauthorizedApiResponses(
      [config.operatorApiBaseUrl],
      onUnauthorized,
    );
    const transport = new OperatorApiTransport(config, auth(), { onUnauthorized });

    try {
      await expect(transport.getJson("/kpi")).rejects.toEqual(
        expect.objectContaining<Partial<OperatorApiError>>({ status: 401 }),
      );
      expect(onUnauthorized).toHaveBeenCalledOnce();
      expect(onUnauthorized).toHaveBeenCalledWith({
        status: 401,
        message: "Authentication is required. Sign in again to continue.",
      });
    } finally {
      stopObserving();
    }
  });

  test("aborts a stalled read request at the configured timeout", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      const signal = init?.signal;
      if (!(signal instanceof AbortSignal)) {
        throw new Error("expected a request abort signal");
      }
      return new Promise<Response>((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(signal.reason), { once: true });
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const transport = new OperatorApiTransport(config, auth());

    const request = transport.getJson("/kpi");
    const expectation = expect(request).rejects.toEqual(
      expect.objectContaining<Partial<OperatorApiError>>({
        status: 504,
        message: "Operator API request timed out. Retry the request.",
      }),
    );
    await vi.advanceTimersByTimeAsync(100);

    await expectation;
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});

describe("Operator entitlement stamp", () => {
  function stamped(status: number, notice: string | null): Response {
    const headers = new Headers({ "content-type": "application/json" });
    if (notice !== null) headers.set("X-FDAI-Entitlement", notice);
    const body = status < 400 ? { ok: true } : { error: { status, message: "denied" } };
    return new Response(JSON.stringify(body), { status, headers });
  }

  test("records the stamp from a successful read and a write", async () => {
    const entitlementStamps = new EntitlementStampStore(() => 7);
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(stamped(200, "none"))
      .mockResolvedValueOnce(stamped(200, "evaluation-ended")));
    const transport = new OperatorApiTransport(config, auth(), { entitlementStamps });

    await transport.getJson("/kpi");
    expect(entitlementStamps.latest()).toEqual({ notice: "none", receivedAt: 7 });
    await transport.postJson("/write", {}, "key-1");
    expect(entitlementStamps.latest()).toEqual({ notice: "evaluation-ended", receivedAt: 7 });
  });

  test("records the stamp before an error response throws", async () => {
    const entitlementStamps = new EntitlementStampStore(() => 1);
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(stamped(503, "not-activated"))
      .mockResolvedValueOnce(stamped(409, "evaluation-ended")));
    const transport = new OperatorApiTransport(config, auth(), { entitlementStamps });

    await expect(transport.getJson("/kpi")).rejects.toMatchObject({ status: 503 });
    expect(entitlementStamps.latest()?.notice).toBe("not-activated");
    await expect(transport.postJson("/write", {}, "key-2")).rejects.toMatchObject({ status: 409 });
    expect(entitlementStamps.latest()?.notice).toBe("evaluation-ended");
  });

  test("leaves the latest stamp unchanged for an unstamped response", async () => {
    const entitlementStamps = new EntitlementStampStore(() => 2);
    entitlementStamps.record("none");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stamped(401, null)));
    const transport = new OperatorApiTransport(config, auth(), { entitlementStamps });

    await expect(transport.getJson("/kpi")).rejects.toMatchObject({ status: 401 });
    expect(entitlementStamps.latest()).toEqual({ notice: "none", receivedAt: 2 });
  });
});
