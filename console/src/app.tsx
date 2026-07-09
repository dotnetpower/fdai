import { useEffect, useState } from "preact/hooks";
import { ReadApiClient } from "./api";
import type { AuthContext } from "./auth";
import { initAuth } from "./auth";
import { loadConfig, type ConsoleConfig } from "./config";
import { Shell } from "./components/shell";
import { CommandDeck } from "./deck/command-deck";
import { ViewContextProvider } from "./deck/context";
import { deckUserFromAuth, setDeckUser } from "./deck/deck-user";
import { LoginRoute } from "./routes/login";
import { DEFAULT_PANEL_ID, panelForId, resolvePanels } from "./panels";

interface AppState {
  readonly status: "loading" | "ready" | "error";
  readonly config?: ConsoleConfig;
  readonly auth?: AuthContext;
  readonly client?: ReadApiClient;
  readonly error?: string;
}

function currentPanelId(): string {
  // Some hosting / port-forwarding layers URL-encode the ``/`` inside
  // the hash (``#/live`` becomes ``#%2Flive``). Decode first so the
  // hash router does not fall back to the default panel unexpectedly.
  let hash = window.location.hash;
  try {
    hash = decodeURIComponent(hash);
  } catch {
    /* keep raw hash if it is not a valid URI component */
  }
  const cleaned = hash.replace(/^#\/?/, "").replace(/\?.*$/, "");
  const known = resolvePanels().some((p) => p.id === cleaned);
  return known ? cleaned : DEFAULT_PANEL_ID;
}

export function App() {
  const [state, setState] = useState<AppState>({ status: "loading" });
  const [panelId, setPanelId] = useState<string>(currentPanelId());

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const config = loadConfig();
        const auth = await initAuth(config);
        const client = new ReadApiClient(config, auth);
        // Expose the signed-in operator's roles to the chat deck so it can
        // answer capability questions ("what can I do?").
        setDeckUser(deckUserFromAuth(auth));
        if (!cancelled) {
          setState({ status: "ready", config, auth, client });
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
    };
  }, []);

  useEffect(() => {
    const onHashChange = () => setPanelId(currentPanelId());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  if (state.status === "loading") {
    return <div class="empty">Loading...</div>;
  }

  if (state.status === "error") {
    return (
      <div class="empty error">
        <p>Console failed to initialize.</p>
        <p class="mono">{state.error}</p>
      </div>
    );
  }

  const { auth, client } = state;
  if (!auth || !client) {
    return <div class="empty error">Internal state missing.</div>;
  }

  if (!auth.devMode && !auth.account) {
    return <LoginRoute auth={auth} />;
  }

  const panel = panelForId(panelId);
  const PanelComponent = panel.component;

  return (
    <ViewContextProvider>
      <Shell activePanelId={panel.id} auth={auth}>
        <PanelComponent client={client} />
      </Shell>
      <CommandDeck />
    </ViewContextProvider>
  );
}
