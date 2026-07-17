export type ConsoleTheme = "light" | "dark";
export type ConsoleLocale = "en" | "ko";
export type MotionPreference = "system" | "reduced";

export interface ConsolePreferences {
  readonly theme: ConsoleTheme;
  readonly locale: ConsoleLocale;
  readonly motion: MotionPreference;
  /** Show per-reply token usage on the chat reply badge. */
  readonly showTokenUsage: boolean;
}

type StorageReader = Pick<Storage, "getItem">;

export const PREFERENCES_CHANGED_EVENT = "fdai:console:preferences-changed";

const STORAGE_KEYS = {
  theme: "fdai:console:theme",
  locale: "fdai:console:locale",
  motion: "fdai:console:motion",
  showTokenUsage: "fdai:console:show-token-usage",
} as const;

const DEFAULT_PREFERENCES: ConsolePreferences = {
  theme: "light",
  locale: "en",
  motion: "system",
  showTokenUsage: true,
};

let sessionPreferences: Partial<ConsolePreferences> = {};

export function readConsolePreferences(
  search = typeof window === "undefined" ? "" : window.location.search,
  storage: StorageReader | null = browserStorage(),
): ConsolePreferences {
  const queryLocale = new URLSearchParams(search).get("locale")?.toLowerCase();
  const storedTheme = safeGet(storage, STORAGE_KEYS.theme);
  const storedLocale = safeGet(storage, STORAGE_KEYS.locale);
  const storedMotion = safeGet(storage, STORAGE_KEYS.motion);
  const storedShowTokenUsage = safeGet(storage, STORAGE_KEYS.showTokenUsage);

  return {
    theme: sessionPreferences.theme
      ?? (storedTheme === "dark" || storedTheme === "light"
        ? storedTheme
        : DEFAULT_PREFERENCES.theme),
    locale: queryLocale?.startsWith("ko")
      ? "ko"
      : queryLocale?.startsWith("en")
        ? "en"
        : sessionPreferences.locale
          ?? (storedLocale === "ko" || storedLocale === "en"
            ? storedLocale
            : DEFAULT_PREFERENCES.locale),
    motion: sessionPreferences.motion
      ?? (storedMotion === "reduced" || storedMotion === "system"
        ? storedMotion
        : DEFAULT_PREFERENCES.motion),
    showTokenUsage: sessionPreferences.showTokenUsage
      ?? (storedShowTokenUsage === "false"
        ? false
        : storedShowTokenUsage === "true"
          ? true
          : DEFAULT_PREFERENCES.showTokenUsage),
  };
}

export function setConsolePreference<Key extends keyof ConsolePreferences>(
  key: Key,
  value: ConsolePreferences[Key],
): boolean {
  sessionPreferences = { ...sessionPreferences, [key]: value };
  if (typeof window === "undefined") return false;
  let persisted = true;
  try {
    window.localStorage.setItem(STORAGE_KEYS[key], String(value));
  } catch {
    persisted = false;
    // The in-memory preference still applies for this browser session.
  }
  applyConsolePreferences(readConsolePreferences());
  window.dispatchEvent(new Event(PREFERENCES_CHANGED_EVENT));
  return persisted;
}

export function resetConsolePreferences(): boolean {
  sessionPreferences = { ...DEFAULT_PREFERENCES };
  if (typeof window === "undefined") return false;
  let persisted = true;
  try {
    Object.values(STORAGE_KEYS).forEach((key) => window.localStorage.removeItem(key));
  } catch {
    persisted = false;
    // Session defaults override storage that cannot be cleared.
  }
  applyConsolePreferences(readConsolePreferences());
  window.dispatchEvent(new Event(PREFERENCES_CHANGED_EVENT));
  return persisted;
}

export function applyConsolePreferences(preferences: ConsolePreferences): void {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-theme", preferences.theme);
  document.documentElement.setAttribute("data-motion", preferences.motion);
  document.documentElement.lang = preferences.locale;
}

export function isPreferenceStorageKey(key: string | null): boolean {
  return key !== null && Object.values(STORAGE_KEYS).includes(key as never);
}

export function acceptStoredConsolePreference(key: string | null): boolean {
  const preferenceKey = Object.entries(STORAGE_KEYS).find(([, storageKey]) => storageKey === key)?.[0];
  if (preferenceKey === undefined) return false;
  delete sessionPreferences[preferenceKey as keyof ConsolePreferences];
  return true;
}

function browserStorage(): StorageReader | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function safeGet(storage: StorageReader | null, key: string): string | null {
  if (storage === null) return null;
  try {
    return storage.getItem(key);
  } catch {
    return null;
  }
}
