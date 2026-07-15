const ROUTE_EVENT = "fdai:route-changed";

export const PANEL_PATHS: Readonly<Record<string, string>> = {
  dashboard: "/overview",
  live: "/live",
  incidents: "/incidents",
  agents: "/agents",
  "hil-queue": "/approvals",
  provision: "/provisioning",
  processes: "/processes",
  reports: "/reports",
  "agent-activity": "/agent-activity",
  audit: "/audit",
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
  settings: "/settings",
  "operating-outcomes": "/operating-outcomes",
  "control-assurance": "/control-assurance",
  verticals: "/verticals",
  "trust-routing": "/trust-routing",
  labs: "/labs",
};

const PATH_PANELS = new Map(
  Object.entries(PANEL_PATHS).map(([panelId, path]) => [path.slice(1), panelId]),
);

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
  return PANEL_PATHS[panelId] ?? PANEL_PATHS.dashboard!;
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
  const segments = normalized.split("/").filter(Boolean).map(decodeURIComponent);
  const matchedPanel = segments.length === 0 ? undefined : PATH_PANELS.get(segments[0]!);
  const panelId = matchedPanel ?? "dashboard";
  const detailSegments = matchedPanel === undefined ? [] : segments.slice(1);
  const canonicalPathname = routeHref(panelId, { segments: detailSegments });
  return {
    panelId,
    pathname: normalized,
    canonicalPathname,
    matched: matchedPanel !== undefined,
    segments: detailSegments,
    search: new URLSearchParams(search.startsWith("?") ? search.slice(1) : search),
  };
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
  const path = panelPath(panelId);
  return query ? `${path}?${query}` : path;
}

export function currentRoute(): ConsoleRoute {
  if (typeof window === "undefined") return parseConsoleRoute("/overview");
  return parseConsoleRoute(window.location.pathname, window.location.search);
}

export function navigate(href: string, replace = false): void {
  if (typeof window === "undefined") return;
  const url = new URL(href, window.location.origin);
  const method = replace ? "replaceState" : "pushState";
  window.history[method](null, "", `${url.pathname}${url.search}`);
  window.dispatchEvent(new Event(ROUTE_EVENT));
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