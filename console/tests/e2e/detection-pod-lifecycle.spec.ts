import { expect, test, type Page, type Route } from "@playwright/test";

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const lifecycle: unknown = JSON.parse(
  readFileSync(
    fileURLToPath(new URL("../../src/routes/fixtures/detection-lifecycle-projection.json", import.meta.url)),
    "utf-8",
  ),
);

const readiness = {
  source: "muninn-state-snapshot",
  observed_at: "2026-08-31T12:00:00Z",
  target_count: 0,
  counts: { ready: 0, partial: 0, blocked: 0, stale: 0, unauthorized: 0, unknown: 0 },
  targets: [],
  lifecycle,
};

async function installFixture(page: Page): Promise<void> {
  const handle = async (route: Route): Promise<void> => {
    if (route.request().resourceType() === "document") {
      await route.continue();
      return;
    }
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api(?=\/)/, "");
    if (path !== "/detection-readiness") {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(readiness),
    });
  };
  await page.route("**/api/**", handle);
  await page.route("**/detection-readiness*", handle);
}

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => {
    const root = document.documentElement;
    return { scrollWidth: root.scrollWidth, clientWidth: root.clientWidth };
  });
  expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth);
}

test.describe("Pod failure and recovery projection", () => {
  test("separates current state, history, recovery, and gaps", async ({ page }) => {
    await installFixture(page);
    await page.goto("/detection-readiness");

    const section = page.getByRole("region", { name: "Pod failure and recovery" });
    await expect(section).toBeVisible();
    await expect(
      section.getByText(
        "Detection never claims a cause and never grants execution authority.",
        { exact: false },
      ),
    ).toBeVisible();

    await expect(section.getByRole("link", { name: /Failing now/ })).toContainText("0");
    await expect(section.getByRole("link", { name: /Recovery verified/ })).toContainText("2");
    await expect(section.getByRole("link", { name: /Retained failures/ })).toContainText("3");
    await expect(section.getByRole("link", { name: /Targets with evidence gaps/ })).toContainText("1");

    const restart = section
      .locator("li.detection-lifecycle-target")
      .filter({ hasText: "cluster-a/default/orders" });
    await restart.locator("summary").click();
    await expect(restart.getByText("Failure history")).toBeVisible();
    await expect(restart.getByRole("cell", { name: "container_restart" })).toBeVisible();
    await expect(restart.getByRole("cell", { name: "restart_observed_recovered" })).toBeVisible();
    await expect(restart.getByText("No evidence gap is recorded for this target.")).toBeVisible();

    const gapped = section
      .locator("li.detection-lifecycle-target")
      .filter({ hasText: "cluster-a/default/reports" });
    await gapped.locator("summary").click();
    await expect(gapped.getByText("Incomplete evidence")).toBeVisible();
    await expect(gapped.getByText("Not independently verified")).toBeVisible();
    await expect(gapped.getByText("restart_history_restart_history_retention_gap")).toBeVisible();
  });

  test("stays within the viewport at desktop and laptop widths", async ({ page }) => {
    await installFixture(page);
    for (const size of [
      { width: 1440, height: 900 },
      { width: 993, height: 641 },
    ]) {
      await page.setViewportSize(size);
      await page.goto("/detection-readiness");
      await expect(page.getByRole("region", { name: "Pod failure and recovery" })).toBeVisible();
      await expectNoHorizontalOverflow(page);
    }
  });

  test("keeps the disclosure reachable and tappable on a phone", async ({ page }) => {
    await installFixture(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/detection-readiness");

    const section = page.getByRole("region", { name: "Pod failure and recovery" });
    await expect(section).toBeVisible();
    await expectNoHorizontalOverflow(page);

    const summary = section.locator("summary.detection-lifecycle-summary").first();
    const box = await summary.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.height).toBeGreaterThanOrEqual(44);

    await summary.focus();
    await page.keyboard.press("Enter");
    await expect(section.getByText("Failure history").first()).toBeVisible();
  });
});
