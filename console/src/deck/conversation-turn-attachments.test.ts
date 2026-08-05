import { describe, expect, it } from "vitest";

import { withoutAttachmentSource } from "./conversation-turn-attachments";

describe("conversation turn attachment failures", () => {
  it("removes only the image source that failed to decode", () => {
    expect(withoutAttachmentSource({
      "att-first": "blob:first",
      "att-second": "blob:second",
    }, "att-first")).toEqual({
      "att-first": "",
      "att-second": "blob:second",
    });
  });
});
