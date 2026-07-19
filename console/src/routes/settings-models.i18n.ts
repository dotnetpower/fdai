import { getLocale } from "../i18n";
import en from "./i18n/settings-models.en.json";
import ko from "./i18n/settings-models.ko.json";

type SettingsModelsMessageKey = keyof typeof en;

export function modelText(key: SettingsModelsMessageKey): string {
  return (getLocale() === "ko" ? ko[key] : undefined) || en[key];
}
