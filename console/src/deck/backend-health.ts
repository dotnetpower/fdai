import type { BackendHealth, RouterSnapshot } from "./backend-types";

const OFFLINE_HEALTH: BackendHealth = {
  available: false,
  mode: "offline",
  model: null,
  endpoint: null,
};

const HEALTH_CACHE_MS = 30_000;

export function createBackendHealthProbe(
  healthUrl: () => string,
  requestHeaders: () => Promise<Record<string, string>>,
  parseRouter: (raw: unknown) => RouterSnapshot | undefined,
): () => Promise<BackendHealth> {
  let cache: { readonly value: BackendHealth; readonly at: number } | null = null;
  let inFlight: Promise<BackendHealth> | null = null;

  const fetchHealth = async (): Promise<BackendHealth> => {
    let response: Response;
    try {
      response = await fetch(healthUrl(), {
        method: "GET",
        headers: await requestHeaders(),
        credentials: "omit",
      });
    } catch {
      return OFFLINE_HEALTH;
    }
    if (!response.ok) {
      return {
        available: false,
        mode: `unreachable (${response.status})`,
        model: null,
        endpoint: null,
      };
    }
    try {
      const payload = (await response.json()) as Partial<BackendHealth> & {
        router?: unknown;
      };
      const router = parseRouter(payload.router);
      const base: BackendHealth = {
        available: payload.available === true,
        mode: typeof payload.mode === "string" ? payload.mode : "unknown",
        model: typeof payload.model === "string" ? payload.model : null,
        endpoint: typeof payload.endpoint === "string" ? payload.endpoint : null,
      };
      return router ? { ...base, router } : base;
    } catch {
      return OFFLINE_HEALTH;
    }
  };

  return () => {
    const now = Date.now();
    if (cache && now - cache.at < HEALTH_CACHE_MS) {
      return Promise.resolve(cache.value);
    }
    if (inFlight) return inFlight;

    const request = fetchHealth().then((value) => {
      cache = { value, at: Date.now() };
      return value;
    });
    inFlight = request;
    void request.then(
      () => {
        if (inFlight === request) inFlight = null;
      },
      () => {
        if (inFlight === request) inFlight = null;
      },
    );
    return request;
  };
}
