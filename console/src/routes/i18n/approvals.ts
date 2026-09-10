import { getLocale, t as mainT } from "../../i18n";
import en from "./approvals.en.json";
import ko from "./approvals.ko.json";

const CATALOGS = { en, ko } as const;

function routeTemplate(key: string): string | undefined {
  const catalog = CATALOGS[getLocale()];
  const name = key.replace(/^approvals\./, "") as keyof typeof en;
  return catalog[name] ?? en[name];
}

export function t(key: string, params?: Record<string, string | number>): string {
  const template = routeTemplate(key) ?? mainT(key, params);
  if (params === undefined) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole,
  );
}
