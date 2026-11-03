import { useState } from "preact/hooks";
import { Tooltip } from "../components/tooltip";
import { t } from "../i18n";
import { formatConsoleTimestamp } from "../time-format";
import type { UserPreferencePayload } from "../user-context-client";
import type { SettingsController } from "./settings.controller";
import {
  SegmentedControl,
  SettingRow,
  SettingsSectionHeader,
} from "./settings.controls";
import { settingsGeneralText } from "./settings-general.i18n";
import { dailyBriefingTime, parseBriefingHour } from "./settings.model";

export function SettingsContextSections({
  controller,
}: {
  readonly controller: SettingsController;
}) {
  const {
    preferences,
    serverContext,
    contextLoading,
    contextError,
    contextNotice,
    timezoneError,
    briefingHourError,
    answerDetail,
    setAnswerDetail,
    answerFormat,
    setAnswerFormat,
    answerPreferencesEnabled,
    setAnswerPreferencesEnabled,
    timezone,
    setTimezone,
    shareWithLearner,
    setShareWithLearner,
    briefingHour,
    setBriefingHour,
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
    saveContextPreferences,
    addDailyBriefing,
    enableOpeningBriefing,
    removeOpeningBriefing,
    removeSubscription,
    removeMemory,
  } = controller;
  const [historyLimit, setHistoryLimit] = useState(10);
  const contextReady = serverContext !== null;
  const fieldsDisabled = savingContext || contextLoading || !contextReady;
  const history = serverContext?.briefing_runs ?? [];
  const previewHour = parseBriefingHour(briefingHour);
  const formatTimestamp = (value: string): string => Number.isFinite(Date.parse(value))
    ? formatConsoleTimestamp(value) : settingsGeneralText("notAvailable");
  return (
    <>
      <section class="settings-section" aria-labelledby="settings-user-context">
        <SettingsSectionHeader
          id="settings-user-context"
          title={settingsGeneralText("contextTitle")}
          description={settingsGeneralText("contextDescription")}
          scope={settingsGeneralText("accountScope")}
        />
        {contextError ? <div class="state-block state-error" role="alert">
          <p>{contextError}</p>
          {!contextReady ? <p>{settingsGeneralText("contextUnavailable")}</p> : null}
          <button type="button" class="btn secondary" disabled={savingContext || contextLoading}
            onClick={() => void refreshContext()}>{settingsGeneralText("retryContext")}</button>
        </div> : null}
        {contextNotice ? <p role="status">{contextNotice}</p> : null}
        {contextLoading ? <p class="muted small" role="status">{t("settings.contextLoading")}</p> : null}
        <fieldset class="settings-context-fields" disabled={fieldsDisabled}>
        <div class="settings-list">
          <SettingRow label={t("settings.answerDetail")} hint={t("settings.answerDetailHint")}>
            <SegmentedControl
              label={t("settings.answerDetail")}
              value={answerDetail}
              options={[
                { value: "brief", label: t("settings.brief") },
                { value: "standard", label: t("settings.standard") },
                { value: "deep", label: t("settings.deep") },
              ]}
              onChange={(value) => setAnswerDetail(value as UserPreferencePayload["answer_detail"])}
            />
          </SettingRow>
          <SettingRow label={t("settings.answerFormat")} hint={t("settings.answerFormatHint")}>
            <SegmentedControl
              label={t("settings.answerFormat")}
              value={answerFormat}
              options={[
                { value: "prose", label: t("settings.formatProse") },
                { value: "bullets", label: t("settings.formatBullets") },
                { value: "numbered_steps", label: t("settings.formatSteps") },
                { value: "table", label: t("settings.formatTable") },
                { value: "chart", label: t("settings.formatChart") },
                { value: "checklist", label: settingsGeneralText("formatChecklist") },
                { value: "mixed", label: settingsGeneralText("formatMixed") },
              ]}
              onChange={(value) => setAnswerFormat(value as UserPreferencePayload["answer_format"])}
            />
          </SettingRow>
          <SettingRow
            label={t("settings.answerPreferences")}
            hint={t("settings.answerPreferencesHint")}
          >
            <label class="settings-toggle-control">
              <input
                type="checkbox"
                checked={answerPreferencesEnabled}
                onChange={(event) => setAnswerPreferencesEnabled(event.currentTarget.checked)}
              />
              <span aria-hidden="true" />
              <strong>
                {answerPreferencesEnabled ? t("settings.enabled") : t("settings.disabled")}
              </strong>
            </label>
          </SettingRow>
          <SettingRow label={t("settings.timezone")} hint={t("settings.timezoneHint")}>
            <input
              id="settings-timezone"
              class="form-input settings-context-input"
              aria-label={t("settings.timezone")}
              value={timezone}
              placeholder="Asia/Seoul"
              onInput={(event) => setTimezone(event.currentTarget.value)}
              aria-invalid={timezoneError || undefined}
              aria-describedby={timezoneError ? "settings-timezone-error" : undefined}
            />
            {timezoneError ? <span id="settings-timezone-error" class="error-text" role="alert">
              {t("settings.contextTimezoneInvalid")}
            </span> : null}
          </SettingRow>
          <SettingRow
            label={t("settings.learnerAccess")}
            hint={t("settings.learnerAccessHint")}
          >
            <label class="settings-toggle-control">
              <input
                type="checkbox"
                checked={shareWithLearner}
                onChange={(event) => setShareWithLearner(event.currentTarget.checked)}
              />
              <span aria-hidden="true" />
              <strong>{shareWithLearner ? t("settings.optedIn") : t("settings.metadataOnly")}</strong>
            </label>
          </SettingRow>
        </div>
        </fieldset>
        {pendingResponsePolicy ? <div class="state-block" role="status">
          <p>{settingsGeneralText("policyPending")}</p>
          <button type="button" class="btn secondary" disabled={savingContext || contextLoading}
            onClick={() => void retryResponsePolicy()}>{settingsGeneralText("retryPolicy")}</button>
        </div> : null}
        <div class="settings-save-bar">
          <div aria-live="polite">
            <strong>
              {!contextReady
                ? (contextLoading ? settingsGeneralText("contextPending") : settingsGeneralText("contextUnavailable"))
                : savingContext
                ? settingsGeneralText("contextSaving")
                : contextDirty
                  ? settingsGeneralText("contextUnsaved")
                  : settingsGeneralText("contextCurrent")}
            </strong>
            <small>{settingsGeneralText("accountScopeHint")}</small>
          </div>
          <button type="button" class="btn secondary"
            disabled={fieldsDisabled || !preferenceDirty}
            onClick={discardContextChanges}>{settingsGeneralText("discard")}</button>
          <button
            type="button"
            class="btn primary"
            disabled={fieldsDisabled || !preferenceDirty}
            onClick={() => void saveContextPreferences()}
          >
            {savingContext ? settingsGeneralText("contextSaving") : settingsGeneralText("saveContext")}
          </button>
        </div>
      </section>

      <section class="settings-section" aria-labelledby="settings-briefings">
        <SettingsSectionHeader
          id="settings-briefings"
          title={settingsGeneralText("briefingsTitle")}
          description={settingsGeneralText("briefingsDescription")}
          scope={settingsGeneralText("accountScope")}
        />
        <div class="settings-context-list">
          <article>
            <div>
              <strong>{t("settings.openingBriefing")}</strong>
              <small class="muted">
                {t("settings.openingBriefingHint")}
              </small>
            </div>
            {openingPolicy ? (
              <button
                type="button"
                class="secondary"
                disabled={fieldsDisabled}
                onClick={() => void removeOpeningBriefing()}
              >
                {t("settings.disable")}
              </button>
            ) : (
              <Tooltip content={latestSourceTurnId === null ? t("settings.startConversation") : undefined}>
                <button
                  type="button"
                  class="btn"
                  disabled={fieldsDisabled || latestSourceTurnId === null}
                  onClick={() => void enableOpeningBriefing()}
                >
                  {t("settings.enable")}
                </button>
              </Tooltip>
            )}
          </article>
          {latestSourceTurnId === null && !openingPolicy ? (
            <p class="muted small">
              {t("settings.startConversationHint")}
            </p>
          ) : null}
        </div>
        <div class="settings-briefing-create">
          <label>
            <span>{t("settings.dailyHour")}</span>
            <input
              id="settings-briefing-hour"
              class="form-input"
              type="number"
              min="0"
              max="23"
              value={briefingHour}
              onInput={(event) => setBriefingHour(event.currentTarget.value)}
              disabled={fieldsDisabled}
              aria-invalid={briefingHourError || undefined}
              aria-describedby={briefingHourError ? "settings-briefing-hour-error" : undefined}
            />
            {briefingHourError ? <span id="settings-briefing-hour-error" class="error-text" role="alert">
              {t("settings.briefingHourInvalid")}
            </span> : null}
          </label>
          <span class="muted small">{previewHour === null ? timezone.trim() :
            settingsGeneralText("dailyPreview", { time: `${String(previewHour).padStart(2, "0")}:00`, timezone: timezone.trim() })}</span>
          <button type="button" class="btn" disabled={fieldsDisabled} onClick={() => void addDailyBriefing()}>
            {t("settings.addDailyBriefing")}
          </button>
        </div>
        <div class="settings-context-list">
          {(serverContext?.subscriptions ?? []).map((subscription) => (
            <article key={subscription.subscription_id}>
              <div>
                <strong>{subscription.name}</strong>
                {dailyBriefingTime(subscription.cron_expression) ? <span>
                  {settingsGeneralText("dailyPreview", {
                    time: dailyBriefingTime(subscription.cron_expression)!,
                    timezone: subscription.timezone,
                  })}
                </span> : null}
                <small class="muted">{settingsGeneralText("nextRun", { time: formatTimestamp(subscription.next_run_at) })}</small>
                <details><summary>{settingsGeneralText("technicalSchedule")}</summary>
                  <code>{subscription.cron_expression}</code><span> {subscription.timezone}</span>
                </details>
              </div>
              <button
                type="button"
                class="secondary"
                disabled={pendingDeletes.has(`subscription:${subscription.subscription_id}`)}
                aria-label={settingsGeneralText("removeSubscription", { name: subscription.name })}
                onClick={() => void removeSubscription(subscription.subscription_id, subscription.revision)}
              >
                {t("settings.remove")}
              </button>
            </article>
          ))}
          {contextReady && !contextLoading && serverContext.subscriptions.length === 0 ? (
            <p class="muted small">{t("settings.noSubscriptions")}</p>
          ) : null}
        </div>
      </section>

      <section class="settings-section" aria-labelledby="settings-saved-memory">
        <SettingsSectionHeader
          id="settings-saved-memory"
          title={settingsGeneralText("memoryTitle")}
          description={settingsGeneralText("memoryDescription")}
          scope={settingsGeneralText("accountScope")}
        />
        <div class="settings-context-list">
          {(serverContext?.memories ?? []).map((memory) => (
            <article key={memory.memory_id}>
              <div>
                <strong>{memory.category}</strong>
                <span>{memory.body}</span>
                <small class="muted">
                  {memory.expires_at
                    ? t("settings.memorySourceExpires", { source: memory.source_turn_id, expires: memory.expires_at })
                    : t("settings.memorySource", { source: memory.source_turn_id })}
                </small>
              </div>
              <button
                type="button"
                class="secondary"
                disabled={pendingDeletes.has(`memory:${memory.memory_id}`)}
                aria-label={settingsGeneralText("removeMemory", { name: `${memory.category}: ${memory.body.slice(0, 80)}` })}
                onClick={() => void removeMemory(memory.memory_id)}
              >
                {t("settings.remove")}
              </button>
            </article>
          ))}
          {contextReady && !contextLoading && serverContext.memories.length === 0 ? (
            <p class="muted small">{t("settings.noMemories")}</p>
          ) : null}
        </div>
      </section>

      <section class="settings-section" aria-labelledby="settings-briefing-history">
        <SettingsSectionHeader
          id="settings-briefing-history"
          title={settingsGeneralText("recentBriefings")}
          description={settingsGeneralText("recentBriefingsDescription")}
          scope={settingsGeneralText("accountScope")}
        />
        <div class="settings-context-list">
          {history.slice(0, historyLimit).map((run) => (
            <article key={run.run_id}>
              <div>
                <strong>{run.title}</strong>
                <span>{run.body_markdown}</span>
                <small class="muted">
                  {t("settings.briefingRunSummary", {
                    status: run.status,
                    count: run.item_count,
                    evidence: run.evidence_refs.length,
                  })}
                </small>
              </div>
            </article>
          ))}
          {contextReady && !contextLoading && history.length === 0 ? (
            <p class="muted small">{t("settings.noBriefingRuns")}</p>
          ) : null}
        </div>
        {history.length > 0 ? <div class="settings-actions">
          <span role="status">{settingsGeneralText("loadedHistory", { shown: Math.min(historyLimit, history.length), total: history.length })}</span>
          {historyLimit < history.length ? <button type="button" class="btn secondary"
            onClick={() => setHistoryLimit((limit) => limit + 10)}>{settingsGeneralText("showMore")}</button> : null}
        </div> : null}
      </section>
    </>
  );
}
