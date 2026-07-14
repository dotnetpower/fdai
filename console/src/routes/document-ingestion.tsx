import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { PageHeader } from "../components/ui";
import { loadConfig } from "../config";
import { usePublishViewContext } from "../deck/context";
import { composeGlossary } from "../deck/glossary";
import { IngestionApiClient, type IngestionCapabilities } from "../ingestion-api";
import { t } from "../i18n";

interface Props { readonly client: ReadApiClient }

type UploadState = "queued" | "hashing" | "uploading" | "received" | "failed";
interface UploadRow {
  readonly key: string;
  readonly file: File;
  readonly state: UploadState;
  readonly uploadId?: string;
  readonly error?: string | undefined;
}

export function DocumentIngestionRoute({ client }: Props) {
  const api = useMemo(() => new IngestionApiClient(loadConfig(), client), [client]);
  const inputRef = useRef<HTMLInputElement>(null);
  const [capabilities, setCapabilities] = useState<IngestionCapabilities | null>(null);
  const [capabilityError, setCapabilityError] = useState<string | null>(null);
  const [rows, setRows] = useState<readonly UploadRow[]>([]);
  const [collection, setCollection] = useState("shared-knowledge");
  const [purpose, setPurpose] = useState("knowledge_base");
  const [storageMode, setStorageMode] = useState("managed_copy");
  const [consent, setConsent] = useState(false);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    void api.capabilities().then(setCapabilities).catch((error: unknown) => {
      setCapabilityError(error instanceof Error ? error.message : t("documents.unavailable"));
    });
  }, [api]);

  usePublishViewContext(
    () => ({
      routeId: "documents",
      routeLabel: t("route.documents"),
      purpose: "Upload customer documents through the isolated ingestion safety pipeline.",
      glossary: composeGlossary([]),
      headline: `${rows.length} files, ${rows.filter((row) => row.state === "received").length} received`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "collection", value: collection, group: "upload" },
        { key: "purpose", value: purpose, group: "upload" },
        { key: "queued", value: rows.length, group: "upload" },
      ],
      records: {
        uploads: rows.map((row) => ({
          name: row.file.name,
          size: row.file.size,
          state: row.state,
          upload_id: row.uploadId ?? null,
        })),
      },
    }),
    [collection, purpose, rows],
  );

  const addFiles = (files: FileList | readonly File[]) => {
    const maxBatch = capabilities?.max_batch_count ?? 1;
    const maxSize = capabilities?.max_file_size ?? 0;
    const selected = Array.from(files).slice(0, maxBatch);
    setRows(selected.map((file, index) => ({
      key: `${file.name}:${file.size}:${file.lastModified}:${index}`,
      file,
      state: maxSize > 0 && file.size > maxSize ? "failed" : "queued",
      ...(maxSize > 0 && file.size > maxSize ? { error: t("documents.fileTooLarge") } : {}),
    })));
  };

  const updateRow = (key: string, update: Partial<UploadRow>) => {
    setRows((current) => current.map((row) => row.key === key ? { ...row, ...update } : row));
  };

  const uploadAll = async () => {
    if (!capabilities || !consent || !collection.trim()) return;
    for (const row of rows) {
      if (row.state !== "queued") continue;
      try {
        updateRow(row.key, { state: "hashing", error: undefined });
        const digest = await sha256(row.file);
        updateRow(row.key, { state: "uploading" });
        const created = await api.createUpload({
          source_name: row.file.name,
          collection_id: collection.trim(),
          media_type_hint: row.file.type || "application/octet-stream",
          expected_size: row.file.size,
          expected_sha256: digest,
          storage_mode: storageMode,
          purposes: [purpose],
          access_descriptor_ref: `collection:${collection.trim()}`,
          retention_policy_version: capabilities.policy_versions[0] ?? "default",
          reader_groups: [],
        });
        updateRow(row.key, { uploadId: created.session.upload_id });
        await api.uploadContent(created.upload.target, row.file);
        const completed = await api.completeUpload(created.session.upload_id);
        updateRow(row.key, { state: completed.state === "received" ? "received" : "failed" });
      } catch (error) {
        updateRow(row.key, {
          state: "failed",
          error: error instanceof Error ? error.message : t("documents.uploadFailed"),
        });
      }
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
          <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.currentTarget.checked)} />
          <span>{t("documents.visibilityConfirm")}</span>
        </label>
      </section>

      <section class="document-upload-settings" aria-label={t("documents.settings") }>
        <label>
          <span>{t("documents.collection")}</span>
          <input value={collection} maxLength={256} onInput={(event) => { setCollection(event.currentTarget.value); setConsent(false); }} />
        </label>
        <label>
          <span>{t("documents.purpose")}</span>
          <select value={purpose} onChange={(event) => { setPurpose(event.currentTarget.value); setConsent(false); }}>
            <option value="knowledge_base">{t("documents.knowledgeBase")}</option>
            <option value="manual_distillation">{t("documents.manualDistillation")}</option>
          </select>
        </label>
        <label>
          <span>{t("documents.storageMode")}</span>
          <select value={storageMode} onChange={(event) => { setStorageMode(event.currentTarget.value); setConsent(false); }}>
            {(capabilities?.storage_modes ?? ["managed_copy"]).map((mode) => <option value={mode}>{mode}</option>)}
          </select>
        </label>
      </section>

      <section
        class={`document-drop-zone${dragging ? " is-dragging" : ""}`}
        onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => { event.preventDefault(); setDragging(false); addFiles(event.dataTransfer?.files ?? []); }}
      >
        <input ref={inputRef} type="file" multiple hidden onChange={(event) => addFiles(event.currentTarget.files ?? [])} />
        <div class="document-drop-icon" aria-hidden="true">⇧</div>
        <h3>{t("documents.dropTitle")}</h3>
        <p>{t("documents.dropHint")}</p>
        <button type="button" class="secondary" onClick={() => inputRef.current?.click()} disabled={!capabilities}>
          {t("documents.chooseFiles")}
        </button>
        <small>{t("documents.limits", { formats, size: maxSize, count: capabilities?.max_batch_count ?? "-" })}</small>
        {capabilityError ? <div class="alert error">{capabilityError}</div> : null}
      </section>

      {rows.length > 0 ? (
        <section class="document-upload-list" aria-labelledby="document-files-title">
          <div class="document-upload-list-head">
            <h3 id="document-files-title">{t("documents.files")}</h3>
            <button type="button" onClick={() => void uploadAll()} disabled={!consent || readyCount === 0}>
              {t("documents.uploadFiles")}
            </button>
          </div>
          {rows.map((row) => (
            <div class="document-upload-row" key={row.key}>
              <div><strong>{row.file.name}</strong><small>{formatBytes(row.file.size)}</small></div>
              <span class={`status status-${row.state}`}>{t(`documents.state.${row.state}`)}</span>
              {row.error ? <small class="document-upload-error">{row.error}</small> : null}
            </div>
          ))}
        </section>
      ) : null}
    </div>
  );
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
