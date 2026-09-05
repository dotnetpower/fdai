import { afterEach, describe, expect, it } from "vitest";
import { setLocale } from "../i18n";
import { handoverText } from "./handover-i18n";

describe("handoverText", () => {
  afterEach(() => setLocale("en"));

  it("distinguishes a completed upload from a failed handover link", () => {
    expect(handoverText("evidenceLinkFailed")).toContain("document was uploaded");

    setLocale("ko");

    expect(handoverText("evidenceLinkFailed")).toContain("문서는 업로드");
  });
});
