import { getLocale } from "../i18n";
import en from "./i18n/run-record.en.json";
import ko from "./i18n/run-record.ko.json";

export type RunRecordTextKey = keyof typeof en;

/**
 * Run-record copy ships with the lazy Command Deck chunk instead of the entry catalog.
 * Like `t`, `params` substitute `{name}` placeholders and an unmatched placeholder stays verbatim.
 */
export function runRecordText(key: RunRecordTextKey, params?: Record<string, string | number>): string {
  const template = (getLocale() === "ko" ? ko[key] : undefined) || en[key];
  if (params === undefined) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole,
  );
}
