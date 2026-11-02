import { describe, expect, it, vi } from "vitest";
const locale = vi.hoisted(() => ({ value: "en" }));
vi.mock("../i18n", () => ({ getLocale: () => locale.value }));
import en from "./i18n/settings-general.en.json";
import ko from "./i18n/settings-general.ko.json";
import { settingsGeneralText } from "./settings-general.i18n";
import { memoryScopeLabel, memoryStateLabel, memoryUxText } from "./operator-memory.i18n";
import { environmentUxText, observerReasonLabel } from "./environment-deployment.i18n";
import { runtimeUxText } from "./settings-runtime.i18n";

describe("menu-owned bilingual preference messages", () => {
  it("keeps General catalog keys paired and interpolates item-specific removal names", () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(ko).sort());
    locale.value = "en";
    expect(settingsGeneralText("removeMemory", { name: "memory-example" })).toContain("memory-example");
    expect(settingsGeneralText("removeMemory", { name: "memory-other" })).not.toBe(settingsGeneralText("removeMemory", { name: "memory-example" }));
  });
  it("renders localized states without changing unknown machine values into approval", () => {
    locale.value = "ko";
    expect(memoryScopeLabel("resource-group")).toBe("리소스 그룹");
    expect(memoryStateLabel("active")).toBe("활성");
    expect(memoryStateLabel("expired")).toBe("만료됨");
    expect(memoryStateLabel("unexpected")).toBe("알 수 없는 상태: unexpected");
    expect(observerReasonLabel("kubernetes_read")).toBe("Kubernetes 읽기 접근 권한");
    expect(observerReasonLabel("unknown_code")).toBe("원본에서 보고한 사전 조건");
  });
  it("provides English fallback and complete localized count/state messages", () => {
    locale.value = "en";
    expect(memoryUxText("count", { entries: 100, compactions: 2 })).toContain("100 loaded");
    expect(environmentUxText("count", { shown: 1, total: 3 })).toBe("Showing 1 of 3 loaded observer targets");
    expect(runtimeUxText("count", { shown: 1, total: 2 })).toBe("Showing 1 of 2 loaded policies");
    locale.value = "ko";
    expect(settingsGeneralText("loadedHistory", { shown: 10, total: 12 })).toBe("불러온 브리핑 결과 12개 중 10개 표시");
    expect(environmentUxText("expiredHint")).toContain("설치가 아니라");
  });
});
