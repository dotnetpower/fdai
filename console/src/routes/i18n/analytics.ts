import { getLocale, t as mainT } from "../../i18n";
import en from "./analytics.en.json";
import ko from "./analytics.ko.json";

type Catalog = Record<string, unknown>;

const CATALOGS: Record<"en" | "ko", Catalog> = { en, ko };

function lookup(catalog: Catalog, key: string): string | undefined {
  let cursor: unknown = catalog;
  for (const part of key.replace(/^analytics\./, "").split(".")) {
    if (typeof cursor !== "object" || cursor === null) return undefined;
    cursor = (cursor as Record<string, unknown>)[part];
  }
  return typeof cursor === "string" && cursor.length > 0 ? cursor : undefined;
}

export function t(key: string, params?: Record<string, string | number>): string {
  const template = lookup(CATALOGS[getLocale()], key) ?? lookup(en, key);
  if (template === undefined) return mainT(key, params);
  if (params === undefined) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole,
  );
}
