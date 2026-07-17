import { t } from "../i18n";
import type { ConsolePreferences } from "../preferences";
import type { SettingsController } from "./settings.controller";
import { SegmentedControl, SettingRow } from "./settings.controls";

export function SettingsDisplaySections({
  controller,
}: {
  readonly controller: SettingsController;
}) {
  const { preferences, update, updateLocale } = controller;
  return (
    <>
      <section class="settings-section" aria-labelledby="settings-appearance">
        <h3 id="settings-appearance">{t("settings.appearance")}</h3>
        <div class="settings-list">
          <SettingRow label={t("settings.theme")} hint={t("settings.themeHint")}>
            <SegmentedControl
              label={t("settings.theme")}
              value={preferences.theme}
              options={[
                { value: "light", label: t("settings.light") },
                { value: "dark", label: t("settings.dark") },
              ]}
              onChange={(value) => update("theme", value as ConsolePreferences["theme"])}
            />
          </SettingRow>
          <SettingRow label={t("settings.language")} hint={t("settings.languageHint")}>
            <SegmentedControl
              label={t("settings.language")}
              value={preferences.locale}
              options={[
                { value: "en", label: "English" },
                { value: "ko", label: t("settings.korean") },
              ]}
              onChange={(value) => updateLocale(value as ConsolePreferences["locale"])}
            />
          </SettingRow>
          <SettingRow label={t("settings.motion")} hint={t("settings.motionHint")}>
            <label class="settings-toggle-control">
              <input
                type="checkbox"
                checked={preferences.motion === "reduced"}
                onChange={(event) => update("motion", event.currentTarget.checked ? "reduced" : "system")}
              />
              <span aria-hidden="true" />
              <strong>{preferences.motion === "reduced" ? t("settings.reduced") : t("settings.system")}</strong>
            </label>
          </SettingRow>
          <SettingRow
            label={t("settings.showTokenUsage")}
            hint={t("settings.showTokenUsageHint")}
          >
            <label class="settings-toggle-control">
              <input
                type="checkbox"
                checked={preferences.showTokenUsage}
                onChange={(event) => update("showTokenUsage", event.currentTarget.checked)}
              />
              <span aria-hidden="true" />
              <strong>
                {preferences.showTokenUsage ? t("settings.enabled") : t("settings.disabled")}
              </strong>
            </label>
          </SettingRow>
        </div>
      </section>

    </>
  );
}
