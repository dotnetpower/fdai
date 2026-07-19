import { afterEach, describe, expect, test, vi } from "vitest";

import type { AuthContext } from "./auth";
import type { ConsoleConfig } from "./config";
import { ReadApiError, ReadApiTransport } from "./api-transport";

const config: ConsoleConfig = {
  readApiBaseUrl: "http://127.0.0.1:8010",
  ingestionApiBaseUrl: "http://127.0.0.1:8011",
  msalClientId: "",
  msalTenantId: "",
  msalApiScope: "",
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
  vi.unstubAllGlobals();
});

describe("read API authentication boundary", () => {
  test("fails closed when a signed-in Entra account has no bearer token", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const transport = new ReadApiTransport(config, auth({
      account: {
        homeAccountId: "home-1",
        localAccountId: "user-1",
        username: "user@example.com",
      },
    }));

    await expect(transport.getJson("/iam/self")).rejects.toEqual(
      expect.objectContaining<Partial<ReadApiError>>({ status: 401 }),
    );
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
});
