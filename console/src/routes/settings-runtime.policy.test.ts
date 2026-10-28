import { describe, expect, test } from "vitest";
import { normalizeRuntimeSettingChanges, type RuntimeSettingView } from "./settings-runtime.model";

const key = "detection.resource_availability";
const policy = { enabled: false, resource_types: [], resources: {}, max_age_seconds: 300 };
const setting: RuntimeSettingView = {
  key, group: "investigation", valueType: "object",
  environmentValue: policy, effectiveValue: policy, overrideValue: null,
  minimum: null, maximum: null, options: [], restartRequired: false,
  available: true, unavailableReason: null,
};
const view = { settings: [setting] };

describe("structured availability policy edits", () => {
  test("normalizes JSON drafts through the existing revisioned command path", () => {
    expect(normalizeRuntimeSettingChanges(view, { [key]: JSON.stringify(policy) }))
      .toEqual({ [key]: policy });
  });
  test("preserves explicit reset and unrelated scalar changes", () => {
    expect(normalizeRuntimeSettingChanges(view, { [key]: null, "irp.enabled": true }))
      .toEqual({ [key]: null, "irp.enabled": true });
  });
  test.each(["{invalid", "[]", "true", "42", "null"])("rejects invalid object drafts: %s", (value) => {
    expect(() => normalizeRuntimeSettingChanges(view, { [key]: value })).toThrow();
  });
});
