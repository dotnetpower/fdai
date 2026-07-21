import { afterEach, describe, expect, test, vi } from "vitest";

import type { AuthContext } from "./auth";
import { observeUnauthorizedApiResponses } from "./auth-response";
import type { ConsoleConfig } from "./config";
import { ReadApiError, ReadApiTransport } from "./api-transport";

const config: ConsoleConfig = {
  readApiBaseUrl: "http://127.0.0.1:8010",
  ingestionApiBaseUrl: "http://127.0.0.1:8011",
  msalClientId: "",
  msalTenantId: "",
  msalApiScope: "",
  authTokenTimeoutMs: 10_000,
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

describe("read API authentication boundary", () => {
  test("fails closed when a signed-in Entra account has no bearer token", async () => {
    const fetchMock = vi.fn();
    const onUnauthorized = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const transport = new ReadApiTransport(config, auth({
      account: {
        homeAccountId: "home-1",
        localAccountId: "user-1",
        username: "user@example.com",
      },
    }), { onUnauthorized });

    await expect(transport.getJson("/iam/self")).rejects.toEqual(
      expect.objectContaining<Partial<ReadApiError>>({ status: 401 }),
    );
    expect(fetchMock).not.toHaveBeenCalled();
    expect(onUnauthorized).toHaveBeenCalledWith(
      expect.objectContaining<Partial<ReadApiError>>({ status: 401 }),
    );
  });

  test("fails closed when silent token acquisition stalls", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const transport = new ReadApiTransport(config, auth({
      account: {
        homeAccountId: "home-1",
        localAccountId: "user-1",
        username: "user@example.com",
      },
      getAuthorizationHeader: () => new Promise<string | null>(() => {}),
    }));

    const request = transport.getJson("/iam/self");
    const expectation = expect(request).rejects.toEqual(
      expect.objectContaining<Partial<ReadApiError>>({
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
    const transport = new ReadApiTransport(config, auth());

    await expect(transport.getJson("/healthz")).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8010/healthz",
      expect.objectContaining({ headers: { accept: "application/json" } }),
    );
  });

  test("keeps tokenless requests for the local Azure CLI projection", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    const transport = new ReadApiTransport(config, auth({
      localAzureCli: true,
      account: {
        homeAccountId: "cli-1",
        localAccountId: "cli-1",
        username: "operator@example.com",
      },
    }));

    await expect(transport.getJson("/healthz")).resolves.toEqual({ ok: true });
  });

  test("reports an HTTP 401 once through the shared fetch boundary", async () => {
    const onUnauthorized = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(
      { error: { status: 401, message: "Authorization header missing" } },
      { status: 401 },
    )));
    const stopObserving = observeUnauthorizedApiResponses(
      [config.readApiBaseUrl],
      onUnauthorized,
    );
    const transport = new ReadApiTransport(config, auth(), { onUnauthorized });

    try {
      await expect(transport.getJson("/kpi")).rejects.toEqual(
        expect.objectContaining<Partial<ReadApiError>>({ status: 401 }),
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
});
