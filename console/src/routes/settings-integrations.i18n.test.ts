import { afterEach, describe, expect, it } from "vitest";
import { setLocale } from "../i18n";
import { settingsIntegrationsText } from "./settings-integrations.i18n";

afterEach(() => setLocale("en"));

describe("Settings integrations route catalog", () => {
  it("renders the English source", () => {
    setLocale("en");
    expect(settingsIntegrationsText("guideSummary")).toBe(
      "Show the Power Automate setup guide",
    );
  });

  it("renders the Korean translation", () => {
    setLocale("ko");
    expect(settingsIntegrationsText("guideSummary")).toBe(
      "Power Automate 설정 가이드 보기",
    );
  });

  it("interpolates result parameters", () => {
    setLocale("en");
    expect(
      settingsIntegrationsText("savedAndAcceptedDetail", {
        status: 202,
        time: "12:00",
      }),
    ).toContain("HTTP 202 at 12:00");
  });
});
