import { getLocale } from "../../i18n";
import en from "./dashboard-essential.en.json";
import ko from "./dashboard-essential.ko.json";

/** Translates lazy-loaded dashboard copy with the mandatory English fallback. */
export function tDashboard(key: keyof typeof en, params: Readonly<Record<string, string | number>> = {}): string {
  const template = (getLocale() === "ko" ? ko[key] : en[key]) || en[key];
  return template.replace(/\{(\w+)\}/g, (whole, name: string) => name in params ? String(params[name]) : whole);
}
