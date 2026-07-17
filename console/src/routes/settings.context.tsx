import { Tooltip } from "../components/tooltip";
import { t } from "../i18n";
import type { UserPreferencePayload } from "../user-context-client";
import type { SettingsController } from "./settings.controller";
import { SegmentedControl, SettingRow } from "./settings.controls";

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
  return (
    <>
      <section class="settings-section" aria-labelledby="settings-user-context">
        <h3 id="settings-user-context">{t("settings.contextTitle")}</h3>
        <p class="muted small">
          {t("settings.contextDescription")}
        </p>
        {contextError ? <p class="error-text">{contextError}</p> : null}
        {contextLoading ? <p class="muted small" role="status">{t("settings.contextLoading")}</p> : null}
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
              class="form-input settings-context-input"
              value={timezone}
              placeholder="Asia/Seoul"
              onInput={(event) => setTimezone(event.currentTarget.value)}
            />
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
        <div class="settings-actions">
          <button type="button" class="btn" disabled={savingContext} onClick={() => void saveContextPreferences()}>
            {t("settings.saveContext")}
          </button>
        </div>
      </section>

      <section class="settings-section" aria-labelledby="settings-briefings">
        <h3 id="settings-briefings">{t("settings.briefingsTitle")}</h3>
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
                disabled={savingContext}
                onClick={() => void removeOpeningBriefing()}
              >
                {t("settings.disable")}
              </button>
            ) : (
              <Tooltip content={latestSourceTurnId === null ? t("settings.startConversation") : undefined}>
                <button
                  type="button"
                  class="btn"
                  disabled={savingContext || latestSourceTurnId === null}
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
              class="form-input"
              type="number"
              min="0"
              max="23"
              value={briefingHour}
              onInput={(event) => setBriefingHour(event.currentTarget.value)}
            />
          </label>
          <span class="muted small">{timezone}</span>
          <button type="button" class="btn" disabled={savingContext} onClick={() => void addDailyBriefing()}>
            {t("settings.addDailyBriefing")}
          </button>
        </div>
        <div class="settings-context-list">
          {(serverContext?.subscriptions ?? []).map((subscription) => (
            <article key={subscription.subscription_id}>
              <div>
                <strong>{subscription.name}</strong>
                <small class="muted">
                  {t("settings.subscriptionSummary", {
                    cron: subscription.cron_expression,
                    timezone: subscription.timezone,
                    next: subscription.next_run_at,
                  })}
                </small>
              </div>
              <button
                type="button"
                class="secondary"
                disabled={pendingDeletes.has(`subscription:${subscription.subscription_id}`)}
                onClick={() => void removeSubscription(subscription.subscription_id, subscription.revision)}
              >
                {t("settings.remove")}
              </button>
            </article>
          ))}
          {!contextLoading && (serverContext?.subscriptions.length ?? 0) === 0 ? (
            <p class="muted small">{t("settings.noSubscriptions")}</p>
          ) : null}
        </div>
      </section>

      <section class="settings-section" aria-labelledby="settings-saved-memory">
        <h3 id="settings-saved-memory">{t("settings.memoryTitle")}</h3>
        <p class="muted small">
          {t("settings.memoryDescription")}
        </p>
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
                onClick={() => void removeMemory(memory.memory_id)}
              >
                {t("settings.remove")}
              </button>
            </article>
          ))}
          {!contextLoading && (serverContext?.memories.length ?? 0) === 0 ? (
            <p class="muted small">{t("settings.noMemories")}</p>
          ) : null}
        </div>
      </section>

      <section class="settings-section" aria-labelledby="settings-briefing-history">
        <h3 id="settings-briefing-history">{t("settings.recentBriefings")}</h3>
        <div class="settings-context-list">
          {(serverContext?.briefing_runs ?? []).slice(0, 10).map((run) => (
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
          {!contextLoading && (serverContext?.briefing_runs.length ?? 0) === 0 ? (
            <p class="muted small">{t("settings.noBriefingRuns")}</p>
          ) : null}
        </div>
      </section>
    </>
  );
}
