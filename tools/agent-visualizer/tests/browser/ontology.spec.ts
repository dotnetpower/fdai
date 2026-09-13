import { expect, test, type Page } from "@playwright/test";
import { fullMapFixture } from "../full-map-fixture";

/** CI uses a declared structural fixture; actual local DB verification is performed separately. */
async function sourceFixture(page: Page) {
  await page.route("**/__neural/ontology", (route) => route.fulfill({
    contentType: "application/json", body: JSON.stringify(fullMapFixture()),
  }));
}
async function openMap(page: Page) {
  await page.goto("/");
  if (await page.locator("#play").getAttribute("aria-label") === "Pause") {
    await page.locator("#controls-dock").hover();
    await page.locator("#play").click();
  }
  await page.locator('[data-view="ontology"]').click();
  await expect(page.locator("#recorded-status")).toHaveText("Local database snapshot ready");
}

test("desktop full map: every type, collected instance and stored relation is available", async ({ page }, testInfo) => {
  await sourceFixture(page);
  await openMap(page);
  await expect(page.locator("#full-type-count")).toHaveText("4");
  await expect(page.locator("#full-instance-count")).toHaveText("4");
  await expect(page.locator(".recorded-labels")).toHaveAttribute("data-drawn-nodes", "8");
  await expect(page.locator(".recorded-labels")).toHaveAttribute("data-drawn-links", "8");
  await expect(page.locator("#map-object-type option")).toHaveCount(5);
  await expect(page.locator("#map-object-type")).toContainText("Signal (0)");
  await expect(page.locator(".provenance")).toContainText("LOCAL DB SNAPSHOT");
  await expect(page.locator("#recorded-connect")).toHaveCount(0);
  await expect(page.locator(".ontology-mode .roster")).toBeHidden();
  await page.locator('[data-map-lens="catalog"]').click();
  await expect(page.locator(".recorded-labels")).toHaveAttribute("data-drawn-nodes", "4");
  await page.locator('[data-map-lens="all"]').click();
  await expect(page.locator(".recorded-labels")).toHaveAttribute("data-drawn-nodes", "8");
  await page.screenshot({ path: testInfo.outputPath("full-map-fixture.png") });
});

test("desktop full map: type expansion and actual retained transition playback stay separate", async ({ page }) => {
  await sourceFixture(page);
  await openMap(page);
  await page.locator("#recorded-root").selectOption("catalog:ot:Resource");
  await expect(page.locator(".type-instance-count")).toHaveText("2 database instances");
  await page.locator("#expand-type").click();
  await expect(page.locator("#map-object-type")).toHaveValue("Resource");
  await expect(page.locator(".recorded-labels")).toHaveAttribute("data-drawn-nodes", "3");
  await page.locator("#map-result-select").selectOption("db:one");
  await expect(page.locator("#snapshot-current-state")).toHaveText("running");
  await expect(page.locator("#recorded-details")).toContainText("running -> stopped");
  await expect(page.locator("#play")).toBeDisabled();
  await page.locator("#map-history-replay").check();
  if (await page.locator("#play").getAttribute("aria-label") === "Pause") {
    await page.locator("#controls-dock").hover();
    await page.locator("#play").click();
  }
  await page.locator("#timeline").fill("0");
  await expect(page.locator("#recorded-details")).toContainText("Replayed observed state stopped");
  await page.locator("#timeline").fill("72");
  await expect(page.locator("#recorded-details")).toContainText("Replayed observed state running");
  await expect(page.locator("#snapshot-current-state")).toHaveText("running");
  await page.locator("#map-history-replay").uncheck();
  await expect(page.locator("#play")).toBeDisabled();
});

test("desktop full map: unavailable DB exports never become mock data", async ({ page }) => {
  let unavailable = true;
  await page.route("**/__neural/ontology", (route) => unavailable
    ? route.fulfill({ status: 503, body: "{}" })
    : route.fulfill({ contentType: "application/json", body: JSON.stringify(fullMapFixture()) }));
  await page.goto("/");
  await page.locator('[data-view="ontology"]').click();
  await expect(page.locator("#recorded-error")).toContainText("local database export is unavailable");
  await expect(page.locator(".recorded-node-label")).toHaveCount(0);
  unavailable = false;
  await page.locator("#snapshot-reload").click();
  await expect(page.locator("#full-type-count")).toHaveText("4");
});

test("responsive full map: complete type filters and source counts remain usable", async ({ page }, testInfo) => {
  await sourceFixture(page);
  await openMap(page);
  for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }, { width: 320, height: 844 }]) {
    await page.setViewportSize(viewport);
    await page.locator("#language").click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await expect(page.locator("#map-object-type option")).toHaveCount(5);
    await expect(page.locator("#full-type-count")).toHaveText("4");
    await page.screenshot({ path: testInfo.outputPath(`full-map-ko-${viewport.width}.png`), fullPage: true });
    await page.locator("#language").click();
  }
});
