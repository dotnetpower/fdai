import { getLocale } from "../../i18n";
import en from "./finding-notifications.en.json";
import ko from "./finding-notifications.ko.json";

export function findingNotificationText(key: keyof typeof en): string {
  return (getLocale() === "ko" ? ko[key] : en[key]) || en[key];
}
