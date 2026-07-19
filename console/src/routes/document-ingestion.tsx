import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { PageHeader } from "../components/ui";
import { loadConfig } from "../config";
import { usePublishViewContext } from "../deck/context";
import {
  IngestionApiClient,
  IngestionApiError,
  type HandoverDraftResult,
  type IngestionCapabilities,
} from "../ingestion-api";
import { t } from "../i18n";
import { buildDocumentViewSnapshot } from "./document-ingestion.view";

interface Props { readonly client: ReadApiClient }

type UploadState = "queued" | "hashing" | "uploading" | "processing" | "ready" | "failed";
interface UploadRow {
  readonly key: string;
  readonly file: File;
  readonly state: UploadState;
  readonly uploadId?: string;
  readonly draft?: HandoverDraftResult;
  readonly error?: string | undefined;
}

interface UploadBatchLock { current: boolean }

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
  return files.slice(0, capabilities.max_batch_count).map((file, index) => ({
    key: `${file.name}:${file.size}:${file.lastModified}:${index}`,
    file,
    state: file.size > capabilities.max_file_size ? "failed" : "queued",
    ...(file.size > capabilities.max_file_size ? { error: t("documents.fileTooLarge") } : {}),
  }));
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
      capabilities: capabilities ? {
        supportedFormats: capabilities.supported_formats,
        maxFileSize: capabilities.max_file_size,
        maxBatchCount: capabilities.max_batch_count,
        storageModes: capabilities.storage_modes,
      } : null,
      capabilitiesAvailable: capabilities !== null && capabilityError === null,
      capturedAt: new Date().toISOString(),
    }),
    [capabilities, capabilityError, collection, consent, purpose, rows, storageMode],
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
            reader_groups: [],
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
            updateRow(row.key, { state: "failed", error: completed.state });
            continue;
          }
          const draft = batch.purpose === "handover_bootstrap"
            ? await api.handoverDraft(created.session.upload_id)
            : undefined;
          if (!mounted.current) return;
          updateRow(row.key, { state: "ready", ...(draft ? { draft } : {}) });
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

  const readyCount = rows.filter((row) => row.state === "queued").length;
  const formats = capabilities?.supported_formats.join(", ") ?? t("documents.loadingCapabilities");
  const maxSize = capabilities ? formatBytes(capabilities.max_file_size) : "-";

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
        <input ref={inputRef} type="file" multiple hidden disabled={uploading} onChange={(event) => addFiles(event.currentTarget.files ?? [])} />
        <div class="document-drop-icon" aria-hidden="true">⇧</div>
        <h3 id="document-drop-title">{t("documents.dropTitle")}</h3>
        <p>{t("documents.dropHint")}</p>
        <button type="button" class="secondary" onClick={() => inputRef.current?.click()} disabled={!capabilities || uploading}>
          {t("documents.chooseFiles")}
        </button>
        <small>{t("documents.limits", { formats, size: maxSize, count: capabilities?.max_batch_count ?? "-" })}</small>
        {capabilityError ? <div class="alert error" role="alert">{capabilityError}</div> : null}
      </section>

      {rows.length > 0 ? (
        <section class="document-upload-list" aria-labelledby="document-files-title">
          <div class="document-upload-list-head">
            <h3 id="document-files-title">{t("documents.files")}</h3>
            <button type="button" onClick={() => void uploadAll()} disabled={!consent || readyCount === 0 || uploading}>
              {t("documents.uploadFiles")}
            </button>
          </div>
          {rows.map((row) => (
            <div class="document-upload-row" key={row.key}>
              <div><strong>{row.file.name}</strong><small>{formatBytes(row.file.size)}</small></div>
              <span class={`status status-${row.state}`}>{t(`documents.state.${row.state}`)}</span>
              {row.error ? <small class="document-upload-error">{row.error}</small> : null}
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
    </div>
  );
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

async function sha256(file: File): Promise<string> {
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

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`;
}
