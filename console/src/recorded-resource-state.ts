import { isRfc3339Timestamp } from "./time-format";

export type RecordedStateAxis = "operational" | "provisioning" | "availability";
export interface RecordedStateFact {
  readonly value: string | null;
  readonly source_path: string | null;
  readonly observed_at: string | null;
  readonly recorded_at: string | null;
  readonly freshness: "fresh" | "stale" | "unknown";
  readonly completeness: number | null;
  readonly conflicts: readonly string[];
  readonly reason: string | null;
}
export interface RecordedResourceStates {
  readonly schema_version: "1.0.0";
  readonly operational: RecordedStateFact;
  readonly provisioning: RecordedStateFact;
  readonly availability: RecordedStateFact;
}

export function stateRecord(value: unknown, label: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error(`Invalid recorded state ${label}`);
  return value as Record<string, unknown>;
}

export function stateText(value: unknown, label: string, max = 1024): string {
  if (typeof value !== "string" || !value.trim() || value.length > max) throw new Error(`Invalid recorded state ${label}`);
  return value;
}

function nullableText(value: unknown, label: string): string | null {
  return value === null ? null : stateText(value, label);
}

export function stateTime(value: unknown, label: string): string {
  const time = stateText(value, label, 64);
  if (!isRfc3339Timestamp(time)) throw new Error(`Invalid recorded state ${label}`);
  return time;
}

function decodeFact(input: unknown): RecordedStateFact {
  const item = stateRecord(input, "fact");
  const freshness = item.freshness;
  if (freshness !== "fresh" && freshness !== "stale" && freshness !== "unknown") throw new Error("Invalid recorded state freshness");
  const completeness = item.completeness;
  if (completeness !== null && (typeof completeness !== "number" || !Number.isFinite(completeness) || completeness < 0 || completeness > 1)) throw new Error("Invalid recorded state completeness");
  if (!Array.isArray(item.conflicts) || item.conflicts.length > 64) throw new Error("Invalid recorded state conflicts");
  const observed = item.observed_at === null ? null : stateTime(item.observed_at, "observed time");
  const recorded = item.recorded_at === null ? null : stateTime(item.recorded_at, "recorded time");
  if (observed !== null && recorded !== null && Date.parse(observed) > Date.parse(recorded)) throw new Error("Invalid recorded state time order");
  const value = nullableText(item.value, "value");
  const path = nullableText(item.source_path, "source path");
  if (value !== null && path === null) throw new Error("Recorded state value is missing its source path");
  return {
    value, source_path: path, observed_at: observed, recorded_at: recorded, freshness, completeness,
    conflicts: item.conflicts.map((entry) => stateText(entry, "conflict")),
    reason: nullableText(item.reason, "reason"),
  };
}

/** Decode display facts without inferring health, current truth, or action authority. */
export function decodeRecordedResourceStates(input: unknown): RecordedResourceStates {
  const item = stateRecord(input, "axes");
  if (item.schema_version !== "1.0.0") throw new Error("Unsupported recorded resource state version");
  return {
    schema_version: "1.0.0",
    operational: decodeFact(item.operational),
    provisioning: decodeFact(item.provisioning),
    availability: decodeFact(item.availability),
  };
}
