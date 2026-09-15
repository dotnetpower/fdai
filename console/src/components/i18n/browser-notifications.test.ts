import { afterEach, describe, expect, test } from "vitest";
import { setLocale } from "../../i18n";
import { browserNotificationText } from "./browser-notifications";

afterEach(() => setLocale("en"));

describe("browser notification catalog", () => {
  test("approval evidence does not claim that an Incident exists", () => {
    expect(browserNotificationText("approvalBody"))
      .toBe("Open the Console to review the approval evidence.");
    setLocale("ko");
    expect(browserNotificationText("approvalBody")).toBe("콘솔에서 승인 근거를 검토하세요.");
  });

  test("renders explicit Console web channel states in both locales", () => {
    expect(browserNotificationText("stateAcknowledged")).toBe("Sent + opened");
    expect(browserNotificationText("stateAcknowledgedCompact")).toBe("Opened");
    setLocale("ko");
    expect(browserNotificationText("stateAcknowledged")).toBe("전송 및 확인됨");
    expect(browserNotificationText("stateAcknowledgedCompact")).toBe("열림");
  });
});
