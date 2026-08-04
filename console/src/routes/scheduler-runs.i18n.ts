import { getLocale } from "../i18n";
import en from "./i18n/scheduler-runs.en.json";
import ko from "./i18n/scheduler-runs.ko.json";

type SchedulerRunsMessageKey = keyof typeof en;

export function schedulerRunsNumber(value: number): string {
  return value.toLocaleString(getLocale() === "ko" ? "ko-KR" : "en-US");
}

export function schedulerRunsText(
  key: SchedulerRunsMessageKey,
  params?: Readonly<Record<string, string | number>>,
): string {
  const template = (getLocale() === "ko" ? ko[key] : undefined) || en[key];
  if (params === undefined) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole,
  );
}
