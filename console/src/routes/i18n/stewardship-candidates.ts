import { getLocale } from "../../i18n";
import en from "./stewardship-candidates.en.json";
import ko from "./stewardship-candidates.ko.json";

const CATALOGS = { en, ko } as const;

export function t(key: string): string {
  let value: unknown = CATALOGS[getLocale()];
  for (const part of key.replace(/^handover\.candidates\./, "").split(".")) {
    if (typeof value !== "object" || value === null) return key;
    value = (value as Record<string, unknown>)[part];
  }
  return typeof value === "string" ? value : key;
}
