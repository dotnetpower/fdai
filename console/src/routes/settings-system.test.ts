import { describe, expect, it } from "vitest";
import type { AuthContext } from "../auth";
import {
  authenticationMode,
  isCurrentDiagnosticCheck,
  isHealthy,
} from "./settings-system";

function auth(overrides: Partial<AuthContext>): AuthContext {
  return {
    devMode: false,
    account: null,
    getAuthorizationHeader: async () => null,
    signIn: async () => undefined,
    signOut: async () => undefined,
    ...overrides,
  };
}

describe("Settings diagnostics health contract", () => {
  it("rejects a probe result superseded by another client or retry", () => {
    expect(isCurrentDiagnosticCheck(4, 3)).toBe(false);
    expect(isCurrentDiagnosticCheck(4, 4)).toBe(true);
  });

  it("accepts only the explicit Operator API health response", () => {
    expect(isHealthy({ status: "ok" })).toBe(true);
    expect(isHealthy({ status: "degraded" })).toBe(false);
    expect(isHealthy({ status: true })).toBe(false);
    expect(isHealthy(null)).toBe(false);
  });
});

describe("Settings authentication mode", () => {
  it("distinguishes local Entra from anonymous development", () => {
    const account = { homeAccountId: "home", localAccountId: "local", username: "user@example.com" };
    expect(authenticationMode(auth({ devMode: true, account }))).toBe("Local Entra");
    expect(authenticationMode(auth({ devMode: true }))).toBe("Development");
  });

  it("distinguishes Azure CLI and production Entra", () => {
    expect(authenticationMode(auth({ devMode: true, localAzureCli: true }))).toBe("Azure CLI");
    expect(authenticationMode(auth({ devMode: false }))).toBe("Microsoft Entra ID");
  });
});
