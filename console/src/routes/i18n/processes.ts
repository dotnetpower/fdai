import { getLocale, t as mainT } from "../../i18n";
import en from "./processes.en.json";
import ko from "./processes.ko.json";

const CATALOGS: Record<"en" | "ko", Record<string, unknown>> = { en, ko };

export function t(key: string, params?: Record<string, string | number>): string {
  const template = lookup(CATALOGS[getLocale()], key) ?? lookup(en, key);
  if (template === undefined) return mainT(key, params);
  if (params === undefined) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole,
  );
}

function lookup(catalog: Record<string, unknown>, key: string): string | undefined {
  let cursor: unknown = catalog;
  for (const part of key.replace(/^processesView\./, "").split(".")) {
    if (typeof cursor !== "object" || cursor === null) return undefined;
    cursor = (cursor as Record<string, unknown>)[part];
  }
  return typeof cursor === "string" && cursor.length > 0 ? cursor : undefined;
}
