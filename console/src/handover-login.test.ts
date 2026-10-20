import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { initAuth } from "./auth";
import { loadConfig } from "./config";
import { handoverLoginSessionId } from "./handover-session";

const { activeAccount, redirect } = vi.hoisted(() => ({
  activeAccount: { value: null as unknown },
  redirect: vi.fn(),
}));
vi.mock("@azure/msal-browser", () => ({
  InteractionRequiredAuthError: class extends Error {},
  PublicClientApplication: class {
    async initialize() {}
    handleRedirectPromise = redirect;
    getActiveAccount() { return activeAccount.value; }
    getAllAccounts() {
      return [{
        homeAccountId: "synthetic-user",
        localAccountId: "synthetic-user",
        username: "user@example.com",
      }];
    }
    setActiveAccount(account: unknown) { activeAccount.value = account; }
  },
}));

let storage: Storage;
beforeEach(() => {
  const values = new Map<string, string>();
  storage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => { values.set(key, value); },
    removeItem: (key) => { values.delete(key); },
    clear: () => values.clear(), key: (index) => [...values.keys()][index] ?? null,
    get length() { return values.size; },
  };
  vi.stubGlobal("window", { location: { origin: "http://localhost:5273" }, sessionStorage: storage });
  redirect.mockReset();
  activeAccount.value = null;
});
afterEach(() => vi.unstubAllGlobals());

async function authenticate() {
  return initAuth({ ...loadConfig(), devMode: false, localAzureCliAuth: false,
    msalClientId: "synthetic-client", msalTenantId: "synthetic-tenant", msalApiScope: "api://example/access" });
}

test("same-tab successful login rotates handover identity but ordinary reload does not", async () => {
  const initial = handoverLoginSessionId(storage);
  redirect.mockResolvedValue(null);
  await authenticate();
  expect(handoverLoginSessionId(storage)).toBe(initial);
  redirect.mockResolvedValue({ account: { homeAccountId: "synthetic-user", username: "user@example.com" } });
  await authenticate();
  const next = handoverLoginSessionId(storage);
  expect(next).not.toBe(initial);
  redirect.mockResolvedValue(null);
  await authenticate();
  expect(handoverLoginSessionId(storage)).toBe(next);
});
