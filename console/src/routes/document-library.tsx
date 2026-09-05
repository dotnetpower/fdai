import { useMemo, useState } from "preact/hooks";
import { triggerBlobDownload } from "../blob-download";
import { Tooltip } from "../components/tooltip";
import {
  type DocumentPreview,
  type DocumentVersionSummary,
  IngestionApiClient,
} from "../ingestion-api";
import {
  groupDocuments,
  type DocumentIndexFilter,
} from "./document-library.model";
import { DocumentLibraryRow } from "./document-library-row";
import { knowledgeText } from "./knowledge-sources.i18n";

interface Props {
  readonly api: IngestionApiClient;
  readonly collection: string;
  readonly collections: readonly string[];
  readonly documents: readonly DocumentVersionSummary[];
  readonly loading: boolean;
  readonly error: string | null;
  readonly onCollectionChange: (collection: string) => void;
  readonly onDeleted: () => void;
  readonly onPromoted: () => void;
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
  onPromoted,
}: Props) {
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [pendingPromotion, setPendingPromotion] = useState<string | null>(null);
  const [actionPending, setActionPending] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [indexFilter, setIndexFilter] = useState<DocumentIndexFilter>("all");
  const [expandedGroups, setExpandedGroups] = useState<ReadonlySet<string>>(new Set());
  const folders = [...new Set([collection, ...collections])];
  const groups = useMemo(
    () => groupDocuments(documents, query, indexFilter),
    [documents, indexFilter, query],
  );

  const toggleGroup = (key: string) => {
    setExpandedGroups((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

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

  const promoteDocument = async (document: DocumentVersionSummary) => {
    const key = documentKey(document);
    if (actionPending) return;
    setActionPending(key);
    setActionError(null);
    try {
      await api.promoteDocument(document.document_id, document.version_id, collection);
      onPromoted();
    } catch (promotionError) {
      setActionError(actionErrorText(promotionError));
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
          {documents.length > 0 ? (
            <div class="document-library-tools">
              <label>
                <span>{knowledgeText("searchDocuments")}</span>
                <input
                  type="search"
                  value={query}
                  placeholder={knowledgeText("searchPlaceholder")}
                  onInput={(event) => setQuery(event.currentTarget.value)}
                />
              </label>
              <label>
                <span>{knowledgeText("filterIndexStatus")}</span>
                <select
                  value={indexFilter}
                  onChange={(event) => {
                    const value = event.currentTarget.value;
                    if (value === "all" || value === "indexed" || value === "attention") {
                      setIndexFilter(value);
                    }
                  }}
                >
                  <option value="all">{knowledgeText("filterAll")}</option>
                  <option value="indexed">{knowledgeText("filterIndexed")}</option>
                  <option value="attention">{knowledgeText("filterAttention")}</option>
                </select>
              </label>
              <span>{knowledgeText("groupSummary", {
                files: groups.length,
                uploads: groups.reduce((total, group) => total + group.documents.length, 0),
              })}</span>
            </div>
          ) : null}
          {!loading && !error && documents.length > 0 && groups.length === 0 ? (
            <p class="document-library-state">{knowledgeText("noMatches")}</p>
          ) : null}
          {preview ? (
            <DocumentPreviewPanel preview={preview} onClose={() => setPreview(null)} />
          ) : null}
          {groups.length > 0 ? (
            <div class="document-library-columns" aria-hidden="true">
              <span>{knowledgeText("columnDocument")}</span>
              <span>{knowledgeText("columnStatus")}</span>
              <span>{knowledgeText("columnDetails")}</span>
              <span>{knowledgeText("columnActions")}</span>
            </div>
          ) : null}
          {groups.map((group) => {
            const expanded = expandedGroups.has(group.key);
            const visible = expanded ? group.documents : group.documents.slice(0, 1);
            return (
              <section class="document-file-group" key={group.key}>
                {visible.map((document, index) => {
                  const key = documentKey(document);
                  return (
                    <DocumentLibraryRow
                      key={key}
                      document={document}
                      promotionCollection={collection}
                      pending={actionPending === key}
                      deleting={pendingDelete === key}
                      promoting={pendingPromotion === key}
                      previous={index > 0}
                      onPreview={() => void openPreview(document)}
                      onDownload={() => void download(document)}
                      onRequestDelete={() => setPendingDelete(key)}
                      onCancelDelete={() => setPendingDelete(null)}
                      onConfirmDelete={() => void deleteDocument(document)}
                      onRequestPromotion={() => setPendingPromotion(key)}
                      onCancelPromotion={() => setPendingPromotion(null)}
                      onConfirmPromotion={() => {
                        setPendingPromotion(null);
                        void promoteDocument(document);
                      }}
                    />
                  );
                })}
                {group.documents.length > 1 ? (
                    <button
                      type="button"
                      class="document-group-toggle"
                      aria-expanded={expanded}
                      onClick={() => toggleGroup(group.key)}
                    >
                      {expanded
                        ? knowledgeText("hidePreviousUploads")
                        : knowledgeText("showPreviousUploads", {
                            count: group.documents.length - 1,
                          })}
                    </button>
                ) : null}
              </section>
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

function documentKey(document: DocumentVersionSummary): string {
  return `${document.document_id}:${document.version_id}`;
}

function actionErrorText(error: unknown): string {
  return error instanceof Error ? error.message : knowledgeText("documentActionFailed");
}
