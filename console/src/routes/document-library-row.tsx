import { Tooltip } from "../components/tooltip";
import type { DocumentVersionSummary } from "../ingestion-api";
import { knowledgeText, type KnowledgeMessageKey } from "./knowledge-sources.i18n";

interface Props {
  readonly document: DocumentVersionSummary;
  readonly promotionCollection: string;
  readonly pending: boolean;
  readonly deleting: boolean;
  readonly promoting: boolean;
  readonly previous: boolean;
  readonly onPreview: () => void;
  readonly onDownload: () => void;
  readonly onRequestDelete: () => void;
  readonly onCancelDelete: () => void;
  readonly onConfirmDelete: () => void;
  readonly onRequestPromotion: () => void;
  readonly onCancelPromotion: () => void;
  readonly onConfirmPromotion: () => void;
}

export function DocumentLibraryRow({
  document,
  promotionCollection,
  pending,
  deleting,
  promoting,
  previous,
  onPreview,
  onDownload,
  onRequestDelete,
  onCancelDelete,
  onConfirmDelete,
  onRequestPromotion,
  onCancelPromotion,
  onConfirmPromotion,
}: Props) {
  return (
    <article class={`document-library-row${previous ? " is-previous" : ""}`}>
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
        <span>{dispositionText(document.disposition)} - {purposeText(document.purposes[0])}</span>
        <small>
          {document.classification}
          {" - "}
          {protectionText(document.protection_state)}
          {" - "}
          {document.updated_at.slice(0, 10)}
          {document.derived_expires_at
            ? ` - ${knowledgeText("expiresOn", { date: document.derived_expires_at.slice(0, 10) })}`
            : ""}
        </small>
      </div>
      <div class="document-library-actions">
        {document.promotable && !promoting ? (
          <button
            type="button"
            class="cs-control-button is-compact"
            disabled={pending}
            onClick={onRequestPromotion}
          >
            {knowledgeText("promote")}
          </button>
        ) : null}
        {document.promotable && promoting ? (
          <div class="document-delete-confirm" role="group" aria-label={knowledgeText("promoteConfirm")}>
            <span>{knowledgeText("promoteConfirm", { collection: promotionCollection })}</span>
            <button type="button" disabled={pending} onClick={onCancelPromotion}>
              {knowledgeText("cancel")}
            </button>
            <button type="button" disabled={pending} onClick={onConfirmPromotion}>
              {knowledgeText("confirmPromote")}
            </button>
          </div>
        ) : null}
        <Tooltip content={!document.preview_available ? knowledgeText("previewUnavailable") : undefined}>
          <button
            type="button"
            class="cs-control-button is-compact"
            {...documentActionProps(document.preview_available, pending, onPreview)}
          >
            {knowledgeText("preview")}
          </button>
        </Tooltip>
        <Tooltip content={!document.download_available ? knowledgeText("downloadUnavailable") : undefined}>
          <button
            type="button"
            class="cs-control-button is-compact"
            {...documentActionProps(document.download_available, pending, onDownload)}
          >
            {knowledgeText("download")}
          </button>
        </Tooltip>
        {!deleting ? (
          <Tooltip content={!document.delete_available ? knowledgeText("deleteUnavailable") : undefined}>
            <button
              type="button"
              class="cs-control-button is-compact"
              {...documentActionProps(document.delete_available, pending, onRequestDelete)}
            >
              {knowledgeText("delete")}
            </button>
          </Tooltip>
        ) : (
          <div class="document-delete-confirm" role="group" aria-label={knowledgeText("deleteConfirm")}>
            <span>{knowledgeText("deleteConfirm")}</span>
            <button type="button" disabled={pending} onClick={onCancelDelete}>
              {knowledgeText("cancel")}
            </button>
            <button type="button" class="is-danger" disabled={pending} onClick={onConfirmDelete}>
              {knowledgeText("confirmDelete")}
            </button>
          </div>
        )}
      </div>
    </article>
  );
}

export function documentActionProps(
  available: boolean,
  pending: boolean,
  onClick: () => void,
) {
  return {
    "aria-disabled": available ? undefined : true,
    disabled: pending,
    onClick: available && !pending ? onClick : undefined,
  } as const;
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

function dispositionText(disposition: DocumentVersionSummary["disposition"]): string {
  if (disposition === "session_ephemeral") return knowledgeText("dispositionSession");
  if (disposition === "workspace_draft") return knowledgeText("dispositionDraft");
  if (disposition === "regulated_record") return knowledgeText("dispositionRecord");
  return knowledgeText("dispositionKnowledge");
}

function protectionText(protection: string): string {
  if (protection === "none") return knowledgeText("protectionNone");
  if (protection === "labeled_unencrypted") return knowledgeText("protectionLabeled");
  if (protection === "rights_managed_accessible") return knowledgeText("protectionRightsManaged");
  if (protection === "rights_managed_access_denied") return knowledgeText("protectionDenied");
  if (protection === "password_encrypted") return knowledgeText("protectionEncrypted");
  return knowledgeText("protectionUnknown");
}

function formatDocumentBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`;
}
