import { describe, expect, it } from "vitest";

import { parseTurnAttachments } from "./turn-attachments";

describe("turn attachment metadata", () => {
  it("rejects duplicate image ids instead of aliasing rendered sources", () => {
    expect(parseTurnAttachments([
      { id: "att-same", name: "first.png", media_type: "image/png" },
      { id: "att-same", name: "second.png", media_type: "image/png" },
    ], "conversation-1")).toEqual([]);
  });

  it("accepts distinct bounded image descriptors", () => {
    expect(parseTurnAttachments([
      { id: "att-first", name: "first.png", media_type: "image/png" },
      { id: "att-second", name: "second.webp", media_type: "image/webp" },
    ], "conversation-1")).toHaveLength(2);
  });
});
