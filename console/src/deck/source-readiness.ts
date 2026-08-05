import {
  sourceForRoute,
  type ReadDataSourceStatus,
  type ReadDataSourcesPayload,
  type ReadSourceAvailability,
} from "../api-data-sources";

export type DeckSourceKey = "inventory" | "incidents" | "audit" | "knowledge" | "automation";

export interface DeckSourceReadiness {
  readonly key: DeckSourceKey;
  readonly route: string;
  readonly availability: ReadSourceAvailability;
  readonly source: ReadDataSourceStatus | null;
}

const DECK_SOURCE_ROUTES: readonly Readonly<{
  key: DeckSourceKey;
  route: string;
}>[] = [
  { key: "inventory", route: "/inventory/graph" },
  { key: "incidents", route: "/incidents" },
  { key: "audit", route: "/audit" },
  { key: "knowledge", route: "/rules" },
  { key: "automation", route: "/scheduler-runs" },
];

export function deckSourceReadiness(
  payload: ReadDataSourcesPayload,
): readonly DeckSourceReadiness[] {
  return DECK_SOURCE_ROUTES.map(({ key, route }) => {
    const source = sourceForRoute(payload, route);
    const availability = source === null || !source.authoritative
      ? "unknown"
      : source.availability;
    return { key, route, availability, source };
  });
}

export function latestSourceObservation(
  sources: readonly DeckSourceReadiness[],
): string | null {
  const observed = sources
    .map((item) => item.source?.last_observed_at ?? null)
    .filter((value): value is string => value !== null)
    .map((value) => ({ value, timestamp: Date.parse(value) }))
    .filter((item) => Number.isFinite(item.timestamp))
    .sort((left, right) => right.timestamp - left.timestamp);
  return observed[0]?.value ?? null;
}
