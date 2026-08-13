import { afterEach, describe, expect, test } from "vitest";

import liveKo from "../routes/i18n/live.messages.ko.json";
import { t as liveT } from "../routes/i18n/live";
import { setLocale, t, tForLocale } from ".";
import ko from "./messages.ko.json";

afterEach(() => setLocale("en"));

describe("mandatory English catalog fallback", () => {
  test("resolves dotted operational activity kinds in both locales", () => {
    expect(tForLocale("en", "agentActivity.log.lane.inventory.scan"))
      .toBe("Inventory scan");
    expect(tForLocale("en", "agentActivity.log.lane.current-state.read"))
      .toBe("Current state");
    expect(tForLocale("en", "agentActivity.log.lane.inventory.ontology-projection"))
      .toBe("Ontology projection");
    expect(tForLocale("ko", "agentActivity.log.lane.inventory.scan"))
      .toBe("인벤토리 검사");
  });

  test("renders an explicit conversational locale without changing the UI locale", () => {
    setLocale("en");
    expect(tForLocale("ko", "deck.incidentCandidates.title")).toBe("조사할 인시던트 선택");
    expect(t("deck.incidentCandidates.title")).toBe("Choose an incident");
  });

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
