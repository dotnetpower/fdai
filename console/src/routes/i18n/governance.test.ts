import { afterEach, describe, expect, it } from "vitest";
import { setLocale } from "../../i18n";
import capabilitiesEn from "./capabilities.en.json";
import capabilitiesKo from "./capabilities.ko.json";
import { t as capabilityText } from "./capabilities";
import en from "./governance.en.json";
import ko from "./governance.ko.json";
import { displayValue, formatNumber, t } from "./governance";

afterEach(() => setLocale("en"));

function leafPaths(value: unknown, prefix = ""): string[] {
  if (typeof value === "string") return [prefix];
  if (typeof value !== "object" || value === null) return [];
  return Object.entries(value).flatMap(([key, child]) =>
    leafPaths(child, prefix === "" ? key : `${prefix}.${key}`),
  );
}

describe("governance route localization", () => {
  it("explains WARA evidence codes without suppressing unrecognized values", () => {
    setLocale("ko");
    expect(displayValue("controlStatus", "unknown")).toBe("알 수 없음");
    expect(displayValue("waraLimitation", "missing_exact_evaluator")).toBe("이 권고에 정확히 연결된 평가기가 없습니다.");
    expect(displayValue("waraEvidence", "recovery_drill")).toBe("복구 훈련 기록");
    expect(displayValue("waraLimitation", "future_reason")).toBe("future_reason");
    expect(t("governance.rules.wara.detail.days", { count: 90 })).toBe("90일");
    expect(t("governance.rules.wara.detail.seconds", { count: 61 })).toBe("61초");
    setLocale("en");
    expect(t("governance.rules.wara.detail.days", { count: 90 })).toBe("90 days");
  });
  it("renders the English source and interpolates values", () => {
    expect(capabilityText("governance.capabilities.unregistered", { id: "cap.read" }))
      .toBe("Capability cap.read is not registered.");
  });

  it("provides complete Korean leaf-key coverage", () => {
    expect(leafPaths(ko).sort()).toEqual(leafPaths(en).sort());
  });

  it("resolves every route-local leaf in both locales", () => {
    const paths = leafPaths(en);
    for (const path of paths) {
      const key = `governance.${path}`;
      expect(t(key)).not.toBe(key);
    }
    setLocale("ko");
    for (const path of paths) {
      const key = `governance.${path}`;
      expect(t(key)).not.toBe(key);
    }
  });

  it("keeps the capability catalog complete in both locales", () => {
    expect(leafPaths(capabilitiesKo).sort()).toEqual(leafPaths(capabilitiesEn).sort());
    const paths = leafPaths(capabilitiesEn);
    for (const path of paths) {
      const key = `governance.capabilities.${path}`;
      expect(capabilityText(key)).not.toBe(key);
    }
    setLocale("ko");
    for (const path of paths) {
      const key = `governance.capabilities.${path}`;
      expect(capabilityText(key)).not.toBe(key);
    }
  });

  it("falls back to English for a missing Korean route value", () => {
    const mutableKo = ko as { common: { all?: string } };
    const original = mutableKo.common.all;
    if (original === undefined) throw new Error("Korean all value is required for this test");
    delete mutableKo.common.all;
    try {
      setLocale("ko");
      expect(t("governance.common.all")).toBe("All");
    } finally {
      mutableKo.common.all = original;
    }
  });

  it("localizes known display values and preserves unknown machine values", () => {
    setLocale("ko");
    expect(displayValue("severity", "critical")).toBe("매우 심각");
    expect(displayValue("severity", "future-value")).toBe("future-value");
  });

  it("falls back to the main catalog for shared keys", () => {
    setLocale("ko");
    expect(t("route.rules")).toBe("규칙");
  });

  it("formats numbers for the active locale", () => {
    expect(formatNumber(1234567)).toBe("1,234,567");
    setLocale("ko");
    expect(formatNumber(1234567)).toBe("1,234,567");
  });
});
