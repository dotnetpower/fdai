import { afterEach, describe, expect, it } from "vitest";
import { setLocale } from "../i18n";
import { handoverText } from "./handover-i18n";

describe("handoverText", () => {
  afterEach(() => setLocale("en"));

  it("distinguishes a completed upload from a failed handover link", () => {
    expect(handoverText("evidenceLinkFailed")).toContain("document was uploaded");
    expect(handoverText("oneFilePerSlot")).toContain("one file");

    setLocale("ko");

    expect(handoverText("evidenceLinkFailed")).toContain("문서는 업로드");
    expect(handoverText("oneFilePerSlot")).toContain("하나만 선택");
  });
});
