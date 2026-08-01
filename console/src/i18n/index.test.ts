import { afterEach, describe, expect, test } from "vitest";

import liveKo from "../routes/i18n/live.messages.ko.json";
import { t as liveT } from "../routes/i18n/live";
import { setLocale, t } from ".";
import ko from "./messages.ko.json";

afterEach(() => setLocale("en"));

describe("mandatory English catalog fallback", () => {
  test("falls back when a global Korean value is empty", () => {
    const mutableKo = ko as { console: { initializeFailed: string } };
    const original = mutableKo.console.initializeFailed;
    mutableKo.console.initializeFailed = "";
    try {
      setLocale("ko");
      expect(t("console.initializeFailed")).toBe("Console failed to initialize.");
    } finally {
      mutableKo.console.initializeFailed = original;
    }
  });

  test("falls back when a Live Korean value is empty", () => {
    const mutableKo = liveKo as { title: string };
    const original = mutableKo.title;
    mutableKo.title = "";
    try {
      setLocale("ko");
      expect(liveT("live.title")).toBe("Control plane");
    } finally {
      mutableKo.title = original;
    }
  });
});
