import { describe, expect, it } from "vitest";
import {
  buildResponseDefaultsPolicy,
  claimSettingsDelete,
  claimSettingsMutation,
  contextPreferencesAreDirty,
  contextWithSavedPreference,
  isValidTimezone,
  parseBriefingHour,
  releaseSettingsMutation,
  responseDefaultsPolicyForSave,
  settingsDraftIsCurrent,
} from "./settings";

describe("General Settings validation", () => {
  it("claims one context mutation synchronously", () => {
    const lock = { current: false };
    expect(claimSettingsMutation(lock)).toBe(true);
    expect(claimSettingsMutation(lock)).toBe(false);
    releaseSettingsMutation(lock);
    expect(claimSettingsMutation(lock)).toBe(true);
  });

  it("deduplicates pending deletes by resource key", () => {
    const claims = new Set<string>();
    expect(claimSettingsDelete(claims, "memory:one")).toBe(true);
    expect(claimSettingsDelete(claims, "memory:one")).toBe(false);
    expect(claimSettingsDelete(claims, "memory:two")).toBe(true);
  });

  it("reuses a disabled response-default policy revision", () => {
    const disabledPolicy = {
      policy_id: "response-defaults",
      kind: "response_defaults",
      enabled: false,
      revision: 7,
    } as never;
    expect(responseDefaultsPolicyForSave([disabledPolicy])?.revision).toBe(7);
  });

  it("disables response defaults when saved answer preferences are disabled", () => {
    expect(buildResponseDefaultsPolicy({
      sourceTurnId: "turn-1",
      enabled: false,
      expectedRevision: 7,
      answerDetail: "deep",
      locale: "ko",
    })).toEqual({
      policy_id: "response-defaults",
      kind: "response_defaults",
      source_turn_id: "turn-1",
      enabled: false,
      expected_revision: 7,
      response_defaults: {
        verbosity: "detailed",
        answer_language: "ko",
      },
    });
  });

  it("rejects context hydration after a local draft edit", () => {
    expect(settingsDraftIsCurrent(4, 4)).toBe(true);
    expect(settingsDraftIsCurrent(5, 4)).toBe(false);
  });

  it("keeps the successful preference revision after a later partial-save failure", () => {
    const context = {
      preference: { revision: 3 },
      memories: [],
      policies: [],
      subscriptions: [],
      conversations: [],
    } as never;
    const saved = { revision: 4 } as never;
    expect(contextWithSavedPreference(context, saved)?.preference?.revision).toBe(4);
  });

  it("detects account-scoped preference changes against the loaded revision", () => {
    const preference = {
      answer_detail: "standard",
      answer_format: "prose",
      answer_preferences_enabled: true,
      timezone: "Asia/Seoul",
      share_with_learner: false,
    } as never;
    expect(contextPreferencesAreDirty({
      preference,
      answerDetail: "standard",
      answerFormat: "prose",
      answerPreferencesEnabled: true,
      timezone: "Asia/Seoul",
      shareWithLearner: false,
    })).toBe(false);
    expect(contextPreferencesAreDirty({
      preference,
      answerDetail: "deep",
      answerFormat: "prose",
      answerPreferencesEnabled: true,
      timezone: "Asia/Seoul",
      shareWithLearner: false,
    })).toBe(true);
  });

  it("accepts valid IANA timezones", () => {
    expect(isValidTimezone("UTC")).toBe(true);
    expect(isValidTimezone("Asia/Seoul")).toBe(true);
  });

  it("rejects invalid or empty timezones", () => {
    expect(isValidTimezone("")).toBe(false);
    expect(isValidTimezone("Not/A_Real_Zone")).toBe(false);
  });

  it.each([
    ["0", 0],
    ["07", 7],
    ["23", 23],
  ])("parses valid briefing hour %s", (value, expected) => {
    expect(parseBriefingHour(value)).toBe(expected);
  });

  it.each(["", "7.5", "-1", "24", "abc"])("rejects invalid briefing hour %s", (value) => {
    expect(parseBriefingHour(value)).toBeNull();
  });
});
