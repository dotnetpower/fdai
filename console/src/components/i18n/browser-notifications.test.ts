import { afterEach, describe, expect, test } from "vitest";
import { setLocale } from "../../i18n";
import { browserNotificationText } from "./browser-notifications";

afterEach(() => setLocale("en"));

describe("browser notification catalog", () => {
  test("renders explicit Console web channel states in both locales", () => {
    expect(browserNotificationText("stateAcknowledged")).toBe("Sent + opened");
    expect(browserNotificationText("stateAcknowledgedCompact")).toBe("Opened");
    setLocale("ko");
    expect(browserNotificationText("stateAcknowledged")).toBe("전송 및 확인됨");
    expect(browserNotificationText("stateAcknowledgedCompact")).toBe("열림");
  });
});
