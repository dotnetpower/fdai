import type { ViewSnapshot } from "../deck/context";
import { composeGlossary, TERMS } from "../deck/glossary";

export interface DocumentUploadViewRow {
  readonly name: string;
  readonly size: number;
  readonly state: string;
  readonly uploadId?: string;
}

export interface DocumentLibraryViewRow {
  readonly documentId: string;
  readonly versionId: string;
  readonly name: string;
  readonly size: number;
  readonly state: string;
  readonly indexStatus: string;
  readonly previewAvailable: boolean;
  readonly downloadAvailable: boolean;
  readonly deleteAvailable: boolean;
}

export interface DocumentCapabilityView {
  readonly supportedFormats: readonly string[];
  readonly maxFileSize: number;
  readonly maxBatchCount: number;
  readonly storageModes: readonly string[];
}

export interface DocumentViewInput {
  readonly routeLabel: string;
  readonly collection: string;
  readonly purpose: string;
  readonly storageMode: string;
  readonly consent: boolean;
  readonly uploads: readonly DocumentUploadViewRow[];
  readonly documents?: readonly DocumentLibraryViewRow[];
  readonly capabilities: DocumentCapabilityView | null;
  readonly capabilitiesAvailable: boolean;
  readonly capturedAt: string;
}

export function buildDocumentViewSnapshot(input: DocumentViewInput): ViewSnapshot {
  const documents = input.documents ?? [];
  const indexedDocuments = documents.filter((document) => document.indexStatus === "indexed").length;
  const ready = input.uploads.filter((upload) => upload.state === "ready").length;
  const failed = input.uploads.filter((upload) => upload.state === "failed").length;
  const queued = input.uploads.filter((upload) => upload.state === "queued").length;
  const formats = input.capabilities?.supportedFormats.join(", ") ?? "unavailable";
  const storageModes = input.capabilities?.storageModes.join(", ") ?? "unavailable";
  const uploadEnabled = input.consent && queued > 0 && input.capabilitiesAvailable;
  const uploadDisabledReason = !input.capabilitiesAvailable
    ? "Upload capabilities are unavailable."
    : !input.consent
      ? "Confirm shared visibility before uploading."
      : queued === 0
        ? "Select at least one eligible file before uploading."
        : null;

  return {
    routeId: "documents",
    routeLabel: input.routeLabel,
    purpose:
      "Prepare governed documents for knowledge-base grounding, manual distillation, " +
      "or agent-handover bootstrap. Operators choose a destination collection, " +
      "processing purpose, and source storage mode; acknowledge shared visibility; " +
      "then select and upload files. Files remain unavailable until quarantine and " +
      "mandatory safety checks complete.",
    glossary: composeGlossary([
      TERMS.documentCollection,
      TERMS.processingPurpose,
      TERMS.sourceStorageMode,
      TERMS.ingestionSafety,
    ]),
    headline: `${input.uploads.length} files, ${ready} ready, ${failed} failed`,
    capturedAt: input.capturedAt,
    facts: [
      { key: "collection", label: "Destination collection", value: input.collection, group: "settings" },
      { key: "processing_purpose", label: "Processing purpose", value: input.purpose, group: "settings" },
      { key: "source_storage_mode", label: "Source storage mode", value: input.storageMode, group: "settings" },
      { key: "shared_visibility_confirmed", label: "Shared visibility confirmed", value: input.consent, group: "safety" },
      { key: "selected_files", label: "Selected files", value: input.uploads.length, group: "status" },
      { key: "queued_files", label: "Files ready to upload", value: queued, group: "status" },
      { key: "ready_files", label: "Files ready to use", value: ready, group: "status" },
      { key: "failed_files", label: "Failed files", value: failed, group: "status" },
      { key: "stored_documents", label: "Documents in collection", value: documents.length, group: "status" },
      { key: "indexed_documents", label: "Indexed documents", value: indexedDocuments, group: "status" },
      { key: "capabilities_available", label: "Upload service available", value: input.capabilitiesAvailable, group: "limits" },
      { key: "supported_formats", label: "Supported formats", value: formats, group: "limits" },
      { key: "max_file_size_bytes", label: "Maximum file size in bytes", value: input.capabilities?.maxFileSize ?? null, group: "limits" },
      { key: "max_batch_count", label: "Maximum files per batch", value: input.capabilities?.maxBatchCount ?? null, group: "limits" },
      { key: "available_storage_modes", label: "Available storage modes", value: storageModes, group: "limits" },
    ],
    records: {
      sections: [
        {
          title: "Shared visibility",
          detail:
            "The upload is visible to people who can access the destination collection. " +
            "Secrets or content outside that audience must not be uploaded.",
          state: input.consent ? "confirmed" : "confirmation_required",
        },
        {
          title: "Upload settings",
          detail: "Choose the destination collection, processing purpose, and storage mode.",
          collection: input.collection,
          processing_purpose: input.purpose,
          source_storage_mode: input.storageMode,
        },
        {
          title: "Document drop zone",
          detail:
            "Choose or drop files. Selected files stay unavailable until protection, " +
            "extraction, and indexing checks complete.",
          supported_formats: formats,
        },
      ],
      controls: [
        {
          control: "shared_visibility_confirmation",
          label: "Shared visibility confirmation",
          detail: "Acknowledge who can see the uploaded content.",
          value: input.consent,
          required: true,
        },
        {
          control: "destination_collection",
          label: "Destination collection",
          detail: "Choose where the processed document will be available.",
          value: input.collection,
          editable: true,
        },
        {
          control: "processing_purpose",
          label: "Processing purpose",
          detail: "Choose how the document will be used after safety checks.",
          value: input.purpose,
          options: "knowledge_base, manual_distillation, handover_bootstrap",
        },
        {
          control: "source_storage_mode",
          label: "Source storage mode",
          detail: "Choose how FDAI retains or references the source file.",
          value: input.storageMode,
          options: storageModes,
        },
        {
          control: "choose_files",
          label: "Choose files",
          detail: "Select files for this upload batch.",
          enabled: input.capabilitiesAvailable,
          disabled_reason: input.capabilitiesAvailable
            ? null
            : "Upload capabilities are unavailable.",
        },
        {
          control: "upload_files",
          label: "Upload files",
          detail: "Start governed ingestion for the eligible selected files.",
          enabled: uploadEnabled,
          disabled_reason: uploadDisabledReason,
        },
      ],
      constraints: [
        {
          supported_formats: formats,
          max_file_size_bytes: input.capabilities?.maxFileSize ?? null,
          max_batch_count: input.capabilities?.maxBatchCount ?? null,
          files_unavailable_until_safety_checks_complete: true,
        },
      ],
      uploads: input.uploads.map((upload) => ({
        name: upload.name,
        size: upload.size,
        state: upload.state,
        upload_id: upload.uploadId ?? null,
      })),
      documents: documents.map((document) => ({
        document_id: document.documentId,
        version_id: document.versionId,
        name: document.name,
        size: document.size,
        state: document.state,
        index_status: document.indexStatus,
        preview_available: document.previewAvailable,
        download_available: document.downloadAvailable,
        delete_available: document.deleteAvailable,
      })),
    },
  };
}
