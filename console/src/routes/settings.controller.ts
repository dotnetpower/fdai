import { useEffect, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { settingsGeneralText } from "./settings-general.i18n";
import { identityForMutationIntent, type MutationIntentIdentity } from "../mutation-intent";
import {
  PREFERENCES_CHANGED_EVENT,
  readConsolePreferences,
  resetConsolePreferences,
  setConsolePreference,
  type ConsolePreferences,
} from "../preferences";
import {
  createBriefingSubscription,
  deleteConversationPolicy,
  deleteBriefingSubscription,
  deleteUserPreference,
  deleteUserMemory,
  fetchUserContext,
  putConversationPolicy,
  putUserPreference,
  type UserContextPayload,
  type UserPreferencePayload,
} from "../user-context-client";
import {
  buildResponseDefaultsPolicy,
  claimSettingsDelete,
  claimSettingsMutation,
  contextPreferencesAreDirty,
  contextWithSavedPreference,
  contextDraftFromPreference,
  defaultTimezone,
  isValidTimezone,
  normalizeSettingsTimezone,
  parseBriefingHour,
  releaseSettingsMutation,
  responseDefaultsPolicyForSave,
  shouldHydrateSettingsDraft,
  settingsResetIsReady,
  setLocaleOverride,
} from "./settings.model";

export function useSettingsController(client: OperatorApiClient) {
  const [preferences, setPreferences] = useState<ConsolePreferences>(readConsolePreferences);
  const [serverContext, setServerContext] = useState<UserContextPayload | null>(null);
  const [contextLoading, setContextLoading] = useState(true);
  const [contextError, setContextError] = useState<string | null>(null);
  const [contextNotice, setContextNotice] = useState<string | null>(null);
  const [timezoneError, setTimezoneError] = useState(false);
  const [briefingHourError, setBriefingHourError] = useState(false);
  const [pendingResponsePolicy, setPendingResponsePolicy] = useState<
    ReturnType<typeof buildResponseDefaultsPolicy> | null
  >(null);
  const [answerDetail, setAnswerDetail] = useState<UserPreferencePayload["answer_detail"]>("standard");
  const [answerFormat, setAnswerFormat] = useState<UserPreferencePayload["answer_format"]>("prose");
  const [answerPreferencesEnabled, setAnswerPreferencesEnabled] = useState(true);
  const [timezone, setTimezone] = useState(defaultTimezone);
  const [shareWithLearner, setShareWithLearner] = useState(false);
  const [briefingHour, setBriefingHour] = useState("07");
  const [savingContext, setSavingContext] = useState(false);
  const [pendingDeletes, setPendingDeletes] = useState<ReadonlySet<string>>(new Set());
  const refreshGeneration = useRef(0);
  const briefingIntent = useRef<MutationIntentIdentity | null>(null);
  const mutationInFlight = useRef(false);
  const pendingDeleteClaims = useRef(new Set<string>());
  const draftRevision = useRef(0);

  const beginMutation = (): boolean => {
    if (!claimSettingsMutation(mutationInFlight)) return false;
    setSavingContext(true);
    return true;
  };

  const finishMutation = (): void => {
    releaseSettingsMutation(mutationInFlight);
    setSavingContext(false);
  };

  useEffect(() => {
    const syncPreferences = () => setPreferences(readConsolePreferences());
    window.addEventListener(PREFERENCES_CHANGED_EVENT, syncPreferences);
    return () => window.removeEventListener(PREFERENCES_CHANGED_EVENT, syncPreferences);
  }, []);

  const hydrateDraft = (preference: UserPreferencePayload | null | undefined): void => {
    const draft = contextDraftFromPreference(preference);
    setAnswerDetail(draft.answerDetail);
    setAnswerFormat(draft.answerFormat);
    setAnswerPreferencesEnabled(draft.answerPreferencesEnabled);
    setTimezone(draft.timezone);
    setShareWithLearner(draft.shareWithLearner);
  };

  const refreshContext = async (savedDraftRevision?: number): Promise<boolean> => {
    const generation = ++refreshGeneration.current;
    const startedDraftRevision = savedDraftRevision ?? draftRevision.current;
    const dirtyAtStart = serverContext !== null && contextPreferencesAreDirty({
      preference: serverContext.preference, answerDetail, answerFormat, answerPreferencesEnabled,
      timezone: normalizeSettingsTimezone(timezone), shareWithLearner,
    });
    setContextLoading(true);
    try {
      const context = await fetchUserContext();
      if (generation !== refreshGeneration.current) return false;
      setServerContext(context);
      if (shouldHydrateSettingsDraft({
        currentRevision: draftRevision.current, startedRevision: startedDraftRevision,
        dirtyAtStart, saveReadback: savedDraftRevision !== undefined,
      })) {
        hydrateDraft(context.preference);
      }
      setContextError(null);
      return true;
    } catch (error) {
      if (generation !== refreshGeneration.current) return false;
      setContextError(error instanceof Error ? error.message : String(error));
      return false;
    } finally {
      if (generation === refreshGeneration.current) setContextLoading(false);
    }
  };

  useEffect(() => {
    setServerContext(null);
    setPendingResponsePolicy(null);
    setContextNotice(null);
    void refreshContext();
    return () => { refreshGeneration.current += 1; };
  }, [client]);

  const updateAnswerDetail = (value: UserPreferencePayload["answer_detail"]): void => {
    setContextNotice(null);
    draftRevision.current += 1;
    setAnswerDetail(value);
  };

  const updateAnswerFormat = (value: UserPreferencePayload["answer_format"]): void => {
    setContextNotice(null);
    draftRevision.current += 1;
    setAnswerFormat(value);
  };

  const updateAnswerPreferencesEnabled = (value: boolean): void => {
    setContextNotice(null);
    draftRevision.current += 1;
    setAnswerPreferencesEnabled(value);
  };

  const updateTimezone = (value: string): void => {
    setContextNotice(null);
    draftRevision.current += 1;
    setTimezone(value);
    if (isValidTimezone(value)) setTimezoneError(false);
  };

  const updateShareWithLearner = (value: boolean): void => {
    setContextNotice(null);
    draftRevision.current += 1;
    setShareWithLearner(value);
  };

  usePublishViewContext(
    () => ({
      routeId: "settings-general",
      routeLabel: t("route.settingsGeneral"),
      purpose: "Browser-local console display and accessibility preferences.",
      glossary: composeGlossary([TERMS.userPreference]),
      headline:
        `${preferences.theme} theme, ${preferences.locale} locale, ` +
        `${preferences.motion} motion`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "theme", value: preferences.theme, group: "display" },
        { key: "locale", value: preferences.locale, group: "display" },
        { key: "motion", value: preferences.motion, group: "accessibility" },
      ],
      records: {},
    }),
    [preferences],
  );

  const update = <Key extends keyof ConsolePreferences>(
    key: Key,
    value: ConsolePreferences[Key],
  ) => {
    setConsolePreference(key, value);
  };

  const updateLocale = (locale: ConsolePreferences["locale"]) => {
    const persisted = setConsolePreference("locale", locale);
    setLocaleOverride(persisted ? null : locale);
    window.location.reload();
  };

  const reset = async (): Promise<void> => {
    if (!settingsResetIsReady({ context: serverContext, loading: contextLoading, saving: savingContext })) return;
    if (!window.confirm(settingsGeneralText("confirmReset"))) return;
    if (!beginMutation()) return;
    try {
      if (serverContext?.preference !== null && serverContext?.preference !== undefined) {
        await deleteUserPreference();
      }
      const persisted = resetConsolePreferences();
      setLocaleOverride(persisted ? null : "en");
      window.location.reload();
    } catch (error) {
      setContextError(error instanceof Error ? error.message : String(error));
      finishMutation();
    }
  };

  const openingPolicy = serverContext?.policies.find(
    (policy) => policy.kind === "opening_briefing" && policy.enabled,
  ) ?? null;
  const responsePolicy = responseDefaultsPolicyForSave(serverContext?.policies ?? []);
  const latestSourceTurnId = serverContext?.conversations.find(
    (conversation) => conversation.latest_operator_turn_id !== null,
  )?.latest_operator_turn_id ?? null;
  const preferenceDirty = serverContext !== null && contextPreferencesAreDirty({
    preference: serverContext?.preference,
    answerDetail,
    answerFormat,
    answerPreferencesEnabled,
    timezone: normalizeSettingsTimezone(timezone),
    shareWithLearner,
  });
  const contextDirty = preferenceDirty || pendingResponsePolicy !== null;

  const discardContextChanges = (): void => {
    if (serverContext === null || savingContext) return;
    draftRevision.current += 1;
    hydrateDraft(serverContext.preference);
    setTimezoneError(false);
    setBriefingHourError(false);
    setContextNotice(null);
  };

  const retryResponsePolicy = async (): Promise<void> => {
    if (pendingResponsePolicy === null || !beginMutation()) return;
    try {
      await putConversationPolicy(pendingResponsePolicy);
      setPendingResponsePolicy(null);
      if (await refreshContext()) setContextNotice(settingsGeneralText("contextSaved"));
    } catch (error) {
      setContextError(error instanceof Error ? error.message : String(error));
    } finally {
      finishMutation();
    }
  };

  const saveContextPreferences = async (): Promise<void> => {
    if (serverContext === null || contextLoading || !preferenceDirty) return;
    if (!isValidTimezone(timezone)) {
      setTimezoneError(true);
      document.getElementById("settings-timezone")?.focus();
      return;
    }
    if (!beginMutation()) return;
    const startedDraftRevision = draftRevision.current;
    setContextNotice(null);
    let preferenceSaved = false;
    try {
      const savedPreference = await putUserPreference({
        locale: preferences.locale,
        verbosity: answerDetail === "deep" ? "detailed" : "concise",
        answer_detail: answerDetail,
        answer_format: answerFormat,
        answer_preferences_enabled: answerPreferencesEnabled,
        answer_intent_detail: serverContext?.preference?.answer_intent_detail ?? {},
        answer_intent_format: serverContext?.preference?.answer_intent_format ?? {},
        timezone: normalizeSettingsTimezone(timezone),
        share_with_learner: shareWithLearner,
        expected_revision: serverContext?.preference?.revision ?? 0,
      });
      preferenceSaved = true;
      setServerContext((current) => contextWithSavedPreference(current, savedPreference));
      if (latestSourceTurnId !== null) {
        const policy = buildResponseDefaultsPolicy({
          sourceTurnId: latestSourceTurnId,
          enabled: answerPreferencesEnabled,
          expectedRevision: responsePolicy?.revision ?? 0,
          answerDetail,
          locale: preferences.locale,
        });
        setPendingResponsePolicy(policy);
        await putConversationPolicy(policy);
        setPendingResponsePolicy(null);
      }
      if (await refreshContext(startedDraftRevision)) setContextNotice(settingsGeneralText("contextSaved"));
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      setContextError(preferenceSaved ? t("settings.contextPartialSave", { error: detail }) : detail);
    } finally {
      finishMutation();
    }
  };

  const addDailyBriefing = async (): Promise<void> => {
    if (serverContext === null || contextLoading) return;
    const hour = parseBriefingHour(briefingHour);
    if (hour === null) {
      setBriefingHourError(true);
      document.getElementById("settings-briefing-hour")?.focus();
      return;
    }
    if (!isValidTimezone(timezone)) {
      setTimezoneError(true);
      document.getElementById("settings-timezone")?.focus();
      return;
    }
    if (!beginMutation()) return;
    try {
      const identity = identityForMutationIntent(
        briefingIntent.current,
        JSON.stringify({ hour, timezone: normalizeSettingsTimezone(timezone) }),
      );
      briefingIntent.current = identity;
      await createBriefingSubscription({
        name: "Daily major issues",
        cron_expression: `0 ${hour} * * *`,
        timezone: normalizeSettingsTimezone(timezone),
        delivery_modes: ["in_app"],
        spec: {
          kind: "major_issues",
          lookback_seconds: 86_400,
          minimum_severity: "high",
          max_items: 5,
        },
      }, identity.idempotencyKey);
      await refreshContext();
    } catch (error) {
      setContextError(error instanceof Error ? error.message : String(error));
    } finally {
      finishMutation();
    }
  };

  const enableOpeningBriefing = async (): Promise<void> => {
    if (latestSourceTurnId === null) return;
    if (!beginMutation()) return;
    try {
      await putConversationPolicy({
        policy_id: "opening-briefing",
        kind: "opening_briefing",
        source_turn_id: latestSourceTurnId,
        enabled: true,
        expected_revision: openingPolicy?.revision ?? 0,
        briefing_spec: {
          kind: "major_issues",
          lookback_seconds: 86_400,
          minimum_severity: "high",
          max_items: 5,
          include_pending_approvals: true,
          include_failed_actions: true,
        },
      });
      await refreshContext();
    } catch (error) {
      setContextError(error instanceof Error ? error.message : String(error));
    } finally {
      finishMutation();
    }
  };

  const removeOpeningBriefing = async (): Promise<void> => {
    if (openingPolicy === null) return;
    if (!beginMutation()) return;
    try {
      await deleteConversationPolicy(openingPolicy.policy_id, openingPolicy.revision);
      await refreshContext();
    } catch (error) {
      setContextError(error instanceof Error ? error.message : String(error));
    } finally {
      finishMutation();
    }
  };

  const withPendingDelete = async (key: string, operation: () => Promise<void>) => {
    if (!claimSettingsDelete(pendingDeleteClaims.current, key)) return;
    setPendingDeletes((current) => new Set(current).add(key));
    setContextError(null);
    try {
      await operation();
    } catch (error) {
      setContextError(error instanceof Error ? error.message : String(error));
    } finally {
      pendingDeleteClaims.current.delete(key);
      setPendingDeletes((current) => {
        const next = new Set(current);
        next.delete(key);
        return next;
      });
    }
  };

  const removeSubscription = async (subscriptionId: string, revision: number): Promise<void> => {
    if (!window.confirm(t("settings.confirmDeleteSubscription"))) return;
    await withPendingDelete(`subscription:${subscriptionId}`, async () => {
      await deleteBriefingSubscription(subscriptionId, revision);
      await refreshContext();
    });
  };

  const removeMemory = async (memoryId: string): Promise<void> => {
    if (!window.confirm(t("settings.confirmDeleteMemory"))) return;
    await withPendingDelete(`memory:${memoryId}`, async () => {
      await deleteUserMemory(memoryId);
      await refreshContext();
    });
  };

  return {
    preferences,
    serverContext,
    contextLoading,
    contextError,
    contextNotice,
    timezoneError,
    briefingHourError,
    answerDetail,
    setAnswerDetail: updateAnswerDetail,
    answerFormat,
    setAnswerFormat: updateAnswerFormat,
    answerPreferencesEnabled,
    setAnswerPreferencesEnabled: updateAnswerPreferencesEnabled,
    timezone,
    setTimezone: updateTimezone,
    shareWithLearner,
    setShareWithLearner: updateShareWithLearner,
    briefingHour,
    setBriefingHour: (value: string) => {
      setBriefingHour(value);
      if (parseBriefingHour(value) !== null) setBriefingHourError(false);
    },
    savingContext,
    contextDirty,
    preferenceDirty,
    pendingResponsePolicy,
    refreshContext,
    discardContextChanges,
    retryResponsePolicy,
    pendingDeletes,
    openingPolicy,
    latestSourceTurnId,
    update,
    updateLocale,
    reset,
    saveContextPreferences,
    addDailyBriefing,
    enableOpeningBriefing,
    removeOpeningBriefing,
    removeSubscription,
    removeMemory,
  };
}

export type SettingsController = ReturnType<typeof useSettingsController>;
