import { getLocale } from "../i18n";
import en from "./i18n/skills-refresh.en.json";
import ko from "./i18n/skills-refresh.ko.json";

type MessageKey = keyof typeof en;

export function skillRefreshText(key: MessageKey): string {
  return (getLocale() === "ko" ? ko[key] : undefined) || en[key];
}
