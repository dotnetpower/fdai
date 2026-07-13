import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { PageHeader } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import {
  PREFERENCES_CHANGED_EVENT,
  readConsolePreferences,
  resetConsolePreferences,
  setConsolePreference,
  type ConsolePreferences,
} from "../preferences";

interface Props { readonly client: ReadApiClient }

export function SettingsRoute({ client }: Props) {
  const [preferences, setPreferences] = useState<ConsolePreferences>(readConsolePreferences);

  useEffect(() => {
    const syncPreferences = () => setPreferences(readConsolePreferences());
    window.addEventListener(PREFERENCES_CHANGED_EVENT, syncPreferences);
    return () => window.removeEventListener(PREFERENCES_CHANGED_EVENT, syncPreferences);
  }, []);

  usePublishViewContext(
    () => ({
      routeId: "settings",
      routeLabel: t("route.settings"),
      purpose: "Browser-local console display preferences and read-only runtime information.",
      glossary: composeGlossary([TERMS.userPreference]),
      headline: `${preferences.theme} theme, ${preferences.locale} locale, ${preferences.motion} motion`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "theme", value: preferences.theme, group: "display" },
        { key: "locale", value: preferences.locale, group: "display" },
        { key: "motion", value: preferences.motion, group: "accessibility" },
        { key: "read_api", value: client.readApiBaseUrl, group: "runtime" },
      ],
      records: {},
    }),
    [client, preferences],
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

  const reset = () => {
    const persisted = resetConsolePreferences();
    setLocaleOverride(persisted ? null : "en");
    window.location.reload();
  };

  return (
    <div class="stack settings-route">
      <PageHeader title={t("route.settings")} subtitle={t("settings.subtitle")} />

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
        </div>
      </section>

      <section class="settings-section" aria-labelledby="settings-runtime">
        <h3 id="settings-runtime">{t("settings.runtime")}</h3>
        <div class="settings-list">
          <SettingRow label={t("settings.readApi")} hint={t("settings.readApiHint")}>
            <code class="settings-runtime-value">{client.readApiBaseUrl}</code>
          </SettingRow>
        </div>
      </section>

      <div class="settings-actions">
        <button type="button" class="secondary" onClick={reset}>{t("settings.reset")}</button>
      </div>
    </div>
  );
}

function SettingRow({ label, hint, children }: {
  readonly label: string;
  readonly hint: string;
  readonly children: preact.ComponentChildren;
}) {
  return (
    <div class="settings-row">
      <div><strong>{label}</strong><small class="muted">{hint}</small></div>
      {children}
    </div>
  );
}

function SegmentedControl({ label, value, options, onChange }: {
  readonly label: string;
  readonly value: string;
  readonly options: readonly { readonly value: string; readonly label: string }[];
  readonly onChange: (value: string) => void;
}) {
  return (
    <div class="settings-segmented" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          class={option.value === value ? "is-active" : undefined}
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function setLocaleOverride(locale: ConsolePreferences["locale"] | null): void {
  const url = new URL(window.location.href);
  if (locale === null) url.searchParams.delete("locale");
  else url.searchParams.set("locale", locale);
  window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
}