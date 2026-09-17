import { useEffect, useRef, useState } from "preact/hooks";
import { lazy, Suspense } from "preact/compat";
import { OperatorApiClient } from "./api";
import type { AuthContext } from "./auth";
import { initAuth } from "./auth";
import { observeUnauthorizedApiResponses } from "./auth-response";
import {
  shouldAllowLocalDevBypass,
  shouldLoadIamSelf,
  shouldShowAccessRequired,
} from "./access-routing";
import { loadConfig, type ConsoleConfig } from "./config";
import {
  clearLocalAuthBypass,
  establishLocalAuthBypass,
  readLocalAuthBypass,
} from "./local-auth-session";
import { Shell } from "./components/shell";
import { PanelErrorBoundary } from "./components/panel-error-boundary";
import { ErrorState, PageHeader } from "./components/ui";
import { setChatAuth } from "./deck/auth";
import { buildFallbackViewSnapshot, ViewContextProvider } from "./deck/context";
import { deckUserFromAuth, setDeckUser } from "./deck/deck-user";
import { setWorkflowAuth } from "./workflow/validate";
import { setPythonTaskAuth } from "./workflow/python-task";
import { setUserContextAuth } from "./user-context-client";
import type { IamSelfStatus } from "./routes/settings-iam.model";
import { t } from "./i18n";
import { DEFAULT_PANEL_ID, panelForId, resolvePanels } from "./panels";
import {
  currentRoute,
  closeTransientRoute,
  hasTransientRoute,
  installNavigationListener,
  migrateLegacyHash,
  navigate,
  openTransientSettingsRoute,
  panelPath,
  shouldReplaceUnmatchedRoute,
} from "./router";
import { withStartupTransportRetry } from "./bootstrap-retry";
import {
  consoleDataMode,
  consoleDataModeHref,
  explicitConsoleDataMode,
  readConsoleDataMode,
  supportsSampleData,
  writeConsoleDataMode,
} from "./console-data-mode";

interface AppState {
  readonly status: "loading" | "starting" | "ready" | "access-error" | "error";
  readonly config?: ConsoleConfig;
  readonly auth?: AuthContext;
  readonly client?: OperatorApiClient;
  readonly sampleClient?: OperatorApiClient;
  readonly iamSelf?: IamSelfStatus;
  readonly error?: string;
}

interface BackgroundRoute {
  readonly panelId: string;
  readonly routeKey: string;
  readonly href: string;
  readonly search: URLSearchParams;
}

const DeferredCommandDeck = lazy(async () => {
  const module = await import("./deck/deferred-command-deck");
  return { default: module.DeferredCommandDeck };
});

const SettingsOverlay = lazy(async () => {
  const module = await import("./components/settings-overlay");
  return { default: module.SettingsOverlay };
});

const LoginRoute = lazy(async () => {
  const module = await import("./routes/login");
  return { default: module.LoginRoute };
});

const AccessRequiredRoute = lazy(async () => {
  const module = await import("./routes/access-required");
  return { default: module.AccessRequiredRoute };
});

function PanelLoading({ title, subtitle }: { readonly title: string; readonly subtitle: string | undefined }) {
  return (
    <div class="stack panel-loading-shell" role="status" aria-live="polite" aria-busy="true">
      <PageHeader title={title} subtitle={subtitle} />
      <span class="sr-only">{t("shared.loadingResource", { resource: title })}</span>
      <div class="panel-loading-summary" aria-hidden="true">
        <span class="skeleton-shimmer" />
        <span class="skeleton-shimmer" />
        <span class="skeleton-shimmer" />
      </div>
      <div class="panel-loading-body" aria-hidden="true">
        <span class="skeleton-shimmer" />
        <span class="skeleton-shimmer" />
        <span class="skeleton-shimmer" />
        <span class="skeleton-shimmer" />
      </div>
    </div>
  );
}

function currentPanelId(): string {
  if (typeof window === "undefined") return DEFAULT_PANEL_ID;
  return currentRoute().panelId;
}

function routeKeyFor(route: ReturnType<typeof currentRoute>): string {
  if (route.panelId === "agent-activity") return route.canonicalPathname;
  const query = route.search.toString();
  return query ? `${route.canonicalPathname}?${query}` : route.canonicalPathname;
}

function initialBackgroundRoute(): BackgroundRoute {
  const route = currentRoute();
  if (panelForId(route.panelId).group !== "settings") {
    const routeKey = routeKeyFor(route);
    return { panelId: route.panelId, routeKey, href: routeKey, search: route.search };
  }
  const href = panelPath(DEFAULT_PANEL_ID);
  return {
    panelId: DEFAULT_PANEL_ID,
    routeKey: href,
    href,
    search: new URLSearchParams(),
  };
}

export function App() {
  const [state, setState] = useState<AppState>({ status: "loading" });
  const [panelId, setPanelId] = useState<string>(currentPanelId());
  const [routeKey, setRouteKey] = useState(() =>
    routeKeyFor(currentRoute()),
  );
  const [backgroundRoute, setBackgroundRoute] = useState<BackgroundRoute>(
    initialBackgroundRoute,
  );
  const [localDevBypass, setLocalDevBypass] = useState(readLocalAuthBypass);
  const preferredDataModeRef = useRef(readConsoleDataMode());
  const [preferredDataMode, setPreferredDataMode] = useState(preferredDataModeRef.current);
  const activePanel = panelForId(panelId);

  useEffect(() => {
    migrateLegacyHash();
    const route = currentRoute();
    if (shouldReplaceUnmatchedRoute(route, window.location.hash)) {
      window.history.replaceState(null, "", panelPath(DEFAULT_PANEL_ID));
    } else if (route.matched && route.pathname !== route.canonicalPathname) {
      const query = route.search.toString();
      window.history.replaceState(
        null,
        "",
        query ? `${route.canonicalPathname}?${query}` : route.canonicalPathname,
      );
    }
    const syncRoute = () => {
      let route = currentRoute();
      if (supportsSampleData(route.panelId)) {
        const explicitDataMode = explicitConsoleDataMode(route.search);
        if (explicitDataMode === "sample") {
          preferredDataModeRef.current = "sample";
          writeConsoleDataMode("sample");
          setPreferredDataMode("sample");
        } else if (explicitDataMode === "live") {
          preferredDataModeRef.current = "live";
          writeConsoleDataMode("live");
          setPreferredDataMode("live");
        } else if (preferredDataModeRef.current === "sample") {
          window.history.replaceState(
            window.history.state,
            "",
            consoleDataModeHref("sample", window.location.pathname, window.location.search),
          );
          route = currentRoute();
        }
      }
      setPanelId(route.panelId);
      const nextRouteKey = routeKeyFor(route);
      setRouteKey(nextRouteKey);
      if (panelForId(route.panelId).group !== "settings") {
        setBackgroundRoute({
          panelId: route.panelId,
          routeKey: nextRouteKey,
          href: nextRouteKey,
          search: route.search,
        });
      }
    };
    syncRoute();
    return installNavigationListener(syncRoute);
  }, []);

  useEffect(() => {
    let cancelled = false;
    let stopObservingUnauthorized = () => {};
    let stopAuthSessionKeeper = () => {};
    (async () => {
      try {
        const config = loadConfig();
        const auth = await initAuth(config);
        stopAuthSessionKeeper = auth.startSessionKeeper?.() ?? (() => {});
        if (!shouldAllowLocalDevBypass(auth) && readLocalAuthBypass()) {
          clearLocalAuthBypass();
          if (!cancelled) setLocalDevBypass(false);
        }
        let client: OperatorApiClient;
        const handleUnauthorized = (error: { readonly message: string }) => {
          if (cancelled) return;
          setState((current) => current.status === "access-error"
            ? current
            : {
                status: "access-error",
                config,
                auth,
                client,
                error: error.message,
              });
        };
        client = new OperatorApiClient(config, auth, {
          onUnauthorized: handleUnauthorized,
        });
        stopObservingUnauthorized = observeUnauthorizedApiResponses(
          [config.operatorApiBaseUrl, config.ingestionApiBaseUrl],
          handleUnauthorized,
        );
        setDeckUser(deckUserFromAuth(auth));
        setWorkflowAuth(auth);
        setPythonTaskAuth(auth);
        setUserContextAuth(auth);
        setChatAuth(auth);
        let iamSelf: IamSelfStatus | undefined;
        if (shouldLoadIamSelf(auth)) {
          try {
            iamSelf = await withStartupTransportRetry(() => client.iamSelf(), {
              onRetry: () => {
                if (cancelled) return;
                setState((current) => current.status === "loading"
                  ? { status: "starting", config, auth, client }
                  : current);
              },
            });
          } catch (err) {
            handleUnauthorized({
              message: err instanceof Error ? err.message : String(err),
            });
            return;
          }
        }
        if (!cancelled) {
          setState({
            status: "ready",
            config,
            auth,
            client,
            ...(iamSelf ? { iamSelf } : {}),
          });
        }
      } catch (err) {
        if (!cancelled) {
          setState({
            status: "error",
            error: err instanceof Error ? err.message : String(err),
          });
        }
      }
    })();
    return () => {
      cancelled = true;
      stopAuthSessionKeeper();
      stopObservingUnauthorized();
      setChatAuth(null);
      setUserContextAuth(null);
    };
  }, []);

  useEffect(() => {
    if (
      state.status !== "ready" ||
      state.sampleClient !== undefined ||
      !supportsSampleData(panelId) ||
      (
        preferredDataMode !== "sample" &&
        currentRoute().search.get("data") !== "sample"
      )
    ) return undefined;
    const { config, auth } = state;
    if (config === undefined || auth === undefined) return undefined;
    let cancelled = false;
    void import("./routes/operations.sample")
      .then(({ operationsSampleResponse }) => {
        if (cancelled) return;
        setState((current) => current.status !== "ready" || current.sampleClient !== undefined
          ? current
          : {
              ...current,
              sampleClient: new OperatorApiClient(config, auth, {
                sampleResponse: operationsSampleResponse,
              }),
            });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({
            status: "error",
            error: error instanceof Error ? error.message : String(error),
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [panelId, preferredDataMode, state]);

  if (state.status === "loading") {
    return (
      <main class="console-bootstrap">
        <PanelLoading title={activePanel.label} subtitle={activePanel.subtitle} />
      </main>
    );
  }

  if (state.status === "starting") {
    const { auth } = state;
    if (!auth) {
      return <div class="empty error">{t("console.internalStateMissing")}</div>;
    }
    return (
      <Suspense fallback={(
        <main class="console-bootstrap">
          <PanelLoading title={activePanel.label} subtitle={activePanel.subtitle} />
        </main>
      )}>
        <LoginRoute auth={auth} startup />
      </Suspense>
    );
  }

  if (state.status === "error") {
    return (
      <main class="console-bootstrap">
        <ErrorState
          message={state.error ?? t("console.initializeFailed")}
          onRetry={() => window.location.reload()}
          retryLabel={t("shared.reloadConsole")}
        />
      </main>
    );
  }

  if (state.status === "access-error") {
    const { auth, client, config } = state;
    if (!auth || !client || !config) {
      return <div class="empty error">{t("console.internalStateMissing")}</div>;
    }
    return (
      <Suspense fallback={<PanelLoading title={activePanel.label} subtitle={activePanel.subtitle} />}>
        <LoginRoute
          auth={auth}
          accessRecovery={{
            error: state.error ?? t("accessRequired.checkFailed"),
            retry: async () => {
              const iamSelf = await client.iamSelf();
              setState({ status: "ready", config, auth, client, iamSelf });
            },
          }}
        />
      </Suspense>
    );
  }

  const { auth, client, sampleClient } = state;
  if (!auth || !client) {
    return <div class="empty error">{t("console.internalStateMissing")}</div>;
  }

  if (!auth.devMode && !auth.account) {
    return (
      <Suspense fallback={<PanelLoading title={activePanel.label} subtitle={activePanel.subtitle} />}>
        <LoginRoute auth={auth} />
      </Suspense>
    );
  }

  if (
    auth.devMode &&
    state.config?.localLoginPrompt &&
    !auth.account &&
    (!shouldAllowLocalDevBypass(auth) || !localDevBypass)
  ) {
    const allowDevBypass = shouldAllowLocalDevBypass(auth);
    return (
      <Suspense fallback={<PanelLoading title={activePanel.label} subtitle={activePanel.subtitle} />}>
        <LoginRoute
          auth={auth}
          allowDevBypass={allowDevBypass}
          {...(allowDevBypass ? {
            onDevBypass: async () => {
              await establishLocalAuthBypass(() => client.dashboardMetrics());
              setLocalDevBypass(true);
            },
          } : {})}
        />
      </Suspense>
    );
  }

  if (state.iamSelf && shouldShowAccessRequired(auth, state.iamSelf)) {
    return (
      <Suspense fallback={<PanelLoading title={activePanel.label} subtitle={activePanel.subtitle} />}>
        <AccessRequiredRoute auth={auth} client={client} initialStatus={state.iamSelf} />
      </Suspense>
    );
  }

  const panel = activePanel;
  const PanelComponent = panel.component;
  const route = currentRoute();
  const dataMode = consoleDataMode(panel.id, route.search, preferredDataMode);
  const settingsOpen = panel.group === "settings";
  const backgroundPanel = settingsOpen ? panelForId(backgroundRoute.panelId) : panel;
  const BackgroundPanelComponent = backgroundPanel.component;
  const backgroundDataMode = settingsOpen
    ? consoleDataMode(backgroundPanel.id, backgroundRoute.search, preferredDataMode)
    : dataMode;
  const closeSettings = () => {
    if (hasTransientRoute()) {
      closeTransientRoute();
    } else {
      navigate(backgroundRoute.href, true);
    }
  };

  return (
    <ViewContextProvider
      scopeKey={routeKey}
      fallbackSnapshot={buildFallbackViewSnapshot({
        routeId: panel.id,
        routeLabel: panel.label,
        ...(panel.subtitle ? { purpose: panel.subtitle } : {}),
      })}
    >
      <Shell
        activePanelId={panel.id}
        auth={auth}
        client={client}
        dataMode={backgroundDataMode}
        settingsOpen={settingsOpen}
        onOpenSettings={() => openTransientSettingsRoute()}
        onDataModeChange={(mode) => {
          preferredDataModeRef.current = mode;
          writeConsoleDataMode(mode);
          setPreferredDataMode(mode);
          navigate(
            consoleDataModeHref(mode, window.location.pathname, window.location.search),
            true,
          );
        }}
        {...(state.iamSelf ? { iamSelf: state.iamSelf } : {})}
        {...(
          auth.devMode
          && state.config?.localLoginPrompt
          && shouldAllowLocalDevBypass(auth)
          && localDevBypass
            ? { onExitLocalSession: () => {
                clearLocalAuthBypass();
                setLocalDevBypass(false);
              } }
            : {}
        )}
      >
        {!settingsOpen || hasTransientRoute() ? (
          <PanelErrorBoundary key={settingsOpen ? backgroundRoute.routeKey : routeKey}>
            <Suspense
              fallback={(
                <PanelLoading
                  title={backgroundPanel.label}
                  subtitle={backgroundPanel.subtitle}
                />
              )}
            >
              {backgroundDataMode === "sample" ? sampleClient === undefined ? (
                <PanelLoading title={backgroundPanel.label} subtitle={backgroundPanel.subtitle} />
              ) : (
                <BackgroundPanelComponent
                  client={sampleClient}
                  auth={auth}
                  dataMode={backgroundDataMode}
                />
              ) : (
                <BackgroundPanelComponent
                  client={client}
                  auth={auth}
                  dataMode={backgroundDataMode}
                />
              )}
            </Suspense>
          </PanelErrorBoundary>
        ) : null}
      </Shell>
      {settingsOpen ? (
        <Suspense fallback={<i class="settings-overlay-scrim" />}>
          <SettingsOverlay
            activePanelId={panel.id}
            onClose={closeSettings}
            onPrefetchPanel={(panelId) => {
              if (panelId === "settings-models") {
                void client.modelSettings().catch(() => undefined);
              }
            }}
          >
            <PanelErrorBoundary key={routeKey}>
              <Suspense fallback={<PanelLoading title={panel.label} subtitle={panel.subtitle} />}>
                <PanelComponent client={client} auth={auth} dataMode={dataMode} />
              </Suspense>
            </PanelErrorBoundary>
          </SettingsOverlay>
        </Suspense>
      ) : null}
      <Suspense
        fallback={(
          <span class="sr-only" role="status">
            {t("shared.loadingResource", { resource: t("deck.conversation") })}
          </span>
        )}
      >
        <DeferredCommandDeck client={client} routeLabel={backgroundPanel.label} />
      </Suspense>
    </ViewContextProvider>
  );
}
