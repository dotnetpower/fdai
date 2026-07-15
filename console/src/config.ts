/**
 * Runtime configuration derived from Vite env vars. All values are
 * fork-supplied via `.env.local` (dev) or a Static Web App configuration
 * (prod). No customer identifiers are baked in at build time - the
 * upstream repo ships only schema and empty defaults.
 *
 * See docs/roadmap/interfaces/user-rbac-and-identity.md § 10.1 for MSAL config.
 */

export interface ConsoleConfig {
  /** Base URL of the read API (`https://api.<fork>/...`). */
  readonly readApiBaseUrl: string;
  /** Base URL of the dedicated document-ingestion gateway. */
  readonly ingestionApiBaseUrl: string;
  /** MSAL.js client id (Entra app registration for the SPA). */
  readonly msalClientId: string;
  /** MSAL.js tenant id (single-tenant per fork). */
  readonly msalTenantId: string;
  /** API audience (`api://<fdai-api-guid>/access`). */
  readonly msalApiScope: string;
  /** When true, MSAL is bypassed and the read API is called anonymously
   *  (matches `FDAI_READ_API_DEV_MODE=1` on the API). */
  readonly devMode: boolean;
  /** When true, MSAL is bypassed and the local read API projects the
   *  current `az login` user (matches `FDAI_READ_API_LOCAL_AZURE_CLI=1`). */
  readonly localAzureCliAuth: boolean;
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

export function loadConfig(): ConsoleConfig {
  return {
    readApiBaseUrl: envVar("VITE_READ_API_BASE_URL", "http://127.0.0.1:8000"),
    ingestionApiBaseUrl: envVar("VITE_INGESTION_API_BASE_URL", "http://127.0.0.1:8010"),
    msalClientId: envVar("VITE_MSAL_CLIENT_ID"),
    msalTenantId: envVar("VITE_MSAL_TENANT_ID"),
    msalApiScope: envVar("VITE_MSAL_API_SCOPE"),
    devMode: envVar("VITE_DEV_MODE", "0") === "1",
    localAzureCliAuth: envVar("VITE_LOCAL_AZURE_CLI_AUTH", "0") === "1",
    workflowCatalogRepo: envVar("VITE_WORKFLOW_CATALOG_REPO"),
    workflowCatalogBranch: envVar("VITE_WORKFLOW_CATALOG_BRANCH", "main"),
  };
}
