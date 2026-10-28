import { readFile } from "node:fs/promises";

import { describe, expect, it } from "vitest";

import { registeredPanelRoutes } from "../../src/router";

describe("live Console route authentication", () => {
  it("restores Browser Entra session storage and rejects the access-error surface", async () => {
    const source = await readFile(
      new URL("./console-routes.spec.ts", import.meta.url),
      "utf8",
    );
    const routeSweep = source.slice(
      source.indexOf("for (const routePath of ROUTES)"),
      source.indexOf('test("the live route inventory stays synchronized'),
    );

    expect(routeSweep.indexOf("restoreBrowserEntraSessionStorage(page)")).toBeGreaterThan(-1);
    expect(routeSweep.indexOf("restoreBrowserEntraSessionStorage(page)"))
      .toBeLessThan(routeSweep.indexOf("page.goto(routePath"));
    expect(routeSweep).toContain(
      '"Authentication token unavailable for signed-in account."',
    );
  });

  it("keeps the live E2E ROUTES inventory synchronized with all 63 registered panels", async () => {
    const source = await readFile(
      new URL("./console-routes.spec.ts", import.meta.url),
      "utf8",
    );
    const routesBlock = source.slice(
      source.indexOf("const ROUTES = ["),
      source.indexOf("] as const;"),
    );
    const declaredRoutes = [...routesBlock.matchAll(/"(\/[^"]+)"/g)]
      .map((match) => match[1]!)
      .sort();
    const registeredPaths = registeredPanelRoutes()
      .map((route) => route.path)
      .sort();

    expect(declaredRoutes).toHaveLength(63);
    expect(declaredRoutes).toEqual(registeredPaths);
  });

  it("skips sandboxed child iframes when restoring Browser Entra session storage", async () => {
    const source = await readFile(
      new URL("./browser-entra-state.ts", import.meta.url),
      "utf8",
    );

    expect(source).toContain("if (window !== window.top) return;");
  });
});
