import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { loadConfig } from "./config";
import type { ConsoleRuntimeConfig } from "./runtime-config";

const runtimeConfig: ConsoleRuntimeConfig = {
  schema_version: "fdai.console-runtime.v1",
  operator_api_base_url: "https://operator.example.com",
  ingestion_api_base_url: "https://ingestion.example.com/api",
  tenant_id: "00000000-0000-0000-0000-000000000001",
  spa_client_id: "00000000-0000-0000-0000-000000000002",
  api_scope: "api://00000000-0000-0000-0000-000000000003/access_as_user",
};

beforeEach(() => {
  vi.stubGlobal("__FDAI_CONSOLE_CONFIG__", undefined);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("console config", () => {
  test("uses the canonical local API origins by default", () => {
    const config = loadConfig();

    expect(config.operatorApiBaseUrl).toBe("http://127.0.0.1:8010");
    expect(config.ingestionApiBaseUrl).toBe("http://127.0.0.1:8011");
  });

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

  test("loads a configured Operator API request timeout", () => {
    vi.stubEnv("VITE_OPERATOR_API_REQUEST_TIMEOUT_MS", "15000");

    expect(loadConfig().operatorApiRequestTimeoutMs).toBe(15_000);
  });

  test("rejects an invalid Operator API request timeout", () => {
    vi.stubEnv("VITE_OPERATOR_API_REQUEST_TIMEOUT_MS", "never");

    expect(() => loadConfig()).toThrow(
      "VITE_OPERATOR_API_REQUEST_TIMEOUT_MS must be a positive integer.",
    );
  });

  test.each([undefined, null])("preserves legacy Vite configuration with %s runtime config", (value) => {
    vi.stubGlobal("__FDAI_CONSOLE_CONFIG__", value);
    vi.stubEnv("VITE_OPERATOR_API_BASE_URL", "http://127.0.0.1:8010/custom");
    vi.stubEnv("VITE_INGESTION_API_BASE_URL", "http://127.0.0.1:8011/custom");
    vi.stubEnv("VITE_MSAL_CLIENT_ID", "legacy-client");
    vi.stubEnv("VITE_MSAL_TENANT_ID", "legacy-tenant");
    vi.stubEnv("VITE_MSAL_API_SCOPE", "legacy-scope");
    vi.stubEnv("VITE_DEV_MODE", "1");
    vi.stubEnv("VITE_LOCAL_AZURE_CLI_AUTH", "1");
    vi.stubEnv("VITE_LOCAL_LOGIN_PROMPT", "1");
    vi.stubEnv("VITE_AUTH_TOKEN_TIMEOUT_MS", "2500");
    vi.stubEnv("VITE_OPERATOR_API_REQUEST_TIMEOUT_MS", "15000");
    vi.stubEnv("VITE_WORKFLOW_CATALOG_REPO", "example/catalog");
    vi.stubEnv("VITE_WORKFLOW_CATALOG_BRANCH", "release");

    expect(loadConfig()).toEqual({
      operatorApiBaseUrl: "http://127.0.0.1:8010/custom",
      ingestionApiBaseUrl: "http://127.0.0.1:8011/custom",
      msalClientId: "legacy-client",
      msalTenantId: "legacy-tenant",
      msalApiScope: "legacy-scope",
      authTokenTimeoutMs: 2500,
      operatorApiRequestTimeoutMs: 15000,
      devMode: true,
      localAzureCliAuth: true,
      localLoginPrompt: true,
      workflowCatalogRepo: "example/catalog",
      workflowCatalogBranch: "release",
    });
  });

  test("runtime bindings override only API and Entra values and close every auth bypass", () => {
    vi.stubGlobal("__FDAI_CONSOLE_CONFIG__", runtimeConfig);
    vi.stubEnv("VITE_OPERATOR_API_BASE_URL", "http://127.0.0.1:8010/stale");
    vi.stubEnv("VITE_INGESTION_API_BASE_URL", "http://127.0.0.1:8011/stale");
    vi.stubEnv("VITE_MSAL_CLIENT_ID", "stale-client");
    vi.stubEnv("VITE_MSAL_TENANT_ID", "stale-tenant");
    vi.stubEnv("VITE_MSAL_API_SCOPE", "stale-scope");
    vi.stubEnv("VITE_DEV_MODE", "1");
    vi.stubEnv("VITE_LOCAL_AZURE_CLI_AUTH", "1");
    vi.stubEnv("VITE_LOCAL_LOGIN_PROMPT", "1");
    vi.stubEnv("VITE_AUTH_TOKEN_TIMEOUT_MS", "2500");
    vi.stubEnv("VITE_OPERATOR_API_REQUEST_TIMEOUT_MS", "15000");
    vi.stubEnv("VITE_WORKFLOW_CATALOG_REPO", "example/catalog");
    vi.stubEnv("VITE_WORKFLOW_CATALOG_BRANCH", "release");

    expect(loadConfig()).toEqual({
      operatorApiBaseUrl: runtimeConfig.operator_api_base_url,
      ingestionApiBaseUrl: runtimeConfig.ingestion_api_base_url,
      msalClientId: runtimeConfig.spa_client_id,
      msalTenantId: runtimeConfig.tenant_id,
      msalApiScope: runtimeConfig.api_scope,
      authTokenTimeoutMs: 2500,
      operatorApiRequestTimeoutMs: 15000,
      devMode: false,
      localAzureCliAuth: false,
      localLoginPrompt: false,
      workflowCatalogRepo: "example/catalog",
      workflowCatalogBranch: "release",
    });
  });

  test.each([
    {},
    [],
    false,
    { ...runtimeConfig, tenant_id: "invalid" },
    { ...runtimeConfig, operator_api_base_url: "http://operator.example.com" },
    { ...runtimeConfig, devMode: true },
  ].map((value) => ({ value })))("malformed present runtime config never falls back to Vite: $value", ({ value }) => {
    vi.stubGlobal("__FDAI_CONSOLE_CONFIG__", value);
    vi.stubEnv("VITE_DEV_MODE", "1");
    vi.stubEnv("VITE_LOCAL_AZURE_CLI_AUTH", "1");
    vi.stubEnv("VITE_LOCAL_LOGIN_PROMPT", "1");

    expect(() => loadConfig()).toThrow("Console runtime configuration");
  });

  test("runtime bindings do not bypass timeout validation", () => {
    vi.stubGlobal("__FDAI_CONSOLE_CONFIG__", runtimeConfig);
    vi.stubEnv("VITE_AUTH_TOKEN_TIMEOUT_MS", "never");

    expect(() => loadConfig()).toThrow(
      "VITE_AUTH_TOKEN_TIMEOUT_MS must be a positive integer.",
    );
  });

  test("generic offline builds require installation-time bindings", () => {
    vi.stubEnv("VITE_REQUIRE_RUNTIME_CONFIG", "1");
    vi.stubEnv("VITE_DEV_MODE", "1");

    expect(() => loadConfig()).toThrow("installation-time configuration is required");
    vi.stubGlobal("__FDAI_CONSOLE_CONFIG__", runtimeConfig);
    expect(loadConfig().devMode).toBe(false);
  });
});
