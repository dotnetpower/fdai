import { expect, test, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

async function catalog(page: Page, revision: number) {
  const writes: string[] = [];
  await page.route("https://hub.test/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() !== "GET") writes.push(path);
    if (path === "/auth/config") return route.fulfill({ json: { profile: "local-development" } });
    if (path === "/v1/auth/session") return route.fulfill({ json: {
      signed_in: false, workstation_accounts: [],
    } });
    if (path === "/v1/catalog") return route.fulfill({ json: {
      revision, updated_at: "2026-01-01T00:00:00Z", expires_at: "2026-01-02T00:00:00Z",
      expired: true, mode: "local-development", key_id: "development",
      releases: [], channels: {}, events: [], export_sha256: "a".repeat(64),
    } });
    if (path.startsWith("/v1/")) throw new Error(`Unexpected catalog write or request: ${path}`);
    const file = path.startsWith("/assets/") || path.startsWith("/brand/") ? path : "/index.html";
    return route.fulfill({
      body: await readFile(resolve("../../release-hub/ui/dist", `.${file}`)),
      contentType: file.endsWith(".js") ? "text/javascript" :
        file.endsWith(".css") ? "text/css" : file.endsWith(".png") ? "image/png" : "text/html",
    });
  });
  return writes;
}

test("initial trust distinguishes empty metadata and unverified health without a write", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const writes = await catalog(page, 0);
  await page.goto("https://hub.test/#/trust");
  await expect(page.getByText("Initial catalog:", { exact: false })).toBeVisible();
  await expect(page.locator("p.warning")).toHaveCount(0);
  await expect(page.getByText("The empty export metadata is expired", { exact: false })).toBeVisible();
  await expect(page.getByText("No active recalls recorded. Health not verified.", { exact: true })).toBeVisible();
  await expect(page.getByText("None (All capabilities healthy)", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("Audit reason", { exact: true })).toHaveValue("");
  await page.getByRole("button", { name: "Renew catalog freshness", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  expect(writes).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("renewed or previously populated catalogs retain real expiry warnings", async ({ page }) => {
  const writes = await catalog(page, 1);
  await page.goto("https://hub.test/#/trust");
  await expect(page.locator("p.warning")).toContainText("Catalog export expired");
  await expect(page.getByText("Initial catalog:", { exact: false })).toHaveCount(0);
  expect(writes).toEqual([]);
});
