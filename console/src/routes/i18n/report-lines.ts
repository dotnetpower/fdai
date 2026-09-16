import { getLocale } from "../../i18n";
import en from "./report-lines.en.json";
import ko from "./report-lines.ko.json";

const CATALOGS = { en, ko } as const;

export function reportLineText(
  key: keyof typeof en,
  params?: Record<string, string | number>,
): string {
  const template = CATALOGS[getLocale()][key] ?? en[key];
  if (params === undefined) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole
  );
}
