import { expect, test, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

async function localSource(page: Page, options: {
  source?: "local-default" | "saved"; previewFails?: boolean; settingsFail?: boolean;
} = {}) {
  const reads: string[] = [];
  const writes: string[] = [];
  await page.route("https://hub.test/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() !== "GET") writes.push(path);
    if (path === "/auth/config") return route.fulfill({ json: { profile: "local-development" } });
    if (path.startsWith("/v1/")) reads.push(path);
    if (path === "/v1/release-hub/connection") return route.fulfill(options.settingsFail
      ? { status: 503, json: { error: "release_hub_settings_unavailable" } }
      : { json: {
        endpoint: "http://127.0.0.1:8091",
        configured_endpoint: options.source === "saved" ? "http://127.0.0.1:8091" : null,
        revision: 0, source: options.source ?? "local-default", editable: true,
        requires_migration: false,
      } });
    if (path === "/v1/release-hub/catalog") return route.fulfill(options.previewFails
      ? { status: 503, json: { error: "release_hub_catalog_unavailable" } }
      : { json: { endpoint: "http://127.0.0.1:8091", revision: 0, mode: "local-development",
        expired: true, releases: [], release_count: 0, build_verification: "not-performed",
        trusted: false } });
    if (path.startsWith("/v1/")) {
      throw new Error(`Local source must not call a trusted catalog API: ${path}`);
    }
    const file = path.startsWith("/assets/") ? path : "/index.html";
    return route.fulfill({
      body: await readFile(resolve("dist", `.${file}`)),
      contentType: file.endsWith(".js") ? "text/javascript" :
        file.endsWith(".css") ? "text/css" : "text/html",
    });
  });
  return { reads, writes };
}

for (const path of ["/updates", "/available-releases"]) {
  for (const source of ["local-default", "saved"] as const) {
    test(`${path} ${source} shows prerequisites and real empty preview without trusted reads`, async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 900 });
      const { reads, writes } = await localSource(page, { source });
      await page.goto(`https://hub.test${path}`);
      await expect(page.getByText("Trusted catalog is not configured", { exact: true })).toBeVisible();
      await expect(page.getByText("No releases registered in the selected Release Hub.", { exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "Check now", exact: true })).toHaveCount(0);
      await expect(page.getByRole("alert")).toHaveCount(0);
      await expect(page.getByRole("link", { name: "Review Release Hub connection and trust setup" }))
        .toHaveAttribute("href", "/catalog");
      await page.getByRole("button", { name: "Refresh preview" }).click();
      await expect.poll(() => reads.filter(path => path === "/v1/release-hub/catalog").length).toBe(2);
      expect(writes).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.getByRole("button", { name: "Switch workspace language" }).click();
      await expect(page.getByText("신뢰된 카탈로그가 구성되지 않았습니다", { exact: true })).toBeVisible();
      await expect(
        page.getByRole("heading", {
          name: path === "/updates" ? "업데이트" : "사용 가능한 릴리스",
          exact: true,
        }),
      ).toBeVisible();
      await expect(page.getByRole("link", { name: "카탈로그 가져오기", exact: true })).toHaveCount(0);
    });
  }

  test(`${path} a failed preview stays an error, never a successful empty catalog`, async ({ page }) => {
    const { writes } = await localSource(page, { previewFails: true });
    await page.goto(`https://hub.test${path}`);
    await expect(page.getByRole("alert")).toContainText("release_hub_catalog_unavailable");
    await expect(page.getByText("No releases registered in the selected Release Hub.")).toHaveCount(0);
    expect(writes).toEqual([]);
  });

  test(`${path} settings failure does not infer a local default`, async ({ page }) => {
    const { reads } = await localSource(page, { settingsFail: true });
    await page.goto(`https://hub.test${path}`);
    await expect(page.getByRole("alert")).toContainText("release_hub_settings_unavailable");
    expect(reads).toEqual(["/v1/release-hub/connection"]);
  });
}
