import { getLocale, t as mainT, tForLocale as mainTForLocale } from "../../i18n";
import en from "./assurance-twin.en.json";
import ko from "./assurance-twin.ko.json";

type Catalog = Record<string, unknown>;
type Locale = "en" | "ko";

const CATALOGS: Record<Locale, Catalog> = { en, ko };
const PREFIX = "assuranceTwin.";

function lookup(catalog: Catalog, key: string): string | undefined {
  let cursor: unknown = catalog;
  for (const part of key.slice(PREFIX.length).split(".")) {
    if (typeof cursor !== "object" || cursor === null) return undefined;
    cursor = (cursor as Record<string, unknown>)[part];
  }
  return typeof cursor === "string" && cursor.length > 0 ? cursor : undefined;
}

/** Resolve an Assurance Twin key in one locale with English fallback; other keys use the app catalog. */
export function tForLocale(locale: Locale, key: string): string {
  if (!key.startsWith(PREFIX)) return mainTForLocale(locale, key);
  return lookup(CATALOGS[locale], key) ?? lookup(en, key) ?? key;
}

export function t(key: string): string {
  return key.startsWith(PREFIX) ? tForLocale(getLocale(), key) : mainT(key);
}
