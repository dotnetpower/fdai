import { getLocale } from "../i18n";
import en from "./i18n/settings-general.en.json";
import ko from "./i18n/settings-general.ko.json";

type SettingsGeneralMessageKey = keyof typeof en;

export function settingsGeneralText(
  key: SettingsGeneralMessageKey,
  values: Readonly<Record<string, string | number>> = {},
): string {
  const message = (getLocale() === "ko" ? ko[key] : undefined) || en[key];
  return message.replace(/\{(\w+)\}/g, (token, name: string) => String(values[name] ?? token));
}
