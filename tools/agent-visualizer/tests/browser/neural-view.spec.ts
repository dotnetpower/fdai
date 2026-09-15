import { expect, test, type Page } from "@playwright/test";

async function seek(page: Page, value: number) {
  await page.locator("#timeline").fill(String(value));
}

async function pause(page: Page) {
  const button = page.locator("#play");
  if (await button.getAttribute("aria-label") === "Pause") {
    await page.locator("#controls-dock").hover();
    await button.click();
  }
}

async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
}

test("desktop: real WebGL, playback, selection, camera, language and cinema provenance", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(page.locator("#stage canvas")).toBeVisible();
  await expect(page.locator("#speed")).toHaveValue("1");
  await expect(page.locator('[data-camera="follow"]')).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#loading")).toBeHidden();
  await expect(page.locator("#error")).toBeHidden();
  await expect(page.locator(".agent-chip")).toHaveCount(15);
  await expect(page.locator(".activity-labels .node-label:not(.service-label)")).toHaveCount(15);
  await pause(page);
  await page.locator("#reset").click();
  await expect(page.locator(".function-node-label:visible")).toHaveCount(0);
  await expect(page.locator(".function-node-label")).toHaveCount(Number(await page.locator("#stage").getAttribute("data-function-count")));
  await expect(page.locator(".function-node-label").first()).toContainText("()");
  await seek(page, 18);
  await expect(page.locator(".agent-name")).toHaveText("Forseti");
  await expect(page.locator("#time")).toHaveText("00:18");
  const geometry = await page.evaluate(() => ({
    introBottom: document.querySelector(".intro-panel")!.getBoundingClientRect().bottom,
    inspectorBottom: document.querySelector(".inspector")!.getBoundingClientRect().bottom,
    playbackTop: document.querySelector(".playback")!.getBoundingClientRect().top,
  }));
  expect(geometry.introBottom).toBeLessThan(geometry.playbackTop);
  expect(geometry.inspectorBottom).toBeLessThan(geometry.playbackTop);
  await page.screenshot({ path: testInfo.outputPath("desktop.png") });
  await seek(page, 2);
  await expect(page.locator(".agent-name")).toHaveText("Huginn");
  await page.locator('[data-agent="Thor"]').click();
  await expect(page.locator(".agent-name")).toHaveText("Thor");
  await expect(page.locator('[data-agent="Thor"]')).toHaveAttribute("aria-pressed", "true");
  await page.locator("#focus").click();
  await expect(page.locator('[data-camera="follow"]')).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#function-list button").first()).toBeVisible();
  await page.locator("#reset").click();
  await expect(page.locator('[data-camera="orbit"]')).toHaveAttribute("aria-pressed", "true");
  await page.locator("#language").click();
  await expect(page.locator("html")).toHaveAttribute("lang", "ko");
  await expect(page.locator(".agent-role")).toHaveText("이벤트 수집");
  await page.locator("#language").click();
  await page.locator("#scenario").selectOption("recovery");
  await expect(page.locator("#duration")).toHaveText("00:56");
  await expect(page.locator(".agent-name")).toHaveText("Loki");
  await page.locator("#labels").uncheck();
  await expect(page.locator(".activity-labels")).toBeHidden();
  await page.locator("#labels").check();
  await page.locator("#cinema").click();
  await expect(page.locator(".cinema-watermark")).toBeVisible();
  await expect(page.locator(".cinema-watermark")).toContainText("SYNTHETIC DEMO");
  await expect(page.locator("#exit-cinema")).toBeFocused();
  await page.screenshot({ path: testInfo.outputPath("cinema.png") });
  await page.keyboard.press("Escape");
  await expect(page.locator("#cinema")).toBeFocused();
  await page.locator("#fullscreen").click();
  await expect.poll(() => page.evaluate(() => document.fullscreenElement !== null)).toBe(true);
  await expect(page.locator(".provenance")).toContainText("SYNTHETIC DEMO");
  await page.locator("#fullscreen").click();
  await noOverflow(page);
  expect(errors).toEqual([]);
});

test("desktop: real Python function selection, source locations, and caller/callee links", async ({ page }) => {
  await page.goto("/");
  await pause(page);
  await page.locator('[data-agent="Huginn"]').click();
  await page.locator("#function-query").fill("_bound_json");
  const target = page.locator('#function-list [data-function="fdai.agents.huginn._bound_json"]');
  await target.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#function-detail h3")).toHaveText("fdai.agents.huginn._bound_json()");
  await expect(page.locator(".source-location")).toContainText("services/core-control-plane/src/fdai/agents/huginn.py:");
  await expect(page.locator(".source-evidence")).toContainText("Runtime invocation is not observed");
  await expect(page.locator(".function-scene-label")).toContainText("_bound_json()");
  await expect(page.locator('#function-list [aria-pressed="true"]')).toBeFocused();
  await expect(page.locator("#function-detail")).toContainText("Static callers");
  expect(Number(await page.locator("#stage").getAttribute("data-function-count"))).toBeGreaterThan(700);
  await page.locator("#function-query").fill("not-a-real-function");
  await expect(page.locator("#function-list")).toHaveText("No matching source functions.");
});

test("desktop: source-declared broadcast fan-out and parallel workers", async ({ page }) => {
  await page.goto("/");
  await pause(page);
  await seek(page, 22);
  await expect(page.locator("#broadcast-topic")).toContainText("Concurrent topics");
  expect(Number(await page.locator("#parallel-count").innerText())).toBeGreaterThanOrEqual(4);
  await expect(page.locator("#concurrent-agents")).toContainText("Heimdall");
  await expect(page.locator("#concurrent-agents")).toContainText("Var");
  await page.locator("#broadcast-panel summary").click();
  await expect(page.locator("#broadcast-detail")).toContainText("Thor -> object.action-run");
  await expect(page.locator("#broadcast-detail")).toContainText("on_typed_message");
  await expect(page.locator(".arg-budget, .arg-workflows, .rate-note")).toHaveCount(0);
  const activeClock = await page.locator("#stage").getAttribute("data-transport-time");
  await page.waitForTimeout(400);
  expect(await page.locator("#stage").getAttribute("data-transport-time")).toBe(activeClock);
  await expect(page.locator(".arg-slots")).toHaveCount(0);
  await page.locator('[data-agent="Thor"]').click();
  await page.locator(".topic-browser > summary").click();
  await expect(page.locator(".topic-browser")).toContainText("object.action-run");
  await page.locator("#cinema").click();
  await expect(page.locator("#flow-panel")).toBeVisible();
  await expect(page.locator(".cinema-watermark")).toContainText("SYNTHETIC DEMO");
});

test("desktop: default 1x, per-second Azure Resource Graph clock, and independent activity phases", async ({ page, baseURL }, testInfo) => {
  if (!baseURL) throw new Error("Neural View tests require a configured base URL.");
  const origin = new URL(baseURL).origin;
  const outside: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).origin !== origin) outside.push(request.url());
  });
  await page.goto("/");
  await expect(page.locator("#speed")).toHaveValue("1");
  await pause(page);
  await seek(page, 0);
  const initial = await page.locator(".workload-lane").evaluateAll((lanes) => lanes.map((lane) => lane.getAttribute("data-active")));
  await expect(page.locator(".workload-lane")).toHaveCount(15);
  expect(await page.locator('.workload-lane[data-active="true"]').count()).toBeGreaterThan(1);
  await page.locator("#play").click();
  const elapsed = await page.evaluate(() => new Promise<{ scenario: number; transport: number }>((resolve) => {
    const scenario = Number((document.querySelector("#timeline") as HTMLInputElement).value);
    const transport = Number(document.querySelector("#stage")!.getAttribute("data-transport-time"));
    setTimeout(() => resolve({
      scenario: Number((document.querySelector("#timeline") as HTMLInputElement).value) - scenario,
      transport: Number(document.querySelector("#stage")!.getAttribute("data-transport-time")) - transport,
    }), 1200);
  }));
  expect(elapsed.transport).toBeGreaterThan(0.9);
  expect(elapsed.transport).toBeLessThan(1.7);
  expect(elapsed.scenario / elapsed.transport).toBeGreaterThan(0.8);
  expect(elapsed.scenario / elapsed.transport).toBeLessThan(1.2);
  await pause(page);
  await seek(page, 2);
  const changed = await page.locator(".workload-lane").evaluateAll((lanes) => lanes.map((lane) => lane.getAttribute("data-active")));
  expect(changed.some((active, index) => active !== initial[index])).toBe(true);
  expect(changed.some((active, index) => active === initial[index])).toBe(true);
  await page.locator('[data-agent="Huginn"]').click();
  await expect(page.locator(".function-node-label")).toHaveCount(Number(await page.locator("#stage").getAttribute("data-function-count")));
  await page.screenshot({ path: testInfo.outputPath("named-functions-parallel.png") });
  expect(outside).toEqual([]);
});

test("desktop: function annotations fade in with zoom and keep invisible targets out of the tab order", async ({ page }, testInfo) => {
  await page.goto("/");
  await pause(page);
  await page.locator("#reset").click();
  await expect(page.locator(".function-node-label:visible")).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("overview-quiet.png") });
  await page.evaluate(() => {
    const zoom = document.querySelector<HTMLButtonElement>("#zoom-in")!;
    for (let step = 0; step < 3; step++) zoom.click();
  });
  await expect.poll(() => page.locator(".function-node-label:visible").count()).toBeGreaterThan(0);
  const labels = await page.locator(".function-node-label:visible").evaluateAll((elements) => elements.map((element) => ({
    opacity: Number(getComputedStyle(element).opacity),
    background: getComputedStyle(element).backgroundColor,
    border: getComputedStyle(element).borderTopWidth,
    name: element.querySelector(".function-annotation-name")?.textContent,
    fullName: element.getAttribute("aria-label"),
    tabIndex: (element as HTMLButtonElement).tabIndex,
  })));
  expect(labels.some((label) => label.opacity > 0 && label.opacity < 0.99)).toBe(true);
  expect(labels.every((label) => label.background === "rgba(0, 0, 0, 0)" && label.border === "0px")).toBe(true);
  expect(labels.every((label) => label.name && label.fullName?.endsWith(`.${label.name}()`))).toBe(true);
  expect(labels.filter((label) => label.opacity < 0.5).every((label) => label.tabIndex === -1)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("zoom-annotations.png") });
  const focusedId = await page.locator('.function-node-label[aria-hidden="false"]:visible').first().getAttribute("data-function-id");
  const focusedAnnotation = page.locator(`.function-node-label[data-function-id="${focusedId}"]`);
  await focusedAnnotation.focus();
  await expect(focusedAnnotation).toBeFocused();
  await page.evaluate(() => {
    const zoom = document.querySelector<HTMLButtonElement>("#zoom-out")!;
    for (let step = 0; step < 4; step++) zoom.click();
  });
  await expect(page.locator(`.function-node-label[data-function-id="${focusedId}"]`)).toBeFocused();
  await expect(page.locator(`.function-node-label[data-function-id="${focusedId}"]`)).toHaveCSS("opacity", "1");
  await page.locator('[data-agent="Huginn"]').click();
  await page.locator("#function-query").fill("_bound_json");
  await page.locator('#function-list [data-function="fdai.agents.huginn._bound_json"]').click();
  await expect(page.locator("#function-detail h3")).toHaveText("fdai.agents.huginn._bound_json()");
  await expect(page.locator(".function-scene-label")).toContainText("_bound_json()");
  await page.locator("#reset").click();
  await expect(page.locator(".function-node-label:visible")).toHaveCount(0, { timeout: 10000 });
  await page.locator("#motion").check();
  await page.evaluate(() => {
    const zoom = document.querySelector<HTMLButtonElement>("#zoom-in")!;
    for (let step = 0; step < 3; step++) zoom.click();
  });
  await expect.poll(() => page.locator(".function-node-label:visible").count()).toBeGreaterThan(0);
});

test("desktop: decorative stars twinkle independently, pause, toggle, and never become graph nodes", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  await page.goto("/");
  await expect(page.locator("#stars")).toBeChecked();
  await expect(page.locator("#stage")).toHaveAttribute("data-decorative-star-count", "360");
  const before = Number(await page.locator("#stage").getAttribute("data-star-time"));
  await expect.poll(async () => Number(await page.locator("#stage").getAttribute("data-star-time"))).toBeGreaterThan(before);
  await pause(page);
  const held = await page.locator("#stage").getAttribute("data-star-time");
  await page.waitForTimeout(150);
  expect(await page.locator("#stage").getAttribute("data-star-time")).toBe(held);
  await page.locator('[data-camera="manual"]').click();
  await page.waitForTimeout(500);
  const graphCount = await page.locator("#stage").getAttribute("data-function-count");
  const withStars = await page.locator("#stage canvas").screenshot();
  await page.locator("#stars").uncheck();
  await expect(page.locator("#stage")).toHaveAttribute("data-stars-visible", "false");
  const withoutStars = await page.locator("#stage canvas").screenshot();
  expect(withStars.equals(withoutStars)).toBe(false);
  expect(await page.locator("#stage").getAttribute("data-function-count")).toBe(graphCount);
  await expect(page.locator(".function-node-label")).toHaveCount(Number(graphCount));
  await page.locator("#stars").check();
  await page.locator("#motion").check();
  await expect(page.locator("#stage")).toHaveAttribute("data-star-time", "0");
  await page.locator("#motion").uncheck();
  await page.locator("#cinema").click();
  await expect(page.locator("#stage")).toHaveAttribute("data-stars-visible", "true");
  await expect(page.locator(".cinema-watermark")).toContainText("SYNTHETIC DEMO");
  await page.screenshot({ path: testInfo.outputPath("cinema-stars.png") });
  expect(errors).toEqual([]);
});

test("desktop: camera tour, reproducible seeks, label decluttering and motion override", async ({ page }, testInfo) => {
  await page.goto("/");
  await pause(page);
  await page.locator('[data-camera="tour"]').click();
  await seek(page, 0);
  await expect(page.locator("#stage")).toHaveAttribute("data-camera-mode", "tour");
  await page.waitForTimeout(1500);
  const first = await page.locator('.activity-labels [data-scene-label="Odin"]').boundingBox();
  for (const [time, shot] of [[9, "broadcast"], [18, "function"], [27, "azure"], [0, "overview"]] as const) {
    await seek(page, time);
    await expect(page.locator("#stage")).toHaveAttribute("data-camera-shot", shot);
  }
  const repeated = await page.locator('.activity-labels [data-scene-label="Odin"]').boundingBox();
  expect(repeated).toEqual(first);
  const collisions = await page.locator("[data-scene-label]:visible").evaluateAll((labels) => {
    const boxes = labels.map((label) => label.getBoundingClientRect());
    let count = 0;
    boxes.forEach((a, index) => boxes.slice(index + 1).forEach((b) => {
      if (a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top) count++;
    }));
    return count;
  });
  expect(collisions).toBe(0);
  await page.locator("#cinema").click();
  await seek(page, 18);
  await expect(page.locator("#tour-status")).toContainText("PYTHON FUNCTION");
  await expect(page.locator(".cinema-watermark")).toContainText("SYNTHETIC DEMO");
  await expect(page.locator(".function-scene-label")).toContainText("Huginn.ingest()");
  const transport = await page.locator("#playback").boundingBox();
  const watermark = await page.locator(".cinema-watermark").boundingBox();
  expect(transport!.y + transport!.height).toBeLessThan(watermark!.y);
  await page.screenshot({ path: testInfo.outputPath("tour-function.png") });
  await page.keyboard.press("Escape");
  await page.locator("#motion").check();
  await expect(page.locator('[data-camera="tour"]')).toBeDisabled();
  await expect(page.locator('[data-camera="manual"]')).toHaveAttribute("aria-pressed", "true");
  await page.locator("#motion").uncheck();
  await page.locator('[data-camera="tour"]').click();
  await page.locator('[data-agent="Huginn"]').click();
  await expect(page.locator('[data-camera="follow"]')).toHaveAttribute("aria-pressed", "true");
});

test("desktop: keyboard, reduced motion, speed and a non-looping ending", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(page.locator("#play")).toHaveAttribute("aria-label", "Play");
  await expect(page.locator("#motion")).toBeChecked();
  await expect(page.locator("#time")).toHaveText("00:00");
  await page.locator("#play").focus();
  await page.keyboard.press("Space");
  await expect(page.locator("#play")).toHaveAttribute("aria-label", "Pause");
  await page.locator("#speed").selectOption("2");
  await page.locator("#loop").click();
  await seek(page, 71.8);
  await expect(page.locator("#play")).toHaveAttribute("aria-label", "Play");
  await expect(page.locator("#time")).toHaveText("01:12");
  await page.locator("#restart").click();
  await expect(page.locator("#time")).toHaveText("00:00");
  await page.locator('[data-agent="Var"]').focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(".agent-name")).toHaveText("Var");
  await expect(page.locator('[data-agent="Var"]')).toBeFocused();
  await page.emulateMedia({ forcedColors: "active" });
  await expect(page.locator('[data-agent="Var"]')).toHaveCSS("outline-style", "solid");
  await noOverflow(page);
});

test("desktop: WebGL unavailable preserves text and exposes an explicit error", async ({ page }) => {
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, ...args: Parameters<typeof original>) {
      if (String(args[0]).includes("webgl")) return null;
      return original.apply(this, args);
    } as typeof original;
  });
  await page.goto("/");
  await expect(page.locator("#error")).toContainText("The 3D view is unavailable");
  await expect(page.locator("#play")).toHaveAttribute("aria-label", "Play");
  await expect(page.locator('[data-camera="orbit"]')).toBeDisabled();
  await expect(page.locator("#focus")).toBeDisabled();
  await page.locator('[data-agent="Saga"]').click();
  await expect(page.locator(".agent-name")).toHaveText("Saga");
  await seek(page, 54);
  await expect(page.locator("#event-detail")).toContainText("Close the evidence trail");
});

test("desktop: graphics loss stops rendering and offers explicit reload", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => {
    const canvas = document.querySelector("canvas")!;
    const context = canvas.getContext("webgl2");
    context?.getExtension("WEBGL_lose_context")?.loseContext();
  });
  await expect(page.locator("#error")).toContainText("graphics context was lost");
  await expect(page.locator("#play")).toHaveAttribute("aria-label", "Play");
  await expect(page.locator("#focus")).toBeDisabled();
  await page.locator("#reload").click();
  await expect(page.locator("#error")).toBeHidden();
  await expect(page.locator("#stage canvas")).toBeVisible();
});

test("constrained desktop then mobile: readable, operable and no horizontal overflow", async ({ page }, testInfo) => {
  await page.goto("/");
  await pause(page);
  for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }, { width: 320, height: 844 }]) {
    await page.setViewportSize(viewport);
    await noOverflow(page);
    await page.locator('[data-agent="Norns"]').click();
    await expect(page.locator(".agent-name")).toHaveText("Norns");
    await page.locator("#language").click();
    await noOverflow(page);
    await expect(page.locator("#scenario")).toBeVisible();
    await expect(page.locator("#speed")).toHaveValue("1");
    await expect(page.locator(".workload-lane")).toHaveCount(15);
    await expect(page.locator(".function-node-label")).toHaveCount(Number(await page.locator("#stage").getAttribute("data-function-count")));
    await page.screenshot({ path: testInfo.outputPath(`ko-${viewport.width}.png`), fullPage: true });
    if (viewport.width === 993) {
      expect(await page.evaluate(() => document.querySelector(".intro-panel")!.getBoundingClientRect().bottom
        < document.querySelector(".playback")!.getBoundingClientRect().top)).toBe(true);
    }
    await page.locator("#language").click();
    await page.locator("#clear").click();
  }
});
