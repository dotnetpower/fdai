/** Exact Operator-owned enabled preference; availability, preference and authority never merge. */
import { alertQualityTimestamp, isAlertQualityRef } from "./alert-quality.model";
import { panelContractError, panelRecord } from "./panel-decode";
import type { IamOverview } from "./settings-iam.model";

export const ALERT_QUALITY_MAX_REVISION = Number.MAX_SAFE_INTEGER;

export interface AlertQualityPrerequisites {
  readonly source_bound: boolean;
  readonly writer_bound: boolean;
  readonly producer_ready: boolean;
  readonly preference_store_available: boolean;
}

/** A default is revision zero with no recorded time; an unreadable preference has no value. */
export interface AlertQualitySettings {
  readonly source: "alert-noise-governance";
  readonly scope_ref: string;
  readonly available: boolean;
  readonly enabled: boolean | null;
  readonly mode: "shadow";
  readonly execution_authority: false;
  readonly prerequisites: AlertQualityPrerequisites;
  readonly unavailable_reason: "preference_store_unavailable" | "source_unavailable"
    | "writer_unavailable" | "producer_not_ready" | null;
  readonly preference_state: "default" | "recorded" | "unavailable";
  readonly revision: number | null;
  readonly recorded_at: string | null;
}

export type AlertQualitySettingsUpdate = {
  readonly scope_ref: string;
  readonly enabled: boolean;
  readonly expected_revision: number;
};

function fail(): never {
  throw panelContractError("alert quality settings: invalid scoped preference projection");
}

function exact(value: unknown, keys: string): Readonly<Record<string, unknown>> {
  const row = panelRecord(value, "alert quality settings");
  const expected = keys.split(" ");
  if (Object.keys(row).length !== expected.length || expected.some((key) => !Object.hasOwn(row, key))) fail();
  return row;
}

function boolean(value: unknown): boolean {
  if (typeof value !== "boolean") fail();
  return value;
}

function revision(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0 || value > ALERT_QUALITY_MAX_REVISION) fail();
  return value;
}

/** Mirror AlertQualitySettingsResponse, including prerequisite precedence and explicit nulls. */
export function decodeAlertQualitySettings(value: unknown, expectedScope: string): AlertQualitySettings {
  const row = exact(value, "source scope_ref available enabled mode execution_authority prerequisites unavailable_reason preference_state revision recorded_at");
  if (!isAlertQualityRef(expectedScope) || row.scope_ref !== expectedScope
    || row.source !== "alert-noise-governance" || row.mode !== "shadow" || row.execution_authority !== false) fail();
  const prerequisites = exact(row.prerequisites, "source_bound writer_bound producer_ready preference_store_available");
  const flags = Object.freeze({
    source_bound: boolean(prerequisites.source_bound), writer_bound: boolean(prerequisites.writer_bound),
    producer_ready: boolean(prerequisites.producer_ready), preference_store_available: boolean(prerequisites.preference_store_available),
  });
  const reason = !flags.preference_store_available ? "preference_store_unavailable"
    : !flags.source_bound ? "source_unavailable" : !flags.writer_bound ? "writer_unavailable"
      : !flags.producer_ready ? "producer_not_ready" : null;
  const available = boolean(row.available);
  if (available !== (reason === null) || row.unavailable_reason !== reason) fail();
  const enabled = row.enabled === null ? null : boolean(row.enabled);
  const currentRevision = row.revision === null ? null : revision(row.revision);
  const recordedAt = row.recorded_at === null ? null : alertQualityTimestamp(row.recorded_at);
  const state = row.preference_state;
  if (state !== "default" && state !== "recorded" && state !== "unavailable") fail();
  if (flags.preference_store_available !== (state !== "unavailable")) fail();
  if (state === "unavailable") {
    if (enabled !== null || currentRevision !== null || recordedAt !== null) fail();
  } else {
    if (enabled === null || currentRevision === null) fail();
    if (state === "default" ? currentRevision !== 0 || recordedAt !== null : currentRevision === 0 || recordedAt === null) fail();
  }
  return Object.freeze({
    source: "alert-noise-governance", scope_ref: expectedScope, available, enabled, mode: "shadow",
    execution_authority: false, prerequisites: flags, unavailable_reason: reason,
    preference_state: state, revision: currentRevision, recorded_at: recordedAt,
  });
}

/** GET /iam is decoded by the existing client. Token claims and broad capabilities are not Owner. */
export function alertQualitySettingsOwner(overview: IamOverview | null, subject: string | null): boolean {
  return subject !== null && overview !== null && overview.authority.source === "server-verified"
    && overview.principal.oid === subject && overview.principal.roles.includes("Owner");
}

/** Use the body's one revision precondition; the caller must NOT also send If-Match. */
export function buildAlertQualitySettingsUpdate(
  settings: AlertQualitySettings, scope: string, enabled: unknown, expectedRevision: unknown,
): AlertQualitySettingsUpdate | null {
  if (!isAlertQualityRef(scope) || scope !== settings.scope_ref || typeof enabled !== "boolean"
    || enabled === settings.enabled || settings.enabled === null || settings.preference_state === "unavailable"
    || typeof expectedRevision !== "number" || !Number.isSafeInteger(expectedRevision)
    || expectedRevision < 0 || expectedRevision >= ALERT_QUALITY_MAX_REVISION
    || expectedRevision !== settings.revision) return null;
  return { scope_ref: scope, enabled, expected_revision: expectedRevision };
}
