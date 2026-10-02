import { afterEach, describe, expect, it } from "vitest";
import { setLocale } from "../i18n";
import { runRecordText } from "./run-record-i18n";
import en from "./i18n/run-record.en.json";
import ko from "./i18n/run-record.ko.json";

describe("runRecordText", () => {
  afterEach(() => setLocale("en"));

  it("renders every run-record label in the active locale", () => {
    for (const key of Object.keys(en) as (keyof typeof en)[]) {
      expect(runRecordText(key)).toBe(en[key]);
    }
    setLocale("ko");
    for (const key of Object.keys(en) as (keyof typeof en)[]) {
      expect(runRecordText(key)).toBe(ko[key]);
    }
    expect(runRecordText("serverElapsed")).toBe("서버 경과 시간");
  });

  it("substitutes placeholders like the main catalog and keeps unmatched ones", () => {
    expect(runRecordText("summary", {
      models: 3,
      modelDuration: "1.2 s",
      tokens: "4,096",
      successful: 2,
      attempted: 2,
    })).toBe("3 model calls / cumulative model 1.2 s / 4,096 tokens / evidence 2/2 / verification {verification}");
  });
});
