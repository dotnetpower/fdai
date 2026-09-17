import { expect, test } from "@playwright/test";

for (const backend of ["gateway", "direct"]) {
  for (const initialStatus of [504, 401]) {
    test(`${backend} API recovers authenticated clients after startup ${initialStatus}`, async ({ page }) => {
      const apiBase = `https://${backend}.example.com`;
      let accessChecks = 0;
      const contextHeaders: (string | undefined)[] = [];
      const writes: string[] = [];
      await page.route("**/fdai-config.js", (route) => route.fulfill({
        contentType: "application/javascript", body: "",
      }));
      await page.addInitScript((base) => {
        globalThis.__FDAI_CONSOLE_CONFIG__ = {
          schema_version: "fdai.console-runtime.v1",
          operator_api_base_url: base,
          ingestion_api_base_url: `${base}/ingestion`,
          tenant_id: "00000000-0000-0000-0000-000000000000",
          spa_client_id: "00000000-0000-0000-0000-000000000000",
          api_scope: "api://00000000-0000-0000-0000-000000000000/access",
        };
      }, apiBase);
      await page.route("**/src/auth.ts*", (route) => route.fulfill({
        contentType: "application/javascript",
        body: `export async function initAuth() { return {
          devMode: false, interactiveSignIn: false,
          account: { homeAccountId: "example-operator", localAccountId: "example-operator",
            username: "operator@example.com", idTokenClaims: { roles: ["Owner"] } },
          getAuthorizationHeader: async () => "Bearer test-only",
          signIn: async () => {}, signOut: async () => {}
        }; }`,
      }));
      await page.route(`${apiBase}/**`, async (route) => {
        const request = route.request();
        const path = new URL(request.url()).pathname;
        if (request.method() !== "GET") writes.push(path);
        if (path === "/iam/self") {
          accessChecks += 1;
          expect(request.headers()["authorization"]).toBe("Bearer test-only");
          if (accessChecks === 1) {
            return route.fulfill({ status: initialStatus, json: { error: { message: "Startup access failed" } } });
          }
          return route.fulfill({ json: {
            principal: { subject_id: "example-operator", username: "operator@example.com", roles: ["Owner"] },
            request: null, can_access_console: true,
          } });
        }
        if (path === "/me/context") {
          contextHeaders.push(request.headers()["authorization"]);
          if (!request.headers()["authorization"]) {
            return route.fulfill({ status: 401, json: { error: { message: "Authentication required" } } });
          }
          return route.fulfill({ json: {
            preference: null, memories: [], policies: [], subscriptions: [], briefing_runs: [],
            scheduled_continuations: [], conversations: [],
            conversation_page: { has_more: false, next_cursor: null },
          } });
        }
        if (path === "/system/data-sources") {
          return route.fulfill({ json: { surface: "read-data-sources", sources: [] } });
        }
        return route.fulfill({ status: 503, json: { error: { message: "Test-only source unavailable" } } });
      });

      await page.goto("/overview?locale=en");
      const retry = page.getByRole("button", { name: "Retry access check", exact: true });
      await expect(retry).toBeVisible();
      expect(accessChecks).toBe(1);
      expect(contextHeaders).toEqual([]);
      await retry.click();
      await expect(retry).toHaveCount(0);
      await page.locator(".deck-invoke").click();
      await expect(page.locator(".deck-overlay")).toBeVisible();
      await expect.poll(() => contextHeaders.length).toBeGreaterThan(0);
      expect(contextHeaders.every((header) => header === "Bearer test-only")).toBe(true);
      await expect(retry).toHaveCount(0);
      await expect(page.locator("nav").first()).toBeVisible();
      expect(accessChecks).toBe(2);
      expect(writes).toEqual([]);
    });
  }
}
