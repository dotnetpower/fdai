import {
  IngestionApiError,
  type CloudKnowledgeFreshness,
  type CloudKnowledgeInspectionResult,
  type CloudKnowledgeOverview,
  type CloudKnowledgeSource,
} from "../ingestion-api";
import { isRfc3339Timestamp } from "../time-format";
import { cloudKnowledgeText, type CloudKnowledgeMessageKey } from "./cloud-knowledge.i18n";

type SourceDates = Pick<CloudKnowledgeSource, "collected_at" | "checked_at" | "freshness">;
type PackageFile = Pick<File, "name" | "size" | "lastModified">;

/** Bind inspection to the selected object and the immutable bytes reused by import, not file metadata. */
export interface InspectedCloudKnowledgePackage {
  readonly file: PackageFile;
  readonly content: Blob;
  readonly result: CloudKnowledgeInspectionResult;
}

const FRESHNESS_KEYS: Readonly<Record<CloudKnowledgeFreshness, CloudKnowledgeMessageKey>> = {
  fresh: "fresh", refresh_due: "refreshDue", stale: "stale", unknown: "unknown",
};

const OUTCOME_KEYS: Readonly<Record<string, CloudKnowledgeMessageKey>> = {
  fetched: "fetched", unchanged: "unchanged", changed: "changed", failed: "failed",
  withdrawal_pending: "withdrawalPending", complete: "complete", partial: "partial",
  registry_expired: "registryExpired", deadline_exceeded: "deadlineExceeded",
};

function timestamp(value: string | null | undefined): number | null {
  if (typeof value !== "string" || !isRfc3339Timestamp(value)) return null;
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(5, 7));
  const day = Number(value.slice(8, 10));
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (year === 0 || day < 1 || day > (days[month - 1] ?? 0)
    || Number(value.slice(11, 13)) > 23 || Number(value.slice(14, 16)) > 59
    || Number(value.slice(17, 19)) > 59 || value.endsWith("-00:00")) return null;
  return Date.parse(value);
}

/** Render trusted-format dates in explicit UTC; invalid calendar dates and absent times stay unknown. */
export function formatCloudKnowledgeDate(value: string | null | undefined): string {
  const parsed = timestamp(value);
  return parsed === null ? cloudKnowledgeText("unknown")
    : new Date(parsed).toISOString().replace("T", " ").replace(/\.000Z$/, "Z").replace(/Z$/, " UTC");
}

/** Preserve the full time range and the number of unknown members; never summarize only the newest. */
export function cloudKnowledgeDateRange(values: readonly (string | null | undefined)[]): string {
  const times = values.map(timestamp).filter((value): value is number => value !== null);
  if (times.length === 0) return cloudKnowledgeText("unknown");
  const from = Math.min(...times);
  const to = Math.max(...times);
  const range = from === to ? formatCloudKnowledgeDate(new Date(from).toISOString())
    : cloudKnowledgeText("dateRange", {
      from: formatCloudKnowledgeDate(new Date(from).toISOString()),
      to: formatCloudKnowledgeDate(new Date(to).toISOString()),
    });
  return times.length === values.length ? range
    : cloudKnowledgeText("dateRangeUnknown", { range, count: values.length - times.length });
}

/** Display the server's freshness, withholding it when its required dates are absent or inconsistent. */
export function cloudKnowledgeFreshness(source: SourceDates): CloudKnowledgeFreshness {
  const collected = timestamp(source.collected_at);
  const checked = timestamp(source.checked_at);
  if (collected === null || checked === null || checked < collected) return "unknown";
  return Object.hasOwn(FRESHNESS_KEYS, source.freshness) ? source.freshness : "unknown";
}

/** Summarize the weakest returned evidence only; this calculation grants no answer or action authority. */
export function weakestCloudKnowledgeFreshness(sources: readonly SourceDates[]): CloudKnowledgeFreshness {
  const states = sources.map(cloudKnowledgeFreshness);
  if (states.length === 0 || states.includes("unknown")) return "unknown";
  if (states.includes("stale")) return "stale";
  return states.includes("refresh_due") ? "refresh_due" : "fresh";
}

/** Localize a canonical freshness token without changing the underlying evidence. */
export function cloudKnowledgeFreshnessText(value: CloudKnowledgeFreshness): string {
  return cloudKnowledgeText(FRESHNESS_KEYS[value]);
}

/** Localize known server outcomes, retaining an unfamiliar machine value rather than inventing success. */
export function cloudKnowledgeOutcomeText(value: string): string {
  const key = Object.hasOwn(OUTCOME_KEYS, value) ? OUTCOME_KEYS[value] : undefined;
  return key === undefined ? value : cloudKnowledgeText(key);
}

/** Match the server's 16 MiB intake ceiling before sending a selected JSON file for verification. */
export function isCloudKnowledgePackageFile(file: PackageFile): boolean {
  return file.name.toLowerCase().endsWith(".json") && Number.isSafeInteger(file.size)
    && file.size > 0 && file.size <= 16 * 1024 * 1024;
}

/** Require explicit service capabilities and the manual-review boundary; missing flags fail closed. */
export function cloudKnowledgePermissions(overview: CloudKnowledgeOverview | null, busy = false) {
  const ready = !busy && overview?.available === true
    && overview.automatic_activation === false && overview.approval_required === true;
  return {
    refresh: ready && overview?.can_refresh === true,
    export: ready && overview?.can_refresh === true,
    stage: ready && overview?.can_import === true,
    inspect: ready && overview?.can_import === true,
    import: ready && overview?.can_import === true,
  };
}

/** Import requires a successful same-file inspection, fresh explicit confirmation, and capability. */
export function canImportCloudKnowledgePackage(
  file: PackageFile | null,
  inspection: InspectedCloudKnowledgePackage | null,
  confirmed: boolean,
  permitted: boolean,
): boolean {
  return permitted === true && confirmed === true && file !== null && inspection !== null && inspection.file === file
    && inspection.result.status === "verified_candidate" && inspection.result.approval_required === true;
}

/** Reject malformed visible projections before rendering; dates themselves degrade to unknown. */
export function requireCloudKnowledgeOverview(value: CloudKnowledgeOverview): CloudKnowledgeOverview {
  const invalid = () => new IngestionApiError(502, "The cloud knowledge projection is malformed.");
  if (!value || typeof value.available !== "boolean" || !Array.isArray(value.sources)
    || !Array.isArray(value.collections)) throw invalid();
  if (!value.available) return value;
  if (value.automatic_activation !== false || value.approval_required !== true
    || (value.can_refresh !== undefined && typeof value.can_refresh !== "boolean")
    || (value.can_import !== undefined && typeof value.can_import !== "boolean")
    || (value.registry_revision !== undefined && (!Number.isSafeInteger(value.registry_revision)
      || value.registry_revision < 1))
    || value.sources.length > 256 || value.collections.length > 256) throw invalid();
  for (const source of value.sources) {
    if (!source || !identifier(source.source_id) || !identifier(source.collection_id)
      || typeof source.title !== "string" || !["online", "offline"].includes(source.mode)
      || typeof source.enabled !== "boolean" || typeof source.update_pending !== "boolean"
      || !Number.isSafeInteger(source.consecutive_failures) || source.consecutive_failures < 0
      || !Number.isSafeInteger(source.check_interval_seconds) || source.check_interval_seconds <= 0
      || !Number.isSafeInteger(source.max_unverified_seconds)
      || source.max_unverified_seconds < source.check_interval_seconds
      || !Object.hasOwn(FRESHNESS_KEYS, source.freshness)) throw invalid();
    if (source.last_attempt !== null && (!source.last_attempt
      || typeof source.last_attempt.outcome !== "string"
      || typeof source.last_attempt.reason !== "string")) throw invalid();
  }
  for (const collection of value.collections) {
    if (!collection || !identifier(collection.collection_id)
      || !Array.isArray(collection.versions) || collection.versions.length > 100) throw invalid();
    for (const version of collection.versions) {
      if (!version || typeof version.document_id !== "string" || typeof version.version_id !== "string"
        || typeof version.state !== "string" || typeof version.active !== "boolean"
        || typeof version.available !== "boolean") throw invalid();
      requireCloudKnowledgeRelease(version.release);
    }
  }
  if (new Set(value.sources.map((source) => source.source_id)).size !== value.sources.length
    || new Set(value.collections.map((collection) => collection.collection_id)).size !== value.collections.length) throw invalid();
  return value;
}

/** Check fields rendered by release disclosures without accepting trust or approval from the browser. */
export function requireCloudKnowledgeRelease(value: CloudKnowledgeInspectionResult["release"]): void {
  if (!value || typeof value.release_id !== "string" || typeof value.manifest_digest !== "string"
    || !Number.isSafeInteger(value.sequence) || value.sequence < 1 || !Array.isArray(value.sources)
    || value.sources.length < 1 || value.sources.length > 256
    || value.sources.some((source) => !source || typeof source.source_id !== "string"
      || typeof source.source_url !== "string" || !source.check
      || typeof source.check !== "object" || Array.isArray(source.check))
    || new Set(value.sources.map((source) => source.source_id)).size !== value.sources.length) {
    throw new IngestionApiError(502, "The cloud knowledge release projection is malformed.");
  }
}

function identifier(value: string): boolean {
  return typeof value === "string" && /^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}$/.test(value);
}
