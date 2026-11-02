import { getLocale, t as mainT } from "../../i18n";
import en from "./approvals.en.json";
import ko from "./approvals.ko.json";

const CATALOGS = { en, ko } as const;

function lookupCatalogValue(
  catalog: Record<string, unknown>,
  name: string,
): string | undefined {
  const direct = catalog[name];
  if (typeof direct === "string") return direct;
  const dot = name.indexOf(".");
  if (dot <= 0) return undefined;
  const group = catalog[name.slice(0, dot)];
  if (typeof group === "object" && group !== null) {
    const nested = (group as Record<string, unknown>)[name.slice(dot + 1)];
    if (typeof nested === "string") return nested;
  }
  return undefined;
}

function routeTemplate(key: string): string | undefined {
  const catalog = CATALOGS[getLocale()] as Record<string, unknown>;
  const fallback = en as Record<string, unknown>;
  const name = key.replace(/^approvals\./, "");
  return lookupCatalogValue(catalog, name) ?? lookupCatalogValue(fallback, name);
}

export function t(key: string, params?: Record<string, string | number>): string {
  const template = routeTemplate(key) ?? mainT(key, params);
  if (params === undefined) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole,
  );
}
