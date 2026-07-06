/**
 * Runtime configuration derived from Vite env vars. All values are
 * fork-supplied via `.env.local` (dev) or a Static Web App configuration
 * (prod). No customer identifiers are baked in at build time — the
 * upstream repo ships only schema and empty defaults.
 *
 * See docs/roadmap/user-rbac-and-identity.md § 10.1 for MSAL config.
 */

export interface ConsoleConfig {
  /** Base URL of the read API (`https://api.<fork>/…`). */
  readonly readApiBaseUrl: string;
  /** MSAL.js client id (Entra app registration for the SPA). */
  readonly msalClientId: string;
  /** MSAL.js tenant id (single-tenant per fork). */
  readonly msalTenantId: string;
  /** API audience (`api://<aiopspilot-api-guid>/access`). */
  readonly msalApiScope: string;
  /** When true, MSAL is bypassed and the read API is called anonymously
   *  (matches `AIOPSPILOT_READ_API_DEV_MODE=1` on the API). */
  readonly devMode: boolean;
}

function envVar(key: string, fallback = ""): string {
  const value = (import.meta.env[key] ?? fallback) as string;
  return value;
}

export function loadConfig(): ConsoleConfig {
  return {
    readApiBaseUrl: envVar("VITE_READ_API_BASE_URL", "http://127.0.0.1:8000"),
    msalClientId: envVar("VITE_MSAL_CLIENT_ID"),
    msalTenantId: envVar("VITE_MSAL_TENANT_ID"),
    msalApiScope: envVar("VITE_MSAL_API_SCOPE"),
    devMode: envVar("VITE_DEV_MODE", "0") === "1",
  };
}
