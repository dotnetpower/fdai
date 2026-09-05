import { getLocale } from "../../i18n";
import en from "./dashboard-v2.en.json";
import ko from "./dashboard-v2.ko.json";

export type DashboardTextKey = keyof typeof en;

export function t(key: DashboardTextKey, params: Readonly<Record<string, string | number>> = {}): string {
  const template = (getLocale() === "ko" ? ko[key] : en[key]) || en[key];
  return template.replace(/\{(\w+)\}/g, (whole, name: string) => name in params ? String(params[name]) : whole);
}

export function number(value: number): string {
  return value.toLocaleString(getLocale() === "ko" ? "ko-KR" : "en-US");
}

export function date(value: string | null): string {
  return value === null ? t("missing") : new Date(value).toLocaleString(getLocale() === "ko" ? "ko-KR" : "en-US");
}
