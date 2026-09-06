/** Validate installer-supplied public Console bindings without granting authority. */

declare global {
  var __FDAI_CONSOLE_CONFIG__: unknown;
}

/** Public installation bindings; credentials and authorization policy are excluded. */
export interface ConsoleRuntimeConfig {
  readonly schema_version: "fdai.console-runtime.v1";
  readonly operator_api_base_url: string;
  readonly ingestion_api_base_url: string;
  readonly tenant_id: string;
  readonly spa_client_id: string;
  readonly api_scope: string;
}

const CONFIG_FIELDS = new Set([
  "schema_version",
  "operator_api_base_url",
  "ingestion_api_base_url",
  "tenant_id",
  "spa_client_id",
  "api_scope",
]);
const UUID_SOURCE = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";
const UUID_PATTERN = new RegExp(`^${UUID_SOURCE}$`);
const API_SCOPE_PATTERN = new RegExp(`^api://${UUID_SOURCE}/[A-Za-z0-9._-]+$`);

function httpsBaseUrl(value: unknown, field: string): string {
  const error = `Console runtime configuration ${field} must be an HTTPS base URL without credentials, query, or fragment.`;
  if (
    typeof value !== "string" || !/^https:\/\/[^/]/i.test(value) ||
    /[^\x21-\x7e]|[\\?#]/u.test(value)
  ) {
    throw new Error(error);
  }
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error(error);
  }
  const authority = value.slice("https://".length).split("/")[0] ?? "";
  if (
    url.protocol !== "https:" || !url.hostname || authority.includes("@") ||
    url.username || url.password || url.search || url.hash
  ) {
    throw new Error(error);
  }
  return value;
}

function uuid(value: unknown, field: string): string {
  if (typeof value !== "string" || value.length !== 36 || !UUID_PATTERN.test(value)) {
    throw new Error(`Console runtime configuration ${field} must be a UUID.`);
  }
  return value;
}

function apiScope(value: unknown): string {
  if (typeof value !== "string" || /\s/u.test(value) || !API_SCOPE_PATTERN.test(value)) {
    throw new Error("Console runtime configuration api_scope must use api://UUID/ASCII_scope_identifier.");
  }
  return value;
}

/** Return null only for absent configuration; reject every malformed supplied binding. */
export function parseConsoleRuntimeConfig(value: unknown): ConsoleRuntimeConfig | null {
  if (value === undefined || value === null) return null;
  if (typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Console runtime configuration must be an object.");
  }
  const keys = Reflect.ownKeys(value);
  if (
    keys.length !== CONFIG_FIELDS.size ||
    keys.some((key) => typeof key !== "string" || !CONFIG_FIELDS.has(key))
  ) {
    throw new Error("Console runtime configuration must contain exactly the supported fields.");
  }
  const record = value as Record<string, unknown>;
  if (record.schema_version !== "fdai.console-runtime.v1") {
    throw new Error("Console runtime configuration schema_version is unsupported.");
  }
  return {
    schema_version: "fdai.console-runtime.v1",
    operator_api_base_url: httpsBaseUrl(record.operator_api_base_url, "operator_api_base_url"),
    ingestion_api_base_url: httpsBaseUrl(record.ingestion_api_base_url, "ingestion_api_base_url"),
    tenant_id: uuid(record.tenant_id, "tenant_id"),
    spa_client_id: uuid(record.spa_client_id, "spa_client_id"),
    api_scope: apiScope(record.api_scope),
  };
}
