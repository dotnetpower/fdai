import { useEffect, useState } from "preact/hooks";
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
    href: () => routeHref("agents"),
    active: () => currentRoute().panelId === "agents" &&
      currentRoute().search.get("view") !== "org" &&
      currentRoute().search.get("view") !== "constellation",
  },
  {
    id: "activity",
    labelKey: "agents.workspace.activity",
    href: () => routeHref("agent-activity"),
    active: () => currentRoute().panelId === "agent-activity",
  },
] as const;

function rolesHref(): string {
  const route = currentRoute();
  if (route.panelId === "pantheon" || (
    route.panelId === "agents" && (
      route.search.get("view") === "org" || route.search.get("view") === "constellation"
    )
  )) {
    return routeHref("pantheon", { params: { agent: route.search.get("agent") } });
  }
  if (route.panelId !== "agent-activity") {
    return routeHref("agent-activity", { params: { roles: "1" } });
  }
  return routeHref("agent-activity", {
    params: {
      view: route.search.get("view"),
      agent: route.search.get("agent"),
      step: route.search.get("step"),
      window: route.search.get("window"),
      layer: route.search.get("layer"),
      verb: route.search.get("verb"),
      q: route.search.get("q"),
      roles: "1",
      roleAgent: route.search.get("agent"),
    },
  });
}

export function AgentWorkspaceNav() {
  const [, setRouteRevision] = useState(0);
  useEffect(() => {
    const refresh = () => setRouteRevision((revision) => revision + 1);
    window.addEventListener("popstate", refresh);
    window.addEventListener("fdai:route-changed", refresh);
    window.addEventListener(ROUTE_STATE_EVENT, refresh);
    return () => {
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
        const active = item.active();
        return (
          <a
            key={item.id}
            href={item.href()}
            class={active ? "is-active" : undefined}
            aria-current={active ? "page" : undefined}
          >
            {t(item.labelKey)}
          </a>
        );
      })}
      <a
        id="agent-roles-trigger"
        href={rolesHref()}
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
          const href = rolesHref();
          if (currentRoute().panelId === "agent-activity") {
            pushRouteState(href, { fdaiAgentRolesOverlay: true });
          } else {
            window.addEventListener("popstate", () => {
              window.setTimeout(() => {
                document.getElementById("agent-roles-trigger")?.focus();
              }, 0);
            }, { once: true });
            navigate(href, false, { fdaiAgentRolesOverlay: true });
          }
        }}
      >
        {t("nav.panel.pantheon")}
      </a>
    </nav>
  );
}
