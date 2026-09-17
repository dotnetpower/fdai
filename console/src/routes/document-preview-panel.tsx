import type { DocumentPreview, DocumentVersionSummary } from "../ingestion-api";
import { knowledgeText } from "./knowledge-sources.i18n";

export interface DocumentPreviewState {
  readonly document: DocumentVersionSummary;
  readonly value: DocumentPreview | null;
  readonly loading: boolean;
  readonly error: string | null;
}

export function DocumentPreviewPanel({
  preview,
  onClose,
}: {
  readonly preview: DocumentPreviewState;
  readonly onClose: () => void;
}) {
  return (
    <aside class="document-preview-panel" aria-labelledby="document-preview-title">
      <div>
        <h4 id="document-preview-title">
          {knowledgeText("previewTitleWithVersion", {
            name: preview.document.source_name,
            date: preview.document.updated_at.slice(0, 10),
          })}
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
