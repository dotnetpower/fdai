import { getLocale } from "../../i18n";
import en from "./browser-notifications.en.json";
import ko from "./browser-notifications.ko.json";

export type BrowserNotificationTextKey = keyof typeof en;

export function browserNotificationText(key: BrowserNotificationTextKey): string {
  return (getLocale() === "ko" ? ko[key] : en[key]) || en[key];
}
