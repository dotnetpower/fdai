// A small path-based router for four screens. No history library: the Hub UI is intentionally
// tiny, and Preact's built-in state plus `history.pushState` cover it without extra dependencies.

export type Route =
  | { kind: "installations" }
  | { kind: "installation"; installationId: string }
  | { kind: "plan"; installationId: string; planId: string }
  | { kind: "enrollments" }
  | { kind: "enrollment"; installationId: string }
  | { kind: "catalog" }
  | { kind: "updates" }
  | { kind: "releases" }
  | { kind: "configurations" }
  | { kind: "not-found"; path: string };

export function parseRoute(pathname: string): Route {
  const segments = pathname.split("/").filter(Boolean);
  if (segments.length === 0) return { kind: "installations" };
  if (segments.length === 1 && segments[0] === "catalog") return { kind: "catalog" };
  if (segments.length === 1 && segments[0] === "updates") return { kind: "updates" };
  if (segments.length === 1 && segments[0] === "available-releases") return { kind: "releases" };
  if (segments.length === 1 && segments[0] === "configuration-packages") return { kind: "configurations" };
  if (segments[0] === "installations") {
    if (segments.length === 1) return { kind: "installations" };
    if (segments.length === 2) return { kind: "installation", installationId: segments[1]! };
    if (segments.length === 4 && segments[2] === "plans") {
      return { kind: "plan", installationId: segments[1]!, planId: segments[3]! };
    }
  }
  if (segments[0] === "enrollments") {
    if (segments.length === 1) return { kind: "enrollments" };
    if (segments.length === 2) return { kind: "enrollment", installationId: segments[1]! };
  }
  return { kind: "not-found", path: pathname };
}

export function installationsPath(): string {
  return "/installations";
}

export function updatesPath(): string {
  return "/updates";
}

export function availableReleasesPath(): string {
  return "/available-releases";
}

export function configurationPackagesPath(): string {
  return "/configuration-packages";
}

export function installationPath(installationId: string): string {
  return `/installations/${encodeURIComponent(installationId)}`;
}

export function planPath(installationId: string, planId: string): string {
  return `/installations/${encodeURIComponent(installationId)}/plans/${encodeURIComponent(planId)}`;
}

export function enrollmentsPath(): string {
  return "/enrollments";
}

export function enrollmentPath(installationId: string): string {
  return `/enrollments/${encodeURIComponent(installationId)}`;
}

const LISTENERS = new Set<() => void>();

/** Push a path onto history and notify every subscribed router hook. */
export function navigate(path: string): void {
  if (path !== window.location.pathname) {
    window.history.pushState(null, "", path);
  }
  for (const listener of LISTENERS) listener();
}

export function subscribe(listener: () => void): () => void {
  LISTENERS.add(listener);
  window.addEventListener("popstate", listener);
  return () => {
    LISTENERS.delete(listener);
    window.removeEventListener("popstate", listener);
  };
}

export function currentRoute(): Route {
  return parseRoute(window.location.pathname);
}
