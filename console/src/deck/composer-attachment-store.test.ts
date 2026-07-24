import { afterEach, describe, expect, it } from "vitest";
import {
  MAX_ATTACHMENTS,
  clearComposerAttachments,
  stageComposerAttachment,
  stagedComposerAttachmentCount,
  subscribeComposerAttachmentDrain,
  takeComposerAttachments,
  unstageComposerAttachment,
  type ChatAttachment,
} from "./composer-attachment-store";
import { createBackendRequestPayload } from "./backend-context";

function att(n: number): ChatAttachment {
  return { name: `img-${n}.png`, media_type: "image/png", data_url: `data:image/png;base64,AA${n}` };
}

afterEach(() => clearComposerAttachments());

describe("composer-attachment-store", () => {
  it("stages, counts, and takes attachments atomically", () => {
    stageComposerAttachment("a", att(1));
    stageComposerAttachment("b", att(2));
    expect(stagedComposerAttachmentCount()).toBe(2);
    const taken = takeComposerAttachments();
    expect(taken.map((a) => a.name)).toEqual(["img-1.png", "img-2.png"]);
    // take clears the store.
    expect(stagedComposerAttachmentCount()).toBe(0);
    expect(takeComposerAttachments()).toEqual([]);
  });

  it("replaces by id and unstages", () => {
    stageComposerAttachment("a", att(1));
    stageComposerAttachment("a", att(9));
    expect(stagedComposerAttachmentCount()).toBe(1);
    unstageComposerAttachment("a");
    expect(stagedComposerAttachmentCount()).toBe(0);
  });

  it("never exceeds the per-turn cap", () => {
    for (let i = 0; i < MAX_ATTACHMENTS + 3; i += 1) {
      stageComposerAttachment(`id-${i}`, att(i));
    }
    expect(stagedComposerAttachmentCount()).toBe(MAX_ATTACHMENTS);
  });

  it("clear drops everything", () => {
    stageComposerAttachment("a", att(1));
    clearComposerAttachments();
    expect(stagedComposerAttachmentCount()).toBe(0);
  });

  it("notifies drain subscribers on take (send), and stops after unsubscribe", () => {
    let drains = 0;
    const unsubscribe = subscribeComposerAttachmentDrain(() => {
      drains += 1;
    });
    stageComposerAttachment("a", att(1));
    takeComposerAttachments();
    expect(drains).toBe(1);
    // A text-only send (empty store) still notifies so the tray clears on
    // every send, on both Enter and button paths.
    takeComposerAttachments();
    expect(drains).toBe(2);
    unsubscribe();
    takeComposerAttachments();
    expect(drains).toBe(2);
  });
});

describe("createBackendRequestPayload attachments", () => {
  it("includes attachments when present", () => {
    const payload = createBackendRequestPayload(
      "how many people?",
      null,
      [],
      "session-1",
      "req-1",
      undefined,
      [att(1), att(2)],
    );
    expect(payload.attachments).toEqual([
      { name: "img-1.png", media_type: "image/png", data_url: "data:image/png;base64,AA1" },
      { name: "img-2.png", media_type: "image/png", data_url: "data:image/png;base64,AA2" },
    ]);
  });

  it("omits attachments when none are supplied", () => {
    const payload = createBackendRequestPayload("hi", null, [], "session-1");
    expect("attachments" in payload).toBe(false);
  });
});
