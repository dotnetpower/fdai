import {
  apiBoolean,
  apiNullableString,
  apiRecord,
  apiString,
  contractError,
} from "./api-contract";

export type ReadSourceAvailability = "available" | "unavailable" | "unknown";

export interface ReadDataSourceStatus {
  readonly key: string;
  readonly source: string;
  readonly routes: readonly string[];
  readonly availability: ReadSourceAvailability;
  readonly configured: boolean;
  readonly reachable: boolean | null;
  readonly authoritative: boolean;
  readonly durable: boolean | null;
  readonly synthetic: boolean;
  readonly reason: string | null;
  readonly last_observed_at: string | null;
}

export interface ReadDataSourcesPayload {
  readonly surface: "read-data-sources";
  readonly sources: readonly ReadDataSourceStatus[];
}

export function decodeReadDataSources(value: unknown): ReadDataSourcesPayload {
  const root = apiRecord(value, "read data sources");
  if (root["surface"] !== "read-data-sources") {
    throw contractError("read data sources.surface MUST be read-data-sources");
  }
  if (!Array.isArray(root["sources"])) {
    throw contractError("read data sources.sources MUST be an array");
  }
  const sources = root["sources"].map((item, index) => decodeSource(
    item,
    `read data sources.sources[${index}]`,
  ));
  if (new Set(sources.map((source) => source.key)).size !== sources.length) {
    throw contractError("read data source keys MUST be unique");
  }
  const routes = sources.flatMap((source) => source.routes);
  if (new Set(routes).size !== routes.length) {
    throw contractError("read data source routes MUST have unique owners");
  }
  return { surface: "read-data-sources", sources };
}

export function sourceForRoute(
  payload: ReadDataSourcesPayload,
  route: string,
): ReadDataSourceStatus | null {
  const path = route.split(/[?#]/, 1)[0] ?? route;
  let selected: ReadDataSourceStatus | null = null;
  let selectedLength = -1;
  for (const source of payload.sources) {
    for (const ownedRoute of source.routes) {
      if (
        (path === ownedRoute || path.startsWith(`${ownedRoute}/`)) &&
        ownedRoute.length > selectedLength
      ) {
        selected = source;
        selectedLength = ownedRoute.length;
      }
    }
  }
  return selected;
}

export function unavailableSourceReason(
  payload: ReadDataSourcesPayload,
  route: string,
): string | null {
  const source = sourceForRoute(payload, route);
  if (source === null || (source.availability !== "unavailable" && source.authoritative)) {
    return null;
  }
  if (!source.authoritative) {
    return source.reason ?? `Source ${source.key} is not authoritative.`;
  }
  return source.reason ?? `Authoritative source ${source.key} is unavailable.`;
}

function decodeSource(value: unknown, label: string): ReadDataSourceStatus {
  const item = apiRecord(value, label);
  const availability = apiString(item, "availability", label);
  if (availability !== "available" && availability !== "unavailable" && availability !== "unknown") {
    throw contractError(`${label}.availability MUST be available, unavailable, or unknown`);
  }
  const routes = item["routes"];
  if (!Array.isArray(routes) || routes.some((route) => typeof route !== "string" || !route.startsWith("/"))) {
    throw contractError(`${label}.routes MUST be an array of absolute paths`);
  }
  return {
    key: apiString(item, "key", label),
    source: apiString(item, "source", label),
    routes,
    availability,
    configured: apiBoolean(item, "configured", label),
    reachable: nullableBoolean(item, "reachable", label),
    authoritative: apiBoolean(item, "authoritative", label),
    durable: nullableBoolean(item, "durable", label),
    synthetic: apiBoolean(item, "synthetic", label),
    reason: apiNullableString(item, "reason", label),
    last_observed_at: apiNullableString(item, "last_observed_at", label),
  };
}

function nullableBoolean(
  value: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): boolean | null {
  if (value[key] === null) return null;
  return apiBoolean(value, key, label);
}
