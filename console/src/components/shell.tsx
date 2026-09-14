import type { ComponentChildren } from "preact";
import { lazy, Suspense } from "preact/compat";
import { useEffect, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import type { AuthContext } from "../auth";
import type { IamSelfStatus } from "../routes/settings-iam.model";
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
import { AccessGrantAttention } from "./access-grant-attention";
import { IncidentAttention } from "./incident-attention";
import { browserNotificationText } from "./i18n/browser-notifications";
import { NavigationShell } from "./navigation-shell";
import { NavigationTitleProvider } from "./navigation-title";
import { NotificationBellIcon } from "./notification-bell-icon";
import type { ConsoleDataMode } from "../console-data-mode";
import { supportsSampleData } from "../console-data-mode";
import { DataModeControl } from "./data-mode-control";

const AccountMenu = lazy(async () => {
  const module = await import("./account-menu");
  return { default: module.AccountMenu };
});

const BrowserNotificationControl = lazy(async () => {
  const module = await import("./browser-notification-control");
  return { default: module.BrowserNotificationControl };
});

interface ShellProps {
  readonly activePanelId: string;
  readonly auth: AuthContext;
  readonly client: OperatorApiClient;
  readonly iamSelf?: IamSelfStatus;
  readonly dataMode: ConsoleDataMode;
  readonly settingsOpen: boolean;
  readonly onOpenSettings: () => void;
  readonly onDataModeChange: (mode: ConsoleDataMode) => void;
  readonly children: ComponentChildren;
  readonly onExitLocalSession?: () => void;
}

export function Shell({
  activePanelId,
  auth,
  client,
  iamSelf,
  dataMode,
  settingsOpen,
  onOpenSettings,
  onDataModeChange,
  children,
  onExitLocalSession,
}: ShellProps) {
  const [preferences, setPreferences] = useState<ConsolePreferences>(readConsolePreferences);
  const [navigationExplorerOpen, setNavigationExplorerOpen] = useState(false);

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
    <div
      class={`shell ${dataMode === "sample" ? "shell-sample-mode" : ""}`}
      inert={settingsOpen}
    >
      <header class="topbar">
        <a class="brand-lockup" href={panelPath("dashboard")} aria-label={t("shell.home")}>
          <img
            class="brand-logo"
            src={`${import.meta.env.BASE_URL}brand/fdai-logo.png`}
            alt=""
          />
          <span class="brand-wordmark">FDAI</span>
          <span class="brand-separator" aria-hidden="true" />
          <span class="brand-product">{t("shell.console")}</span>
        </a>
        <div class="principal">
          {supportsSampleData(activePanelId) ? (
            <DataModeControl mode={dataMode} onChange={onDataModeChange} />
          ) : null}
          <IncidentAttention
            client={client}
            principalId={auth.account?.homeAccountId ?? null}
          />
          <AccessGrantAttention
            auth={auth}
            client={client}
            principalId={auth.account?.homeAccountId ?? null}
          />
          <Suspense fallback={(
            <button
              type="button"
              class="topbar-control browser-notification-control"
              aria-label={browserNotificationText("enabling")}
              aria-pressed="false"
              disabled
            >
              <span class="browser-notification-indicator" aria-hidden="true" />
              <NotificationBellIcon />
              <span class="topbar-control-label">{browserNotificationText("label")}</span>
              <span class="browser-notification-state" role="status" aria-live="polite">
                {browserNotificationText("stateEnabling")}
              </span>
            </button>
          )}>
            <BrowserNotificationControl
              client={client}
              principalId={auth.account?.homeAccountId ?? null}
            />
          </Suspense>
          {auth.account ? (
            <Suspense fallback={(
              <span class="account-menu-loading" role="status" aria-live="polite">
                <span class="account-avatar account-avatar-small skeleton-shimmer" aria-hidden="true" />
                <span class="sr-only">
                  {t("shared.loadingResource", { resource: auth.account.username })}
                </span>
              </span>
            )}>
              <AccountMenu auth={auth} iamSelf={iamSelf} />
            </Suspense>
          ) : auth.devMode ? (
            <>
              <span class="badge">{t("shell.devMode")}</span>
              {onExitLocalSession ? (
                <button type="button" onClick={onExitLocalSession}>
                  {t("login.exitLocalSession")}
                </button>
              ) : null}
            </>
          ) : null}
        </div>
      </header>
      {dataMode === "sample" ? (
        <div class="sample-mode-banner" role="status">
          <strong>{t("dataMode.bannerTitle")}</strong>
          <span>{t("dataMode.bannerBody")}</span>
        </div>
      ) : null}
      <div class="shell-body">
        <NavigationTitleProvider
          activePanelId={activePanelId}
          explorerOpen={navigationExplorerOpen}
          onOpenExplorer={() => setNavigationExplorerOpen(true)}
        >
          <NavigationShell
            activePanelId={activePanelId}
            client={client}
            principalId={auth.account?.homeAccountId ?? null}
            devMode={auth.devMode}
            explorerOpen={navigationExplorerOpen}
            settingsOpen={settingsOpen}
            onOpenSettings={onOpenSettings}
            onExplorerOpenChange={setNavigationExplorerOpen}
          />
          <main>
            {children}
          </main>
        </NavigationTitleProvider>
      </div>
    </div>
  );
}
