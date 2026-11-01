import { useEffect, useState } from "preact/hooks";

export type HubLocale = "en" | "ko";

let currentLocale: HubLocale = "en";
const listeners = new Set<() => void>();

export function getHubLocale(): HubLocale {
  return currentLocale;
}

export function setHubLocale(next: HubLocale): void {
  if (currentLocale === next) return;
  currentLocale = next;
  for (const listener of listeners) listener();
}

export function useHubLocale(): [HubLocale, (next: HubLocale) => void] {
  const [locale, setLocale] = useState<HubLocale>(currentLocale);
  useEffect(() => {
    const sync = () => setLocale(currentLocale);
    listeners.add(sync);
    return () => {
      listeners.delete(sync);
    };
  }, []);
  return [locale, setHubLocale];
}

export function tr(locale: HubLocale, en: string, ko: string): string {
  return locale === "ko" ? ko : en;
}
