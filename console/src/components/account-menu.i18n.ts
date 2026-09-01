import { getLocale } from "../i18n";
import en from "./i18n/account-menu.en.json";
import ko from "./i18n/account-menu.ko.json";

type AccountMenuMessageKey = keyof typeof en;

export function accountMenuText(
  key: AccountMenuMessageKey,
  params?: Readonly<Record<string, string>>,
): string {
  const template = (getLocale() === "ko" ? ko[key] : undefined) || en[key];
  if (params === undefined) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) => params[name] ?? whole);
}
