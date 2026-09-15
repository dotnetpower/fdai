import { getLocale } from "../i18n";
import en from "./i18n/rca.en.json";
import ko from "./i18n/rca.ko.json";

export type RcaTextKey = keyof typeof en;

export function rcaText(
  key: RcaTextKey,
  params: Readonly<Record<string, string | number>> = {},
): string {
  const template = (getLocale() === "ko" ? ko[key] : en[key]) || en[key];
  return template.replace(
    /\{(\w+)\}/g,
    (whole, name: string) => name in params ? String(params[name]) : whole,
  );
}
