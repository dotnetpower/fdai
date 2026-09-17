import type { OperatorApiClient } from "./api";
import type { ConsoleConfig } from "./config";

export interface IngestionCapabilities {
  readonly supported_formats: readonly string[];
  readonly storage_modes: readonly string[];
  readonly max_file_size: number;
  readonly max_batch_count: number;
  readonly archives_enabled: boolean;
  readonly policy_versions: readonly string[];
  readonly direct_upload: boolean;
  readonly ocr_available?: boolean;
  readonly collections?: readonly string[];
}

export interface UploadSession {
  readonly upload_id: string;
  readonly document_id: string;
  readonly version_id: string;
  readonly source_name: string;
  readonly state: string;
  readonly collection_id: string;
  readonly failure_code?: string | null;
  readonly collections?: readonly string[];
}

export interface DocumentVersionSummary {
  readonly document_id: string;
  readonly version_id: string;
  readonly source_name: string;
  readonly size_bytes: number;
  readonly media_type: string;
  readonly observed_format: string | null;
  readonly state: string;
  readonly classification: string;
  readonly sensitivity_label: string | null;
  readonly protection_state: string;
  readonly purposes: readonly string[];
  readonly created_at: string;
  readonly updated_at: string;
  readonly active: boolean;
  readonly available: boolean;
  readonly warnings: readonly string[];
  readonly failure_code: string | null;
  readonly index_status: "pending" | "indexing" | "indexed" | "not_indexed";
  readonly preview_available: boolean;
  readonly download_available: boolean;
  readonly delete_available: boolean;
  readonly disposition: "session_ephemeral" | "workspace_draft" | "governed_knowledge" | "regulated_record";
  readonly scope_kind: "conversation" | "workspace" | "collection" | "regulated" | null;
  readonly scope_ref: string | null;
  readonly source_expires_at: string | null;
  readonly derived_expires_at: string | null;
  readonly retention_state: "live" | "expiring" | "held" | "tombstoned" | "purge_pending" | "purged";
  readonly index_state: "not_requested" | "queued" | "building" | "active" | "tombstoned" | "purged" | "failed";
  readonly promotable: boolean;
}

export interface DocumentPreview {
  readonly document_id: string;
  readonly version_id: string;
  readonly units: readonly {
    readonly unit_id: string;
    readonly kind: string;
    readonly locator: string;
    readonly text: string;
  }[];
  readonly warnings: readonly string[];
}

export interface HandoverDraftResult {
  readonly upload_id: string;
  readonly document_id: string;
  readonly version_id: string;
  readonly draft: {
    readonly outcome: "drafted" | "abstained";
    readonly mappings: readonly unknown[];
    readonly abstained: readonly unknown[];
    readonly unresolved_people: readonly unknown[];
    readonly unmapped_agents: readonly string[];
    readonly warnings: readonly string[];
  };
  readonly yaml: string;
  readonly proposal?: {
    readonly pr_ref: string;
    readonly url: string | null;
    readonly already_existed: boolean;
  } | null;
}

export interface ReportLineDraftResult {
  readonly schema_version: "1.0.0";
  readonly upload_id: string;
  readonly document_id: string;
  readonly version_id: string;
  readonly source_sha256: string;
  readonly outcome: "drafted" | "abstained";
  readonly candidates: readonly {
    readonly candidate_id: string;
    readonly subject: { readonly display_name: string; readonly oid: string | null };
    readonly manager: { readonly display_name: string; readonly oid: string | null };
    readonly relationship_kind: "primary_manager";
    readonly confidence: number;
    readonly extraction_source: "deterministic" | "model";
    readonly citations: readonly {
      readonly unit_id: string;
      readonly locator: string;
      readonly quote: string;
    }[];
    readonly directory_manager_oid: string | null;
    readonly directory_comparison: "matched" | "conflict" | "unavailable" | "not_checked";
  }[];
  readonly abstained: readonly unknown[];
  readonly unresolved_people: readonly {
    readonly display_name: string;
    readonly oid: string | null;
  }[];
  readonly warnings: readonly string[];
}

/** Server-owned freshness of reference knowledge, never observed cloud resource health. */
export type CloudKnowledgeFreshness = "fresh" | "refresh_due" | "stale" | "unknown";

/** Latest collection attempt; a failed attempt does not renew a source check. */
export interface CloudKnowledgeAttempt {
  readonly checked_at: string;
  readonly outcome: "fetched" | "unchanged" | "changed" | "failed" | "withdrawal_pending";
  readonly reason: string;
}

/** Registered source status, keeping admitted source evidence separate from collector attempts. */
export interface CloudKnowledgeSource {
  readonly source_id: string;
  readonly title: string;
  readonly collection_id: string;
  readonly mode: "online" | "offline";
  readonly enabled: boolean;
  readonly check_interval_seconds: number;
  readonly max_unverified_seconds: number;
  readonly collected_at: string | null;
  readonly checked_at: string | null;
  readonly freshness: CloudKnowledgeFreshness;
  readonly next_due_at: string | null;
  readonly last_attempt: CloudKnowledgeAttempt | null;
  readonly update_pending: boolean;
  readonly consecutive_failures: number;
}

/** Immutable per-source provenance supplied by a release, not a new fetch instruction. */
export interface CloudKnowledgeSourceEvidence {
  readonly source_id: string;
  readonly source_url: string;
  readonly source_sha256: string;
  readonly normalized_sha256: string;
  readonly collected_at: string;
  readonly source_updated_at: string | null;
  readonly license_ref: string;
  readonly check: CloudKnowledgeAttempt & {
    readonly source_id: string;
    readonly source_url: string;
    readonly content_sha256: string | null;
    readonly equivalence: "body_hash" | "strong_etag" | "none";
    readonly etag: string | null;
    readonly last_modified: string | null;
    readonly collector_id: string;
    readonly collector_version: string;
  };
  readonly applicability: {
    readonly provider: string;
    readonly resource_type: string;
    readonly service_generation: string;
    readonly skus: readonly string[];
    readonly api_versions: readonly string[];
    readonly regions: readonly string[];
    readonly deployment_modes: readonly string[];
  };
  readonly policy: {
    readonly policy_id: string;
    readonly check_interval_seconds: number;
    readonly max_unverified_seconds: number;
    readonly full_fetch_interval_seconds: number;
  };
}

/** A verified provenance binding is not approval, admission, or activation. */
export interface CloudKnowledgeRelease {
  readonly release_id: string;
  readonly sequence: number;
  readonly manifest_digest: string;
  readonly registry_digest: string;
  readonly package_created_at: string;
  readonly imported_at: string;
  readonly admission_expires_at: string;
  readonly verified_key_id: string;
  readonly sources: readonly CloudKnowledgeSourceEvidence[];
  readonly rollback_of: string | null;
}

/** Stored document-version projection; visibility is reported only by the server. */
export interface CloudKnowledgeVersion {
  readonly document_id: string;
  readonly version_id: string;
  readonly state: string;
  readonly active: boolean;
  readonly available: boolean;
  readonly updated_at: string;
  readonly release: CloudKnowledgeRelease;
}

/** Bounded, access-scoped version list for a registered collection. */
export interface CloudKnowledgeCollection {
  readonly collection_id: string;
  readonly versions: readonly CloudKnowledgeVersion[];
}

/** Capability omissions stay read-only, including older or unavailable service responses. */
export interface CloudKnowledgeOverview {
  readonly available: boolean;
  readonly reason?: string;
  readonly registry_revision?: number;
  readonly registry_valid_until?: string;
  readonly can_refresh?: boolean;
  readonly can_import?: boolean;
  readonly sources: readonly CloudKnowledgeSource[];
  readonly collections: readonly CloudKnowledgeCollection[];
  readonly automatic_activation?: false;
  readonly approval_required?: true;
}

/** Result of one bounded due-only sweep; completion does not imply source or activation success. */
export interface CloudKnowledgeRefreshResult {
  readonly checked: number;
  readonly failed: number;
  readonly status: string;
}

/** Successful inspection verifies a candidate without importing it or granting approval. */
export interface CloudKnowledgeInspectionResult {
  readonly status: "verified_candidate";
  readonly approval_required: true;
  readonly release: CloudKnowledgeRelease;
  readonly document_count: number;
}

/** Intake acknowledgement only; independent review and activation remain in the document pipeline. */
export interface CloudKnowledgeIntakeResult {
  readonly session: Pick<UploadSession, "upload_id" | "document_id" | "version_id" | "state">;
  readonly approval_required: true;
  readonly status: "ingestion_requested";
  readonly release: CloudKnowledgeRelease;
}

interface CreatedUploadResponse {
  readonly outcome: "created";
  readonly session: UploadSession;
  readonly upload: {
    readonly target: string;
    readonly expires_at: string;
    readonly completed_parts: readonly string[];
  };
}

interface UnchangedUploadResponse {
  readonly outcome: "unchanged";
  readonly session: UploadSession;
  readonly upload: null;
}

type CreateUploadResponse = CreatedUploadResponse | UnchangedUploadResponse;

export interface CreateUploadInput {
  readonly source_name: string;
  readonly collection_id: string;
  readonly media_type_hint: string;
  readonly expected_size: number;
  readonly expected_sha256: string;
  readonly storage_mode: string;
  readonly purposes: readonly string[];
  readonly access_descriptor_ref: string;
  readonly retention_policy_version: string;
  readonly disposition?: DocumentVersionSummary["disposition"];
  readonly scope_kind?: Exclude<DocumentVersionSummary["scope_kind"], null>;
  readonly scope_ref?: string;
}

export class IngestionApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "IngestionApiError";
  }
}

/** Dedicated client for content writes. It is intentionally separate from the GET-only client. */
export class IngestionApiClient {
  readonly #baseUrl: string;
  readonly #readClient: OperatorApiClient;

  constructor(config: ConsoleConfig, readClient: OperatorApiClient) {
    this.#baseUrl = config.ingestionApiBaseUrl;
    this.#readClient = readClient;
  }

  async capabilities(): Promise<IngestionCapabilities> {
    return this.#json<IngestionCapabilities>("/ingestion/capabilities", { method: "GET" });
  }

  /** Read configured sources, admitted evidence, stored revisions, and current server capabilities. */
  async cloudKnowledge(signal?: AbortSignal): Promise<CloudKnowledgeOverview> {
    return this.#json<CloudKnowledgeOverview>("/ingestion/cloud-knowledge", {
      method: "GET", signal: signal ?? null,
    });
  }

    async rollbackCloudKnowledge(
      collectionId: string,
      versionId: string,
      signal?: AbortSignal,
    ): Promise<CloudKnowledgeIntakeResult> {
      return this.#json<CloudKnowledgeIntakeResult>(
        `/ingestion/cloud-knowledge/${encodeURIComponent(collectionId)}/versions/${encodeURIComponent(versionId)}/rollback`,
        { method: "POST", signal: signal ?? null },
      );
    }

  /** Owner-only due sweep, with no force option or body. The server may take up to 15 minutes. */
  async refreshCloudKnowledge(signal?: AbortSignal): Promise<CloudKnowledgeRefreshResult> {
    return this.#json<CloudKnowledgeRefreshResult>("/ingestion/cloud-knowledge/refresh", {
      method: "POST", signal: signal ?? null,
    });
  }

  /** Download unsigned JSON review material for an independently approved external signer. */
  async exportCloudKnowledge(collectionId: string, signal?: AbortSignal): Promise<Blob> {
    const response = await this.#request(new URL(
      `/ingestion/cloud-knowledge/${encodeURIComponent(collectionId)}/export`, this.#baseUrl,
    ), { method: "POST", signal: signal ?? null });
    return response.blob();
  }

  /** Submit the collected revision for governed review; never approve or activate it here. */
  async stageCloudKnowledge(
    collectionId: string,
    signal?: AbortSignal,
  ): Promise<CloudKnowledgeIntakeResult> {
    return this.#json<CloudKnowledgeIntakeResult>(
      `/ingestion/cloud-knowledge/${encodeURIComponent(collectionId)}/stage`,
      { method: "POST", signal: signal ?? null },
    );
  }

  /** Send exact file bytes to the offline verifier; no client-supplied trust or reviewer fields. */
  async inspectCloudKnowledgePackage(
    file: Blob,
    signal?: AbortSignal,
  ): Promise<CloudKnowledgeInspectionResult> {
    return this.#json<CloudKnowledgeInspectionResult>("/ingestion/cloud-knowledge/packages/inspect", {
      method: "POST", headers: { "content-type": "application/json" },
      body: file, signal: signal ?? null,
    });
  }

  /** Import the same sealed bytes after explicit confirmation; the server verifies them again. */
  async importCloudKnowledgePackage(
    file: Blob,
    signal?: AbortSignal,
  ): Promise<CloudKnowledgeIntakeResult> {
    return this.#json<CloudKnowledgeIntakeResult>("/ingestion/cloud-knowledge/packages/import", {
      method: "POST", headers: { "content-type": "application/json" },
      body: file, signal: signal ?? null,
    });
  }

  async createUpload(input: CreateUploadInput): Promise<CreatedUploadResponse> {
    return this.#json<CreatedUploadResponse>("/ingestion/uploads", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(input),
    });
  }

  async createOrReuseUpload(input: CreateUploadInput): Promise<CreateUploadResponse> {
    return this.#json<CreateUploadResponse>("/ingestion/uploads", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ...input, replace_existing: true }),
    });
  }

  async uploadContent(target: string, file: File): Promise<void> {
    const url = new URL(target, this.#baseUrl);
    await this.#request(url, {
      method: "PUT",
      headers: { "content-type": file.type || "application/octet-stream" },
      body: file,
    }, { authorize: url.origin === new URL(this.#baseUrl).origin });
  }

  async completeUpload(uploadId: string): Promise<UploadSession> {
    return this.#json<UploadSession>(`/ingestion/uploads/${encodeURIComponent(uploadId)}/complete`, {
      method: "POST",
    });
  }

  async status(uploadId: string): Promise<UploadSession> {
    return this.#json<UploadSession>(`/ingestion/uploads/${encodeURIComponent(uploadId)}`, {
      method: "GET",
    });
  }

  async listDocuments(collectionId: string, limit = 100): Promise<readonly DocumentVersionSummary[]> {
    const params = new URLSearchParams({
      collection_id: collectionId,
      limit: String(limit),
    });
    const response = await this.#json<{ readonly items: readonly DocumentVersionSummary[] }>(
      `/documents?${params.toString()}`,
      { method: "GET" },
    );
    return response.items;
  }

  async listDocumentVersions(
    documentId: string,
  ): Promise<readonly DocumentVersionSummary[]> {
    const response = await this.#json<{
      readonly items: readonly DocumentVersionSummary[];
    }>(`/documents/${encodeURIComponent(documentId)}/versions`, { method: "GET" });
    return response.items;
  }

  async previewDocument(documentId: string, versionId: string): Promise<DocumentPreview> {
    return this.#json<DocumentPreview>(
      `/documents/${encodeURIComponent(documentId)}/versions/${encodeURIComponent(versionId)}/preview`,
      { method: "GET" },
    );
  }

  async downloadDocument(documentId: string, versionId: string): Promise<Blob> {
    const response = await this.#request(new URL(
      `/documents/${encodeURIComponent(documentId)}/versions/${encodeURIComponent(versionId)}/download`,
      this.#baseUrl,
    ), { method: "GET" });
    return response.blob();
  }

  async deleteDocument(documentId: string, versionId: string): Promise<void> {
    await this.#request(new URL(
      `/documents/${encodeURIComponent(documentId)}/versions/${encodeURIComponent(versionId)}`,
      this.#baseUrl,
    ), { method: "DELETE" });
  }

  async promoteDocument(
    documentId: string,
    versionId: string,
    collectionId: string,
  ): Promise<UploadSession> {
    return this.#json<UploadSession>(
      `/documents/${encodeURIComponent(documentId)}/versions/${encodeURIComponent(versionId)}/promote`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ collection_id: collectionId }),
      },
    );
  }

  async handoverDraft(uploadId: string): Promise<HandoverDraftResult> {
    return this.#json<HandoverDraftResult>(
      `/ingestion/uploads/${encodeURIComponent(uploadId)}/handover-draft`,
      { method: "GET" },
    );
  }

  async reportLineDraft(uploadId: string): Promise<ReportLineDraftResult> {
    return this.#json<ReportLineDraftResult>(
      `/ingestion/uploads/${encodeURIComponent(uploadId)}/report-line-draft`,
      { method: "GET" },
    );
  }

  async cancel(uploadId: string): Promise<UploadSession> {
    return this.#json<UploadSession>(`/ingestion/uploads/${encodeURIComponent(uploadId)}/cancel`, {
      method: "POST",
    });
  }

  async #json<T>(path: string, init: RequestInit): Promise<T> {
    const response = await this.#request(new URL(path, this.#baseUrl), init);
    try {
      return (await response.json()) as T;
    } catch (error) {
      if (init.signal?.aborted) throw error;
      throw new IngestionApiError(response.status, "The ingestion service returned invalid JSON.");
    }
  }

  async #request(
    url: URL,
    init: RequestInit,
    options: { readonly authorize?: boolean } = {},
  ): Promise<Response> {
    init.signal?.throwIfAborted();
    const headers = new Headers(init.headers);
    headers.set("accept", "application/json");
    if (options.authorize !== false) {
      const authorization = await this.#readClient.authorizationHeader();
      if (authorization) headers.set("authorization", authorization);
    }
    init.signal?.throwIfAborted();
    const response = await fetch(url, { ...init, headers, credentials: "omit" });
    if (!response.ok) {
      let message = `HTTP ${response.status}`;
      try {
        const body = (await response.json()) as { message?: unknown };
        if (typeof body.message === "string") message = body.message;
      } catch {
        // Preserve the bounded HTTP fallback when the body is not JSON.
      }
      throw new IngestionApiError(response.status, message);
    }
    return response;
  }
}
