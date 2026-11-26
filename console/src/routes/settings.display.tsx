import { ToggleSwitch } from "../components/form-controls";
import { t } from "../i18n";
import type { ConsolePreferences } from "../preferences";
import type { SettingsController } from "./settings.controller";
import {
  SegmentedControl,
  SettingRow,
  SettingsSectionHeader,
} from "./settings.controls";
import { settingsGeneralText } from "./settings-general.i18n";

export function SettingsDisplaySections({
  controller,
}: {
  readonly controller: SettingsController;
}) {
  const { preferences, update, updateLocale } = controller;
  return (
    <>
      <section class="settings-section" aria-labelledby="settings-appearance">
        <SettingsSectionHeader
          id="settings-appearance"
          title={settingsGeneralText("appearance")}
          description={settingsGeneralText("appearanceDescription")}
          scope={settingsGeneralText("browserScope")}
        />
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
            <ToggleSwitch
              label={preferences.motion === "reduced" ? t("settings.reduced") : t("settings.system")}
              checked={preferences.motion === "reduced"}
              onChange={(checked) => update("motion", checked ? "reduced" : "system")}
            />
          </SettingRow>
          <SettingRow
            label={t("settings.showTokenUsage")}
            hint={t("settings.showTokenUsageHint")}
          >
            <ToggleSwitch
              label={preferences.showTokenUsage ? t("settings.enabled") : t("settings.disabled")}
              checked={preferences.showTokenUsage}
              onChange={(checked) => update("showTokenUsage", checked)}
            />
          </SettingRow>
          <SettingRow
            label={t("settings.showModelTrace")}
            hint={t("settings.showModelTraceHint")}
          >
            <ToggleSwitch
              label={preferences.showModelTrace ? t("settings.enabled") : t("settings.disabled")}
              checked={preferences.showModelTrace}
              onChange={(checked) => update("showModelTrace", checked)}
            />
          </SettingRow>
        </div>
      </section>

    </>
  );
}
