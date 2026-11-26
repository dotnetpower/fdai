import { getLocale } from "../../i18n";
import en from "./cost-governance.en.json";
import ko from "./cost-governance.ko.json";

const CATALOGS = { en, ko } as const;

function lookup(catalog: unknown, key: string): string | undefined {
  let value: unknown = catalog;
  for (const part of key.replace(/^costGovernance\./, "").split(".")) {
    if (typeof value !== "object" || value === null) return undefined;
    value = (value as Record<string, unknown>)[part];
  }
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

export function t(key: string, params: Readonly<Record<string, string | number>> = {}): string {
  const template = lookup(CATALOGS[getLocale()], key) ?? lookup(en, key);
  if (template === undefined) return key;
  return template.replace(/\{(\w+)\}/g, (match, name: string) => {
    const replacement = params[name];
    return replacement === undefined ? match : String(replacement);
  });
}
