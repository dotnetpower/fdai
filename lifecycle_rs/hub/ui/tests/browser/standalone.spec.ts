import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const scenarios = [
  { name: "ready", health: "ok", ready: "ok" },
  { name: "not-ready", health: "ok", ready: "http-error" },
  { name: "health-network-failure", health: "network", ready: "ok" },
  { name: "health-invalid-json", health: "invalid-json", ready: "ok" },
  { name: "health-timeout", health: "timeout", ready: "ok" },
  { name: "health-unavailable", health: "http-error", ready: "ok" },
  { name: "readiness-network-failure", health: "ok", ready: "network" },
  { name: "readiness-invalid-json", health: "ok", ready: "invalid-json" },
  { name: "readiness-timeout", health: "ok", ready: "timeout" },
] as const;

for (const product of ["lifecycle", "release"]) {
  for (const scenario of scenarios) {
    test(`${product} independent UI ${scenario.name}`, async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 900 });
      const directory = product === "lifecycle" ? resolve("dist") :
        resolve("../../release-hub/ui/dist");
      const requests: string[] = [];
      await page.route("**/*", async route => {
        const url = new URL(route.request().url());
        requests.push(url.pathname);
        expect(url.origin).toBe("https://hub.test");
        expect(url.pathname.startsWith("/v1")).toBe(false);
        if (url.pathname === "/auth/config") {
          return route.fulfill({ json: {
            profile: "remote-unconfigured", product, origin: "https://hub.test",
            management: "unavailable", reason: "operator_auth_not_configured",
          } });
        }
        if (url.pathname === "/healthz" || url.pathname === "/readyz") {
          const outcome = url.pathname === "/healthz" ? scenario.health : scenario.ready;
          if (outcome === "network") return route.abort("connectionfailed");
          if (outcome === "timeout") return;
          if (outcome === "invalid-json") return route.fulfill({
            body: "{", contentType: "application/json",
          });
          return route.fulfill({
            status: outcome === "ok" ? 200 : 503,
            json: { status: url.pathname === "/healthz" ? "ok" : "ready" },
          });
        }
        const file = url.pathname.startsWith("/assets/") ? url.pathname : "/index.html";
        return route.fulfill({
          body: await readFile(resolve(directory, `.${file}`)),
          contentType: file.endsWith(".js") ? "text/javascript" :
            file.endsWith(".css") ? "text/css" : "text/html",
        });
      });
      await page.goto("https://hub.test/");
      await expect(page.getByRole("heading", { name: product === "release" ?
        "FDAI Release Hub" : "FDAI Lifecycle Hub" })).toBeVisible();
      await expect(page.getByRole("status")).toContainText(
        scenario.ready === "ok" ? "Database schema ready" : "Database readiness unavailable",
        { timeout: 10_000 });
      await expect(page.getByRole("status")).toContainText(
        scenario.health === "ok" ? "API process responding" : "API health unavailable",
        { timeout: 10_000 });
      await expect(page.getByText("Management APIs are unavailable.", { exact: false })).toBeVisible();
      await expect(page.getByRole("button", { name: /sign in/i })).toHaveCount(0);
      expect(requests).toContain("/healthz");
      expect(requests).toContain("/readyz");
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      for (const width of [993, 390]) {
        await page.setViewportSize({ width, height: 844 });
        await expect(page.getByRole("status")).toBeVisible();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      }
    });
  }
}
