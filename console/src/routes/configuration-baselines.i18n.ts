import { getLocale } from "../i18n";
import en from "./i18n/configuration-baselines.en.json";
import ko from "./i18n/configuration-baselines.ko.json";

type MessageKey = keyof typeof en;

export function configurationBaselinesText(key: MessageKey): string {
  return (getLocale() === "ko" ? ko[key] : undefined) || en[key];
}
