import en from "./messages.en.json";
import ko from "./messages.ko.json";
import type { Locale } from "../model";

export type MessageKey = keyof typeof en;
const korean: Partial<Record<MessageKey, string>> = ko;

/** English is canonical and the fallback for missing or empty translations. */
export function t(key: MessageKey, locale: Locale = "en"): string {
  return (locale === "ko" ? korean[key] : undefined) || en[key];
}
