/**
 * Vite environment values are embedded at build time. An optional
 * installer-provided public runtime overlay supplies API and Entra bindings
 * without rebuilding the Console and disables local authentication bypasses.
 * The overlay contains no secrets and grants no authorization or execution
 * authority; the API remains responsible for authentication and authorization.
 *
 * See docs/roadmap/interfaces/user-rbac-and-identity.md § 10.1 for MSAL config.
 */

import { parseConsoleRuntimeConfig } from "./runtime-config";

export interface ConsoleConfig {
  /** Base URL of the Operator API (`https://api.<fork>/...`). */
  readonly operatorApiBaseUrl: string;
  /** Base URL of the dedicated document-ingestion gateway. */
  readonly ingestionApiBaseUrl: string;
  /** MSAL.js client id (Entra app registration for the SPA). */
  readonly msalClientId: string;
  /** MSAL.js tenant id (single-tenant per fork). */
  readonly msalTenantId: string;
  /** API audience (`api://<fdai-api-guid>/access`). */
  readonly msalApiScope: string;
  /** Maximum wait for a bearer token before the console surfaces an
   *  authentication error instead of leaving panels in a loading state. */
  readonly authTokenTimeoutMs: number;
  /** Maximum wait for one Operator API response before the request is aborted. */
  readonly operatorApiRequestTimeoutMs: number;
  /** When true, MSAL is bypassed and the Operator API is called anonymously
   *  (matches `FDAI_OPERATOR_API_DEV_MODE=1` on the API). */
  readonly devMode: boolean;
  /** When true, MSAL is bypassed and the local Operator API projects the
   *  current `az login` user (matches `FDAI_OPERATOR_API_LOCAL_AZURE_CLI=1`). */
  readonly localAzureCliAuth: boolean;
  /** Show a local auth chooser before entering a dev-mode console. Defaults
   *  to true when VITE_DEV_MODE=1; set VITE_LOCAL_LOGIN_PROMPT=0 to retain
   *  immediate anonymous bypass. */
  readonly localLoginPrompt: boolean;
  /** Optional `owner/repo` of the catalog repository. When set, the
   *  workflow builder can offer a one-click "Open a PR on GitHub" for a
   *  validated draft (a new-file link; the console still never commits).
   *  Empty upstream - a fork supplies its own repo. */
  readonly workflowCatalogRepo: string;
  /** Branch the new-file PR link targets (default `main`). */
  readonly workflowCatalogBranch: string;
}

function envVar(key: string, fallback = ""): string {
  const value = (import.meta.env[key] ?? fallback) as string;
  return value;
}

function positiveIntegerEnv(key: string, fallback: string): number {
  const raw = envVar(key, fallback);
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value <= 0) {
    throw new Error(`${key} must be a positive integer.`);
  }
  return value;
}

/** Load build defaults or a validated installer overlay; malformed overlays fail closed. */
export function loadConfig(): ConsoleConfig {
  const runtime = parseConsoleRuntimeConfig(globalThis.__FDAI_CONSOLE_CONFIG__);
  if (runtime === null && envVar("VITE_REQUIRE_RUNTIME_CONFIG", "0") === "1") {
    throw new Error("Console installation-time configuration is required.");
  }
  const devMode = runtime === null && envVar("VITE_DEV_MODE", "0") === "1";
  return {
    operatorApiBaseUrl: runtime?.operator_api_base_url ?? envVar("VITE_OPERATOR_API_BASE_URL", "http://127.0.0.1:8010"),
    ingestionApiBaseUrl: runtime?.ingestion_api_base_url ?? envVar("VITE_INGESTION_API_BASE_URL", "http://127.0.0.1:8011"),
    msalClientId: runtime?.spa_client_id ?? envVar("VITE_MSAL_CLIENT_ID"),
    msalTenantId: runtime?.tenant_id ?? envVar("VITE_MSAL_TENANT_ID"),
    msalApiScope: runtime?.api_scope ?? envVar("VITE_MSAL_API_SCOPE"),
    authTokenTimeoutMs: positiveIntegerEnv("VITE_AUTH_TOKEN_TIMEOUT_MS", "10000"),
    operatorApiRequestTimeoutMs: positiveIntegerEnv("VITE_OPERATOR_API_REQUEST_TIMEOUT_MS", "30000"),
    devMode,
    localAzureCliAuth: runtime === null && envVar("VITE_LOCAL_AZURE_CLI_AUTH", "0") === "1",
    localLoginPrompt: runtime === null && envVar("VITE_LOCAL_LOGIN_PROMPT", devMode ? "1" : "0") === "1",
    workflowCatalogRepo: envVar("VITE_WORKFLOW_CATALOG_REPO"),
    workflowCatalogBranch: envVar("VITE_WORKFLOW_CATALOG_BRANCH", "main"),
  };
}
