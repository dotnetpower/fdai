import { expect, test, type Locator, type Page, type Response } from "@playwright/test";

const ENDED = "Evaluation period ended";
const NOT_ACTIVATED = "FDAI is not activated";
const DATA_SOURCES = /\/(?:api\/)?system\/data-sources(?:\?|$)/;

/** Serve the Operator read the watermark probes, stamped with the current notice. */
async function serveOperator(page: Page, notice: () => string | null): Promise<void> {
  await page.route(DATA_SOURCES, async (route) => {
    if (route.request().resourceType() === "document") {
      await route.continue();
      return;
    }
    const value = notice();
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      headers: value === null ? {} : { "X-FDAI-Entitlement": value },
      body: JSON.stringify({ detail: "Optional test source unavailable." }),
    });
  });
}

function isProbe(response: Response, notice?: string): boolean {
  return DATA_SOURCES.test(new URL(response.url()).pathname)
    && (notice === undefined || response.headers()["x-fdai-entitlement"] === notice);
}

/** Return whether the watermark's centre hits the watermark, optionally with input enabled. */
async function hitsWatermark(watermark: Locator, acceptInput: boolean): Promise<boolean> {
  return watermark.evaluate((element, enable) => {
    const node = element as HTMLElement;
    const previous = node.style.pointerEvents;
    if (enable) node.style.pointerEvents = "auto";
    const box = node.getBoundingClientRect();
    const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
    node.style.pointerEvents = previous;
    return hit !== null && node.contains(hit);
  }, acceptInput);
}

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
});

test("an ended evaluation shows a persistent notice above Settings that passes input through", async ({ page }) => {
  await serveOperator(page, () => "evaluation-ended");
  await page.goto("/settings/general");

  const settings = page.getByRole("dialog", { name: "Settings" });
  const watermark = page.locator(".entitlement-watermark");
  await expect(settings).toBeVisible();
  await expect(watermark).toBeVisible();
  await expect(watermark).toContainText(ENDED);
  await expect(watermark).toContainText("Acting work is unavailable until FDAI is activated.");
  await expect(watermark).toHaveAttribute("aria-live", "polite");
  await expect(watermark).not.toHaveAttribute("role", /.+/);
  expect(await watermark.evaluate((element) => element.matches(":popover-open"))).toBe(true);
  expect(await watermark.evaluate((element) => getComputedStyle(element).pointerEvents))
    .toBe("none");

  // Painted above the Settings overlay, yet every pointer event reaches the page below.
  expect(await hitsWatermark(watermark, true)).toBe(true);
  expect(await hitsWatermark(watermark, false)).toBe(false);

  await page.keyboard.press("Escape");
  await expect(settings).toHaveCount(0);
  await expect(watermark).toBeVisible();
  await expect(watermark).toContainText(ENDED);
});

test("the notice rises above a modal dialog or fullscreen view opened later", async ({ page }) => {
  await serveOperator(page, () => "not-activated");
  await page.goto("/labs");

  const watermark = page.locator(".entitlement-watermark");
  await expect(watermark).toContainText(NOT_ACTIVATED);
  await watermark.evaluate((element) => {
    const node = element as HTMLElement;
    const show = node.showPopover.bind(node);
    node.dataset.shown = "0";
    node.showPopover = () => {
      node.dataset.shown = String(Number(node.dataset.shown) + 1);
      show();
    };
    const fullscreen = document.createElement("button");
    fullscreen.id = "e2e-fullscreen";
    fullscreen.textContent = "Enter fullscreen";
    fullscreen.style.cssText = "position: fixed; top: 50%; left: 50%; z-index: 2147483646";
    fullscreen.addEventListener("click", () => {
      void document.documentElement.requestFullscreen();
    });
    document.body.append(fullscreen);
  });

  await page.evaluate(() => {
    const dialog = document.createElement("dialog");
    dialog.id = "e2e-modal";
    dialog.textContent = "Modal test dialog";
    document.body.append(dialog);
    dialog.showModal();
  });
  await expect(watermark).toHaveAttribute("data-shown", "1");
  expect(await watermark.evaluate((element) => element.matches(":popover-open"))).toBe(true);
  await page.evaluate(() => {
    const dialog = document.getElementById("e2e-modal") as HTMLDialogElement;
    dialog.close();
    dialog.remove();
  });

  await page.locator("#e2e-fullscreen").click();
  await page.waitForFunction(() => document.fullscreenElement !== null);
  await expect(watermark).toHaveAttribute("data-shown", "2");
  expect(await watermark.evaluate((element) => element.matches(":popover-open"))).toBe(true);
  await expect(watermark).toBeVisible();
});

test("the notice follows the Korean locale", async ({ page }) => {
  await serveOperator(page, () => "not-activated");
  await page.goto("/labs?locale=ko");

  const watermark = page.locator(".entitlement-watermark");
  await expect(watermark).toContainText("FDAI가 활성화되지 않았습니다");
  await expect(watermark).toContainText("FDAI를 활성화할 때까지 변경 작업을 사용할 수 없습니다.");
});

test("a missing stamp shows the notice after the first-stamp wait", async ({ page }) => {
  await page.clock.install();
  await serveOperator(page, () => null);
  const firstResponse = page.waitForResponse((response) => isProbe(response));
  await page.goto("/labs");
  await firstResponse;

  const watermark = page.locator(".entitlement-watermark");
  await expect(watermark).toHaveCount(0);
  await page.clock.runFor(10_000);
  await expect(watermark).toContainText(NOT_ACTIVATED);
});

test("an activated stamp hides the notice until it goes stale", async ({ page }) => {
  let notice: string | null = "none";
  await page.clock.install();
  await serveOperator(page, () => notice);
  const firstStamp = page.waitForResponse((response) => isProbe(response, "none"));
  await page.goto("/labs");
  await firstStamp;

  const watermark = page.locator(".entitlement-watermark");
  await page.clock.runFor(11_000);
  await expect(watermark).toHaveCount(0);

  // Later responses carry no stamp, so the last activated stamp ages past five minutes.
  notice = null;
  await page.clock.runFor(4 * 60_000);
  await expect(watermark).toHaveCount(0);
  await page.clock.runFor(2 * 60_000);
  await expect(watermark).toContainText(NOT_ACTIVATED);
});
