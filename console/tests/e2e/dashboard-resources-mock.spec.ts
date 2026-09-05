import { fileURLToPath, pathToFileURL } from "node:url";

import { expect, test, type Page } from "@playwright/test";

const shell = pathToFileURL(fileURLToPath(new URL("../../../index.html", import.meta.url))).href;

async function openDashboard(page: Page) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(`${shell}#mocks/ui/dashboard.html`);
  const frame = page.frameLocator("#preview-frame");
  await expect(frame.locator("#resource-count")).toHaveText("24 shown / 24 match scope / 24 in snapshot");
  return frame;
}

test.describe("Resource-first Dashboard mock", () => {
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
    await expect(frame.locator(".dr-summary dd")).toHaveText(["24", "14", "3", "7"]);
    await expect(frame.locator("#resource-honeycomb .dr-cluster")).toHaveCount(3);
    await expect(frame.locator("#resource-honeycomb .dr-cell")).toHaveCount(24);
    await expect(frame.locator(".dr-cell").first()).toBeInViewport();
    await expect(frame.locator(".dr-cell").last()).toBeInViewport({ ratio: 1 });
    await expect(frame.getByRole("heading", { name: "Check first", exact: true })).toBeInViewport();
    await expect(frame.locator(".dr-lens-note")).toContainText("Running is not a health verdict");
    await expect(frame.locator("#historical-performance")).not.toHaveAttribute("open", "");
    await expect(frame.locator("#resource-honeycomb .dr-cell[data-resource-id='app-web-01']")).toHaveAttribute("data-state", "running");
    await expect(frame.locator("#resource-honeycomb .dr-cell[data-resource-id='platform-ca-02']")).toHaveAttribute("data-state", "unknown");
    for (const [lens, counts] of [
      ["operation", [9, 3, 1, 1, 3, 7]],
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
    await expect(frame.locator("#resource-count")).toHaveText("3 shown / 3 match scope / 24 in snapshot");
    await frame.locator("#resource-legend [data-state-key='running']").click();
    await expect(frame.locator("#resource-count")).toHaveText("2 shown / 3 match scope / 24 in snapshot");
    await frame.getByRole("button", { name: "List", exact: true }).click();
    await expect(frame.locator("#resource-list tbody tr:visible")).toHaveCount(2);
    await expect(frame.locator("#resource-honeycomb")).toBeHidden();
    await frame.getByRole("button", { name: "db-orders-01", exact: true }).first().click();
    await expect(frame.locator("#resource-list button[aria-pressed='true']")).toBeFocused();
    await expect(frame.locator("#resource-selected-name")).toHaveText("db-orders-01");
    await expect(frame.locator("#resource-selected-facts")).toContainText("Degraded");
    await frame.locator("#resource-evidence > summary").click();
    const source = JSON.parse(await frame.locator("#resource-selected-evidence").innerText());
    expect(source).toMatchObject({ synthetic: true, resource: "data-db-01", presented_operation: "running", presented_availability: "degraded", execution_authority: false });
    await frame.getByLabel("Find resource").fill("no-resource-matches");
    await expect(frame.locator("#resource-empty")).toBeVisible();
    await expect(frame.locator("#resource-count")).toHaveText("0 shown / 0 match scope / 24 in snapshot");
    await expect(frame.locator("#resource-selection-filtered")).toBeVisible();
    await expect(frame.locator("#resource-selected-name")).toHaveText("db-orders-01");
    await expect(frame.locator("#resource-evidence")).toHaveAttribute("open", "");
    await frame.getByRole("button", { name: "Clear filters", exact: true }).click();
    await expect(frame.locator("#resource-count")).toContainText("24 shown");
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
    await expect(frame.locator("#resource-count")).toContainText("24 shown");
    await frame.getByRole("button", { name: "store-archive-02", exact: true }).click();
    await expect(frame.locator("#resource-selected-name")).toHaveText("store-archive-02");
    await expect(frame.locator("#resource-selected-facts")).toContainText("Not applicable");
    await expect(frame.locator("#resource-selected-facts")).toContainText("Read denied");
    await page.screenshot({ path: testInfo.outputPath("dashboard-resource-inspector.png") });
    await frame.getByRole("button", { name: "Clear selection", exact: true }).click();
    await expect(frame.locator("#resource-inspector")).toBeHidden();
    const first = frame.locator(".dr-cell").first();
    await first.focus();
    await page.keyboard.press("ArrowRight");
    await expect(frame.locator(".dr-cell").nth(1)).toBeFocused();
    await page.keyboard.press("End");
    await expect(frame.locator(".dr-cell").last()).toBeFocused();
    await page.keyboard.press("Home");
    await expect(first).toBeFocused();
  });

  test("preserves legible cells, list fallback and historical boundaries on small screens", async ({ page }, testInfo) => {
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
    await expect(frame.locator("#historical-performance")).not.toHaveAttribute("open", "");
    await frame.locator("#historical-performance > summary").click();
    await expect(frame.locator("#historical-performance")).toContainText("do not share the resource snapshot's time window or denominator");
    await expect(frame.locator(".db-metric-value")).toHaveText(["73%", "6.7", "Insufficient evidence", "Unavailable", "Unavailable"]);
  });
});
