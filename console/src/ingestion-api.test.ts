import { afterEach, describe, expect, test, vi } from "vitest";
import type { OperatorApiClient } from "./api";
import type { ConsoleConfig } from "./config";
import { IngestionApiClient } from "./ingestion-api";

const config = {
  ingestionApiBaseUrl: "https://ingestion.example.com",
} as ConsoleConfig;

function client(authorizationHeader = "Bearer test-token"): IngestionApiClient {
  return new IngestionApiClient(config, {
    authorizationHeader: vi.fn().mockResolvedValue(authorizationHeader),
  } as unknown as OperatorApiClient);
}

describe("IngestionApiClient upload authorization", () => {
  afterEach(() => vi.unstubAllGlobals());

  test("leaves collection reader groups to the server policy", async () => {
    const fetch = vi.fn().mockResolvedValue(Response.json({
      session: {
        upload_id: "upload-1",
        document_id: "document-1",
        version_id: "version-1",
        source_name: "guide.txt",
        state: "created",
        collection_id: "shared-knowledge",
      },
      upload: {
        target: "/ingestion/uploads/upload-1/content",
        expires_at: "2026-09-04T10:00:00Z",
        completed_parts: [],
      },
    }));
    vi.stubGlobal("fetch", fetch);

    await client().createUpload({
      source_name: "guide.txt",
      collection_id: "shared-knowledge",
      media_type_hint: "text/plain",
      expected_size: 7,
      expected_sha256: "a".repeat(64),
      storage_mode: "managed_copy",
      purposes: ["knowledge_base"],
      access_descriptor_ref: "collection:shared-knowledge",
      retention_policy_version: "v1",
    });

    const body = JSON.parse(String(fetch.mock.calls[0]![1].body)) as Record<string, unknown>;
    expect(body).not.toHaveProperty("reader_groups");
    expect(body.access_descriptor_ref).toBe("collection:shared-knowledge");
  });

  test("does not forward the API bearer token to a cross-origin upload target", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetch);

    await client().uploadContent(
      "https://storage.example.com/container/object?signature=example",
      new File(["content"], "handover.txt", { type: "text/plain" }),
    );

    const headers = new Headers(fetch.mock.calls[0]![1].headers);
    expect(headers.get("authorization")).toBeNull();
    expect(headers.get("content-type")).toBe("text/plain");
  });

  test("keeps the API bearer token for a same-origin proxy upload target", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetch);

    await client().uploadContent(
      "/ingestion/uploads/upload-1/content",
      new File(["content"], "handover.txt", { type: "text/plain" }),
    );

    const headers = new Headers(fetch.mock.calls[0]![1].headers);
    expect(headers.get("authorization")).toBe("Bearer test-token");
  });
});
