import { useEffect, useState } from "preact/hooks";
import { lazy, Suspense } from "preact/compat";
import { ReadApiClient } from "./api";
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
import { PageHeader } from "./components/ui";
import { setChatAuth } from "./deck/auth";
import { ViewContextProvider } from "./deck/context";
import { deckUserFromAuth, setDeckUser } from "./deck/deck-user";
import { setWorkflowAuth } from "./workflow/validate";
import { setPythonTaskAuth } from "./workflow/python-task";
import { setUserContextAuth } from "./user-context-client";
import type { IamSelfStatus } from "./routes/settings-iam.model";
import { t } from "./i18n";
import { DEFAULT_PANEL_ID, panelForId, resolvePanels } from "./panels";
import {
  currentRoute,
  installNavigationListener,
  migrateLegacyHash,
  panelPath,
  shouldReplaceUnmatchedRoute,
} from "./router";

interface AppState {
  readonly status: "loading" | "ready" | "access-error" | "error";
  readonly config?: ConsoleConfig;
  readonly auth?: AuthContext;
  readonly client?: ReadApiClient;
  readonly iamSelf?: IamSelfStatus;
  readonly error?: string;
}

const CommandDeck = lazy(async () => {
  const module = await import("./deck/command-deck");
  return { default: module.CommandDeck };
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
    <div class="stack panel-loading-shell" role="status" aria-live="polite">
      <PageHeader title={title} subtitle={subtitle} />
      <span class="sr-only">{t("shared.loadingResource", { resource: title })}</span>
      <div class="panel-loading-summary" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
      <div class="panel-loading-body" aria-hidden="true">
        <span />
        <span />
        <span />
        <span />
      </div>
    </div>
  );
}

function currentPanelId(): string {
  if (typeof window === "undefined") return DEFAULT_PANEL_ID;
  return currentRoute().panelId;
}

export function App() {
  const [state, setState] = useState<AppState>({ status: "loading" });
  const [panelId, setPanelId] = useState<string>(currentPanelId());
  const [routeKey, setRouteKey] = useState(() =>
    typeof window === "undefined" ? "/overview" : `${window.location.pathname}${window.location.search}`,
  );
  const [localDevBypass, setLocalDevBypass] = useState(readLocalAuthBypass);

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
      setPanelId(currentPanelId());
      setRouteKey(`${window.location.pathname}${window.location.search}`);
    };
    syncRoute();
    return installNavigationListener(syncRoute);
  }, []);

  useEffect(() => {
    let cancelled = false;
    let stopObservingUnauthorized = () => {};
    (async () => {
      try {
        const config = loadConfig();
        const auth = await initAuth(config);
        if (!shouldAllowLocalDevBypass(auth) && readLocalAuthBypass()) {
          clearLocalAuthBypass();
          if (!cancelled) setLocalDevBypass(false);
        }
        let client: ReadApiClient;
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
        client = new ReadApiClient(config, auth, {
          onUnauthorized: handleUnauthorized,
        });
        stopObservingUnauthorized = observeUnauthorizedApiResponses(
          [config.readApiBaseUrl, config.ingestionApiBaseUrl],
          handleUnauthorized,
        );
        let iamSelf: IamSelfStatus | undefined;
        if (shouldLoadIamSelf(auth)) {
          try {
            iamSelf = await client.iamSelf();
          } catch (err) {
            handleUnauthorized({
              message: err instanceof Error ? err.message : String(err),
            });
            return;
          }
        }
        // Expose the signed-in operator's roles to the chat deck so it can
        // answer capability questions ("what can I do?").
        setDeckUser(deckUserFromAuth(auth));
        // Thread the operator's bearer token to the workflow-builder's
        // validate POST (the one non-GET, read-only call the console makes).
        setWorkflowAuth(auth);
        setPythonTaskAuth(auth);
        setUserContextAuth(auth);
        setChatAuth(auth);
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
      stopObservingUnauthorized();
      setChatAuth(null);
      setUserContextAuth(null);
    };
  }, []);

  if (state.status === "loading") {
    const loadingPanel = panelForId(panelId);
    return (
      <main class="console-bootstrap">
        <PanelLoading title={loadingPanel.label} subtitle={loadingPanel.subtitle} />
      </main>
    );
  }

  if (state.status === "error") {
    return (
      <div class="empty error">
        <p>{t("console.initializeFailed")}</p>
        <p class="mono">{state.error}</p>
      </div>
    );
  }

  if (state.status === "access-error") {
    const { auth, client, config } = state;
    if (!auth || !client || !config) {
      return <div class="empty error">{t("console.internalStateMissing")}</div>;
    }
    return (
      <Suspense fallback={null}>
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

  const { auth, client } = state;
  if (!auth || !client) {
    return <div class="empty error">{t("console.internalStateMissing")}</div>;
  }

  if (!auth.devMode && !auth.account) {
    return <Suspense fallback={null}><LoginRoute auth={auth} /></Suspense>;
  }

  if (
    auth.devMode &&
    state.config?.localLoginPrompt &&
    !auth.account &&
    (!shouldAllowLocalDevBypass(auth) || !localDevBypass)
  ) {
    const allowDevBypass = shouldAllowLocalDevBypass(auth);
    return (
      <Suspense fallback={null}>
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
      <Suspense fallback={null}>
        <AccessRequiredRoute auth={auth} client={client} initialStatus={state.iamSelf} />
      </Suspense>
    );
  }

  const panel = panelForId(panelId);
  const PanelComponent = panel.component;

  return (
    <ViewContextProvider scopeKey={routeKey}>
      <Shell
        activePanelId={panel.id}
        auth={auth}
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
        <PanelErrorBoundary key={routeKey}>
          <Suspense fallback={<PanelLoading title={panel.label} subtitle={panel.subtitle} />}>
            <PanelComponent client={client} auth={auth} />
          </Suspense>
        </PanelErrorBoundary>
      </Shell>
      <Suspense fallback={null}>
        <CommandDeck />
      </Suspense>
    </ViewContextProvider>
  );
}
