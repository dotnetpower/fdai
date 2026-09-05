import type { DocumentVersionSummary } from "../ingestion-api";
import { knowledgeText, type KnowledgeMessageKey } from "./knowledge-sources.i18n";

interface Props {
  readonly collection: string;
  readonly documents: readonly DocumentVersionSummary[];
  readonly loading: boolean;
  readonly error: string | null;
}

export function DocumentLibrary({ collection, documents, loading, error }: Props) {
  return (
    <section class="document-library" aria-labelledby="document-library-title">
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
      {!loading && !error && documents.length === 0 ? (
        <p class="document-library-state">{knowledgeText("libraryEmpty")}</p>
      ) : null}
      {documents.map((document) => (
        <article class="document-library-row" key={`${document.document_id}:${document.version_id}`}>
          <div class="document-library-name">
            <strong>{document.source_name}</strong>
            <small>{knowledgeText("version", { version: document.version_id.slice(0, 8) })}</small>
          </div>
          <span class={`status status-${document.state}`}>
            {documentStateText(document.state)}
          </span>
          <div class="document-library-meta">
            <small>{document.updated_at.slice(0, 10)}</small>
          </div>
          <span class="document-library-size">{formatDocumentBytes(document.size_bytes)}</span>
        </article>
      ))}
    </section>
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

function documentStateText(state: string): string {
  const key = DOCUMENT_STATE_KEYS[state];
  return key === undefined ? state : knowledgeText(key);
}

export function formatDocumentBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`;
}
