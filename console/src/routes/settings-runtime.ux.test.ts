import { describe, expect, it } from "vitest";
import {
  filterRuntimePolicies, normalizeRuntimeSettingChanges, runtimeDraftError, runtimeNetChange,
  type RuntimeSettingView,
} from "./settings-runtime.model";

const numberSetting: RuntimeSettingView = {
  key: "analyzer.budget_seconds", group: "investigation", valueType: "integer",
  environmentValue: 30, overrideValue: null, effectiveValue: 30, minimum: 10, maximum: 300,
  options: [], restartRequired: false, available: true, unavailableReason: null,
};
const objectSetting: RuntimeSettingView = {
  ...numberSetting, key: "detection.resource_availability", valueType: "object",
  minimum: null, maximum: null, environmentValue: { enabled: false }, effectiveValue: { enabled: false },
};

describe("runtime policy editing UX contracts", () => {
  it("does not dirty a net-noop edit or reset without an existing override", () => {
    expect(runtimeNetChange(numberSetting, "30")).toBeUndefined();
    expect(runtimeNetChange(numberSetting, null)).toBeUndefined();
    expect(runtimeNetChange({ ...numberSetting, overrideValue: 60, effectiveValue: 60 }, null)).toBeNull();
    expect(runtimeNetChange(objectSetting, '{ "enabled": false }')).toBeUndefined();
  });
  it.each(["", "5", "301", "12.5", "NaN"])("retains invalid raw numeric draft for correction: %s", (raw) => {
    expect(runtimeNetChange(numberSetting, raw)).toBe(raw);
    expect(runtimeDraftError(numberSetting, raw)).toBe("numeric");
    expect(() => normalizeRuntimeSettingChanges({ settings: [numberSetting] }, { [numberSetting.key]: raw })).toThrow();
  });
  it("normalizes a valid raw numeric edit only at the request boundary", () => {
    expect(normalizeRuntimeSettingChanges({ settings: [numberSetting] }, { [numberSetting.key]: "60" }))
      .toEqual({ [numberSetting.key]: 60 });
  });
  it.each(["{invalid", "[]", "true", "42", "null"])("identifies local structured input errors: %s", (raw) => {
    expect(runtimeDraftError(objectSetting, raw)).toBe("object");
  });
  it("filters labels, canonical keys, and groups without changing the saved batch", () => {
    const settings = [numberSetting, objectSetting];
    const changes = { [numberSetting.key]: 60, [objectSetting.key]: null };
    expect(filterRuntimePolicies(settings, "가용성", false, changes, (key) => key === objectSetting.key ? "가용성 정책" : "예산"))
      .toEqual([objectSetting]);
    expect(filterRuntimePolicies(settings, "BUDGET_SECONDS", true, changes, () => "")).toEqual([numberSetting]);
    expect(filterRuntimePolicies(settings, "unknown", true, changes, () => "")).toEqual([]);
    expect(changes).toEqual({ [numberSetting.key]: 60, [objectSetting.key]: null });
  });
});
