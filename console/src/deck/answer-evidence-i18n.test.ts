import { afterEach, describe, expect, it } from "vitest";
import { setLocale } from "../i18n";
import { answerEvidenceText } from "./answer-evidence-i18n";
import en from "./i18n/answer-evidence.en.json";
import ko from "./i18n/answer-evidence.ko.json";

describe("answerEvidenceText", () => {
  afterEach(() => setLocale("en"));

  it("renders every answer evidence label in the active locale", () => {
    for (const key of Object.keys(en) as (keyof typeof en)[]) {
      expect(answerEvidenceText(key)).toBe(en[key]);
    }
    setLocale("ko");
    for (const key of Object.keys(en) as (keyof typeof en)[]) {
      expect(answerEvidenceText(key)).toBe(ko[key]);
    }
    expect(answerEvidenceText("returnToAnswer")).toBe("답변으로 돌아가기");
  });
});
