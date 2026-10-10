import { getLocale } from "../../i18n";
import en from "./code-security.en.json";
import ko from "./code-security.ko.json";

const CATALOGS = { en, ko } as const;

export function t(
  key: string,
  params: Readonly<Record<string, string | number>> = {},
): string {
  let value: unknown = CATALOGS[getLocale()];
  for (const part of key.replace(/^codeSecurity\./, "").split(".")) {
    if (typeof value !== "object" || value === null) return key;
    value = (value as Record<string, unknown>)[part];
  }
  if (typeof value !== "string") return key;
  return value.replace(/\{([A-Za-z0-9_]+)\}/g, (match, name: string) =>
    Object.hasOwn(params, name) ? String(params[name]) : match);
}
