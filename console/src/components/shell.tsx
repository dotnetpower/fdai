import type { ComponentChildren } from "preact";
import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import type { AuthContext } from "../auth";
import { t } from "../i18n";
import {
  acceptStoredConsolePreference,
  applyConsolePreferences,
  isPreferenceStorageKey,
  PREFERENCES_CHANGED_EVENT,
  readConsolePreferences,
  type ConsolePreferences,
} from "../preferences";
import { panelPath } from "../router";
import { BrowserNotificationControl } from "./browser-notification-control";
import { NavigationShell } from "./navigation-shell";
import { NavigationTitleProvider } from "./navigation-title";

interface ShellProps {
  readonly activePanelId: string;
  readonly auth: AuthContext;
  readonly client: ReadApiClient;
  readonly children: ComponentChildren;
  readonly onExitLocalSession?: () => void;
}

export function Shell({ activePanelId, auth, client, children, onExitLocalSession }: ShellProps) {
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

  return (
    <div class="shell">
      <header class="topbar">
        <a class="brand-lockup" href={panelPath("dashboard")} aria-label={t("shell.home")}>
          <img
            class="brand-logo"
            src={`${import.meta.env.BASE_URL}brand/concepts/fdai-cloud-aperture.svg`}
            alt=""
          />
          <span class="brand-wordmark">FDAI</span>
          <span class="brand-separator" aria-hidden="true" />
          <span class="brand-product">{t("shell.console")}</span>
        </a>
        <div class="principal">
          <BrowserNotificationControl
            client={client}
            principalId={auth.account?.homeAccountId ?? null}
          />
          {auth.localAzureCli && auth.account ? (
            <>
              <span>{auth.account.username}</span>
              <span class="badge">Azure CLI</span>
            </>
          ) : auth.devMode && auth.account ? (
            <>
              <span>{auth.account.username}</span>
              <span class="badge">Local Entra</span>
              <button type="button" onClick={() => { void auth.signOut(); }}>
                {t("login.signOut")}
              </button>
            </>
          ) : auth.devMode ? (
            <>
              <span class="badge">{t("shell.devMode")}</span>
              {onExitLocalSession ? (
                <button type="button" onClick={onExitLocalSession}>
                  {t("login.exitLocalSession")}
                </button>
              ) : null}
            </>
          ) : auth.account ? (
            <>
              <span>{auth.account.username}</span>
              <button
                type="button"
                onClick={() => {
                  void auth.signOut();
                }}
              >
                {t("login.signOut")}
              </button>
            </>
          ) : null}
        </div>
      </header>
      <div class="shell-body">
        <NavigationShell
          activePanelId={activePanelId}
          principalId={auth.account?.homeAccountId ?? null}
          devMode={auth.devMode}
        />
        <main>
          <NavigationTitleProvider activePanelId={activePanelId}>
            {children}
          </NavigationTitleProvider>
        </main>
      </div>
    </div>
  );
}
