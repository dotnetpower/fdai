import { fileURLToPath, pathToFileURL } from "node:url";

import { expect, test, type Page } from "@playwright/test";

const shell = pathToFileURL(fileURLToPath(new URL("../../../index.html", import.meta.url))).href;

async function openDashboard(page: Page) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(`${shell}#mocks/ui/dashboard-v2.html`);
  const frame = page.frameLocator("#preview-frame");
  await expect(frame.locator("#resource-count")).toHaveText("24 resources shown / 24 match filters / 24 received");
  return frame;
}

test.describe("Resource Dashboard v2 mock", () => {
  test.describe.configure({ mode: "serial" });
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "Desktop scenarios precede constrained/mobile geometry.");
  });

  test("separates resource counts, state lenses and snapshot authority", async ({ page }, testInfo) => {
    const frame = await openDashboard(page);
    const initial = await frame.locator(".dr-cell").evaluateAll((cells) =>
      cells.map((cell) => ({ id: cell.getAttribute("data-resource-id"), x: cell.getBoundingClientRect().x, y: cell.getBoundingClientRect().y })),
    );
    expect(new Set(initial.map((cell) => cell.id)).size).toBe(24);
    await expect(frame.locator(".dr-summary dd")).toHaveText(["24", "14", "3", "3"]);
    await expect(frame.locator(".dr-summary dt").last()).toHaveText("Provisioning recorded");
    await expect(frame.locator("#operation-coverage")).toHaveText("14 known / 3 unknown / 7 not applicable");
    await expect(frame.locator(".cs-readonly-banner")).toContainText("make no operational claim");
    await expect(frame.locator("body")).toHaveAttribute("data-chat-theme", "clear-neutral");
    await expect(frame.locator("body")).toHaveCSS("background-color", "rgb(255, 255, 255)");
    await expect(frame.locator("#resource-honeycomb .dr-cluster")).toHaveCount(3);
    await expect(frame.locator("#resource-honeycomb .dr-cell")).toHaveCount(24);
    await expect(frame.locator(".dr-cell").first()).toBeInViewport();
    await expect(frame.locator(".dr-cell").last()).toBeInViewport({ ratio: 1 });
    await expect(frame.getByRole("heading", { name: "Check first", exact: true })).toBeInViewport();
    await expect(frame.locator(".dr-lens-note")).toContainText("Running is not a health verdict");
    await expect(frame.locator("#historical-performance")).toHaveCount(0);
    await expect(frame.getByRole("link", { name: "Operating dashboard", exact: true })).toHaveAttribute("href", "dashboard.html");
    await expect(frame.locator("#resource-honeycomb .dr-cell[data-resource-id='app-web-01']")).toHaveAttribute("data-state", "running");
    await expect(frame.locator("#resource-honeycomb .dr-cell[data-resource-id='platform-ca-02']")).toHaveAttribute("data-state", "unknown");
    for (const [lens, counts] of [
      ["operation", [9, 3, 1, 1, 3, 7]],
      ["provisioning", [1, 1, 1, 21]],
      ["availability", [9, 2, 2, 8, 3]],
      ["observation", [17, 2, 2, 3]],
    ] as const) {
      await frame.locator(`[data-resource-lens="${lens}"]`).click();
      const actual = await frame.locator("#resource-legend button:not([data-state-key='all'])").evaluateAll((buttons) =>
        buttons.map((button) => Number(button.getAttribute("data-count"))),
      );
      expect(actual).toEqual(counts);
      expect(actual.reduce((sum, count) => sum + count, 0)).toBe(24);
      const positions = await frame.locator(".dr-cell").evaluateAll((cells) =>
        cells.map((cell) => ({ id: cell.getAttribute("data-resource-id"), x: cell.getBoundingClientRect().x, y: cell.getBoundingClientRect().y })),
      );
      // Lens descriptions may change height, but no cell changes its slot within its group.
      expect(positions.map((cell) => cell.id)).toEqual(initial.map((cell) => cell.id));
      expect(positions.map((cell) => cell.x)).toEqual(initial.map((cell) => cell.x));
      const firstY = positions[0]!.y;
      expect(positions.map((cell) => cell.y - firstY)).toEqual(initial.map((cell) => cell.y - initial[0]!.y));
    }
    await frame.locator('[data-resource-lens="availability"]').click();
    await expect(frame.locator(".dr-cell[data-resource-id='app-web-01']")).toHaveAttribute("data-state", "unavailable");
    await expect(frame.locator(".dr-cell[data-resource-id='app-web-01'] .dr-cell-symbol")).toHaveText("X");
    await expect(frame.locator(".dr-cell[data-resource-id='data-db-01'] .dr-cell-symbol")).toHaveText("!");
    await expect(frame.locator(".dr-cell[data-resource-id='platform-ca-02']")).toHaveAttribute("data-state", "unknown");
    await expect(frame.locator(".dr-cell[data-resource-id='app-net-01']")).toHaveAttribute("data-state", "unsupported");
    await page.screenshot({ path: testInfo.outputPath("dashboard-availability-desktop.png") });
  });

  test("filters exact resources, retains selection, and offers an equivalent list without requests", async ({ page }) => {
    const frame = await openDashboard(page);
    const requests: string[] = [];
    page.on("request", (request) => requests.push(request.url()));
    await frame.getByLabel("Group", { exact: true }).selectOption("data");
    await frame.getByRole("combobox", { name: "Type", exact: true }).fill("postgres");
    await frame.getByRole("option").filter({ hasText: "PostgreSQL" }).click();
    await expect(frame.locator("#resource-count")).toHaveText("3 resources shown / 3 match filters / 24 received");
    await frame.locator("#resource-legend [data-state-key='running']").click();
    await expect(frame.locator("#resource-count")).toHaveText("2 resources shown / 2 match filters / 24 received");
    await expect(frame.locator("#resource-legend [data-state-key='all']")).toHaveAttribute("data-count", "3");
    await frame.getByRole("button", { name: "List", exact: true }).click();
    await expect(frame.locator("#resource-list tbody tr:visible")).toHaveCount(2);
    await expect(frame.locator("#resource-honeycomb")).toBeHidden();
    await frame.getByRole("button", { name: "db-orders-01", exact: true }).first().click();
    await expect(frame.locator("#resource-list button[aria-pressed='true']")).toBeFocused();
    await expect(frame.locator("#resource-selected-name")).toHaveText("db-orders-01");
    await expect(frame.locator("#resource-selected-facts")).toContainText("Degraded");
    await frame.locator("#resource-evidence > summary").click();
    const source = JSON.parse(await frame.locator("#resource-selected-evidence").innerText());
    expect(source).toMatchObject({
      synthetic: true, resource: "data-db-01", presented_operation: "running",
      presented_availability: "degraded", execution_authority: false,
      recorded_provisioning: "failed", presented_provisioning: "failed",
      provisioning_source: "example-recorded-state", provisioning_observed_at: "2026-09-05T11:59:00+09:00",
    });
    await expect(frame.locator("#resource-ontology-link")).toHaveAttribute("href", "ontology-instances-2d.html?instance=data-db-01");
    await frame.getByLabel("Find resource").fill("no-resource-matches");
    await expect(frame.locator("#resource-empty")).toBeVisible();
    await expect(frame.locator("#resource-count")).toHaveText("0 resources shown / 0 match filters / 24 received");
    await expect(frame.locator("#resource-selection-filtered")).toBeVisible();
    await expect(frame.locator("#resource-selected-name")).toHaveText("db-orders-01");
    await expect(frame.locator("#resource-evidence")).toHaveAttribute("open", "");
    await frame.getByRole("button", { name: "Clear filters", exact: true }).click();
    await expect(frame.locator("#resource-count")).toContainText("24 resources shown");
    await frame.getByRole("button", { name: "Honeycomb", exact: true }).click();
    await expect(frame.locator(".dr-cell[data-resource-id='data-db-01']")).toHaveAttribute("aria-pressed", "true");
    await frame.locator('[data-resource-lens="observation"]').click();
    await expect(frame.locator("#resource-selected-name")).toHaveText("db-orders-01");
    await expect(frame.locator(".dr-cell[data-resource-id='data-db-01']")).toHaveAttribute("aria-pressed", "true");
    await expect(frame.locator("#resource-evidence")).toHaveAttribute("open", "");
    expect(requests).toEqual([]);
  });

  test("makes stale, stopped, unsupported and priority evidence inspectable with keyboard controls", async ({ page }, testInfo) => {
    const frame = await openDashboard(page);
    const stale = frame.locator(".dr-cell[data-resource-id='platform-ca-02']");
    await stale.focus();
    await page.keyboard.press("Enter");
    await expect(frame.locator("#resource-selected-note")).toContainText("Last reported state was running");
    await expect(frame.locator("#resource-selected-facts")).toContainText("Unknown");
    await frame.locator("#resource-evidence > summary").click();
    expect(JSON.parse(await frame.locator("#resource-selected-evidence").innerText())).toMatchObject({
      recorded_operation: "running", presented_operation: "unknown",
      recorded_provisioning: null, provisioning_source: null, provisioning_observed_at: null,
      presented_provisioning: "unknown", execution_authority: false,
    });
    await frame.locator(".dr-cell[data-resource-id='platform-vm-01']").click();
    await expect(frame.locator("#resource-selected-note")).toContainText("does not establish an incident or a planned shutdown");
    await frame.locator(".dr-cell[data-resource-id='app-net-01']").click();
    await expect(frame.locator("#resource-selected-note")).toContainText("has no start/stop state");
    await frame.getByRole("button", { name: "Clear selection", exact: true }).click();
    await frame.getByLabel("Find resource").fill("db-");
    await frame.getByRole("button", { name: "Inspect vm-build-02", exact: true }).click();
    await expect(frame.locator("#resource-selected-name")).toHaveText("vm-build-02");
    await expect(frame.locator("#resource-selected-note")).toContainText("state read was denied");
    await expect(frame.getByLabel("Find resource")).toHaveValue("");
    await expect(frame.locator("#resource-count")).toContainText("24 resources shown");
    await frame.getByRole("button", { name: "List", exact: true }).click();
    await frame.locator("#resource-list").getByRole("button", { name: "store-archive-02", exact: true }).click();
    await expect(frame.locator("#resource-selected-name")).toHaveText("store-archive-02");
    await expect(frame.locator("#resource-selected-facts")).toContainText("Not applicable");
    await expect(frame.locator("#resource-selected-facts")).toContainText("Read denied");
    await page.screenshot({ path: testInfo.outputPath("dashboard-resource-inspector.png") });
    await frame.getByRole("button", { name: "Clear selection", exact: true }).click();
    await expect(frame.locator("#resource-inspector")).toBeHidden();
    await frame.getByRole("button", { name: "Honeycomb", exact: true }).click();
    const first = frame.locator(".dr-cell").first();
    await first.focus();
    await page.keyboard.press("ArrowRight");
    await expect(frame.locator(".dr-cell").nth(1)).toBeFocused();
    await page.keyboard.press("End");
    await expect(frame.locator(".dr-cell").last()).toBeFocused();
    await page.keyboard.press("Home");
    await expect(first).toBeFocused();
  });

  test("preserves legible cells, list fallback and unavailable history on small screens", async ({ page }, testInfo) => {
    const frame = await openDashboard(page);
    for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport);
      await frame.locator(".dr-resource-panel").scrollIntoViewIfNeeded();
      const geometry = await frame.locator("main").evaluate((element) => ({
        document: document.documentElement.scrollWidth <= innerWidth,
        main: element.scrollWidth <= element.clientWidth,
        panels: [...element.querySelectorAll(".dr-resource-panel,.dr-attention,.dr-inspector")].every((panel) => panel.scrollWidth <= panel.clientWidth),
        cells: [...element.querySelectorAll(".dr-cell")].every((cell) => cell.getBoundingClientRect().width >= 44 && cell.getBoundingClientRect().height >= 44),
      }));
      expect(geometry).toEqual({ document: true, main: true, panels: true, cells: true });
      await page.screenshot({ path: testInfo.outputPath(`dashboard-honeycomb-${viewport.width}x${viewport.height}.png`) });
      await frame.getByRole("button", { name: "List", exact: true }).click();
      await expect(frame.locator("#resource-list tbody tr:visible")).toHaveCount(24);
      expect(await frame.locator("#resource-list").evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
      await frame.getByRole("button", { name: "web-checkout-01", exact: true }).first().click();
      await expect(frame.locator("#resource-selected-name")).toHaveText("web-checkout-01");
      await frame.locator("#resource-selected-name").evaluate((element) => {
        element.textContent = "관측 대상 / " + "long-resource-identifier".repeat(6);
      });
      expect(await frame.locator("#resource-inspector").evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
      await frame.getByRole("button", { name: "Honeycomb", exact: true }).click();
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    await expect(frame.locator("#historical-performance")).toHaveCount(0);
    const history = frame.locator(".dr-history-panel").filter({ has: frame.getByRole("heading", { name: "State history", exact: true }) });
    await expect(history).toContainText("Not connected in this projection");
    await expect(history).toContainText("does not establish a continuous history, transition onset, or recovery duration");
    await expect(frame.locator("#resource-changes")).toBeHidden();
    await expect(frame.locator("#resource-changes button:visible")).toHaveCount(0);
    await expect(frame.locator(".ov-evidence")).toContainText("Manifest digest: not recorded");
    await expect(frame.locator(".ov-evidence")).toContainText("Pending changes: unavailable");
    await expect(frame.getByRole("link", { name: "Open operating outcomes dashboard", exact: true })).toHaveAttribute("href", "dashboard.html");
  });

  test("drills independent summary axes and reloads the same fixture without requests", async ({ page }) => {
    const frame = await openDashboard(page);
    const requests: string[] = [];
    page.on("request", (request) => requests.push(request.url()));
    await frame.locator(".dr-preview-controls > summary").click();
    const snapshotId = await frame.locator("#resource-snapshot-id").innerText();
    expect(snapshotId).not.toBe("");
    await frame.locator(".dr-preview-controls > summary").click();
    const summaries = frame.locator(".dr-summary > div");
    for (const [index, count, lens] of [[0, 24, "operation"], [1, 14, "operation"], [2, 3, "operation"], [3, 3, "provisioning"]] as const) {
      await summaries.nth(index).getByRole("button", { name: "Inspect records", exact: true }).click();
      await expect(frame.locator("#resource-list tbody tr")).toHaveCount(count);
      await expect(frame.locator(`[data-resource-lens="${lens}"]`)).toHaveAttribute("aria-pressed", "true");
      await expect(frame.locator(".dr-summary dd")).toHaveText(["24", "14", "3", "3"]);
      if (index === 1) await expect(frame.locator("#resource-list tbody td:nth-child(3)").filter({ hasText: /Unknown|Not applicable/ })).toHaveCount(0);
      if (index === 2) await expect(frame.locator("#resource-list tbody td:nth-child(3)")).toHaveText(["? Unknown", "? Unknown", "? Unknown"]);
    }
    await expect(frame.locator("#resource-count")).toHaveText("3 resources shown / 3 match filters / 24 received / provisioning evidence filter");
    await expect(frame.locator("#resource-lens-note")).toContainText("not power, availability, or verified effect");
    expect(await frame.locator("#resource-list tbody tr").evaluateAll((rows) => rows.map((row) => row.getAttribute("data-resource-id")))).toEqual([
      "app-web-01", "app-vm-02", "data-db-01",
    ]);
    await frame.getByRole("button", { name: "Reload fixture", exact: true }).click();
    await expect(frame.locator("#resource-snapshot-id")).toHaveText(snapshotId);
    await expect(frame.locator("#resource-count")).toHaveText("24 resources shown / 24 match filters / 24 received");
    await expect(frame.locator("#resource-refresh-status")).toHaveText("Same frozen fixture reloaded. No runtime request.");
    await expect(frame.locator("#resource-inspector")).toBeHidden();
    expect(requests).toEqual([]);
  });
});
