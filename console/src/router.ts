import { resolvePanels } from "./panels";

const ROUTE_EVENT = "fdai:route-changed";

export const PANEL_PATHS: Readonly<Record<string, string>> = {
  dashboard: "/overview",
  live: "/live",
  incidents: "/incidents",
  agents: "/agents",
  "hil-queue": "/approvals",
  provision: "/provisioning",
  onboarding: "/onboarding",
  processes: "/processes",
  "workflow-apps": "/workflow-apps",
  "scheduler-runs": "/scheduler-runs",
  "scheduled-continuations": "/scheduled-continuations",
  "conversation-delivery": "/conversation-delivery",
  reports: "/reports",
  "agent-activity": "/agent-activity",
  audit: "/audit",
  "browser-evidence": "/browser-evidence",
  trace: "/trace",
  rca: "/root-cause-analysis",
  architecture: "/architecture",
  ontology: "/ontology",
  pantheon: "/pantheon",
  handover: "/handover",
  rules: "/rules",
  "workflow-builder": "/workflow-builder",
  documents: "/documents",
  "blast-radius": "/blast-radius",
  "promotion-gates": "/promotion-gates",
  scope: "/scope",
  "llm-cost": "/llm-cost",
  "settings-general": "/settings/general",
  "settings-models": "/settings/models",
  "settings-memory": "/settings/memory",
  "settings-iam": "/settings/iam",
  "settings-integrations": "/settings/integrations",
  "settings-diagnostics": "/settings/diagnostics",
  "operating-outcomes": "/operating-outcomes",
  "control-assurance": "/control-assurance",
  verticals: "/verticals",
  "trust-routing": "/trust-routing",
  labs: "/labs",
  capabilities: "/capabilities",
};

const PATH_ALIASES: Readonly<Record<string, string>> = {
  "/settings": "settings-general",
  "/processes/scheduler-runs": "scheduler-runs",
};

const LEGACY_ALIASES: Readonly<Record<string, string>> = {
  dashboard: "dashboard",
  "hil-queue": "hil-queue",
};

export interface ConsoleRoute {
  readonly panelId: string;
  readonly pathname: string;
  readonly canonicalPathname: string;
  readonly matched: boolean;
  readonly segments: readonly string[];
  readonly search: URLSearchParams;
}

function normalizePathname(pathname: string): string {
  const withLeadingSlash = pathname.startsWith("/") ? pathname : `/${pathname}`;
  const normalized = withLeadingSlash.replace(/\/+/g, "/").replace(/\/$/, "");
  return normalized === "" ? "/" : normalized;
}

export function panelPath(panelId: string): string {
  const explicit = PANEL_PATHS[panelId];
  if (explicit !== undefined) return explicit;
  return resolvePanels().some((panel) => panel.id === panelId)
    ? `/${panelId}`
    : PANEL_PATHS.dashboard!;
}

export function routeHref(
  panelId: string,
  options: {
    readonly segments?: readonly string[];
    readonly params?: Readonly<Record<string, string | number | null | undefined>>;
  } = {},
): string {
  const suffix = (options.segments ?? [])
    .map((segment) => encodeURIComponent(segment.trim().toLowerCase().replace(/[\s_]+/g, "-")))
    .join("/");
  const path = `${panelPath(panelId)}${suffix ? `/${suffix}` : ""}`;
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(options.params ?? {})) {
    if (value !== null && value !== undefined && value !== "") search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}

export function parseConsoleRoute(pathname: string, search = ""): ConsoleRoute {
  const normalized = normalizePathname(pathname);
  const aliasPanel = PATH_ALIASES[normalized];
  const matchedRoute = registeredPanelRoutes().find(
    (candidate) => normalized === candidate.path || normalized.startsWith(`${candidate.path}/`),
  );
  const matchedPanel = aliasPanel ?? matchedRoute?.panelId;
  const panelId = matchedPanel ?? "dashboard";
  const matchedPath = aliasPanel === undefined ? matchedRoute?.path : normalized;
  const rawSegments = matchedPanel === undefined || matchedPath === undefined
    ? []
    : normalized
      .slice(matchedPath.length)
      .split("/")
      .filter(Boolean);
  let detailSegments: readonly string[] = [];
  try {
    detailSegments = rawSegments.map(decodeURIComponent);
  } catch {
    return {
      panelId: "dashboard",
      pathname: normalized,
      canonicalPathname: panelPath("dashboard"),
      matched: false,
      segments: [],
      search: new URLSearchParams(search.startsWith("?") ? search.slice(1) : search),
    };
  }
  const canonicalPathname = panelId === "processes" && detailSegments.length > 0
    ? `${panelPath(panelId)}/${detailSegments.map(encodeURIComponent).join("/")}`
    : routeHref(panelId, { segments: detailSegments });
  return {
    panelId,
    pathname: normalized,
    canonicalPathname,
    matched: matchedPanel !== undefined,
    segments: detailSegments,
    search: new URLSearchParams(search.startsWith("?") ? search.slice(1) : search),
  };
}

export function registeredPanelRoutes(): readonly { readonly panelId: string; readonly path: string }[] {
  const routes = resolvePanels().map((panel) => ({ panelId: panel.id, path: panelPath(panel.id) }));
  const paths = new Map<string, string>();
  for (const route of routes) {
    const existing = paths.get(route.path);
    if (existing !== undefined && existing !== route.panelId) {
      throw new Error(`Duplicate console panel path ${route.path}: ${existing}, ${route.panelId}`);
    }
    if (!/^\/[a-z0-9]+(?:[/-][a-z0-9]+)*$/.test(route.path)) {
      throw new Error(`Console panel path MUST be lowercase kebab-case: ${route.path}`);
    }
    paths.set(route.path, route.panelId);
  }
  for (const [aliasPath, aliasPanel] of Object.entries(PATH_ALIASES)) {
    const canonicalPanel = paths.get(aliasPath);
    if (canonicalPanel !== undefined && canonicalPanel !== aliasPanel) {
      throw new Error(`Console alias path collides with panel path ${aliasPath}`);
    }
  }
  return routes.sort((left, right) => right.path.length - left.path.length);
}

export function legacyHashHref(hash: string): string | null {
  if (!hash.startsWith("#")) return null;
  let decoded = hash;
  try {
    decoded = decodeURIComponent(hash);
  } catch {
    return null;
  }
  const raw = decoded.replace(/^#\/?/, "");
  if (!raw) return PANEL_PATHS.dashboard!;
  const [legacyId = "", query = ""] = raw.split("?", 2);
  const panelId = LEGACY_ALIASES[legacyId] ?? legacyId;
  if (!(panelId in PANEL_PATHS)) return null;
  const path = panelPath(panelId);
  return query ? `${path}?${query}` : path;
}

export function currentRoute(): ConsoleRoute {
  if (typeof window === "undefined") return parseConsoleRoute("/overview");
  return parseConsoleRoute(window.location.pathname, window.location.search);
}

export function shouldReplaceUnmatchedRoute(route: ConsoleRoute, hash: string): boolean {
  return !route.matched && hash === "";
}

export function shouldResetScroll(currentPathname: string, nextPathname: string): boolean {
  return normalizePathname(currentPathname) !== normalizePathname(nextPathname);
}

export function navigate(href: string, replace = false): void {
  if (typeof window === "undefined") return;
  const url = new URL(href, window.location.origin);
  const resetScroll = shouldResetScroll(window.location.pathname, url.pathname);
  const method = replace ? "replaceState" : "pushState";
  window.history[method](null, "", `${url.pathname}${url.search}`);
  window.dispatchEvent(new Event(ROUTE_EVENT));
  if (resetScroll) window.scrollTo({ top: 0, left: 0, behavior: "auto" });
}

/** Replace the current clean URL without notifying the route boundary.
 * Use this for free-text controls whose component already owns the next
 * state; dispatching ROUTE_EVENT on every keystroke would remount the panel
 * and drop input focus. */
export function replaceRouteState(href: string): void {
  if (typeof window === "undefined") return;
  const url = new URL(href, window.location.origin);
  window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}`);
}

export function installNavigationListener(onRoute: () => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  const onClick = (event: MouseEvent) => {
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) return;
    const target = event.target as Element | null;
    const anchor = target?.closest("a[href]") as HTMLAnchorElement | null;
    if (!anchor || anchor.target || anchor.hasAttribute("download")) return;
    const url = new URL(anchor.href, window.location.origin);
    if (url.origin !== window.location.origin || url.hash) return;
    event.preventDefault();
    navigate(`${url.pathname}${url.search}`);
  };
  window.addEventListener("popstate", onRoute);
  window.addEventListener(ROUTE_EVENT, onRoute);
  document.addEventListener("click", onClick);
  return () => {
    window.removeEventListener("popstate", onRoute);
    window.removeEventListener(ROUTE_EVENT, onRoute);
    document.removeEventListener("click", onClick);
  };
}

export function migrateLegacyHash(): void {
  if (typeof window === "undefined" || !window.location.hash) return;
  const target = legacyHashHref(window.location.hash);
  if (target !== null) navigate(target, true);
}
