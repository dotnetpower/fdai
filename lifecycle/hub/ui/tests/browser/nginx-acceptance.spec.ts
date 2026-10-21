import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

test("nginx acceptance is distinct from FDAI across vendor views without deployment calls", async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const directory = resolve("../../release-hub/ui/dist");
  const image = `sha256:${"a".repeat(64)}`;
  const manifest = JSON.stringify({
    schema_version: "fdai.nginx-acceptance-release.v1",
    release_version: "1.5.0", source_commit: "a".repeat(40),
    platform_tag: "linux-x86_64", workloads: { nginx: { image_digest: image } },
  });
  const release = {
    id: "1.5.0", label: "Synthetic nginx acceptance", manifest,
    digest: "b".repeat(64), signed_payload_sha256: "c".repeat(64),
    signature: "synthetic-signature", signature_status: "development-verified",
    state: "published", channels: ["DEV"], published_at: "2026-10-21T03:00:00Z",
    recalled_at: null,
  };
  const catalog = {
    revision: 2, updated_at: "2026-10-21T03:00:00Z", expires_at: "2026-10-22T03:00:00Z",
    expired: false, key_id: "synthetic-vendor-key", mode: "development",
    releases: [release], channels: { DEV: ["1.5.0"], RELEASE_CANDIDATE: [], RELEASE: [] },
    events: [],
  };
  const errors: string[] = [];
  const writes: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/*", async route => {
    const request = route.request();
    const url = new URL(request.url());
    expect(url.origin).toBe("https://hub.test");
    if (request.method() !== "GET") writes.push(url.pathname);
    if (url.pathname === "/auth/config") {
      return route.fulfill({ json: { profile: "local-development" } });
    }
    if (url.pathname === "/v1/catalog") return route.fulfill({ json: catalog });
    expect(url.pathname.startsWith("/v1/")).toBe(false);
    const file = url.pathname.startsWith("/assets/") || url.pathname.startsWith("/brand/")
      ? url.pathname : "/index.html";
    return route.fulfill({
      body: await readFile(resolve(directory, `.${file}`)),
      contentType: file.endsWith(".js") ? "text/javascript" : file.endsWith(".css")
        ? "text/css" : file.endsWith(".png") ? "image/png" : "text/html",
    });
  });
  await page.goto("https://hub.test/#/releases");
  await page.getByRole("link", { name: /nginx acceptance 1.5.0/ }).click();
  await expect(page.getByRole("heading", { name: "nginx acceptance 1.5.0", exact: true })).toBeVisible();
  await expect(page.getByText("Not applicable (nginx acceptance; no database)", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "nginx", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Add to channel", exact: true })).toHaveCount(0);
  await expect(page.getByText("undefined", { exact: false })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("nginx-acceptance-desktop.png"), fullPage: true });
  await page.getByRole("button", { name: "Recall release", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("nginx acceptance 1.5.0");
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.getByRole("link", { name: "Channels", exact: true }).click();
  await page.getByRole("link", { name: "nginx acceptance 1.5.0", exact: true }).click();
  for (const width of [993, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await expect(page.getByRole("heading", { name: "nginx acceptance 1.5.0", exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  expect(errors).toEqual([]);
  expect(writes).toEqual([]);
});
