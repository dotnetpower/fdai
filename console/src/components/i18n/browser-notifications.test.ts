import { afterEach, describe, expect, test } from "vitest";
import { setLocale } from "../../i18n";
import { browserNotificationText } from "./browser-notifications";

afterEach(() => setLocale("en"));

describe("browser notification catalog", () => {
  test("renders explicit Console web channel states in both locales", () => {
    expect(browserNotificationText("stateAcknowledged")).toBe("Sent + opened");
    setLocale("ko");
    expect(browserNotificationText("stateAcknowledged")).toBe("전송 및 확인됨");
  });
});
