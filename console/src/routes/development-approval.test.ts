import { afterEach, describe, expect, test, vi } from "vitest";
import {
  DEVELOPMENT_REAUTH_WINDOW_MS,
  clearDevelopmentReauthentication,
  hasDevelopmentReauthentication,
  markDevelopmentReauthentication,
} from "./development-approval";

afterEach(() => vi.unstubAllGlobals());

function stubSessionStorage(): Map<string, string> {
  const values = new Map<string, string>();
  vi.stubGlobal("window", {
    sessionStorage: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => void values.set(key, value),
      removeItem: (key: string) => void values.delete(key),
    },
  });
  return values;
}

describe("development reauthentication marker", () => {
  test("survives the sign-in redirect for exactly one approval", () => {
    stubSessionStorage();

    markDevelopmentReauthentication("approval-1", 1_000);

    expect(hasDevelopmentReauthentication("approval-1", 2_000)).toBe(true);
    expect(hasDevelopmentReauthentication("approval-2", 2_000)).toBe(false);
    clearDevelopmentReauthentication();
    expect(hasDevelopmentReauthentication("approval-1", 2_000)).toBe(false);
  });

  test("expires with the Operator freshness window and ignores malformed state", () => {
    const values = stubSessionStorage();

    markDevelopmentReauthentication("approval-1", 1_000);

    expect(hasDevelopmentReauthentication("approval-1", 1_000 + DEVELOPMENT_REAUTH_WINDOW_MS)).toBe(true);
    expect(hasDevelopmentReauthentication("approval-1", 1_001 + DEVELOPMENT_REAUTH_WINDOW_MS)).toBe(false);
    expect(hasDevelopmentReauthentication("approval-1", 999)).toBe(false);
    values.set("fdai:development-approval-reauth", "approval-1");
    expect(hasDevelopmentReauthentication("approval-1", 2_000)).toBe(false);
  });
});
