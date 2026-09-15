import { expect, test, type Page } from "@playwright/test";

test.use({ trace: "off", contextOptions: { reducedMotion: "reduce" } });

async function steadyOverview(page: Page) {
  await page.goto("/");
  await expect(page.locator("#loading")).toBeHidden();
  await expect(page.locator("#error")).toBeHidden();
  await page.locator("#reset").click();
  await page.locator('[data-camera="manual"]').click();
  await expect(page.locator(".function-node-label:visible")).toHaveCount(0);
}

test("unchanged hidden function labels do not mutate every render frame", async ({ page }) => {
  await steadyOverview(page);
  const mutations = await page.evaluate(() => new Promise<number>((resolve) => {
    let count = 0;
    let frames = 0;
    const observer = new MutationObserver((records) => {
      count += records.filter((record) => record.target instanceof Element
        && record.target.matches(".function-node-label[hidden]")).length;
    });
    observer.observe(document.querySelector(".activity-labels")!, { attributes: true, subtree: true });
    const tick = () => {
      if (++frames < 4) { requestAnimationFrame(tick); return; }
      observer.disconnect();
      resolve(count);
    };
    requestAnimationFrame(tick);
  }));
  expect(mutations).toBeLessThanOrEqual(6);
});

test("changing selected source functions releases superseded GPU buffers", async ({ page }) => {
  await page.addInitScript(() => {
    const counts = { created: 0, deleted: 0 };
    const create = WebGL2RenderingContext.prototype.createBuffer;
    const remove = WebGL2RenderingContext.prototype.deleteBuffer;
    WebGL2RenderingContext.prototype.createBuffer = function () {
      const buffer = create.call(this);
      if (buffer) counts.created++;
      return buffer;
    };
    WebGL2RenderingContext.prototype.deleteBuffer = function (buffer) {
      if (buffer) counts.deleted++;
      return remove.call(this, buffer);
    };
    Object.defineProperty(globalThis, "__neuralGpuCounts", { value: counts });
  });

  await steadyOverview(page);
  await page.locator(".adapter-browser > summary").click();
  const entries = ["openai", "console", "teams", "resource-graph"];
  const select = async (id: string) => {
    const button = page.locator(`[data-service-entry="${id}"]`);
    const symbol = (await button.getAttribute("title"))!.split("\n")[0]!;
    await button.click();
    await expect(page.locator("#function-detail h3")).toHaveText(`${symbol}()`);
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  };
  const counts = () => page.evaluate(() => {
    const value = Reflect.get(globalThis, "__neuralGpuCounts") as { created: number; deleted: number };
    return { ...value };
  });
  for (const id of entries) await select(id);
  const before = await counts();
  for (const id of entries) await select(id);
  const after = await counts();
  expect(after.created).toBeGreaterThan(before.created);
  expect(after.deleted - before.deleted).toBeGreaterThanOrEqual(after.created - before.created);
  await expect(page.locator("#error")).toBeHidden();
});

test("a late initialization failure removes the partial canvas, labels and wheel relay", async ({ page }) => {
  await page.addInitScript(() => {
    const counters = { added: 0, removed: 0 };
    Object.defineProperty(globalThis, "__neuralWheelCounts", { value: counters });
    const add = EventTarget.prototype.addEventListener;
    const remove = EventTarget.prototype.removeEventListener;
    EventTarget.prototype.addEventListener = function (type, listener, options) {
      if (type === "wheel" && this instanceof HTMLElement && this.id === "stage") counters.added++;
      return add.call(this, type, listener, options);
    };
    EventTarget.prototype.removeEventListener = function (type, listener, options) {
      if (type === "wheel" && this instanceof HTMLElement && this.id === "stage") counters.removed++;
      return remove.call(this, type, listener, options);
    };
    const OriginalObserver = ResizeObserver;
    globalThis.ResizeObserver = class extends OriginalObserver {
      override observe(target: Element, options?: ResizeObserverOptions) {
        if (target.id === "stage") throw new Error("Injected scene initialization failure");
        super.observe(target, options);
      }
    };
  });
  await page.goto("/");
  await expect(page.locator("#error")).toBeVisible();
  await expect(page.locator("#stage canvas, #stage .node-labels")).toHaveCount(0);
  const counters = await page.evaluate(() => Reflect.get(globalThis, "__neuralWheelCounts"));
  expect(counters.added).toBe(1);
  expect(counters.removed).toBe(1);
});

test("stationary paused views stop rendering and repeated zoom still invalidates the scene", async ({ page }) => {
  await steadyOverview(page);
  await expect(page.locator("#fps")).toHaveText("0", { timeout: 5000 });
  const canvas = page.locator("#stage canvas");
  const before = await canvas.screenshot();
  await page.locator("#zoom-in").click();
  const first = await canvas.screenshot();
  await page.locator("#zoom-in").click();
  const second = await canvas.screenshot();
  expect(before.equals(first)).toBe(false);
  expect(first.equals(second)).toBe(false);
  await expect(page.locator("#error")).toBeHidden();
});

test("pagehide preserves BFCache views but releases non-persisted views", async ({ page }) => {
  await steadyOverview(page);
  await page.evaluate(() => dispatchEvent(new PageTransitionEvent("pagehide", { persisted: true })));
  await expect(page.locator("#stage canvas")).toHaveCount(1);
  await page.evaluate(() => dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true })));
  await page.locator("#zoom-in").click();
  await expect(page.locator("#error")).toBeHidden();
  await page.evaluate(() => dispatchEvent(new PageTransitionEvent("pagehide", { persisted: false })));
  await expect(page.locator("#stage canvas, #stage .node-labels")).toHaveCount(0);
});
