import type { OperatorApiClient } from "../api";
import { PageHeader } from "../components/ui";
import { useSettingsDirtyState } from "../components/settings-dirty-state";
import { t } from "../i18n";
import { SettingsContextSections } from "./settings.context";
import { useSettingsController } from "./settings.controller";
import { SettingsSectionHeader } from "./settings.controls";
import { SettingsDisplaySections } from "./settings.display";
import { settingsGeneralText } from "./settings-general.i18n";

export {
  SegmentedControl,
  SettingRow,
  SettingsSectionHeader,
} from "./settings.controls";
export {
  buildResponseDefaultsPolicy,
  claimSettingsDelete,
  claimSettingsMutation,
  contextPreferencesAreDirty,
  contextWithSavedPreference,
  defaultTimezone,
  isValidTimezone,
  parseBriefingHour,
  releaseSettingsMutation,
  responseDefaultsPolicyForSave,
  settingsDraftIsCurrent,
} from "./settings.model";

interface Props { readonly client: OperatorApiClient }

export function SettingsGeneralRoute({ client }: Props) {
  const controller = useSettingsController(client);
  useSettingsDirtyState("settings-general-context", controller.contextDirty);
  return (
    <div class="stack settings-route">
      <PageHeader title={t("route.settingsGeneral")} subtitle={settingsGeneralText("subtitle")} />
      <nav class="cs-workspace-tabs" aria-label={t("route.settingsGeneral")}>
        <button type="button" class="cs-workspace-tab" onClick={() => document.getElementById("settings-appearance")?.scrollIntoView({ block: "start" })}>{settingsGeneralText("appearance")}</button>
        <button type="button" class="cs-workspace-tab" onClick={() => document.getElementById("settings-user-context")?.scrollIntoView({ block: "start" })}>{settingsGeneralText("contextTitle")}</button>
        <button type="button" class="cs-workspace-tab" onClick={() => document.getElementById("settings-briefings")?.scrollIntoView({ block: "start" })}>{settingsGeneralText("briefingsTitle")}</button>
        <button type="button" class="cs-workspace-tab" onClick={() => document.getElementById("settings-saved-memory")?.scrollIntoView({ block: "start" })}>{settingsGeneralText("memoryTitle")}</button>
        <button type="button" class="cs-workspace-tab" onClick={() => document.getElementById("settings-reset")?.scrollIntoView({ block: "start" })}>{settingsGeneralText("resetTitle")}</button>
      </nav>
      <SettingsDisplaySections controller={controller} />
      <SettingsContextSections controller={controller} />
      <section class="settings-section settings-reset-section" aria-labelledby="settings-reset">
        <SettingsSectionHeader
          id="settings-reset"
          title={settingsGeneralText("resetTitle")}
          description={settingsGeneralText("resetDescription")}
        />
        <div class="settings-reset-action">
          <button
            type="button"
            class="secondary"
            disabled={controller.savingContext || controller.contextLoading || controller.serverContext === null}
            onClick={() => void controller.reset()}
          >
            {settingsGeneralText("reset")}
          </button>
        </div>
      </section>
    </div>
  );
}
