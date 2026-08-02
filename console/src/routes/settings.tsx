import type { OperatorApiClient } from "../api";
import { PageHeader } from "../components/ui";
import { t } from "../i18n";
import { SettingsContextSections } from "./settings.context";
import { useSettingsController } from "./settings.controller";
import { SettingsDisplaySections } from "./settings.display";

export { SegmentedControl, SettingRow } from "./settings.controls";
export {
  buildResponseDefaultsPolicy,
  claimSettingsDelete,
  claimSettingsMutation,
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
      <PageHeader title={t("route.settingsGeneral")} subtitle={t("settings.subtitle")} />
      <SettingsDisplaySections controller={controller} />
      <SettingsContextSections controller={controller} />
      <div class="settings-actions">
        <button
          type="button"
          class="secondary"
          disabled={controller.savingContext}
          onClick={() => void controller.reset()}
        >
          {t("settings.reset")}
        </button>
      </div>
    </div>
  );
}
