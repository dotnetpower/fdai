import type { ReadApiClient } from "./api";
import type { ConsoleConfig } from "./config";

export interface IngestionCapabilities {
  readonly supported_formats: readonly string[];
  readonly storage_modes: readonly string[];
  readonly max_file_size: number;
  readonly max_batch_count: number;
  readonly archives_enabled: boolean;
  readonly policy_versions: readonly string[];
  readonly direct_upload: boolean;
}

export interface UploadSession {
  readonly upload_id: string;
  readonly document_id: string;
  readonly version_id: string;
  readonly source_name: string;
  readonly state: string;
  readonly collection_id: string;
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
  readonly reader_groups: readonly string[];
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
  readonly #readClient: ReadApiClient;

  constructor(config: ConsoleConfig, readClient: ReadApiClient) {
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
