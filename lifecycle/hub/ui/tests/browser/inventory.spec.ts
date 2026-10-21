import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const release = {
  release_id: "1.0.0", digest: "a".repeat(64), source_commit: "b".repeat(40),
  platform_tag: "linux-x86_64", channels: ["DEV"], schema_target: 15,
  schema_range: { minimum: 12, maximum: 16 },
  images: [{ section: "services", component: "core-control-plane", image_digest: `sha256:${"c".repeat(64)}` }],
  recall_notices: [{ sequence: 1, action: "recall", notice_digest: "d".repeat(64) }],
};
const configuration = {
  digest: "e".repeat(64), imported_at: "2026-10-01T00:00:00Z",
  schema_key_count: 1, override_count: 0, installation_ids: ["installation-alpha"],
  signature_status: "not-recorded",
};

for (const view of ["releases", "configurations"] as const) {
  for (const state of ["populated", "empty", "unavailable"] as const) {
    test(`${view} inventory ${state}`, async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 900 });
      const path = view === "releases" ? "/available-releases" : "/configuration-packages";
      const api = view === "releases" ? "/v1/catalog/releases" : "/v1/configurations";
      const title = view === "releases" ? "Available releases" : "Configuration packages";
      let reads = 0;
      const writes: string[] = [];
      await page.route("https://hub.test/**", async route => {
        const request = route.request();
        const pathname = new URL(request.url()).pathname;
        if (!["GET", "HEAD"].includes(request.method())) writes.push(request.method());
        if (pathname === "/auth/config") return route.fulfill({ json: { profile: "local-development" } });
        if (pathname === api) {
          reads += 1;
          if (reads === 1) {
            await expect(page.getByRole("status", { name: "Loading Hub data" })).toBeVisible();
            await expect(page.getByRole("button", { name: "Refresh", exact: true })).toBeDisabled();
          }
          if (state === "unavailable") {
            return route.fulfill({ status: 503, json: { error: "catalog_unavailable_review_trust_and_expiry" } });
          }
          return route.fulfill({ json: view === "releases"
            ? { releases: state === "empty" ? [] : [release] }
            : { configurations: state === "empty" ? [] : [configuration] } });
        }
        if (pathname.startsWith("/v1/")) return route.fulfill({ status: 404, json: { error: "not_found" } });
        const file = pathname.startsWith("/assets/") ? pathname : "/index.html";
        return route.fulfill({
          body: await readFile(resolve("dist", `.${file}`)),
          contentType: file.endsWith(".js") ? "text/javascript" :
            file.endsWith(".css") ? "text/css" : "text/html",
        });
      });
      await page.goto(`https://hub.test${path}`);
      await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
      await expect(page.getByRole("link", { name: title, exact: true })).toHaveAttribute("aria-current", "page");
      if (state === "unavailable") {
        await expect(page.getByRole("alert")).toContainText("catalog_unavailable_review_trust_and_expiry");
        await page.getByRole("button", { name: "Try again", exact: true }).click();
      } else {
        if (state === "empty") {
          await expect(page.getByText(view === "releases"
            ? "The verified catalog contains no releases." : "No configuration revisions stored.")).toBeVisible();
        } else if (view === "releases") {
          const disclosure = page.locator("summary");
          await disclosure.focus();
          await page.keyboard.press("Enter");
          await expect(page.getByText(release.images[0]!.image_digest, { exact: true })).toBeVisible();
          await expect(page.getByRole("listitem").filter({ hasText: "Sequence 1: recall" })).toBeVisible();
          await expect(page.getByText("12 to 16", { exact: true })).toBeVisible();
        } else {
          await expect(page.getByRole("link", { name: "installation-alpha" }))
            .toHaveAttribute("href", "/installations/installation-alpha");
          await expect(page.getByRole("cell", { name: "Not recorded", exact: true })).toBeVisible();
          await expect(page.getByText("Stored configuration revisions, not verified signed packages"))
            .toBeVisible();
        }
        await page.getByRole("button", { name: "Refresh", exact: true }).click();
      }
      await expect.poll(() => reads).toBe(2);
      if (state === "populated" && view === "releases") {
        await page.locator("summary").click();
        await expect(page.getByText(release.images[0]!.image_digest, { exact: true })).toBeVisible();
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect(await page.locator("main").evaluate(main => main.scrollWidth <= main.clientWidth)).toBe(true);
      for (const width of [993, 390]) {
        await page.setViewportSize({ width, height: 844 });
        await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        expect(await page.locator("main").evaluate(main => main.scrollWidth <= main.clientWidth)).toBe(true);
      }
      expect(writes).toEqual([]);
      await expect(page.locator("nav [aria-disabled=true]")).toHaveCount(4);
    });
  }
}
