import { expect, test } from "@playwright/test";
import graph from "../../src/generated/code-graph.json" with { type: "json" };

test.use({ trace: "off", contextOptions: { reducedMotion: "no-preference" } });

test("fresh AST, inset inspector, right-side OpenAI and fast channel streams are source-backed", async ({ page }, testInfo) => {
  const external: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.origin !== "http://127.0.0.1:5573" || url.pathname.startsWith("/__neural/")) external.push(url.pathname);
  });
  await page.goto("/");
  await expect(page.locator("#loading")).toBeHidden();
  await expect(page.locator("#error")).toBeHidden();
  const stage = page.locator("#stage");
  await expect(stage).toHaveAttribute("data-function-count", String(graph.functions.length));
  expect(graph.functions.length).toBeGreaterThan(1000);
  await expect(page.locator(".agent-chip")).toHaveCount(15);
  const inset = await page.locator(".activity-inspector").evaluate((panel) =>
    panel.querySelector(".section-heading")!.getBoundingClientRect().left - panel.getBoundingClientRect().left);
  expect(inset).toBe(12);
  await page.locator("#controls-dock").hover();
  await page.locator("#play").click();
  await page.locator("#reset").click();
  await page.locator("#motion").check();
  await page.locator('[data-camera="manual"]').click();
  await page.locator("#motion").uncheck();
  await page.locator("#timeline").fill("1.5");
  await page.mouse.move(24, 90);
  const openai = page.locator('[data-service-port="openai"]');
  const consoleStream = page.locator('[data-service-port="console"]');
  await expect(openai).toBeVisible();
  await expect(consoleStream).toBeVisible();
  const field = (await stage.boundingBox())!;
  expect((await openai.boundingBox())!.x).toBeGreaterThan(field.x + field.width / 2);
  expect((await consoleStream.boundingBox())!.x).toBeLessThan(field.x + field.width / 2);
  await expect.poll(async () => Number(await stage.getAttribute("data-channel-stream-particles"))).toBeGreaterThan(20);
  const held = await stage.getAttribute("data-service-particles");
  await page.screenshot({ path: testInfo.outputPath("model-channel-overview.png") });
  await page.locator("#controls-dock").hover();
  await page.locator("#timeline").fill("3");
  await page.locator("#timeline").fill("1.5");
  await expect(stage).toHaveAttribute("data-service-particles", held!);
  await page.mouse.move(24, 90);
  await openai.click();
  await expect(page.locator(".agent-name")).toHaveText("Azure OpenAI");
  await expect(page.locator(".agent-role").first()).toContainText("not an agent");
  await expect(page.locator("#function-detail h3")).toContainText("LocalAzureNarratorAdapters._stream_answer()");
  await expect(page.locator("#clear")).toBeEnabled();
  await page.screenshot({ path: testInfo.outputPath("openai-source-inspector.png") });
  await page.locator("#clear").click();
  await expect(page.locator(".agent-name")).toHaveText("Huginn");
  await page.locator(".adapter-browser > summary").click();
  const entry = page.locator('[data-service-entry="console"]');
  await entry.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(".agent-name")).toHaveText("Channels");
  await expect(page.locator("#function-detail h3")).toContainText("_live_chunks()");
  await expect(page.locator(".adapter-browser")).toContainText("not measured throughput");
  await page.locator("#motion").check();
  await expect(stage).toHaveAttribute("data-service-particles", "0");
  await page.locator("#reset").click();
  await page.locator("#cinema").click();
  await expect(openai).toBeVisible();
  await expect(page.locator(".cinema-watermark")).toContainText("SYNTHETIC DEMO");
  const labelBox = (await openai.boundingBox())!;
  const exitBox = (await page.locator("#exit-cinema").boundingBox())!;
  expect(labelBox.x < exitBox.x + exitBox.width && labelBox.x + labelBox.width > exitBox.x
    && labelBox.y < exitBox.y + exitBox.height && labelBox.y + labelBox.height > exitBox.y).toBe(false);
  await page.screenshot({ path: testInfo.outputPath("model-channel-cinema.png") });
  expect(external).toEqual([]);
});

test("service sources and inspector remain usable at constrained and mobile widths", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/?lang=ko");
  for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    const disclosure = page.locator(".adapter-browser > summary");
    if (await page.locator(".adapter-browser").getAttribute("open") === null) await disclosure.click();
    await page.locator('[data-service-entry="slack"]').click();
    await expect(page.locator(".agent-name")).toHaveText("채널");
    await expect(page.locator("#function-detail h3")).toContainText("SlackWebhookChannel.send()");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  }
});
