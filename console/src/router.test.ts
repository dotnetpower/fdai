import { describe, expect, test } from "vitest";
import {
  legacyHashHref,
  panelPath,
  parseConsoleRoute,
  registeredPanelRoutes,
  routeHref,
  shouldResetScroll,
  shouldReplaceUnmatchedRoute,
} from "./router";

describe("clean console routes", () => {
  test("maps internal panel ids to user-facing kebab-case paths", () => {
    expect(panelPath("dashboard")).toBe("/overview");
    expect(panelPath("hil-queue")).toBe("/approvals");
    expect(panelPath("agent-activity")).toBe("/agent-activity");
    expect(panelPath("scheduler-runs")).toBe("/scheduler-runs");
    expect(panelPath("scheduled-continuations")).toBe("/scheduled-continuations");
    expect(panelPath("conversation-delivery")).toBe("/conversation-delivery");
    expect(panelPath("browser-evidence")).toBe("/browser-evidence");
    expect(panelPath("labs")).toBe("/labs");
    expect(panelPath("settings-general")).toBe("/settings/general");
    expect(panelPath("settings-models")).toBe("/settings/models");
    expect(panelPath("not-registered")).toBe("/overview");
  });

  test("gives every registered panel one unique canonical route", () => {
    const routes = registeredPanelRoutes();
    expect(new Set(routes.map((route) => route.panelId)).size).toBe(routes.length);
    expect(new Set(routes.map((route) => route.path)).size).toBe(routes.length);
    expect(routes.every((route) => /^\/[a-z0-9]+(?:[/-][a-z0-9]+)*$/.test(route.path))).toBe(true);
  });

  test("builds path segments without spaces or underscores", () => {
    expect(routeHref("verticals", { segments: ["Change Safety"] })).toBe(
      "/verticals/change-safety",
    );
    expect(routeHref("operating-outcomes", { segments: ["human_touchpoints"] })).toBe(
      "/operating-outcomes/human-touchpoints",
    );
  });

  test("parses detail routes and query filters", () => {
    const route = parseConsoleRoute("/trust-routing/t2", "?window=30d");
    expect(route.panelId).toBe("trust-routing");
    expect(route.matched).toBe(true);
    expect(route.canonicalPathname).toBe("/trust-routing/t2");
    expect(route.segments).toEqual(["t2"]);
    expect(route.search.get("window")).toBe("30d");
  });

  test("round-trips Overview analytical routes with preserved filters", () => {
    const href = routeHref("control-assurance", {
      params: { guard: "false_negative", window: "30d" },
    });
    const url = new URL(href, "https://example.com");
    const route = parseConsoleRoute(url.pathname, url.search);
    expect(route.panelId).toBe("control-assurance");
    expect(route.search.get("guard")).toBe("false_negative");
    expect(route.search.get("window")).toBe("30d");
  });

  test("preserves opaque Process identifiers during canonicalization", () => {
    const route = parseConsoleRoute("/processes/Run_A");
    expect(route.canonicalPathname).toBe("/processes/Run_A");
    expect(route.segments).toEqual(["Run_A"]);
  });

  test("matches nested Settings routes by their longest registered prefix", () => {
    const route = parseConsoleRoute("/settings/iam/users", "?role=Owner");
    expect(route.panelId).toBe("settings-iam");
    expect(route.matched).toBe(true);
    expect(route.canonicalPathname).toBe("/settings/iam/users");
    expect(route.segments).toEqual(["users"]);
    expect(route.search.get("role")).toBe("Owner");
  });

  test("keeps the legacy Settings URL as a canonical General alias", () => {
    const route = parseConsoleRoute("/settings");
    expect(route.panelId).toBe("settings-general");
    expect(route.matched).toBe(true);
    expect(route.canonicalPathname).toBe("/settings/general");
    expect(route.segments).toEqual([]);
  });

  test("canonicalizes the former nested Scheduler Runs route", () => {
    const route = parseConsoleRoute("/processes/scheduler-runs", "?task_id=inventory");
    expect(route.panelId).toBe("scheduler-runs");
    expect(route.matched).toBe(true);
    expect(route.canonicalPathname).toBe("/scheduler-runs");
    expect(route.search.get("task_id")).toBe("inventory");
  });

  test("marks unknown and root paths for canonical Overview replacement", () => {
    for (const pathname of ["/", "/typo", "/typo/detail"]) {
      const route = parseConsoleRoute(pathname);
      expect(route.panelId).toBe("dashboard");
      expect(route.matched).toBe(false);
      expect(route.canonicalPathname).toBe("/overview");
      expect(route.segments).toEqual([]);
    }
  });

  test("treats malformed percent-encoded segments as unmatched", () => {
      const route = parseConsoleRoute("/settings/iam/%E0%A4%A");
      expect(route.matched).toBe(false);
      expect(route.panelId).toBe("dashboard");
      expect(route.segments).toEqual([]);
    });

  test("migrates legacy hash bookmarks", () => {
    expect(legacyHashHref("#/dashboard")).toBe("/overview");
    expect(legacyHashHref("#%2Fhil-queue")).toBe("/approvals");
    expect(legacyHashHref("#/audit?correlation=corr-1")).toBe(
      "/audit?correlation=corr-1",
    );
  });

  test("preserves MSAL response and unknown hashes", () => {
    expect(legacyHashHref("#code=authorization-code&state=request-state")).toBeNull();
    expect(legacyHashHref("#error=access_denied&state=request-state")).toBeNull();
    expect(legacyHashHref("#custom-fragment")).toBeNull();
  });

  test("does not canonicalize an unmatched callback route while a hash is present", () => {
    const callbackRoute = parseConsoleRoute("/");
    expect(shouldReplaceUnmatchedRoute(callbackRoute, "#code=value&state=value")).toBe(false);
    expect(shouldReplaceUnmatchedRoute(callbackRoute, "")).toBe(true);
  });
  test("resolves capability and onboarding panels", () => {
    expect(parseConsoleRoute("/capabilities").panelId).toBe("capabilities");
    expect(parseConsoleRoute("/onboarding").panelId).toBe("onboarding");
  });

  test("resets scroll only when navigation changes the pathname", () => {
    expect(shouldResetScroll("/agents", "/agent-activity")).toBe(true);
    expect(shouldResetScroll("/agent-activity", "/agent-activity/")).toBe(false);
    expect(shouldResetScroll("/agent-activity", "/agent-activity")).toBe(false);
  });
});
