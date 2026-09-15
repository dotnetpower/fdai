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

  it("localizes pending feedback, field requirements and specific evidence disclosures", () => {
    for (const locale of ["en", "ko"] as const) {
      setLocale(locale);
      for (const key of ["updating", "slotHint", "reasonHint", "sourceGoalHint"] as const) {
        expect(handoverText(key).length).toBeGreaterThan(20);
      }
      expect(handoverText("slotDetails", { slot: handoverText("scope_exclusions") }))
        .toContain(handoverText("scope_exclusions"));
      expect(handoverText("sourceGoalHint")).toContain("64");
      expect(handoverText("slotDetails", { slot: "synthetic-slot" })).not.toContain("{slot}");
    }
    expect(handoverText("updating")).toContain("아직 변경되지 않았습니다");
    setLocale("en");
    expect(handoverText("updating")).toContain("not changed yet");
  });
});
