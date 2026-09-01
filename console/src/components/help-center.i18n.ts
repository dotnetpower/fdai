import { getLocale } from "../i18n";
import en from "./i18n/help-center.en.json";
import ko from "./i18n/help-center.ko.json";

type HelpCenterMessageKey = keyof typeof en;

export function helpCenterText(
  key: HelpCenterMessageKey,
  params?: Readonly<Record<string, string | number>>,
): string {
  const template = (getLocale() === "ko" ? ko[key] : undefined) || en[key];
  if (params === undefined) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole
  );
}
