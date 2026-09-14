import { afterEach, describe, expect, it } from "vitest";
import { setLocale } from "../i18n";
import {
  IngestionApiError,
  type CloudKnowledgeInspectionResult,
  type CloudKnowledgeOverview,
  type CloudKnowledgeRelease,
  type CloudKnowledgeSource,
} from "../ingestion-api";
import { cloudKnowledgeText } from "./cloud-knowledge.i18n";
import {
  canImportCloudKnowledgePackage, cloudKnowledgeDateRange, cloudKnowledgeFreshness,
  cloudKnowledgeFreshnessText, cloudKnowledgeOutcomeText, cloudKnowledgePermissions,
  formatCloudKnowledgeDate, isCloudKnowledgePackageFile, requireCloudKnowledgeOverview,
  requireCloudKnowledgeRelease, weakestCloudKnowledgeFreshness,
  type InspectedCloudKnowledgePackage,
} from "./cloud-knowledge.model";

const SOURCE: CloudKnowledgeSource = {
  source_id: "reference-source", title: "Reference guide", collection_id: "cloud-reference",
  mode: "offline", enabled: false, check_interval_seconds: 604800, max_unverified_seconds: 2592000,
  collected_at: "2026-08-01T00:00:00Z", checked_at: "2026-08-02T00:00:00Z",
  freshness: "stale", next_due_at: "2026-08-09T00:00:00Z", last_attempt: null,
  update_pending: false, consecutive_failures: 0,
};
const RELEASE: CloudKnowledgeRelease = {
  release_id: "reference-release-1", sequence: 1, manifest_digest: "a".repeat(64),
  registry_digest: "b".repeat(64), package_created_at: "2026-09-01T00:00:00Z",
  imported_at: "2026-09-14T00:00:00Z", admission_expires_at: "2026-09-30T00:00:00Z",
  verified_key_id: "configured-signer", rollback_of: null,
  sources: [{
    source_id: SOURCE.source_id, source_url: "https://example.com/cloud/reference",
    source_sha256: "c".repeat(64), normalized_sha256: "d".repeat(64),
    collected_at: SOURCE.collected_at!, source_updated_at: null, license_ref: "reviewed-license",
    check: {
      source_id: SOURCE.source_id, source_url: "https://example.com/cloud/reference",
      checked_at: SOURCE.checked_at!, outcome: "unchanged", reason: "source_observed",
      content_sha256: "c".repeat(64), equivalence: "body_hash", etag: null,
      last_modified: null, collector_id: "approved-collector", collector_version: "1.0.0",
    },
    applicability: {
      provider: "azure", resource_type: "reference-type", service_generation: "reference-v1",
      skus: [], api_versions: [], regions: [], deployment_modes: [],
    },
    policy: {
      policy_id: "operational-v1", check_interval_seconds: SOURCE.check_interval_seconds,
      max_unverified_seconds: SOURCE.max_unverified_seconds, full_fetch_interval_seconds: 2592000,
    },
  }],
};
const OVERVIEW: CloudKnowledgeOverview = {
  available: true, registry_revision: 1, registry_valid_until: "2026-09-30T00:00:00Z",
  can_refresh: true, can_import: true, automatic_activation: false, approval_required: true,
  sources: [SOURCE], collections: [{
    collection_id: SOURCE.collection_id,
    versions: [{
      document_id: "document-1", version_id: "version-1", state: "received",
      active: false, available: false, updated_at: RELEASE.imported_at, release: RELEASE,
    }],
  }],
};
const FILE = { name: "reference-package.json", size: 100, lastModified: 1 };
const INSPECTION: InspectedCloudKnowledgePackage = {
  file: FILE, content: new Blob(["sealed-package-bytes"]),
  result: { status: "verified_candidate", approval_required: true, release: RELEASE, document_count: 1 },
};
const DENIED = { refresh: false, export: false, stage: false, inspect: false, import: false };

afterEach(() => setLocale("en"));

describe("cloud knowledge dates and freshness", () => {
  it.each([
    null, undefined, "", "not-a-date", "2026-09-14", "2026-09-14T03:04:05",
    "2026-02-30T00:00:00Z", "2026-02-29T00:00:00Z", "1900-02-29T00:00:00Z",
    "2026-09-31T00:00:00Z", "2026-09-14T24:00:00Z", "2026-09-14T03:04:05-00:00",
  ])("keeps absent, ambiguous, or invalid dates unknown: %s", (value) => {
    expect(formatCloudKnowledgeDate(value)).toBe("Unknown");
  });

  it("normalizes explicit offsets to UTC and preserves millisecond precision", () => {
    expect(formatCloudKnowledgeDate("2026-09-14T12:04:05+09:00")).toBe("2026-09-14 03:04:05 UTC");
    expect(formatCloudKnowledgeDate("2026-09-14T03:04:05.123Z")).toBe("2026-09-14 03:04:05.123 UTC");
    expect(formatCloudKnowledgeDate("2000-02-29T00:00:00Z")).toBe("2000-02-29 00:00:00 UTC");
  });

  it("retains both ends of a mixed-source range and discloses unknown dates", () => {
    expect(cloudKnowledgeDateRange([
      "2026-09-14T00:00:00Z", null, "2026-08-01T00:00:00Z", "invalid",
    ])).toBe("2026-08-01 00:00:00 UTC to 2026-09-14 00:00:00 UTC; 2 unknown");
    expect(cloudKnowledgeDateRange([])).toBe("Unknown");
    expect(cloudKnowledgeDateRange([null, "invalid"])).toBe("Unknown");
  });

  it("collapses only genuinely equal instants rather than different source dates", () => {
    expect(cloudKnowledgeDateRange(["2026-09-14T00:00:00Z", "2026-09-14T09:00:00+09:00"]))
      .toBe("2026-09-14 00:00:00 UTC");
  });

  it("does not replace source collection or check dates with a recent import date", () => {
    expect(formatCloudKnowledgeDate(RELEASE.imported_at)).toBe("2026-09-14 00:00:00 UTC");
    expect(cloudKnowledgeDateRange(RELEASE.sources.map((source) => source.collected_at)))
      .toBe("2026-08-01 00:00:00 UTC");
    expect(cloudKnowledgeDateRange(RELEASE.sources.map((source) => source.check.checked_at)))
      .toBe("2026-08-02 00:00:00 UTC");
    expect(cloudKnowledgeFreshness(SOURCE)).toBe("stale");
  });

  it.each(["fresh", "refresh_due", "stale", "unknown"] as const)(
    "preserves server freshness %s without reclassifying it from the browser clock", (freshness) => {
      expect(cloudKnowledgeFreshness({ ...SOURCE, freshness })).toBe(freshness);
    },
  );

  it("withholds freshness for absent, invalid, or reversed required dates", () => {
    expect(cloudKnowledgeFreshness({ ...SOURCE, freshness: "fresh", checked_at: null })).toBe("unknown");
    expect(cloudKnowledgeFreshness({ ...SOURCE, freshness: "fresh", collected_at: "invalid" })).toBe("unknown");
    expect(cloudKnowledgeFreshness({ ...SOURCE, freshness: "fresh", checked_at: "2026-07-01T00:00:00Z" })).toBe("unknown");
  });

  it("cannot hide stale or unknown evidence behind a fresher source", () => {
    const fresh = { ...SOURCE, freshness: "fresh" as const };
    const due = { ...SOURCE, freshness: "refresh_due" as const };
    expect(weakestCloudKnowledgeFreshness([fresh, SOURCE])).toBe("stale");
    expect(weakestCloudKnowledgeFreshness([fresh, due])).toBe("refresh_due");
    expect(weakestCloudKnowledgeFreshness([SOURCE, { ...fresh, checked_at: null }])).toBe("unknown");
    expect(weakestCloudKnowledgeFreshness([fresh])).toBe("fresh");
    expect(weakestCloudKnowledgeFreshness([])).toBe("unknown");
  });
});

describe("cloud knowledge action permissions", () => {
  it("keeps missing, unavailable, and busy capabilities disabled", () => {
    const { can_refresh: _refresh, can_import: _import, ...missing } = OVERVIEW;
    expect(cloudKnowledgePermissions(null)).toEqual(DENIED);
    expect(cloudKnowledgePermissions(missing)).toEqual(DENIED);
    expect(cloudKnowledgePermissions({ ...OVERVIEW, available: false })).toEqual(DENIED);
    expect(cloudKnowledgePermissions(OVERVIEW, true)).toEqual(DENIED);
  });

  it("separates Owner checks and export from intake capability", () => {
    expect(cloudKnowledgePermissions({ ...OVERVIEW, can_refresh: false })).toEqual({
      ...DENIED, stage: true, inspect: true, import: true,
    });
    expect(cloudKnowledgePermissions({ ...OVERVIEW, can_import: false })).toEqual({
      ...DENIED, refresh: true, export: true,
    });
  });

  it("requires literal booleans and never tolerates automatic activation or missing review", () => {
    const invalidCapabilities = { ...OVERVIEW, can_refresh: "true", can_import: 1 } as unknown as CloudKnowledgeOverview;
    expect(cloudKnowledgePermissions(invalidCapabilities)).toEqual(DENIED);
    expect(cloudKnowledgePermissions({ ...OVERVIEW, automatic_activation: true } as unknown as CloudKnowledgeOverview)).toEqual(DENIED);
    expect(cloudKnowledgePermissions({ ...OVERVIEW, approval_required: false } as unknown as CloudKnowledgeOverview)).toEqual(DENIED);
  });

  it("requires successful inspection, explicit confirmation, and current import permission", () => {
    expect(canImportCloudKnowledgePackage(FILE, INSPECTION, true, true)).toBe(true);
    expect(canImportCloudKnowledgePackage(FILE, null, true, true)).toBe(false);
    expect(canImportCloudKnowledgePackage(FILE, INSPECTION, false, true)).toBe(false);
    expect(canImportCloudKnowledgePackage(FILE, INSPECTION, true, false)).toBe(false);
    expect(canImportCloudKnowledgePackage(null, INSPECTION, true, true)).toBe(false);
  });

  it("invalidates inspection for a different selection even when all file metadata matches", () => {
    expect(canImportCloudKnowledgePackage({ ...FILE }, INSPECTION, true, true)).toBe(false);
    expect(canImportCloudKnowledgePackage({ ...FILE, name: "other.json" }, INSPECTION, true, true)).toBe(false);
  });

  it("does not interpret a signature or unexpected status as approval", () => {
    const signed = { ...INSPECTION.result, status: "signed" } as unknown as CloudKnowledgeInspectionResult;
    const approved = { ...INSPECTION.result, approval_required: false } as unknown as CloudKnowledgeInspectionResult;
    expect(canImportCloudKnowledgePackage(FILE, { ...INSPECTION, result: signed }, true, true)).toBe(false);
    expect(canImportCloudKnowledgePackage(FILE, { ...INSPECTION, result: approved }, true, true)).toBe(false);
  });

  it("bounds local selection to non-empty JSON packages, not key or archive files", () => {
    expect(isCloudKnowledgePackageFile(FILE)).toBe(true);
    expect(isCloudKnowledgePackageFile({ ...FILE, name: "REFERENCE.JSON", size: 16 * 1024 * 1024 })).toBe(true);
    expect(isCloudKnowledgePackageFile({ ...FILE, name: "signer.pem" })).toBe(false);
    expect(isCloudKnowledgePackageFile({ ...FILE, name: "archive.zip" })).toBe(false);
    expect(isCloudKnowledgePackageFile({ ...FILE, size: 0 })).toBe(false);
    expect(isCloudKnowledgePackageFile({ ...FILE, size: 16 * 1024 * 1024 + 1 })).toBe(false);
  });
});

describe("cloud knowledge projection and localization", () => {
  it("keeps an explicitly unavailable service unavailable without inventing authority", () => {
    const value = { available: false, sources: [], collections: [] };
    expect(requireCloudKnowledgeOverview(value)).toBe(value);
    expect(cloudKnowledgePermissions(value)).toEqual(DENIED);
  });

  it("accepts the bounded server projection without changing source timestamps", () => {
    expect(requireCloudKnowledgeOverview(OVERVIEW)).toBe(OVERVIEW);
    expect(requireCloudKnowledgeOverview({ ...OVERVIEW, sources: [{ ...SOURCE, checked_at: "invalid" }] }).sources[0]?.checked_at)
      .toBe("invalid");
    expect(() => requireCloudKnowledgeRelease(RELEASE)).not.toThrow();
  });

  it("rejects ambiguous authority, duplicate identities, unsafe collection IDs, and oversized lists", () => {
    expect(() => requireCloudKnowledgeOverview({ ...OVERVIEW, can_refresh: "true" } as unknown as CloudKnowledgeOverview)).toThrow(IngestionApiError);
    expect(() => requireCloudKnowledgeOverview({ ...OVERVIEW, sources: [SOURCE, SOURCE] })).toThrow(IngestionApiError);
    expect(() => requireCloudKnowledgeOverview({ ...OVERVIEW, collections: [{ collection_id: "..", versions: [] }] })).toThrow(IngestionApiError);
    expect(() => requireCloudKnowledgeOverview({ ...OVERVIEW, sources: Array.from({ length: 257 }, (_, index) => ({ ...SOURCE, source_id: `source-${index}` })) })).toThrow(IngestionApiError);
    expect(() => requireCloudKnowledgeRelease({ ...RELEASE, sources: [] })).toThrow(IngestionApiError);
    expect(() => requireCloudKnowledgeRelease({ ...RELEASE, sources: [RELEASE.sources[0]!, RELEASE.sources[0]!] })).toThrow(IngestionApiError);
  });

  it("uses English by default and the Console Korean locale for every key boundary", () => {
    expect(cloudKnowledgeText("title")).toBe("Cloud reference knowledge");
    expect(cloudKnowledgeText("checkDue")).toBe("Check due sources");
    expect(cloudKnowledgeText("export")).toBe("Download unsigned review manifest");
    expect(cloudKnowledgeFreshnessText("stale")).toBe("Stale reference");
    expect(cloudKnowledgeOutcomeText("withdrawal_pending")).toBe("Withdrawal pending review");
    expect(cloudKnowledgeOutcomeText("unrecognized_outcome")).toBe("unrecognized_outcome");
    setLocale("ko");
    expect(cloudKnowledgeText("title")).toBe("클라우드 참조 지식");
    expect(formatCloudKnowledgeDate(null)).toBe("알 수 없음");
    expect(cloudKnowledgeFreshnessText("refresh_due")).toBe("원본 확인 필요");
    expect(cloudKnowledgeOutcomeText("partial")).toBe("일부 완료");
    expect(cloudKnowledgeText("inspected", { count: 2 })).toContain("문서 2개");
    expect(cloudKnowledgeText("confirmImport")).toContain("승인이나 활성화가 아닙니다");
  });
});
