import { useEffect, useRef, useState } from "preact/hooks";
import {
  currentRoute,
  navigate,
  pushRouteState,
  ROUTE_STATE_EVENT,
  routeHref,
} from "../router";
import { t } from "../i18n";

const AGENT_WORKSPACE_ITEMS = [
  {
    id: "fleet",
    labelKey: "agents.workspace.fleet",
    href: (route = currentRoute()) => routeHref("agents", {
      params: { data: route.search.get("data") === "sample" ? "sample" : null },
    }),
    active: (route = currentRoute()) => route.panelId === "agents" &&
      route.search.get("view") !== "org" &&
      route.search.get("view") !== "constellation",
  },
  {
    id: "activity",
    labelKey: "agents.workspace.activity",
    href: (route = currentRoute()) => routeHref("agent-activity", {
      params: { data: route.search.get("data") === "sample" ? "sample" : null },
    }),
    active: (route = currentRoute()) => route.panelId === "agent-activity",
  },
] as const;

export function rolesHref(route = currentRoute()): string {
  const data = route.search.get("data") === "sample" ? "sample" : null;
  if (route.panelId === "pantheon" || (
    route.panelId === "agents" && (
      route.search.get("view") === "org" || route.search.get("view") === "constellation"
    )
  )) {
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
  const rolesActive = route.panelId === "pantheon" || (
    route.panelId === "agents" && (
      route.search.get("view") === "org" || route.search.get("view") === "constellation"
    )
  ) || (
    route.panelId === "agent-activity" && route.search.get("roles") === "1"
  );
  const rolesFallback = route.panelId === "pantheon" || (
    route.panelId === "agents" && (
      route.search.get("view") === "org" || route.search.get("view") === "constellation"
    )
  );
  return (
    <nav class="agent-workspace-nav" aria-label={t("agents.workspace.label")}>
      {AGENT_WORKSPACE_ITEMS.map((item) => {
        const active = item.active(route);
        return (
          <a
            key={item.id}
            href={item.href(route)}
            class={active ? "is-active" : undefined}
            aria-current={active ? "page" : undefined}
          >
            {t(item.labelKey)}
          </a>
        );
      })}
      <a
        id="agent-roles-trigger"
        href={rolesHref(route)}
        class={`agent-workspace-roles${rolesActive ? " is-active" : ""}`}
        aria-current={rolesFallback ? "page" : undefined}
        aria-haspopup={rolesFallback ? undefined : "dialog"}
        aria-expanded={rolesFallback ? undefined : rolesActive}
        onClick={(event) => {
          if (
            rolesFallback ||
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
