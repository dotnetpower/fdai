import { describe, expect, test } from "vitest";
import type { ConsoleRoute } from "../router";
import { isRolesPanelRoute, rolesHref } from "./agent-workspace-nav";

function route(panelId: string, query = ""): ConsoleRoute {
  return {
    panelId,
    segments: [],
    search: new URLSearchParams(query),
    pathname: `/${panelId}`,
    canonicalPathname: `/${panelId}`,
    matched: true,
  };
}

describe("AgentWorkspaceNav deduplication contract", () => {
  test("suppresses duplicate workspace nav on Pantheon and legacy org views owned by PanelHubTabs", () => {
    expect(isRolesPanelRoute(route("pantheon"))).toBe(true);
    expect(isRolesPanelRoute(route("agents", "view=org"))).toBe(true);
    expect(isRolesPanelRoute(route("agents", "view=constellation"))).toBe(true);
    expect(isRolesPanelRoute(route("agents"))).toBe(false);
    expect(isRolesPanelRoute(route("agent-activity"))).toBe(false);
  });

  test("preserves route-backed roles overlay deep links and query parameters", () => {
    expect(rolesHref(route("agents"))).toBe("/agent-activity?roles=1");
    expect(rolesHref(route("agents", "data=sample"))).toBe("/agent-activity?data=sample&roles=1");
    expect(rolesHref(route("agent-activity", "view=activity&agent=Var&q=approval"))).toBe(
      "/agent-activity?view=activity&agent=Var&q=approval&roles=1&roleAgent=Var",
    );
    expect(rolesHref(route("pantheon", "agent=Odin"))).toBe("/pantheon?agent=Odin");
  });
});
