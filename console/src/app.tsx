import { useEffect, useState } from "preact/hooks";
import { ReadApiClient } from "./api";
import type { AuthContext } from "./auth";
import { initAuth } from "./auth";
import { loadConfig, type ConsoleConfig } from "./config";
import { Shell } from "./components/shell";
import { AuditRoute } from "./routes/audit";
import { DashboardRoute } from "./routes/dashboard";
import { HilQueueRoute } from "./routes/hil-queue";
import { LoginRoute } from "./routes/login";

type View = "dashboard" | "audit" | "hil-queue";

interface AppState {
  readonly status: "loading" | "ready" | "error";
  readonly config?: ConsoleConfig;
  readonly auth?: AuthContext;
  readonly client?: ReadApiClient;
  readonly error?: string;
}

function currentView(): View {
  const hash = window.location.hash.replace(/^#\/?/, "");
  if (hash === "audit" || hash === "hil-queue") return hash;
  return "dashboard";
}

export function App() {
  const [state, setState] = useState<AppState>({ status: "loading" });
  const [view, setView] = useState<View>(currentView());

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const config = loadConfig();
        const auth = await initAuth(config);
        const client = new ReadApiClient(config, auth);
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
    const onHashChange = () => setView(currentView());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  if (state.status === "loading") {
    return <div class="empty">Loading…</div>;
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

  return (
    <Shell view={view} auth={auth}>
      {view === "dashboard" ? (
        <DashboardRoute client={client} />
      ) : view === "audit" ? (
        <AuditRoute client={client} />
      ) : (
        <HilQueueRoute client={client} />
      )}
    </Shell>
  );
}
