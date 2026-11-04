import { useEffect, useState } from "preact/hooks";

export type HubLocale = "en" | "ko";

const LOCALE_STORAGE_KEY = "fdai-lifecycle-hub-locale";

function readInitialLocale(): HubLocale {
  try {
    if (typeof localStorage !== "undefined") {
      const saved = localStorage.getItem(LOCALE_STORAGE_KEY);
      if (saved === "ko" || saved === "en") return saved;
    }
  } catch {
    // Ignore storage access errors in restricted contexts.
  }
  return "en";
}

let currentLocale: HubLocale = readInitialLocale();
const listeners = new Set<() => void>();

export function getHubLocale(): HubLocale {
  return currentLocale;
}

export function setHubLocale(next: HubLocale): void {
  if (currentLocale === next) return;
  currentLocale = next;
  try {
    if (typeof localStorage !== "undefined") {
      localStorage.setItem(LOCALE_STORAGE_KEY, next);
    }
  } catch {
    // Ignore storage write errors.
  }
  if (typeof document !== "undefined") {
    document.documentElement.lang = next;
  }
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

const RELEASE_STATE_KO: Readonly<Record<string, string>> = {
  draft: "초안",
  published: "발행됨",
  recalled: "회수됨",
};

export function releaseStateLabel(state: string, locale: HubLocale = "en"): string {
  if (locale !== "ko") return state;
  return RELEASE_STATE_KO[state] ?? state;
}

const CONNECTION_SOURCE_KO: Readonly<Record<string, string>> = {
  "local-default": "로컬 기본값",
  saved: "저장된 설정",
  environment: "환경 변수",
  deployment: "배포 구성",
};

export function connectionSourceLabel(source: string, locale: HubLocale = "en"): string {
  if (locale !== "ko") return source;
  return CONNECTION_SOURCE_KO[source] ?? source;
}
