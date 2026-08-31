import { afterEach, describe, expect, test, vi } from "vitest";

import { initAuth } from "./auth";
import type { ConsoleConfig } from "./config";

function config(overrides: Partial<ConsoleConfig> = {}): ConsoleConfig {
  return {
    operatorApiBaseUrl: "http://127.0.0.1:8000",
    ingestionApiBaseUrl: "http://127.0.0.1:8010",
    msalClientId: "",
    msalTenantId: "",
    msalApiScope: "",
    authTokenTimeoutMs: 10_000,
    operatorApiRequestTimeoutMs: 30_000,
    devMode: false,
    localAzureCliAuth: true,
    localLoginPrompt: false,
    workflowCatalogRepo: "",
    workflowCatalogBranch: "main",
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("local Azure CLI auth", () => {
  test("projects the local profile with a process-local bearer token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          oid: "cli-user",
          username: "operator@example.com",
          name: "Example Operator",
          roles: ["Contributor"],
          source: "azure-cli",
        }),
        {
          status: 200,
          headers: {
            "content-type": "application/json",
            "x-fdai-local-session": "local-session-token",
          },
        },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const auth = await initAuth(config());

    expect(auth.localAzureCli).toBe(true);
    expect(auth.account?.homeAccountId).toBe("cli-user");
    expect(auth.account?.username).toBe("operator@example.com");
    expect(auth.account?.idTokenClaims?.roles).toEqual(["Contributor"]);
    expect(await auth.getAuthorizationHeader()).toBe("Bearer local-session-token");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/local-auth/me",
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  test("rejects ambiguous anonymous and CLI modes", async () => {
    await expect(initAuth(config({ devMode: true }))).rejects.toThrow("MUST NOT both");
  });

  test("rejects a malformed local profile", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        Response.json(
          { source: "azure-cli" },
          { headers: { "x-fdai-local-session": "local-session-token" } },
        ),
      ),
    );

    await expect(initAuth(config())).rejects.toThrow("invalid profile");
  });

  test("rejects a profile response without a local session token", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        Response.json({
          oid: "cli-user",
          username: "operator@example.com",
          name: null,
          roles: ["Contributor"],
          source: "azure-cli",
        }),
      ),
    );

    await expect(initAuth(config())).rejects.toThrow("no local session token");
  });

  test("keeps immediate anonymous bypass when the local prompt is disabled", async () => {
    const auth = await initAuth(config({
      devMode: true,
      localAzureCliAuth: false,
      localLoginPrompt: false,
    }));

    expect(auth.devMode).toBe(true);
    expect(auth.interactiveSignIn).toBe(false);
    expect(auth.account).toBeNull();
  });
});
