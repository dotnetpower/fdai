import { getLocale } from "../i18n";
import en from "./i18n/settings-integrations.en.json";
import ko from "./i18n/settings-integrations.ko.json";

type SettingsIntegrationsMessageKey = keyof typeof en;

export function settingsIntegrationsText(
  key: SettingsIntegrationsMessageKey,
  params?: Readonly<Record<string, string | number>>,
): string {
  const template = (getLocale() === "ko" ? ko[key] : undefined) || en[key];
  if (params === undefined) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole,
  );
}
