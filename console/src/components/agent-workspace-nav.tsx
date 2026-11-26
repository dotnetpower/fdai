import { useEffect, useRef, useState } from "preact/hooks";
import {
  currentRoute,
  navigate,
  pushRouteState,
  ROUTE_STATE_EVENT,
  routeHref,
} from "../router";
import { t } from "../i18n";

export function isRolesPanelRoute(route = currentRoute()): boolean {
  return route.panelId === "pantheon" || (
    route.panelId === "agents" && (
      route.search.get("view") === "org" || route.search.get("view") === "constellation"
    )
  );
}

export function rolesHref(route = currentRoute()): string {
  const data = route.search.get("data") === "sample" ? "sample" : null;
  if (isRolesPanelRoute(route)) {
    return routeHref("pantheon", { params: { data, agent: route.search.get("agent") } });
  }
  if (route.panelId !== "agent-activity") {
    return routeHref("agent-activity", { params: { data, roles: "1" } });
  }
  return routeHref("agent-activity", {
    params: {
      data,
      view: route.search.get("view"),
      agent: route.search.get("agent"),
      trajectory: route.search.get("trajectory"),
      step: route.search.get("step"),
      q: route.search.get("q"),
      roles: "1",
      roleAgent: route.search.get("agent"),
    },
  });
}

/**
 * Compact quick-access trigger for the route-backed Roles and ownership overlay.
 *
 * Hub switching across Agents routes is owned by NavigationShell and PanelHubTabs,
 * so this bar never duplicates Fleet/Activity tabs and renders nothing on Pantheon
 * where PanelHubTabs already owns hub tabs.
 */
export function AgentWorkspaceNav() {
  const [, setRouteRevision] = useState(0);
  const popstateCleanupRef = useRef<(() => void) | null>(null);
  useEffect(() => {
    const refresh = () => setRouteRevision((revision) => revision + 1);
    window.addEventListener("popstate", refresh);
    window.addEventListener("fdai:route-changed", refresh);
    window.addEventListener(ROUTE_STATE_EVENT, refresh);
    return () => {
      popstateCleanupRef.current?.();
      popstateCleanupRef.current = null;
      window.removeEventListener("popstate", refresh);
      window.removeEventListener("fdai:route-changed", refresh);
      window.removeEventListener(ROUTE_STATE_EVENT, refresh);
    };
  }, []);
  const route = currentRoute();
  if (isRolesPanelRoute(route)) {
    return null;
  }
  const rolesActive = route.panelId === "agent-activity" && route.search.get("roles") === "1";
  return (
    <nav class="agent-workspace-nav agent-workspace-nav--compact" aria-label={t("agents.workspace.label")}>
      <a
        id="agent-roles-trigger"
        href={rolesHref(route)}
        class={`cs-control-button agent-workspace-roles${rolesActive ? " is-active" : ""}`}
        aria-haspopup="dialog"
        aria-expanded={rolesActive}
        onClick={(event) => {
          if (
            event.defaultPrevented ||
            event.button !== 0 ||
            event.metaKey ||
            event.ctrlKey ||
            event.shiftKey ||
            event.altKey
          ) return;
          event.preventDefault();
          const current = currentRoute();
          const href = rolesHref(current);
          if (current.panelId === "agent-activity") {
            pushRouteState(href, { fdaiAgentRolesOverlay: true });
          } else {
            popstateCleanupRef.current?.();
            const onPopstate = () => {
              popstateCleanupRef.current = null;
              window.setTimeout(() => {
                document.getElementById("agent-roles-trigger")?.focus();
              }, 0);
            };
            window.addEventListener("popstate", onPopstate, { once: true });
            popstateCleanupRef.current = () => window.removeEventListener("popstate", onPopstate);
            navigate(href, false, { fdaiAgentRolesOverlay: true });
          }
        }}
      >
        {t("nav.panel.pantheon")}
      </a>
    </nav>
  );
}
