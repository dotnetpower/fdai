import type { ComponentChildren } from "preact";
import { useEffect, useState } from "preact/hooks";
import type { AuthContext } from "../auth";
import { t } from "../i18n";
import {
  acceptStoredConsolePreference,
  applyConsolePreferences,
  isPreferenceStorageKey,
  PREFERENCES_CHANGED_EVENT,
  readConsolePreferences,
  setConsolePreference,
  type ConsolePreferences,
} from "../preferences";
import { LeftRail } from "./left-rail";

interface ShellProps {
  readonly activePanelId: string;
  readonly auth: AuthContext;
  readonly children: ComponentChildren;
}

export function Shell({ activePanelId, auth, children }: ShellProps) {
  const [preferences, setPreferences] = useState<ConsolePreferences>(readConsolePreferences);

  useEffect(() => {
    applyConsolePreferences(preferences);
  }, [preferences]);

  useEffect(() => {
    const syncPreferences = () => setPreferences(readConsolePreferences());
    const syncStoredPreferences = (event: StorageEvent) => {
      if (!isPreferenceStorageKey(event.key)) return;
      acceptStoredConsolePreference(event.key);
      if (event.key === "fdai:console:locale") {
        window.location.reload();
        return;
      }
      syncPreferences();
    };
    window.addEventListener(PREFERENCES_CHANGED_EVENT, syncPreferences);
    window.addEventListener("storage", syncStoredPreferences);
    return () => {
      window.removeEventListener(PREFERENCES_CHANGED_EVENT, syncPreferences);
      window.removeEventListener("storage", syncStoredPreferences);
    };
  }, []);

  const toggleTheme = () => {
    setConsolePreference("theme", preferences.theme === "dark" ? "light" : "dark");
  };

  return (
    <div class="shell">
      <header class="topbar">
        <h1 class="topbar-title">FDAI Console</h1>
        <div class="principal">
          <a
            href="#/settings"
            class={`theme-toggle ${activePanelId === "settings" ? "is-active" : ""}`}
            aria-label={t("settings.open")}
            title={t("route.settings")}
          >
            <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
              <circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="1.8" />
              <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3A1.7 1.7 0 0 0 10 3V2.8h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </a>
          <button
            type="button"
            class="theme-toggle"
            onClick={toggleTheme}
            aria-label={preferences.theme === "dark" ? t("settings.switchLight") : t("settings.switchDark")}
            title={preferences.theme === "dark" ? t("settings.switchLight") : t("settings.switchDark")}
          >
            {preferences.theme === "dark" ? (
              // sun icon (indicates the target: click to go light)
              <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
                <circle cx="8" cy="8" r="3" fill="currentColor" />
                <g stroke="currentColor" stroke-width="1.4" stroke-linecap="round">
                  <line x1="8" y1="1.5" x2="8" y2="3.5" />
                  <line x1="8" y1="12.5" x2="8" y2="14.5" />
                  <line x1="1.5" y1="8" x2="3.5" y2="8" />
                  <line x1="12.5" y1="8" x2="14.5" y2="8" />
                  <line x1="3.2" y1="3.2" x2="4.6" y2="4.6" />
                  <line x1="11.4" y1="11.4" x2="12.8" y2="12.8" />
                  <line x1="3.2" y1="12.8" x2="4.6" y2="11.4" />
                  <line x1="11.4" y1="4.6" x2="12.8" y2="3.2" />
                </g>
              </svg>
            ) : (
              // moon icon (indicates the target: click to go dark)
              <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
                <path
                  d="M13 10.2 A5.5 5.5 0 1 1 5.8 3 A4.5 4.5 0 0 0 13 10.2 Z"
                  fill="currentColor"
                />
              </svg>
            )}
          </button>
          {auth.devMode ? (
            <span class="badge">dev mode</span>
          ) : auth.account ? (
            <>
              <span>{auth.account.username}</span>
              <button
                type="button"
                onClick={() => {
                  void auth.signOut();
                }}
              >
                Sign out
              </button>
            </>
          ) : null}
        </div>
      </header>
      <div class="shell-body">
        <LeftRail activePanelId={activePanelId} />
        <main>{children}</main>
      </div>
    </div>
  );
}
