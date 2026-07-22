import { afterEach, describe, expect, test, vi } from "vitest";
import type { ReadApiClient } from "./api";
import type { ConsoleConfig } from "./config";
import { IngestionApiClient } from "./ingestion-api";

const config = {
  ingestionApiBaseUrl: "https://ingestion.example.com",
} as ConsoleConfig;

function client(authorizationHeader = "Bearer test-token"): IngestionApiClient {
  return new IngestionApiClient(config, {
    authorizationHeader: vi.fn().mockResolvedValue(authorizationHeader),
  } as unknown as ReadApiClient);
}

describe("IngestionApiClient upload authorization", () => {
  afterEach(() => vi.unstubAllGlobals());

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
