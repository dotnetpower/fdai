import { describe, expect, it, vi } from "vitest";

import { releaseFailedAttachmentSource } from "./conversation-turn-attachments";

describe("conversation turn attachment failures", () => {
  it("removes only the image source that failed to decode", () => {
    const revoke = vi.fn();
    expect(releaseFailedAttachmentSource({
      "att-first": "blob:first",
      "att-second": "blob:second",
    }, "att-first", revoke)).toEqual({
      "att-first": "",
      "att-second": "blob:second",
    });
    expect(revoke).toHaveBeenCalledWith("blob:first");
  });
});
