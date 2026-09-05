import { lazy, Suspense } from "preact/compat";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { PageHeader } from "../components/ui";
import { loadConfig } from "../config";
import { usePublishViewContext } from "../deck/context";
import {
  IngestionApiClient,
  IngestionApiError,
  type DocumentVersionSummary,
  type HandoverDraftResult,
  type IngestionCapabilities,
} from "../ingestion-api";
import { t } from "../i18n";
import { buildDocumentViewSnapshot } from "./document-ingestion.view";
import { knowledgeText, type KnowledgeMessageKey } from "./knowledge-sources.i18n";
import { openDeckWithContext } from "../deck/open-deck";
import { addHandoverEvidence, fetchHandoverGoal } from "../handover-api";
import { handoverText } from "../deck/handover-i18n";

const DocumentLibrary = lazy(async () => ({
  default: (await import("./document-library")).DocumentLibrary,
}));

interface Props { readonly client: OperatorApiClient }

type UploadState = "queued" | "hashing" | "uploading" | "processing" | "ready" | "failed";
interface UploadRow {
  readonly key: string;
  readonly file: File;
  readonly state: UploadState;
  readonly uploadId?: string;
  readonly draft?: HandoverDraftResult;
  readonly error?: string | undefined;
  readonly notice?: string | undefined;
}

interface UploadBatchLock { current: boolean }
interface HandoverUploadContext {
  readonly goalId: string;
}

const FORMAT_EXTENSIONS: Readonly<Record<string, readonly string[]>> = {
  text: [".txt", ".md", ".rst", ".json", ".yaml", ".yml", ".xml", ".csv", ".tf", ".rego"],
  pdf: [".pdf"],
  docx: [".docx"],
  pptx: [".pptx"],
  xlsx: [".xlsx"],
  png: [".png"],
  jpeg: [".jpg", ".jpeg"],
  tiff: [".tif", ".tiff"],
};
const LEGACY_OFFICE_EXTENSIONS = new Set([".doc", ".ppt", ".xls"]);
const FORMAT_LABEL_KEYS: Readonly<Record<string, KnowledgeMessageKey>> = {
  text: "formatText",
  pdf: "formatPdf",
  docx: "formatDocx",
  pptx: "formatPptx",
  xlsx: "formatXlsx",
  png: "formatPng",
  jpeg: "formatJpeg",
  tiff: "formatTiff",
};

export function claimUploadBatch(lock: UploadBatchLock): boolean {
  if (lock.current) return false;
  lock.current = true;
  return true;
}

export function documentCapabilityFailure(error: unknown): string {
  if (error instanceof IngestionApiError && (error.status === 404 || error.status === 501)) {
    return t("documents.unavailable");
  }
  return error instanceof Error ? error.message : t("documents.unavailable");
}

export function documentFilesForUpload(
  files: readonly File[],
  capabilities: IngestionCapabilities | null,
): readonly UploadRow[] {
  if (capabilities === null) return [];
  const supportedExtensions = new Set(
    capabilities.supported_formats.flatMap((format) => FORMAT_EXTENSIONS[format] ?? []),
  );
  return files.slice(0, capabilities.max_batch_count).map((file, index) => {
    const extension = fileExtension(file.name);
    const error = file.size > capabilities.max_file_size
      ? t("documents.fileTooLarge")
      : LEGACY_OFFICE_EXTENSIONS.has(extension)
        ? knowledgeText("legacyOfficeFormat")
        : !supportedExtensions.has(extension)
          ? knowledgeText("unsupportedFileFormat")
          : undefined;
    return {
      key: `${file.name}:${file.size}:${file.lastModified}:${index}`,
      file,
      state: error ? "failed" as const : "queued" as const,
      ...(error ? { error } : {}),
    };
  });
}

export function documentAccept(capabilities: IngestionCapabilities | null): string | undefined {
  if (capabilities === null) return undefined;
  const extensions = capabilities.supported_formats.flatMap(
    (format) => FORMAT_EXTENSIONS[format] ?? [],
  );
  return extensions.length > 0 ? [...new Set(extensions)].join(",") : undefined;
}

export function documentFormatLabels(formats: readonly string[]): string {
  return formats.map((format) => {
    const key = FORMAT_LABEL_KEYS[format];
    return key === undefined ? format : knowledgeText(key);
  }).join(", ");
}

export function DocumentIngestionRoute({ client }: Props) {
  const api = useMemo(() => new IngestionApiClient(loadConfig(), client), [client]);
  const inputRef = useRef<HTMLInputElement>(null);
  const uploadBatchLock = useRef(false);
  const mounted = useRef(true);
  const [capabilities, setCapabilities] = useState<IngestionCapabilities | null>(null);
  const [capabilityError, setCapabilityError] = useState<string | null>(null);
  const [rows, setRows] = useState<readonly UploadRow[]>([]);
  const [collection, setCollection] = useState("shared-knowledge");
  const [purpose, setPurpose] = useState("knowledge_base");
  const [storageMode, setStorageMode] = useState("managed_copy");
  const [consent, setConsent] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [documents, setDocuments] = useState<readonly DocumentVersionSummary[]>([]);
  const [documentsLoading, setDocumentsLoading] = useState(true);
  const [documentsError, setDocumentsError] = useState<string | null>(null);
  const [documentsRevision, setDocumentsRevision] = useState(0);
  const handover = handoverUploadContext(
    typeof window === "undefined" ? "" : window.location.search,
  );

  useEffect(() => () => {
    mounted.current = false;
  }, []);

  useEffect(() => {
    let cancelled = false;
    void api.capabilities().then(
      (value) => { if (!cancelled) setCapabilities(value); },
      (error: unknown) => {
        if (!cancelled) setCapabilityError(documentCapabilityFailure(error));
      },
    );
    return () => { cancelled = true; };
  }, [api]);

  useEffect(() => {
    const selectedCollection = collection.trim();
    if (!selectedCollection) {
      setDocuments([]);
      setDocumentsLoading(false);
      setDocumentsError(null);
      return;
    }
    let cancelled = false;
    setDocuments([]);
    setDocumentsLoading(true);
    setDocumentsError(null);
    const timer = globalThis.setTimeout(() => {
      void api.listDocuments(selectedCollection).then(
        (items) => {
          if (!cancelled) {
            setDocuments(items);
            setDocumentsLoading(false);
          }
        },
        (error: unknown) => {
          if (!cancelled) {
            setDocumentsError(
              error instanceof Error ? error.message : knowledgeText("libraryUnavailable"),
            );
            setDocumentsLoading(false);
          }
        },
      );
    }, 250);
    return () => {
      cancelled = true;
      globalThis.clearTimeout(timer);
    };
  }, [api, collection, documentsRevision]);

  usePublishViewContext(
    () => buildDocumentViewSnapshot({
      routeLabel: t("route.documents"),
      collection,
      purpose,
      storageMode,
      consent,
      uploads: rows.map((row) => ({
        name: row.file.name,
        size: row.file.size,
        state: row.state,
        ...(row.uploadId ? { uploadId: row.uploadId } : {}),
      })),
      documents: documents.map((document) => ({
        documentId: document.document_id,
        versionId: document.version_id,
        name: document.source_name,
        size: document.size_bytes,
        state: document.state,
      })),
      capabilities: capabilities ? {
        supportedFormats: capabilities.supported_formats,
        maxFileSize: capabilities.max_file_size,
        maxBatchCount: capabilities.max_batch_count,
        storageModes: capabilities.storage_modes,
      } : null,
      capabilitiesAvailable: capabilities !== null && capabilityError === null,
      capturedAt: new Date().toISOString(),
    }),
    [capabilities, capabilityError, collection, consent, documents, purpose, rows, storageMode],
  );

  const addFiles = (files: FileList | readonly File[]) => {
    if (uploadBatchLock.current || capabilities === null) return;
    setRows(documentFilesForUpload(Array.from(files), capabilities));
  };

  const updateRow = (key: string, update: Partial<UploadRow>) => {
    if (!mounted.current) return;
    setRows((current) => current.map((row) => row.key === key ? { ...row, ...update } : row));
  };

  const uploadAll = async () => {
    if (!capabilities || !consent || !collection.trim()) return;
    if (!claimUploadBatch(uploadBatchLock)) return;
    const batch = {
      capabilities,
      collection: collection.trim(),
      purpose,
      storageMode,
    };
    setUploading(true);
    try {
      for (const row of rows) {
        if (row.state !== "queued") continue;
        try {
          updateRow(row.key, { state: "hashing", error: undefined });
          const digest = await sha256(row.file);
          if (!mounted.current) return;
          updateRow(row.key, { state: "uploading" });
          const created = await api.createUpload({
            source_name: row.file.name,
            collection_id: batch.collection,
            media_type_hint: row.file.type || "application/octet-stream",
            expected_size: row.file.size,
            expected_sha256: digest,
            storage_mode: batch.storageMode,
            purposes: [batch.purpose],
            access_descriptor_ref: `collection:${batch.collection}`,
            retention_policy_version: batch.capabilities.policy_versions[0] ?? "default",
          });
          if (!mounted.current) {
            await api.cancel(created.session.upload_id).catch(() => undefined);
            return;
          }
          updateRow(row.key, { uploadId: created.session.upload_id });
          await api.uploadContent(created.upload.target, row.file);
          if (!mounted.current) {
            await api.cancel(created.session.upload_id).catch(() => undefined);
            return;
          }
          await api.completeUpload(created.session.upload_id);
          if (!mounted.current) return;
          updateRow(row.key, { state: "processing" });
          const completed = await waitForTerminal(
            api,
            created.session.upload_id,
            () => mounted.current,
          );
          if (completed.state !== "ready" && completed.state !== "ready_with_warnings") {
            updateRow(row.key, { state: "failed", error: uploadTerminalError(completed) });
            continue;
          }
          if (handover) {
            const evidenceRef = `doc:${completed.document_id}:${completed.version_id}`;
            try {
              const goal = await fetchHandoverGoal(client, handover.goalId);
              await addHandoverEvidence(
                client,
                handover.goalId,
                goal.revision,
                evidenceRef,
                digest,
              );
              openDeckWithContext({
                sessionKey: `handover:${handover.goalId}`,
                sessionLabel: goal.agentName,
                targetAgent: goal.agentName,
                onlyWhenIdle: true,
                openingBriefing: handoverText("prompt", {
                  agent: goal.agentName,
                }),
                prompt: `${handoverText("prompt", {
                  agent: goal.agentName,
                })} ${evidenceRef}`,
              });
            } catch (error) {
              console.warn("handover_evidence_link_failed", {
                error_type: error instanceof Error ? error.name : "UnknownError",
                upload_id: created.session.upload_id,
              });
              updateRow(row.key, { notice: handoverText("evidenceLinkFailed") });
            }
          }
          const draft = batch.purpose === "handover_bootstrap"
            ? await api.handoverDraft(created.session.upload_id)
            : undefined;
          if (!mounted.current) return;
          updateRow(row.key, {
            state: "ready",
            ...(completed.state === "ready_with_warnings"
              ? { notice: knowledgeText("readyWithWarnings") }
              : {}),
            ...(draft ? { draft } : {}),
          });
          setDocumentsRevision((current) => current + 1);
        } catch (error) {
          updateRow(row.key, {
            state: "failed",
            error: error instanceof Error ? error.message : t("documents.uploadFailed"),
          });
        }
      }
    } finally {
      uploadBatchLock.current = false;
      if (mounted.current) setUploading(false);
    }
  };

  const checkUploadStatus = async (row: UploadRow) => {
    if (!row.uploadId || uploading) return;
    setUploading(true);
    updateRow(row.key, { state: "processing", error: undefined });
    try {
      const completed = await waitForTerminal(api, row.uploadId, () => mounted.current);
      if (!mounted.current) return;
      updateRow(row.key, completed.state === "ready" || completed.state === "ready_with_warnings"
        ? {
            state: "ready",
            error: undefined,
            ...(completed.state === "ready_with_warnings"
              ? { notice: knowledgeText("readyWithWarnings") }
              : {}),
          }

        : { state: "failed", error: uploadTerminalError(completed) });
      if (completed.state === "ready" || completed.state === "ready_with_warnings") {
        setDocumentsRevision((current) => current + 1);
      }
    } catch (error) {
      updateRow(row.key, {
        state: "failed",
        error: error instanceof Error ? error.message : t("documents.uploadFailed"),
      });
    } finally {
      if (mounted.current) setUploading(false);
    }
  };

  const retryUpload = (row: UploadRow) => {
    if (uploading || !capabilities || row.file.size > capabilities.max_file_size) return;
    setRows((current) => current.map((candidate) => candidate.key === row.key
      ? { key: candidate.key, file: candidate.file, state: "queued" }
      : candidate));
  };

  const readyCount = rows.filter((row) => row.state === "queued").length;
  const formats = capabilities
    ? documentFormatLabels(capabilities.supported_formats)
    : t("documents.loadingCapabilities");
  const maxSize = capabilities ? formatDocumentBytes(capabilities.max_file_size) : "-";

  return (
    <div class="stack document-ingestion-route">
      <PageHeader title={t("route.documents")} subtitle={t("documents.subtitle")} />

      <section class="document-upload-policy" aria-labelledby="document-policy-title">
        <div>
          <h3 id="document-policy-title">{t("documents.visibilityTitle")}</h3>
          <p>{t("documents.visibilityNotice", { collection: collection || t("documents.collectionFallback") })}</p>
        </div>
        <label class="document-consent">
          <input type="checkbox" checked={consent} disabled={uploading} onChange={(event) => setConsent(event.currentTarget.checked)} />
          <span>{t("documents.visibilityConfirm")}</span>
        </label>
      </section>

      <section class="document-upload-settings" aria-label={t("documents.settings") }>
        <label>
          <span>{t("documents.collection")}</span>
          <input value={collection} maxLength={256} disabled={uploading} onInput={(event) => { setCollection(event.currentTarget.value); setConsent(false); }} />
          <small>{knowledgeText("collectionHint")}</small>
        </label>
        <label>
          <span>{t("documents.purpose")}</span>
          <select value={purpose} disabled={uploading} onChange={(event) => { setPurpose(event.currentTarget.value); setConsent(false); }}>
            <option value="knowledge_base">{t("documents.knowledgeBase")}</option>
            <option value="manual_distillation">{t("documents.manualDistillation")}</option>
            <option value="handover_bootstrap">{t("documents.handoverBootstrap")}</option>
          </select>
        </label>
        <label>
          <span>{t("documents.storageMode")}</span>
          <select value={storageMode} disabled={uploading} onChange={(event) => { setStorageMode(event.currentTarget.value); setConsent(false); }}>
            {(capabilities?.storage_modes ?? ["managed_copy"]).map((mode) => <option value={mode}>{mode}</option>)}
          </select>
        </label>
      </section>

      <section
        class={`document-drop-zone${dragging ? " is-dragging" : ""}`}
        aria-labelledby="document-drop-title"
        onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
        onDragLeave={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false);
        }}
        onDrop={(event) => { event.preventDefault(); setDragging(false); addFiles(event.dataTransfer?.files ?? []); }}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          hidden
          accept={documentAccept(capabilities)}
          disabled={uploading}
          onChange={(event) => addFiles(event.currentTarget.files ?? [])}
        />
        <div class="document-drop-icon" aria-hidden="true">⇧</div>
        <h3 id="document-drop-title">{t("documents.dropTitle")}</h3>
        <p>{t("documents.dropHint")}</p>
        <button type="button" class="cs-control-button document-file-picker" onClick={() => inputRef.current?.click()} disabled={!capabilities || uploading}>
          {t("documents.chooseFiles")}
        </button>
        <small>{t("documents.limits", { formats, size: maxSize, count: capabilities?.max_batch_count ?? "-" })}</small>
        {capabilities?.ocr_available === false ? (
          <small class="document-upload-note">{knowledgeText("ocrUnavailableHint")}</small>
        ) : null}
        {capabilityError ? <div class="alert error" role="alert">{capabilityError}</div> : null}
      </section>

      {rows.length > 0 ? (
        <section class="document-upload-list" aria-labelledby="document-files-title">
          <div class="document-upload-list-head">
            <h3 id="document-files-title">{t("documents.files")}</h3>
            <button type="button" class="cs-control-button is-primary" onClick={() => void uploadAll()} disabled={!consent || readyCount === 0 || uploading}>
              {t("documents.uploadFiles")}
            </button>
          </div>
          {rows.map((row) => (
            <div class="document-upload-row" key={row.key}>
              <div><strong>{row.file.name}</strong><small>{formatDocumentBytes(row.file.size)}</small></div>
              <span class={`status status-${row.state}`}>{t(`documents.state.${row.state}`)}</span>
              {row.error ? <small class="document-upload-error">{row.error}</small> : null}
              {row.notice ? <small class="document-upload-notice">{row.notice}</small> : null}
              {row.state === "failed" && row.uploadId ? (
                <button type="button" class="cs-control-button is-compact" disabled={uploading} onClick={() => void checkUploadStatus(row)}>
                  {knowledgeText("checkStatus")}
                </button>
              ) : null}
              {row.state === "failed" && !row.uploadId && capabilities && row.file.size <= capabilities.max_file_size ? (
                <button type="button" class="cs-control-button is-compact" disabled={uploading} onClick={() => retryUpload(row)}>
                  {knowledgeText("retry")}
                </button>
              ) : null}
              {row.draft ? (
                <details class="document-handover-draft">
                  <summary>{t("documents.handoverDraft", { outcome: row.draft.draft.outcome })}</summary>
                  <p>{t("documents.handoverDraftSummary", {
                    mappings: row.draft.draft.mappings.length,
                    unresolved: row.draft.draft.unresolved_people.length,
                    unmapped: row.draft.draft.unmapped_agents.length,
                  })}</p>
                  <pre><code>{row.draft.yaml}</code></pre>
                </details>
              ) : null}
            </div>
          ))}
        </section>
      ) : null}

      <Suspense fallback={<p role="status">{knowledgeText("libraryLoading")}</p>}>
        <DocumentLibrary
          collection={collection.trim() || t("documents.collectionFallback")}
          documents={documents}
          loading={documentsLoading}
          error={documentsError}
        />
      </Suspense>
    </div>
  );
}

export function handoverUploadContext(search: string): HandoverUploadContext | null {
  const params = new URLSearchParams(search);
  const goalId = params.get("handover_goal");
  if (
    goalId === null ||
    !/^[a-f0-9]{64}$/.test(goalId)
  ) {
    return null;
  }
  return { goalId };
}

export async function waitForTerminal(
  api: IngestionApiClient,
  uploadId: string,
  active: () => boolean = () => true,
): Promise<import("../ingestion-api").UploadSession> {
  let transientFailures = 0;
  for (let attempt = 0; attempt < 240; attempt += 1) {
    if (!active()) throw new Error("Upload batch cancelled");
    let session: import("../ingestion-api").UploadSession;
    try {
      session = await api.status(uploadId);
      transientFailures = 0;
    } catch (error) {
      const transient = !(error instanceof IngestionApiError) || error.status >= 500;
      transientFailures += 1;
      if (!transient || transientFailures > 3) throw error;
      if (!active()) throw new Error("Upload batch cancelled");
      await new Promise((resolve) => globalThis.setTimeout(resolve, 500));
      continue;
    }
    if (["ready", "ready_with_warnings", "held", "failed", "deleted"].includes(session.state)) {
      return session;
    }
    if (!active()) throw new Error("Upload batch cancelled");
    await new Promise((resolve) => globalThis.setTimeout(resolve, 500));
  }
  throw new Error(t("documents.processingTimeout"));
}

export async function sha256(file: File): Promise<string> {
  const { createSHA256 } = await import("hash-wasm");
  const hasher = await createSHA256();
  const reader = file.stream().getReader();
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    hasher.update(value);
  }
  return hasher.digest("hex");
}

function formatDocumentBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`;
}

function fileExtension(name: string): string {
  const index = name.lastIndexOf(".");
  return index >= 0 ? name.slice(index).toLowerCase() : "";
}

function uploadTerminalError(session: import("../ingestion-api").UploadSession): string {
  const code = session.failure_code ?? "";
  if (code === "format_signature_mismatch") return knowledgeText("formatSignatureMismatch");
  if (code === "malformed_ooxml_package" || code === "extraction_malformed_package") {
    return knowledgeText("malformedPackage");
  }
  if (code === "extraction_ocr_unavailable") return knowledgeText("ocrUnavailable");
  if (code === "extraction_no_extractable_content") {
    return knowledgeText("noExtractableContent");
  }
  if (
    code.includes("encrypted")
    || code.includes("password")
    || code.includes("rights_managed")
  ) {
    return knowledgeText("encryptedDocument");
  }
  return code || session.state;
}
