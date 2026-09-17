import { getLocale } from "../../i18n";
import en from "./aks-commerce.en.json";
import ko from "./aks-commerce.ko.json";

const CATALOGS = { en, ko } as const;

export function t(key: string): string {
  let value: unknown = CATALOGS[getLocale()];
  for (const part of key.replace(/^aksCommerce\./, "").split(".")) {
    if (typeof value !== "object" || value === null) return key;
    value = (value as Record<string, unknown>)[part];
  }
  return typeof value === "string" ? value : key;
}
