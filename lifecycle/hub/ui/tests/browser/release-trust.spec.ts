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
  await page.getByText("Configure surgical capability recall or lift", { exact: true }).click();
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

test("1-click release creation composes, registers, and signs 0.5.0 into DEV without modal friction", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const digest = "b".repeat(64);
  const writes: string[] = [];
  let currentCatalog = {
    revision: 0,
    updated_at: "2026-11-04T00:00:00Z",
    expires_at: "2026-11-05T00:00:00Z",
    expired: false,
    mode: "local-development",
    key_id: "development",
    releases: [] as unknown[],
    channels: { DEV: [] as string[], RELEASE_CANDIDATE: [] as string[], RELEASE: [] as string[] },
    events: [] as unknown[],
    export_sha256: digest,
  };
  await page.route("https://hub.test/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() !== "GET") writes.push(path);
    if (path === "/auth/config") return route.fulfill({ json: { profile: "local-development" } });
    if (path === "/v1/auth/session") return route.fulfill({ json: { signed_in: false, workstation_accounts: [] } });
    if (path === "/v1/catalog") return route.fulfill({ json: currentCatalog });
    if (path === "/v1/stencils") {
      return route.fulfill({
        json: {
          presets: [{
            stencil: {
              schema_version: "fdai.stencil-definition.v1",
              stencil_id: "lite-observe-alert",
              title: "Lite",
              title_ko: "경량",
              description: "Lite",
              description_ko: "경량",
              topology_profile: "lite-observe-alert",
              enabled_workloads: ["core-control-plane", "operator-service"],
              enabled_scheduled_jobs: ["analyzer", "inventory"],
              enabled_loops: ["anomaly-analyzer", "inventory-reconciliation", "notification-dispatch", "saga-audit"],
              enabled_addons: ["notifications", "read-only-console"],
              enabled_panel_ids: ["audit", "dashboard", "live", "settings-general"],
              authority_granted: false,
            },
            footprint: {
              stencil_id: "lite-observe-alert",
              stencil_digest: `sha256:${digest}`,
              topology_profile: "lite-observe-alert",
              workload_count: 2,
              total_workloads: 5,
              omitted_workloads: [],
              scheduled_job_count: 2,
              omitted_scheduled_jobs: [],
              includes_clamav_sidecar: false,
              includes_privileged_executor: false,
              enabled_panel_count: 4,
              total_panel_count: 60,
              omitted_panel_count: 56,
              active_navigation_groups: ["overview"],
              enabled_feature_ids: ["F01.1"],
              azure_rbac_posture: "read-only-observation",
              required_azure_roles: ["Reader"],
              terraform_flags: {},
              console_build_command: "npm run build",
            },
          }],
          panels: [],
          locked_panels: ["dashboard"],
          locked_workloads: ["core-control-plane", "operator-service"],
          locked_scheduled_jobs: ["analyzer", "inventory"],
          locked_loops: ["anomaly-analyzer"],
          locked_addons: ["notifications"],
        },
      });
    }
    if (path === "/v1/stencils/compose" && request.method() === "POST") {
      const body = request.postDataJSON() as { release_version: string };
      return route.fulfill({
        json: {
          stencil: {
            schema_version: "fdai.stencil-definition.v1",
            stencil_id: "lite-observe-alert",
            title: "Lite",
            title_ko: "경량",
            description: "Lite",
            description_ko: "경량",
            topology_profile: "lite-observe-alert",
            enabled_workloads: ["core-control-plane", "operator-service"],
            enabled_scheduled_jobs: ["analyzer", "inventory"],
            enabled_loops: ["anomaly-analyzer"],
            enabled_addons: ["notifications"],
            enabled_panel_ids: ["dashboard"],
            authority_granted: false,
          },
          footprint: {
            stencil_id: "lite-observe-alert",
            stencil_digest: `sha256:${digest}`,
            topology_profile: "lite-observe-alert",
            workload_count: 2,
            total_workloads: 5,
            omitted_workloads: [],
            scheduled_job_count: 2,
            omitted_scheduled_jobs: [],
            includes_clamav_sidecar: false,
            includes_privileged_executor: false,
            enabled_panel_count: 4,
            total_panel_count: 60,
            omitted_panel_count: 56,
            active_navigation_groups: ["overview"],
            enabled_feature_ids: ["F01.1"],
            azure_rbac_posture: "read-only-observation",
            required_azure_roles: ["Reader"],
            terraform_flags: {},
            console_build_command: "npm run build",
          },
          release_manifest: {
            schema_version: "fdai.application-release.v2",
            product: "fdai",
            release_version: body.release_version,
            source_commit: "a".repeat(40),
            platform_tag: "linux-x86_64",
            components: {
              "core-control-plane": { image_digest: `sha256:${digest}` },
              "operator-service": { image_digest: `sha256:${digest}` },
            },
          },
        },
      });
    }
    if (path === "/v1/releases/0.5.0/register" && request.method() === "POST") {
      currentCatalog = {
        ...currentCatalog,
        revision: 1,
        releases: [{
          id: "0.5.0",
          label: "lite-observe-alert (4 menus, 2 workloads)",
          manifest: "{}",
          digest,
          signed_payload_sha256: digest,
          signature: null,
          signature_status: "unsigned",
          state: "draft",
          channels: [],
          published_at: null,
          recalled_at: null,
        }],
      };
      return route.fulfill({ json: currentCatalog });
    }
    if (path === "/v1/releases/0.5.0/publish" && request.method() === "POST") {
      currentCatalog = {
        ...currentCatalog,
        revision: 2,
        releases: [{
          id: "0.5.0",
          label: "lite-observe-alert (4 menus, 2 workloads)",
          manifest: "{}",
          digest,
          signed_payload_sha256: digest,
          signature: "sig",
          signature_status: "verified",
          state: "published",
          channels: ["DEV"],
          published_at: "2026-11-04T00:01:00Z",
          recalled_at: null,
        }],
        channels: { DEV: ["0.5.0"], RELEASE_CANDIDATE: [], RELEASE: [] },
      };
      return route.fulfill({ json: currentCatalog });
    }
    const file = path.startsWith("/assets/") || path.startsWith("/brand/") ? path : "/index.html";
    return route.fulfill({
      body: await readFile(resolve("../../release-hub/ui/dist", `.${file}`)),
      contentType: file.endsWith(".js") ? "text/javascript" :
        file.endsWith(".css") ? "text/css" : file.endsWith(".png") ? "image/png" : "text/html",
    });
  });

  await page.goto("https://hub.test/#/releases");
  await expect(page.getByRole("button", { name: "1-Click Create Release (0.5.0)" })).toBeVisible();
  await page.getByRole("button", { name: "1-Click Create Release (0.5.0)" }).click();
  await expect(page.getByRole("status")).toContainText("1-Click release created: Release 0.5.0");
  await expect(page.getByText("1 releases", { exact: true })).toBeVisible();
  expect(writes).toEqual([
    "/v1/stencils/compose",
    "/v1/releases/0.5.0/register",
    "/v1/releases/0.5.0/publish",
  ]);
});
