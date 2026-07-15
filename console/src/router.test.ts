import { describe, expect, test } from "vitest";
import { legacyHashHref, panelPath, parseConsoleRoute, routeHref } from "./router";

describe("clean console routes", () => {
  test("maps internal panel ids to user-facing kebab-case paths", () => {
    expect(panelPath("dashboard")).toBe("/overview");
    expect(panelPath("hil-queue")).toBe("/approvals");
    expect(panelPath("agent-activity")).toBe("/agent-activity");
    expect(panelPath("labs")).toBe("/labs");
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

  test("marks unknown and root paths for canonical Overview replacement", () => {
    for (const pathname of ["/", "/typo", "/typo/detail"]) {
      const route = parseConsoleRoute(pathname);
      expect(route.panelId).toBe("dashboard");
      expect(route.matched).toBe(false);
      expect(route.canonicalPathname).toBe("/overview");
      expect(route.segments).toEqual([]);
    }
  });

  test("migrates legacy hash bookmarks", () => {
    expect(legacyHashHref("#/dashboard")).toBe("/overview");
    expect(legacyHashHref("#%2Fhil-queue")).toBe("/approvals");
    expect(legacyHashHref("#/audit?correlation=corr-1")).toBe(
      "/audit?correlation=corr-1",
    );
  });
});