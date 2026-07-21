export interface UnauthorizedResponse {
  readonly status: 401;
  readonly message: string;
}

interface UnauthorizedSubscription {
  readonly apiBases: readonly URL[];
  readonly onUnauthorized: (error: UnauthorizedResponse) => void;
}

const subscriptions = new Set<UnauthorizedSubscription>();
let originalFetch: typeof fetch | null = null;
let observedFetch: typeof fetch | null = null;

export function observeUnauthorizedApiResponses(
  baseUrls: readonly string[],
  onUnauthorized: (error: UnauthorizedResponse) => void,
): () => void {
  const subscription: UnauthorizedSubscription = {
    apiBases: baseUrls
      .filter((value) => value.trim().length > 0)
      .map((value) => new URL(value, globalThis.location?.href)),
    onUnauthorized,
  };
  subscriptions.add(subscription);
  installObserver();
  let active = true;
  return () => {
    if (!active) return;
    active = false;
    subscriptions.delete(subscription);
    uninstallObserverIfIdle();
  };
}

function installObserver(): void {
  if (observedFetch !== null && globalThis.fetch === observedFetch) return;
  observedFetch = null;
  originalFetch = null;
  originalFetch = globalThis.fetch;
  const fetchDelegate = originalFetch;
  observedFetch = async (input, init) => {
    const response = await fetchDelegate(input, init);
    if (response.status === 401) {
      for (const subscription of subscriptions) {
        if (isApiRequest(input, subscription.apiBases)) {
          subscription.onUnauthorized({
            status: 401,
            message: "Authentication is required. Sign in again to continue.",
          });
        }
      }
    }
    return response;
  };
  globalThis.fetch = observedFetch;
}

function uninstallObserverIfIdle(): void {
  if (subscriptions.size > 0 || observedFetch === null || originalFetch === null) return;
  if (globalThis.fetch === observedFetch) {
    globalThis.fetch = originalFetch;
  }
  observedFetch = null;
  originalFetch = null;
}

function isApiRequest(
  input: RequestInfo | URL,
  apiBases: readonly URL[],
): boolean {
  const requestUrl = new URL(
    typeof input === "string"
      ? input
      : input instanceof URL
        ? input.href
        : input.url,
    globalThis.location?.href,
  );
  return apiBases.some((base) => {
    const basePath = base.pathname.replace(/\/$/, "");
    return requestUrl.origin === base.origin
      && (requestUrl.pathname === basePath || requestUrl.pathname.startsWith(`${basePath}/`));
  });
}