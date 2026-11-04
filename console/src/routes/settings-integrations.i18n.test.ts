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

  it("labels the personal Console web selection scope", () => {
    expect(settingsIntegrationsText("consoleWebPersonalHint", {
      user: "operator@example.com",
    })).toContain("operator@example.com");
    setLocale("ko");
    expect(settingsIntegrationsText("personalChannelsTitle")).toBe("내 알림 채널");
    expect(settingsIntegrationsText("consoleWebPersonalLabel")).toBe("콘솔 웹(개인)");
  });

  it("renders bilingual Teams and Slack A1/A3 integration labels", () => {
    setLocale("en");
    expect(settingsIntegrationsText("slackA1SendLabel")).toBe("Slack A1 approval delivery");
    expect(settingsIntegrationsText("slackA1CallbackLabel")).toBe("Slack A1 approval handoff");
    expect(settingsIntegrationsText("slackA3Label")).toBe("Slack A3 conversations");
    setLocale("ko");
    expect(settingsIntegrationsText("slackA1SendLabel")).toBe("Slack A1 승인 전달");
    expect(settingsIntegrationsText("slackA1CallbackLabel")).toBe("Slack A1 승인 핸드오프");
    expect(settingsIntegrationsText("slackA3Label")).toBe("Slack A3 대화");
  });
});
