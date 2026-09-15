/** Presentation-only catalog shared by the lazy route and its navigation label. */
import { getLocale } from "../../i18n";
import en from "./alert-quality.en.json";
import ko from "./alert-quality.ko.json";

export type AlertQualityMessage = keyof typeof en;

/** English is mandatory fallback; canonical machine records are never translated. */
export function alertQualityText(
  key: AlertQualityMessage,
  params?: Readonly<Record<string, string | number>>,
): string {
  const template = (getLocale() === "ko" ? ko[key] : undefined) || en[key];
  return params === undefined ? template : template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    Object.hasOwn(params, name) ? String(params[name]) : whole);
}
