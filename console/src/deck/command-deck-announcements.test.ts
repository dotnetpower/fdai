import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, test } from "vitest";

import { setLocale, t } from "../i18n";

const sources = [
  "./use-command-deck-submit.ts",
  "./use-command-deck-composer.ts",
  "./use-command-deck-events.ts",
].map((relative) => readFileSync(fileURLToPath(new URL(relative, import.meta.url)), "utf8"));

afterEach(() => setLocale("en"));

describe("Command Deck screen-reader announcements", () => {
  test("localizes fixed lifecycle announcements", () => {
    setLocale("ko");

    expect(t("deck.announcement.retrieving")).toBe("답변을 가져오는 중입니다...");
    expect(t("deck.announcement.answering")).toBe("답변을 작성하는 중입니다...");
    expect(t("deck.announcement.corrected")).toBe("답변이 수정되었습니다.");
    expect(t("deck.announcement.unverified")).toBe("답변을 검증하지 못했습니다.");
    expect(t("deck.announcement.verified")).toBe("답변이 검증되었습니다.");
    expect(t("deck.announcement.stopped")).toBe("중지되었습니다.");
    expect(t("deck.announcement.ready")).toBe("답변이 준비되었습니다.");
    expect(t("deck.announcement.responseDismissed")).toBe(
      "응답 표시를 중단했습니다. 제출 결과는 아직 확인되지 않았을 수 있습니다.",
    );
  });

  test("does not reintroduce fixed English announcements in deck hooks", () => {
    const combined = sources.join("\n");
    for (const literal of [
      "Retrieving answer...",
      "Assistant is answering...",
      "Answer corrected.",
      "Answer could not be verified.",
      "Answer verified.",
      "Stopped.",
      "Answer ready.",
      "Response dismissed; submission outcome may be unknown.",
    ]) {
      expect(combined).not.toContain(`"${literal}"`);
    }
  });
});
