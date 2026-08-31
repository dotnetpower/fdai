import { expect, test, type Page, type Route, type TestInfo } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";

const snapshot = {
  schema_version: "fdai.provision-status.v1",
  type: "provision.snapshot",
  run_id: "run.genesis-example",
  sequence: 31,
  attempt: 1,
  state: "applying",
  current_stage: "initial-inventory",
  stages_completed: 4,
  stages_total: 6,
  checkpoints_completed: 18,
  checkpoints_total: 24,
  last_progress_at: "2026-08-31T02:20:00+00:00",
  reason_code: null,
  ready: false,
  readiness: {
    database: true,
    semantic: true,
    models: true,
    runtime: true,
    inventory: false,
    system: false,
  },
  stages: [
    { id: "database", status: "completed" },
    { id: "semantic-defaults", status: "completed" },
    { id: "model-deployments", status: "completed" },
    { id: "console", status: "completed" },
    { id: "initial-inventory", status: "active" },
    { id: "system-readiness", status: "pending" },
  ],
  inventory: {
    resources_observed: 184,
    resources_expected: 260,
    pages_completed: 12,
    pages_expected: 18,
  },
};

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function installProvisioningFixture(page: Page): Promise<void> {
  const handle = async (route: Route): Promise<void> => {
    if (route.request().resourceType() === "document") {
      await route.continue();
      return;
    }
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api(?=\/)/, "");
    if (path === "/system/data-sources") {
      await json(route, {
        surface: "read-data-sources",
        sources: [{
          key: "provisioning-stream",
          source: "browser-test-fixture",
          routes: ["/provision/stream"],
          availability: "available",
          configured: true,
          reachable: true,
          authoritative: true,
          durable: true,
          synthetic: true,
          reason: null,
          last_observed_at: snapshot.last_progress_at,
        }],
      });
      return;
    }
    if (path === "/provision/stream") {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: `data: ${JSON.stringify(snapshot)}\n\n`,
      });
      return;
    }
    await json(route, { detail: `unmocked browser-test route: ${url.pathname}` }, 404);
  };
  await page.route("**/api/**", handle);
  await page.route("**/system/data-sources*", handle);
  await page.route("**/provision/stream*", handle);
}

async function assertNoHorizontalOverflow(page: Page): Promise<void> {
  const dimensions = await page.locator("html").evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
}

async function capture(page: Page, testInfo: TestInfo, name: string): Promise<void> {
  const screenshot = await page.screenshot({ fullPage: true });
  await testInfo.attach(name, {
    body: screenshot,
    contentType: "image/png",
  });
  const captureRoot = process.env.FDAI_PROVISION_VISUAL_CAPTURE_ROOT;
  if (!captureRoot) return;
  await mkdir(captureRoot, { recursive: true });
  await writeFile(`${captureRoot}/${name}.png`, screenshot);
}

test("shows verified setup stages and estimated resource discovery", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "Sequential viewport gate runs once.");
  await installProvisioningFixture(page);

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/provisioning");

  await expect(page.getByRole("heading", { name: "Setup stages" })).toBeVisible();
  await expect(page.getByText("4 of 6 stages completed")).toBeVisible();
  await expect(page.getByText("184 observed / 260 estimated")).toBeVisible();
  await expect(page.getByText("Awaiting independent verification")).toBeVisible();
  await expect(page.getByText("Subscription setup is verified and ready.")).toHaveCount(0);
  await assertNoHorizontalOverflow(page);
  await capture(page, testInfo, "provisioning-desktop");

  await page.setViewportSize({ width: 993, height: 641 });
  await assertNoHorizontalOverflow(page);
  await capture(page, testInfo, "provisioning-constrained");

  await page.setViewportSize({ width: 390, height: 844 });
  await assertNoHorizontalOverflow(page);
  await expect(page.getByText("initial-inventory")).toBeVisible();
  const headerBox = await page.locator(".provision > .page-header").boundingBox();
  expect(headerBox).not.toBeNull();
  expect((headerBox?.x ?? 0) + (headerBox?.width ?? 0)).toBeLessThanOrEqual(390);
  await capture(page, testInfo, "provisioning-mobile");
});
