import { fileURLToPath, pathToFileURL } from "node:url";

import { expect, test, type Page } from "@playwright/test";

const shell = pathToFileURL(fileURLToPath(new URL("../../../index.html", import.meta.url))).href;

async function openExample(page: Page, size: string) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(`${shell}#mocks/ui/dashboard-v2.html`);
  const frame = page.frameLocator("#preview-frame");
  await expect(frame.locator("#count-resources")).toHaveText("24");
  await frame.locator(".dr-preview-controls > summary").click();
  await frame.getByLabel("Example resources", { exact: true }).selectOption(size);
  await expect(frame.locator("#count-resources")).toHaveText(size);
  await frame.locator(".dr-preview-controls > summary").click();
  await expect(frame.locator(".dr-preview-controls")).toHaveJSProperty("open", false);
  return frame;
}

test.describe("Scale-aware Dashboard mock", () => {
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "Desktop baseline precedes responsive checks.");
  });

  for (const size of [100, 1000, 10000]) {
    test(`bounds DOM and verifies all-page partitions for ${size} resources`, async ({ page }, testInfo) => {
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      const frame = await openExample(page, String(size));
      await expect(frame.getByRole("button", { name: "Honeycomb", exact: true })).toHaveAttribute("aria-pressed", "true");
      await frame.getByRole("button", { name: "Groups", exact: true }).click();
      await expect(frame.getByRole("button", { name: "Groups", exact: true })).toHaveAttribute("aria-pressed", "true");
      expect(await frame.locator(".dr-group").count()).toBeLessThanOrEqual(6);
      await expect(frame.locator(".dr-cell")).toHaveCount(0);
      await expect(frame.locator("#resource-list tbody tr")).toHaveCount(0);
      const allCounts = await frame.locator(".dr-summary dd").allTextContents();
      expect(allCounts).toHaveLength(4);
      expect(Number(allCounts[0])).toBe(size);
      expect(Number(allCounts[3])).toBe(3);
      // Provisioning is an independent axis; only known, unknown and not-applicable operation counts partition inventory.
      expect(Number(allCounts[1]) + Number(allCounts[2]) + Number(await frame.locator("#count-na").textContent())).toBe(size);
      for (const lens of ["operation", "provisioning", "availability", "observation"]) {
        await frame.locator(`[data-resource-lens="${lens}"]`).click();
        const counts = await frame.locator("#resource-legend button:not([data-state-key='all'])").evaluateAll((buttons) =>
          buttons.map((button) => Number(button.getAttribute("data-count"))),
        );
        expect(counts.reduce((sum, count) => sum + count, 0)).toBe(size);
        if (lens === "provisioning") expect(counts).toEqual([1, 1, 1, size - 3]);
        expect(await frame.locator(".dr-group").evaluateAll((groups) => groups.every((group) =>
          [...group.querySelectorAll("[data-state]")].reduce((sum, status) => sum + Number(status.getAttribute("data-count")), 0) === Number(group.getAttribute("data-count")),
        ))).toBe(true);
      }
      await frame.locator('[data-resource-lens="availability"]').click();
      const groupedTotal = await frame.locator(".dr-group").evaluateAll((groups) => groups.reduce((sum, group) => sum + Number(group.getAttribute("data-count")), 0));
      if (size === 10000) expect(groupedTotal).toBe(6000);
      await frame.locator(".dr-resource-panel").scrollIntoViewIfNeeded();
      await page.screenshot({ path: testInfo.outputPath(`dashboard-groups-${size}.png`) });
      const requests: string[] = [];
      page.on("request", (request) => requests.push(request.url()));
      const began = performance.now();
      await frame.getByRole("button", { name: "Honeycomb", exact: true }).click();
      await frame.getByRole("button", { name: "Comfortable", exact: true }).click();
      await expect(frame.locator(".dr-cell")).toHaveCount(48);
      await expect(frame.locator(".dr-group")).toHaveCount(0);
      await expect(frame.locator("#resource-list tbody tr")).toHaveCount(0);
      await expect(frame.locator("#resource-page-label")).toContainText(`Resources 1-48 of ${size} matching`);
      const firstIds = await frame.locator(".dr-cell").evaluateAll((cells) => cells.map((cell) => cell.getAttribute("data-resource-id")));
      await frame.getByRole("button", { name: "Next page", exact: true }).click();
      await expect(frame.locator(".dr-cell")).toHaveCount(48);
      const nextIds = await frame.locator(".dr-cell").evaluateAll((cells) => cells.map((cell) => cell.getAttribute("data-resource-id")));
      expect(nextIds.some((id) => firstIds.includes(id))).toBe(false);
      await frame.getByRole("button", { name: "Previous page", exact: true }).click();
      expect(await frame.locator(".dr-cell").evaluateAll((cells) => cells.map((cell) => cell.getAttribute("data-resource-id")))).toEqual(firstIds);
      await frame.getByRole("button", { name: "List", exact: true }).click();
      await expect(frame.locator("#resource-list tbody tr")).toHaveCount(48);
      await expect(frame.locator(".dr-cell")).toHaveCount(0);
      await expect(frame.locator("#resource-page-boundary")).toContainText("Other pages are not missing observations");
      expect(await frame.locator("main").evaluate((element) => ({
        page: document.documentElement.scrollWidth <= innerWidth,
        main: element.scrollWidth <= element.clientWidth,
        boundedDom: element.querySelectorAll("*").length < 3500,
      }))).toEqual({ page: true, main: true, boundedDom: true });
      expect(requests).toEqual([]);
      expect(errors).toEqual([]);
      if (size === 100) {
        await frame.getByRole("button", { name: "Next page", exact: true }).click();
        await frame.getByRole("button", { name: "Next page", exact: true }).click();
        await expect(frame.locator("#resource-list tbody tr")).toHaveCount(4);
        await expect(frame.locator("#resource-page-label")).toContainText("Resources 97-100 of 100");
        await expect(frame.getByRole("button", { name: "Next page", exact: true })).toBeDisabled();
      }
      console.log(`Synthetic ${size}: five bounded-view/page interactions ${Math.round(performance.now() - began)}ms; not a server latency measurement.`);
    });
  }

  test("drills subscriptions and groups, finds the last record, and keeps selection across pages", async ({ page }, testInfo) => {
    const frame = await openExample(page, "10000");
    await frame.getByRole("button", { name: "Groups", exact: true }).click();
    await frame.getByRole("button", { name: "Next page", exact: true }).click();
    await expect(frame.locator("#resource-page-label")).toContainText("Groups 7-10 of 10");
    await expect(frame.getByRole("button", { name: "Next page", exact: true })).toBeDisabled();
    await frame.locator("[data-group-id='subscription-10'] .dr-group-open").click();
    await expect(frame.getByLabel("Subscription", { exact: true })).toHaveValue("subscription-10");
    await expect(frame.locator("#resource-count")).toContainText("1000 match filters");
    await expect(frame.locator("#resource-view-note")).toContainText("Grouped by resource group");
    await frame.locator(".dr-group-open").first().click();
    await expect(frame.locator(".dr-cell")).not.toHaveCount(0);
    await expect(frame.locator("#resource-breadcrumb")).toContainText("Example subscription 10");
    await frame.getByRole("button", { name: "All scope", exact: true }).click();
    await frame.getByLabel("Group", { exact: true }).selectOption("application");
    await expect(frame.locator("#resource-count")).toContainText("36 match filters");
    await frame.locator(".dr-group-open").click();
    await expect(frame.locator("#resource-count")).toContainText("36 match filters");
    await expect(frame.getByLabel("Group", { exact: true })).toHaveValue("application");
    await frame.getByRole("button", { name: "All scope", exact: true }).click();
    await frame.getByLabel("Find resource", { exact: true }).fill("RESOURCE-10000");
    await expect(frame.locator("#resource-count")).toContainText("1 match filters");
    await frame.getByRole("button", { name: "List", exact: true }).click();
    await expect(frame.locator("#resource-list tbody tr")).toHaveCount(1);
    await frame.locator("#resource-list tbody button").click();
    await expect(frame.locator("#resource-selected-name")).toContainText("10000");
    await frame.locator("#resource-evidence > summary").click();
    const before = JSON.parse(await frame.locator("#resource-selected-evidence").innerText());
    expect(before).toMatchObject({ resource: "resource-10000", subscription: "subscription-10", execution_authority: false, inventory_complete: true });
    await frame.getByRole("button", { name: "Clear filters", exact: true }).click();
    await expect(frame.locator("#resource-selection-paged")).toBeVisible();
    await expect(frame.locator("#resource-selection-filtered")).toBeHidden();
    await frame.getByRole("button", { name: "Next page", exact: true }).click();
    expect(JSON.parse(await frame.locator("#resource-selected-evidence").innerText())).toEqual(before);
    await frame.getByLabel("Group", { exact: true }).selectOption("application");
    await expect(frame.locator("#resource-selection-filtered")).toBeVisible();
    await frame.getByRole("button", { name: "Clear selection", exact: true }).click();
    await frame.getByRole("button", { name: "Inspect vm-build-02", exact: true }).click();
    await expect(frame.locator("#resource-selected-name")).toHaveText("vm-build-02");
    await expect(frame.locator("#resource-count")).toContainText("10000 match filters / 10000 received");
    await frame.getByRole("button", { name: "Back to resources", exact: true }).click();
    await expect(frame.locator("#resource-list button[aria-pressed='true']")).toBeFocused();
    await page.screenshot({ path: testInfo.outputPath("dashboard-scale-list.png") });
  });

  test("separates partial inventory, stale state, loading, read error and an empty snapshot", async ({ page }, testInfo) => {
    const frame = await openExample(page, "1000");
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await frame.locator(".dr-preview-controls > summary").click();
    const mode = frame.getByLabel("Inventory example", { exact: true });
    await mode.selectOption("partial");
    await expect(frame.locator("#count-resources")).toHaveText("750");
    await expect(frame.locator("#resource-page-boundary")).toContainText("full total unknown");
    await expect(frame.locator("#resource-snapshot-status")).toContainText("Partial inventory");
    await frame.getByRole("button", { name: "Inspect web-checkout-01", exact: true }).click();
    await frame.locator("#resource-evidence > summary").click();
    expect(JSON.parse(await frame.locator("#resource-selected-evidence").innerText()).inventory_complete).toBe(false);
    await mode.selectOption("stale");
    await expect(frame.locator("#count-known")).toHaveText("0");
    await expect(frame.locator("#resource-selected-name")).not.toBeVisible();
    await expect(frame.locator("#resource-snapshot-status")).toContainText("current state unknown");
    await expect(frame.locator("#count-provisioning")).toHaveText("3");
    await frame.locator('[data-resource-lens="provisioning"]').click();
    await expect(frame.locator("#resource-legend [data-state-key='succeeded']")).toHaveAttribute("data-count", "0");
    await expect(frame.locator("#resource-legend [data-state-key='unknown']")).toHaveAttribute("data-count", "1000");
    await frame.locator('[data-resource-lens="observation"]').click();
    await expect(frame.locator("#resource-legend [data-state-key='ready']")).toHaveAttribute("data-count", "0");
    expect(Number(await frame.locator("#resource-legend [data-state-key='denied']").getAttribute("data-count"))).toBeGreaterThan(0);
    await mode.selectOption("loading");
    await expect(frame.locator("#resource-data")).toBeHidden();
    await expect(frame.locator("#resource-loading")).toBeVisible();
    await expect(frame.locator(".dr-loading-skeleton span")).toHaveCount(4);
    await expect(frame.locator("#resource-read-state")).toHaveAttribute("aria-busy", "true");
    await mode.selectOption("error");
    await expect(frame.locator("#resource-loading")).toBeHidden();
    await expect(frame.locator("#resource-read-error")).toBeVisible();
    await expect(frame.locator("#resource-read-state")).toHaveAttribute("aria-busy", "false");
    await page.screenshot({ path: testInfo.outputPath("dashboard-inventory-error.png") });
    await frame.getByRole("button", { name: "Show complete example", exact: true }).click();
    await expect(frame.locator("#count-resources")).toHaveText("1000");
    await mode.selectOption("empty");
    await expect(frame.locator("#resource-empty-title")).toContainText("No resources in this example snapshot");
    await expect(frame.locator("#resource-priorities")).toBeHidden();
    await expect(frame.locator("#resource-priorities-empty")).toContainText("not an all-clear");
    await expect(frame.locator(".dr-summary dd")).toHaveText(["0", "0", "0", "0"]);
    await expect(frame.locator("#resource-changes")).toBeHidden();
    await expect(frame.locator("#resource-changes button:visible")).toHaveCount(0);
    await expect(frame.locator(".dr-cell,.dr-group,#resource-list tbody tr")).toHaveCount(0);
    await frame.getByLabel("Example resources", { exact: true }).selectOption("24");
    await mode.selectOption("partial");
    await expect(frame.locator("#count-resources")).toHaveText("18");
    await expect(frame.locator("#resource-changes")).toBeHidden();
    await frame.getByLabel("Find resource", { exact: true }).fill("store-archive-02");
    await expect(frame.locator("#resource-count")).toHaveText("0 resources shown / 0 match filters / 18 received");
    await expect(frame.locator("#resource-empty")).toContainText("does not establish absence outside the received snapshot");
    await expect(frame.locator("#resource-honeycomb [data-resource-id='data-store-02']")).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test("keeps large-scope exploration usable at constrained and mobile widths", async ({ page }, testInfo) => {
    const frame = await openExample(page, "10000");
    for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport);
      await frame.getByRole("button", { name: "Groups", exact: true }).click();
      await frame.locator(".dr-resource-panel").scrollIntoViewIfNeeded();
      await page.screenshot({ path: testInfo.outputPath(`dashboard-scale-${viewport.width}x${viewport.height}.png`) });
      expect(await frame.locator("main").evaluate((element) => ({
        document: document.documentElement.scrollWidth <= innerWidth,
        main: element.scrollWidth <= element.clientWidth,
        panels: [...element.querySelectorAll(".dr-resource-panel,.dr-attention")].every((panel) => panel.scrollWidth <= panel.clientWidth),
      }))).toEqual({ document: true, main: true, panels: true });
      await frame.getByRole("link", { name: "Check first", exact: true }).click();
      await expect(frame.getByRole("heading", { name: "Check first", exact: true })).toBeInViewport();
      await frame.getByRole("button", { name: "List", exact: true }).click();
      await frame.getByLabel("Find resource", { exact: true }).fill("resource-10000");
      await frame.locator("#resource-list tbody button").click();
      await expect(frame.locator("#resource-selected-name")).toContainText("10000");
      await frame.locator("#resource-selected-name").evaluate((element) => {
        element.textContent = "긴 리소스 이름 / " + "long-resource-identifier".repeat(8);
      });
      expect(await frame.locator("#resource-inspector").evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
      await frame.getByRole("button", { name: "Clear filters", exact: true }).click();
      await frame.getByRole("button", { name: "Honeycomb", exact: true }).click();
      await frame.getByRole("button", { name: "Comfortable", exact: true }).click();
      const cells = await frame.locator(".dr-cell").evaluateAll((nodes) => nodes.map((node) => ({
        width: node.getBoundingClientRect().width, height: node.getBoundingClientRect().height,
      })));
      expect(cells).toHaveLength(48);
      expect(cells.every((cell) => cell.width >= 44 && cell.height >= 44)).toBe(true);
      await frame.locator(".dr-cell").first().click();
      await frame.getByRole("button", { name: "Back to resources", exact: true }).click();
      await expect(frame.locator(".dr-cell[aria-pressed='true']")).toBeFocused();
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    await frame.getByRole("button", { name: "Groups", exact: true }).click();
    expect(await frame.locator("main").evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  });
});
