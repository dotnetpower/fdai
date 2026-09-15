import { afterEach, describe, expect, it } from "vitest";
import { setLocale } from "../../i18n";
import { t } from "./browser-evidence";

afterEach(() => setLocale("en"));

describe("Browser evidence route catalog", () => {
  it("renders the English source and interpolates values", () => {
    setLocale("en");
    expect(t("browserEvidence.loadedSummary", {
      loaded: 25,
      matching: 42,
    })).toBe("25 loaded of 42 matching");
  });

  it("renders the Korean translation", () => {
    setLocale("ko");
    expect(t("browserEvidence.detail.securityReview")).toBe("보안 검토 필요");
    expect(t("browserEvidence.retention.expired_pending_purge")).toBe(
      "만료됨, 정리 대기",
    );
  });

  it("falls back to the main catalog for shared and route labels", () => {
    setLocale("en");
    expect(t("route.browserEvidence")).toBe("Browser evidence");
    expect(t("shared.loading")).toBe("Loading...");
  });
});
