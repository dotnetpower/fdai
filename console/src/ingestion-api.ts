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

interface CreateUploadResponse {
  readonly session: UploadSession;
  readonly upload: {
    readonly target: string;
    readonly expires_at: string;
    readonly completed_parts: readonly string[];
  };
}

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

  async createUpload(input: CreateUploadInput): Promise<CreateUploadResponse> {
    return this.#json<CreateUploadResponse>("/ingestion/uploads", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(input),
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

  async cancel(uploadId: string): Promise<UploadSession> {
    return this.#json<UploadSession>(`/ingestion/uploads/${encodeURIComponent(uploadId)}/cancel`, {
      method: "POST",
    });
  }

  async #json<T>(path: string, init: RequestInit): Promise<T> {
    const response = await this.#request(new URL(path, this.#baseUrl), init);
    try {
      return (await response.json()) as T;
    } catch {
      throw new IngestionApiError(response.status, "The ingestion service returned invalid JSON.");
    }
  }

  async #request(
    url: URL,
    init: RequestInit,
    options: { readonly authorize?: boolean } = {},
  ): Promise<Response> {
    const headers = new Headers(init.headers);
    headers.set("accept", "application/json");
    if (options.authorize !== false) {
      const authorization = await this.#readClient.authorizationHeader();
      if (authorization) headers.set("authorization", authorization);
    }
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
