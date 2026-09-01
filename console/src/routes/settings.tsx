import type { OperatorApiClient } from "../api";
import { PageHeader } from "../components/ui";
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
  return (
    <div class="stack settings-route">
      <PageHeader title={t("route.settingsGeneral")} subtitle={settingsGeneralText("subtitle")} />
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
            disabled={controller.savingContext}
            onClick={() => void controller.reset()}
          >
            {settingsGeneralText("reset")}
          </button>
        </div>
      </section>
    </div>
  );
}
