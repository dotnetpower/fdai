import { expect, test, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const digest = "a".repeat(64);
const initial = {
  approved_revision: 0, approved_sha256: null as string | null,
  minimum_revision: 0, accepted_sha256: null as string | null,
  imported: false, mode: "development-pinned-export",
};

async function assets(page: Page, directory: string) {
  await page.route("https://hub.test/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.startsWith("/v1/") || path === "/auth/config") {
      throw new Error(`Unexpected API request: ${path}`);
    }
    const file = path.startsWith("/assets/") || path.startsWith("/brand/") ? path : "/index.html";
    const contentType = file.endsWith(".js") ? "text/javascript" :
      file.endsWith(".css") ? "text/css" : file.endsWith(".svg") ? "image/svg+xml" : "text/html";
    await route.fulfill({ body: await readFile(resolve(directory, `.${file}`)), contentType });
  });
}

for (const width of [1440, 390]) {
  test(`approved pin, explicit import, Plan and rejection at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    await assets(page, resolve("dist"));
    let trust = { ...initial };
    await page.route("**/auth/config", route => route.fulfill({ json: { profile: "local-development" } }));
    await page.route("**/v1/catalog/trust", route => route.fulfill({ json: trust }));
    await page.route("**/v1/catalog/trust/approve", async route => {
      const body = route.request().postDataJSON();
      expect(body).toEqual({
        revision: 4, sha256: digest, reason: "Independent customer review",
        confirmation: `approve 4 ${digest}`,
      });
      trust = { ...trust, approved_revision: 4, approved_sha256: digest };
      await route.fulfill({ json: trust });
    });
    let imported = false;
    await page.route("**/v1/catalog/import", async route => {
      expect(trust.approved_sha256).toBe(digest);
      if (imported) return route.fulfill({ status: 422, json: { error: "tampered_export" } });
      trust = { ...trust, minimum_revision: 4, accepted_sha256: digest, imported: true };
      imported = true;
      await route.fulfill({ json: trust });
    });
    await page.route("**/v1/installations/synthetic-installation/recompute", route =>
      route.fulfill({ json: { outcome: "issued", checks: [], plan_id: "synthetic-plan" } }));
    await page.goto("https://hub.test/catalog");
    await expect(page.getByRole("button", { name: "Import approved catalog" })).toBeDisabled();
    await page.getByLabel("Revision", { exact: true }).fill("4");
    await page.getByLabel("SHA-256", { exact: true }).fill(digest);
    await page.getByLabel("Approval reason").fill("Independent customer review");
    await page.getByLabel("Type approve, revision and digest separated by spaces").fill(`approve 4 ${digest}`);
    await page.getByRole("button", { name: "Approve exact pin" }).click();
    await expect(page.getByRole("button", { name: "Import approved catalog" })).toBeEnabled();
    await page.getByRole("button", { name: "Import approved catalog" }).click();
    await expect(page.getByRole("button", { name: "Compute Plan" })).toBeEnabled();
    await page.getByLabel("Installation ID").fill("synthetic-installation");
    await page.getByRole("button", { name: "Compute Plan" }).click();
    await expect(page.getByRole("status")).toContainText("issued");
    await page.getByRole("button", { name: "Import approved catalog" }).click();
    await expect(page.getByRole("alert")).toContainText("Request rejected");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.evaluate(() => scrollTo(0, 0));
    await page.screenshot({ path: info.outputPath(`catalog-${width}.png`), fullPage: true });
  });
}

for (const kind of ["target", "release"]) {
  test(`${kind} remote profile exposes login, never business API before authentication`, async ({ page }) => {
    await assets(page, kind === "target" ? resolve("dist") : resolve("../../release-hub/ui/dist"));
    await page.route("**/auth/config", route => route.fulfill({ json: {
      profile: "remote-development", origin: "https://hub.test",
      clientId: "00000000-0000-0000-0000-000000000001",
      authority: "https://login.microsoftonline.com/00000000-0000-0000-0000-000000000000",
      scope: "api://synthetic-api/Hub.Access",
    } }));
    await page.route("https://login.microsoftonline.com/**", () => {
      throw new Error("Live access is not authorized.");
    });
    await page.goto("https://hub.test/");
    await expect(page.getByRole("button", { name: "Sign in with Microsoft Entra ID" })).toBeVisible();
    await expect(page.getByText("This is not a production trust root.", { exact: false })).toBeVisible();
  });
}
