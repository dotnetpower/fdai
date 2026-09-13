/** Verify both visual-study themes without calling a live backend or an external renderer. */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const require = createRequire(join(root, "console/package.json"));
const { chromium } = require("playwright");

test("icon theme changes preserve readable cards, title, and control targets", { timeout: 20000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
    await page.route("**/*", route => new URL(route.request().url()).origin === "http://127.0.0.1:5373"
      ? route.continue() : route.abort());
    await page.goto("http://127.0.0.1:5373/#mocks/ui/agent-icons.html");
    const frame = await (await page.locator("#preview-frame").elementHandle()).contentFrame();
    const toggle = frame.locator("#icon-theme-toggle");
    await toggle.click();
    assert.equal(await toggle.getAttribute("aria-pressed"), "true");
    await frame.waitForFunction(() => getComputedStyle(document.querySelector("h1")).color === "rgb(38, 49, 61)");
    assert.equal(await frame.locator("h1").evaluate(element => getComputedStyle(element).color), "rgb(38, 49, 61)");
    assert.equal(await frame.locator(".name").first().evaluate(element => getComputedStyle(element).color), "rgb(38, 49, 61)");
    const folder = join(root, ".fdai/visual-review/interactions-study");
    await mkdir(folder, { recursive: true });
    await page.screenshot({ path: join(folder, "icons-light.png") });
    await toggle.click();
    assert.equal(await toggle.getAttribute("aria-pressed"), "false");
    await frame.waitForFunction(() => getComputedStyle(document.querySelector("h1")).color === "rgb(231, 237, 246)");
    assert.equal(await frame.locator("h1").evaluate(element => getComputedStyle(element).color), "rgb(231, 237, 246)");
    await page.setViewportSize({ width: 390, height: 844 });
    await frame.waitForFunction(() => innerWidth <= 390 && document.querySelector(".toolbar button").getBoundingClientRect().height >= 44);
    assert.ok(await frame.locator(".toolbar button").evaluateAll(elements => elements.every(element => element.getBoundingClientRect().height >= 44)));
    await writeFile(join(folder, "results.json"), JSON.stringify({ name: "Icon dark/light and mobile targets", disposition: "passed", scope: "synthetic-local-mocks" }) + "\n");
  } finally {
    await browser.close();
  }
});
