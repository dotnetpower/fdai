import { getLocale } from "../i18n";
import en from "./i18n/settings-diagnostics.en.json";
import ko from "./i18n/settings-diagnostics.ko.json";

export function settingsDiagnosticsText(
  key: keyof typeof en,
  params?: Readonly<Record<string, string | number>>,
): string {
  const template = (getLocale() === "ko" ? ko[key] : undefined) || en[key];
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    params && name in params ? String(params[name]) : whole);
}
