import { readFile } from "node:fs/promises";

import { describe, expect, it } from "vitest";

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
});
