import { getLocale } from "../../i18n";
import en from "./cost-governance.en.json";
import ko from "./cost-governance.ko.json";

const CATALOGS = { en, ko } as const;

export function t(key: string, params: Readonly<Record<string, string | number>> = {}): string {
  let value: unknown = CATALOGS[getLocale()];
  for (const part of key.replace(/^costGovernance\./, "").split(".")) {
    if (typeof value !== "object" || value === null) return key;
    value = (value as Record<string, unknown>)[part];
  }
  if (typeof value !== "string") return key;
  return value.replace(/\{(\w+)\}/g, (match, name: string) => {
    const replacement = params[name];
    return replacement === undefined ? match : String(replacement);
  });
}
