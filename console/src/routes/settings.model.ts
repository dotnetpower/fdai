import type { ConsolePreferences } from "../preferences";
import type {
  ConversationPolicyPayload,
  UserContextPayload,
  UserPreferencePayload,
} from "../user-context-client";

export interface SettingsMutationLock {
  current: boolean;
}

export function claimSettingsMutation(lock: SettingsMutationLock): boolean {
  if (lock.current) return false;
  lock.current = true;
  return true;
}

export function releaseSettingsMutation(lock: SettingsMutationLock): void {
  lock.current = false;
}

export function settingsDraftIsCurrent(currentRevision: number, startedRevision: number): boolean {
  return currentRevision === startedRevision;
}

export function claimSettingsDelete(claims: Set<string>, key: string): boolean {
  if (claims.has(key)) return false;
  claims.add(key);
  return true;
}

export function contextWithSavedPreference(
  context: UserContextPayload | null,
  preference: UserPreferencePayload,
): UserContextPayload | null {
  return context === null ? null : { ...context, preference };
}

export function contextPreferencesAreDirty(input: {
  readonly preference: UserPreferencePayload | null | undefined;
  readonly answerDetail: UserPreferencePayload["answer_detail"];
  readonly answerFormat: UserPreferencePayload["answer_format"];
  readonly answerPreferencesEnabled: boolean;
  readonly timezone: string;
  readonly shareWithLearner: boolean;
}): boolean {
  return input.answerDetail !== (input.preference?.answer_detail ?? "standard")
    || input.answerFormat !== (input.preference?.answer_format ?? "prose")
    || input.answerPreferencesEnabled
      !== (input.preference?.answer_preferences_enabled ?? true)
    || input.timezone !== (input.preference?.timezone ?? defaultTimezone())
    || input.shareWithLearner !== (input.preference?.share_with_learner ?? false);
}

export function responseDefaultsPolicyForSave(
  policies: readonly ConversationPolicyPayload[],
): ConversationPolicyPayload | null {
  return policies.find((policy) => policy.kind === "response_defaults") ?? null;
}

export function buildResponseDefaultsPolicy(input: {
  readonly sourceTurnId: string;
  readonly enabled: boolean;
  readonly expectedRevision: number;
  readonly answerDetail: UserPreferencePayload["answer_detail"];
  readonly locale: ConsolePreferences["locale"];
}) {
  return {
    policy_id: "response-defaults",
    kind: "response_defaults",
    source_turn_id: input.sourceTurnId,
    enabled: input.enabled,
    expected_revision: input.expectedRevision,
    response_defaults: {
      verbosity: input.answerDetail === "deep" ? "detailed" : "concise",
      answer_language: input.locale,
    },
  } as const;
}

export function setLocaleOverride(locale: ConsolePreferences["locale"] | null): void {
  const url = new URL(window.location.href);
  if (locale === null) url.searchParams.delete("locale");
  else url.searchParams.set("locale", locale);
  window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
}

export function defaultTimezone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

export function isValidTimezone(value: string): boolean {
  if (!value.trim()) return false;
  try {
    new Intl.DateTimeFormat("en", { timeZone: value.trim() }).format();
    return true;
  } catch {
    return false;
  }
}

export function parseBriefingHour(value: string): number | null {
  if (!/^\d{1,2}$/.test(value.trim())) return null;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 0 && parsed <= 23 ? parsed : null;
}
