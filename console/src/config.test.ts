import { afterEach, describe, expect, test, vi } from "vitest";

import { loadConfig } from "./config";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("console config", () => {
  test("loads a configured authentication token timeout", () => {
    vi.stubEnv("VITE_AUTH_TOKEN_TIMEOUT_MS", "2500");

    expect(loadConfig().authTokenTimeoutMs).toBe(2500);
  });

  test("rejects an invalid authentication token timeout", () => {
    vi.stubEnv("VITE_AUTH_TOKEN_TIMEOUT_MS", "never");

    expect(() => loadConfig()).toThrow(
      "VITE_AUTH_TOKEN_TIMEOUT_MS must be a positive integer.",
    );
  });
});
