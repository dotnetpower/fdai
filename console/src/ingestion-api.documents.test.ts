import { afterEach, describe, expect, test, vi } from "vitest";
import type { OperatorApiClient } from "./api";
import type { ConsoleConfig } from "./config";
import { IngestionApiClient } from "./ingestion-api";

const config = {
  ingestionApiBaseUrl: "https://ingestion.example.com",
} as ConsoleConfig;

describe("IngestionApiClient document catalog", () => {
  afterEach(() => vi.unstubAllGlobals());

  test("lists one encoded collection through the authenticated API boundary", async () => {
    const items = [{
      document_id: "document-1",
      version_id: "version-1",
      source_name: "guide.txt",
      size_bytes: 7,
      media_type: "text/plain",
      state: "ready",
      classification: "unclassified",
      purposes: ["knowledge_base"],
      created_at: "2026-09-05T03:00:00Z",
      updated_at: "2026-09-05T03:01:00Z",
      active: true,
      available: true,
      warnings: [],
    }];
    const fetch = vi.fn().mockResolvedValue(Response.json({ items }));
    vi.stubGlobal("fetch", fetch);
    const client = new IngestionApiClient(config, {
      authorizationHeader: vi.fn().mockResolvedValue("Bearer test-token"),
    } as unknown as OperatorApiClient);

    await expect(client.listDocuments("shared knowledge", 25)).resolves.toEqual(items);

    expect(String(fetch.mock.calls[0]![0])).toBe(
      "https://ingestion.example.com/documents?collection_id=shared+knowledge&limit=25",
    );
    expect(new Headers(fetch.mock.calls[0]![1].headers).has("authorization")).toBe(true);
  });
});
