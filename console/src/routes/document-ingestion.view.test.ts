import { afterEach, describe, expect, it, vi } from "vitest";
import { IngestionApiError, type IngestionApiClient } from "../ingestion-api";
import { t } from "../i18n";
import {
  claimUploadBatch,
  documentCapabilityFailure,
  documentFilesForUpload,
  waitForTerminal,
} from "./document-ingestion";
import { buildDocumentViewSnapshot } from "./document-ingestion.view";

describe("Documents ViewSnapshot", () => {
  afterEach(() => vi.useRealTimers());

  it("allows only one upload batch to own the route lock", () => {
    const lock = { current: false };
    expect(claimUploadBatch(lock)).toBe(true);
    expect(claimUploadBatch(lock)).toBe(false);
  });

  it("classifies unwired capability endpoints without hiding operational failures", () => {
    expect(documentCapabilityFailure(new IngestionApiError(404, "Not Found")))
      .toBe(t("documents.unavailable"));
    expect(documentCapabilityFailure(new IngestionApiError(501, "Not Implemented")))
      .toBe(t("documents.unavailable"));
    expect(documentCapabilityFailure(new IngestionApiError(503, "gateway unavailable")))
      .toBe("gateway unavailable");
  });

  it("does not queue files until upload limits are authoritative", () => {
    const file = { name: "guide.txt", size: 5, lastModified: 1 } as File;
    expect(documentFilesForUpload([file], null)).toEqual([]);
    expect(documentFilesForUpload([file], {
      supported_formats: ["text"],
      storage_modes: ["managed_copy"],
      max_file_size: 4,
      max_batch_count: 1,
      archives_enabled: false,
      policy_versions: ["v1"],
      direct_upload: true,
    })[0]).toMatchObject({ state: "failed", error: t("documents.fileTooLarge") });
  });

  it("retries transient status failures but fails 4xx responses immediately", async () => {
    vi.useFakeTimers();
    const ready = { upload_id: "upload-1", state: "ready" };
    const status = vi.fn()
      .mockRejectedValueOnce(new IngestionApiError(503, "retry"))
      .mockResolvedValueOnce(ready);
    const completed = waitForTerminal({ status } as unknown as IngestionApiClient, "upload-1");
    await vi.advanceTimersByTimeAsync(500);
    await expect(completed).resolves.toBe(ready);
    expect(status).toHaveBeenCalledTimes(2);

    const denied = vi.fn().mockRejectedValue(new IngestionApiError(404, "missing"));
    await expect(waitForTerminal({ status: denied } as unknown as IngestionApiClient, "upload-2"))
      .rejects.toThrow("missing");
    expect(denied).toHaveBeenCalledTimes(1);
  });

  it("publishes visible sections, controls, constraints, and current state", () => {
    const snapshot = buildDocumentViewSnapshot({
      routeLabel: "Documents",
      collection: "shared-knowledge",
      purpose: "knowledge_base",
      storageMode: "managed_copy",
      consent: false,
      uploads: [],
      capabilities: {
        supportedFormats: ["text", "ooxml", "pdf-detect-only"],
        maxFileSize: 25 * 1024 * 1024,
        maxBatchCount: 10,
        storageModes: ["managed_copy", "linked_source"],
      },
      capabilitiesAvailable: true,
      capturedAt: "2026-07-16T00:00:00Z",
    });

    expect(snapshot.purpose).toContain("shared visibility");
    expect(snapshot.glossary?.map((entry) => entry.term)).toEqual([
      "document collection",
      "processing purpose",
      "source storage mode",
      "ingestion safety checks",
    ]);
    expect(snapshot.facts).toEqual(expect.arrayContaining([
      expect.objectContaining({ key: "supported_formats", label: "Supported formats", value: "text, ooxml, pdf-detect-only" }),
      expect.objectContaining({ key: "shared_visibility_confirmed", label: "Shared visibility confirmed", value: false }),
      expect.objectContaining({ key: "max_batch_count", value: 10 }),
    ]));
    expect(snapshot.records?.sections).toHaveLength(3);
    expect(snapshot.records?.controls).toEqual(expect.arrayContaining([
      expect.objectContaining({ control: "choose_files", label: "Choose files", enabled: true }),
      expect.objectContaining({
        control: "upload_files",
        label: "Upload files",
        enabled: false,
        disabled_reason: "Confirm shared visibility before uploading.",
      }),
    ]));
    expect(snapshot.records?.constraints?.[0]).toMatchObject({
      supported_formats: "text, ooxml, pdf-detect-only",
      max_batch_count: 10,
      files_unavailable_until_safety_checks_complete: true,
    });
  });

  it("publishes upload status and enables upload only after confirmation", () => {
    const snapshot = buildDocumentViewSnapshot({
      routeLabel: "Documents",
      collection: "shared-knowledge",
      purpose: "handover_bootstrap",
      storageMode: "managed_copy",
      consent: true,
      uploads: [
        { name: "guide.docx", size: 1024, state: "queued" },
        { name: "ready.txt", size: 256, state: "ready", uploadId: "upload-1" },
      ],
      capabilities: {
        supportedFormats: ["text", "ooxml"],
        maxFileSize: 4096,
        maxBatchCount: 2,
        storageModes: ["managed_copy"],
      },
      capabilitiesAvailable: true,
      capturedAt: "2026-07-16T00:00:00Z",
    });

    expect(snapshot.headline).toBe("2 files, 1 ready, 0 failed");
    expect(snapshot.records?.uploads).toHaveLength(2);
    expect(snapshot.records?.controls).toEqual(expect.arrayContaining([
      expect.objectContaining({
        control: "upload_files",
        label: "Upload files",
        enabled: true,
        disabled_reason: null,
      }),
    ]));
  });
});
