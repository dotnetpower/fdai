import { useState } from "preact/hooks";
import { triggerBlobDownload } from "../blob-download";
import { Tooltip } from "../components/tooltip";
import {
  type DocumentPreview,
  type DocumentVersionSummary,
  IngestionApiClient,
} from "../ingestion-api";
import { knowledgeText, type KnowledgeMessageKey } from "./knowledge-sources.i18n";

interface Props {
  readonly api: IngestionApiClient;
  readonly collection: string;
  readonly collections: readonly string[];
  readonly documents: readonly DocumentVersionSummary[];
  readonly loading: boolean;
  readonly error: string | null;
  readonly onCollectionChange: (collection: string) => void;
  readonly onDeleted: () => void;
}

interface PreviewState {
  readonly document: DocumentVersionSummary;
  readonly value: DocumentPreview | null;
  readonly loading: boolean;
  readonly error: string | null;
}

export function DocumentLibrary({
  api,
  collection,
  collections,
  documents,
  loading,
  error,
  onCollectionChange,
  onDeleted,
}: Props) {
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [actionPending, setActionPending] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const folders = [...new Set([collection, ...collections])];

  const openPreview = async (document: DocumentVersionSummary) => {
    const key = documentKey(document);
    if (actionPending) return;
    setActionPending(key);
    setActionError(null);
    setPreview({ document, value: null, loading: true, error: null });
    try {
      const value = await api.previewDocument(document.document_id, document.version_id);
      setPreview({ document, value, loading: false, error: null });
    } catch (previewError) {
      setPreview({
        document,
        value: null,
        loading: false,
        error: actionErrorText(previewError),
      });
    } finally {
      setActionPending(null);
    }
  };

  const download = async (document: DocumentVersionSummary) => {
    const key = documentKey(document);
    if (actionPending) return;
    setActionPending(key);
    setActionError(null);
    try {
      triggerBlobDownload(
        await api.downloadDocument(document.document_id, document.version_id),
        document.source_name,
      );
    } catch (downloadError) {
      setActionError(actionErrorText(downloadError));
    } finally {
      setActionPending(null);
    }
  };

  const deleteDocument = async (document: DocumentVersionSummary) => {
    const key = documentKey(document);
    if (actionPending) return;
    setActionPending(key);
    setActionError(null);
    try {
      await api.deleteDocument(document.document_id, document.version_id);
      setPendingDelete(null);
      if (preview?.document.document_id === document.document_id) setPreview(null);
      onDeleted();
    } catch (deleteError) {
      setActionError(actionErrorText(deleteError));
    } finally {
      setActionPending(null);
    }
  };

  return (
    <section class="document-library" aria-labelledby="document-library-title">
      <div class="document-library-layout">
        <nav class="document-library-folders" aria-label={knowledgeText("collectionsTitle")}>
          <h3>{knowledgeText("collectionsTitle")}</h3>
          <p>{knowledgeText("collectionsHint")}</p>
          {folders.map((folder) => (
            <button
              type="button"
              class={folder === collection ? "is-active" : ""}
              aria-current={folder === collection ? "page" : undefined}
              onClick={() => onCollectionChange(folder)}
            >
              <span aria-hidden="true">/</span>
              {folder}
            </button>
          ))}
        </nav>

        <div class="document-library-content">
          <div class="document-library-head">
            <div>
              <h3 id="document-library-title">{knowledgeText("libraryTitle", { collection })}</h3>
              <p>{knowledgeText("libraryHint")}</p>
            </div>
            <span>{knowledgeText("libraryCount", { count: documents.length })}</span>
          </div>
          {loading ? (
            <p class="document-library-state" role="status">{knowledgeText("libraryLoading")}</p>
          ) : null}
          {error ? <div class="alert error" role="alert">{error}</div> : null}
          {actionError ? <div class="alert error" role="alert">{actionError}</div> : null}
          {!loading && !error && documents.length === 0 ? (
            <p class="document-library-state">{knowledgeText("libraryEmpty")}</p>
          ) : null}
          {preview ? (
            <DocumentPreviewPanel preview={preview} onClose={() => setPreview(null)} />
          ) : null}
          {documents.length > 0 ? (
            <div class="document-library-columns" aria-hidden="true">
              <span>{knowledgeText("columnDocument")}</span>
              <span>{knowledgeText("columnStatus")}</span>
              <span>{knowledgeText("columnDetails")}</span>
              <span>{knowledgeText("columnActions")}</span>
            </div>
          ) : null}
          {documents.map((document) => {
            const key = documentKey(document);
            const deleting = pendingDelete === key;
            const pending = actionPending === key;
            return (
              <article class="document-library-row" key={key}>
                <div class="document-library-name">
                  <strong>{document.source_name}</strong>
                  <small>
                    {document.observed_format ?? document.media_type}
                    {" - "}
                    {formatDocumentBytes(document.size_bytes)}
                  </small>
                </div>
                <div class="document-library-statuses">
                  <span class={`status status-${document.state}`}>
                    {documentStateText(document.state)}
                  </span>
                  <span class={`document-index-status is-${document.index_status}`}>
                    {indexStatusText(document.index_status)}
                  </span>
                </div>
                <div class="document-library-meta">
                  <span>{purposeText(document.purposes[0])}</span>
                  <small>
                    {document.classification}
                    {" - "}
                    {protectionText(document.protection_state)}
                    {" - "}
                    {document.updated_at.slice(0, 10)}
                  </small>
                </div>
                <div class="document-library-actions">
                  <Tooltip content={!document.preview_available ? knowledgeText("previewUnavailable") : undefined}>
                    <span
                      class="document-library-action-tooltip"
                      aria-label={!document.preview_available
                        ? `${knowledgeText("preview")}: ${knowledgeText("previewUnavailable")}`
                        : undefined}
                    >
                      <button
                        type="button"
                        class="cs-control-button is-compact"
                        disabled={!document.preview_available || pending}
                        onClick={() => void openPreview(document)}
                      >
                        {knowledgeText("preview")}
                      </button>
                    </span>
                  </Tooltip>
                  <Tooltip content={!document.download_available ? knowledgeText("downloadUnavailable") : undefined}>
                    <span
                      class="document-library-action-tooltip"
                      aria-label={!document.download_available
                        ? `${knowledgeText("download")}: ${knowledgeText("downloadUnavailable")}`
                        : undefined}
                    >
                      <button
                        type="button"
                        class="cs-control-button is-compact"
                        disabled={!document.download_available || pending}
                        onClick={() => void download(document)}
                      >
                        {knowledgeText("download")}
                      </button>
                    </span>
                  </Tooltip>
                  {!deleting ? (
                    <Tooltip content={!document.delete_available ? knowledgeText("deleteUnavailable") : undefined}>
                      <span
                        class="document-library-action-tooltip"
                        aria-label={!document.delete_available
                          ? `${knowledgeText("delete")}: ${knowledgeText("deleteUnavailable")}`
                          : undefined}
                      >
                        <button
                          type="button"
                          class="cs-control-button is-compact"
                          disabled={!document.delete_available || pending}
                          onClick={() => setPendingDelete(key)}
                        >
                          {knowledgeText("delete")}
                        </button>
                      </span>
                    </Tooltip>
                  ) : (
                    <div class="document-delete-confirm" role="group" aria-label={knowledgeText("deleteConfirm")}>
                      <span>{knowledgeText("deleteConfirm")}</span>
                      <button type="button" disabled={pending} onClick={() => setPendingDelete(null)}>
                        {knowledgeText("cancel")}
                      </button>
                      <button type="button" class="is-danger" disabled={pending} onClick={() => void deleteDocument(document)}>
                        {knowledgeText("confirmDelete")}
                      </button>
                    </div>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function DocumentPreviewPanel({
  preview,
  onClose,
}: {
  readonly preview: PreviewState;
  readonly onClose: () => void;
}) {
  return (
    <aside class="document-preview-panel" aria-labelledby="document-preview-title">
      <div>
        <h4 id="document-preview-title">
          {knowledgeText("previewTitle", { name: preview.document.source_name })}
        </h4>
        <button type="button" class="cs-control-button is-compact" onClick={onClose}>
          {knowledgeText("close")}
        </button>
      </div>
      {preview.loading ? <p role="status">{knowledgeText("previewLoading")}</p> : null}
      {preview.error ? <div class="alert error" role="alert">{preview.error}</div> : null}
      {preview.value?.units.map((unit) => (
        <section class="document-preview-unit" key={unit.unit_id}>
          <small>{unit.locator}</small>
          <p>{unit.text}</p>
        </section>
      ))}
      {preview.value && preview.value.units.length === 0 ? (
        <p>{knowledgeText("previewEmpty")}</p>
      ) : null}
    </aside>
  );
}

const DOCUMENT_STATE_KEYS: Readonly<Record<string, KnowledgeMessageKey>> = {
  created: "stateCreated",
  uploading: "stateUploading",
  received: "stateReceived",
  quarantined: "stateQuarantined",
  scanning: "stateScanning",
  protection_check: "stateProtectionCheck",
  extracting: "stateExtracting",
  indexing: "stateIndexing",
  ready: "stateReady",
  ready_with_warnings: "stateReadyWithWarnings",
  held: "stateHeld",
  deleting: "stateDeleting",
  deleted: "stateDeleted",
  failed: "stateFailed",
};

const INDEX_STATUS_KEYS: Readonly<Record<DocumentVersionSummary["index_status"], KnowledgeMessageKey>> = {
  pending: "indexPending",
  indexing: "indexing",
  indexed: "indexed",
  not_indexed: "notIndexed",
};

function documentKey(document: DocumentVersionSummary): string {
  return `${document.document_id}:${document.version_id}`;
}

function documentStateText(state: string): string {
  const key = DOCUMENT_STATE_KEYS[state];
  return key === undefined ? state : knowledgeText(key);
}

function indexStatusText(status: DocumentVersionSummary["index_status"]): string {
  return knowledgeText(INDEX_STATUS_KEYS[status]);
}

function purposeText(purpose: string | undefined): string {
  if (purpose === "manual_distillation") return knowledgeText("purposeManualDistillation");
  if (purpose === "handover_bootstrap") return knowledgeText("purposeHandover");
  if (purpose === "handover_evidence") return knowledgeText("purposeHandoverEvidence");
  return knowledgeText("purposeKnowledgeBase");
}

function protectionText(protection: string): string {
  if (protection === "none") return knowledgeText("protectionNone");
  if (protection === "labeled_unencrypted") return knowledgeText("protectionLabeled");
  if (protection === "rights_managed_accessible") return knowledgeText("protectionRightsManaged");
  if (protection === "rights_managed_access_denied") return knowledgeText("protectionDenied");
  if (protection === "password_encrypted") return knowledgeText("protectionEncrypted");
  return knowledgeText("protectionUnknown");
}

function actionErrorText(error: unknown): string {
  return error instanceof Error ? error.message : knowledgeText("documentActionFailed");
}

function formatDocumentBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`;
}
