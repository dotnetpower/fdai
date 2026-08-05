import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";

import { releaseFailedAttachmentSource } from "./conversation-turn-attachments";

const source = readFileSync(
  new URL("./conversation-turn-attachments.tsx", import.meta.url),
  "utf8",
);
const presenters = readFileSync(
  new URL("./command-deck-presenters.tsx", import.meta.url),
  "utf8",
);

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

  it("renders sent images above the question without filenames and opens a modal", () => {
    const attachmentsIndex = presenters.indexOf("<ConversationTurnAttachments");
    const questionIndex = presenters.indexOf(
      '<div class="deck-turn-body">',
      attachmentsIndex,
    );
    expect(attachmentsIndex).toBeGreaterThan(-1);
    expect(questionIndex).toBeGreaterThan(attachmentsIndex);
    expect(source).toContain('class="deck-turn-attachment-open"');
    expect(source).toContain('role="dialog"');
    expect(source).toContain('aria-modal="true"');
    expect(source).toContain('event.key === "Escape"');
    expect(source).toContain("createPortal(");
    expect(source).not.toContain("deck-turn-attachment-name");
    expect(source).not.toContain("{attachment.name}");
  });
});
