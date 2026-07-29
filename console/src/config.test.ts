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

  test("loads a configured Read API request timeout", () => {
    vi.stubEnv("VITE_READ_API_REQUEST_TIMEOUT_MS", "15000");

    expect(loadConfig().readApiRequestTimeoutMs).toBe(15_000);
  });

  test("rejects an invalid Read API request timeout", () => {
    vi.stubEnv("VITE_READ_API_REQUEST_TIMEOUT_MS", "never");

    expect(() => loadConfig()).toThrow(
      "VITE_READ_API_REQUEST_TIMEOUT_MS must be a positive integer.",
    );
  });
});
