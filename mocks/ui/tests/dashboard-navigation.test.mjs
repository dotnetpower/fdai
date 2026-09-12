/** Local-only navigation memory and theme-aware menu tooltip regressions. */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const require = createRequire(join(root, "console/package.json"));
const { chromium } = require("playwright");
const origin = "http://127.0.0.1:5373";

test("Dashboard preserves per-entry disclosure, scroll and focus through back and forward", { timeout: 30000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
    await context.route("**/*", route => new URL(route.request().url()).origin === origin
      ? route.continue() : route.abort());
    const page = await context.newPage();
    page.setDefaultTimeout(6000);
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto(`${origin}/#mocks/ui/dashboard.html`);
    const frame = await (await page.locator("#preview-frame").elementHandle()).contentFrame();
    await frame.locator(".de-preview-note").waitFor();
    await page.evaluate(() => history.replaceState({ ...history.state, unrelated: "preserve-me" }, "", location.href));
    const summary = frame.locator("#operational-evidence > summary");
    await summary.click();
    const link = frame.locator('.de-verticals a[href^="verticals.html#"]').first();
    await link.evaluate(el => el.setAttribute("href", "verticals.html#%72esilience"));
    await link.focus();
    await link.evaluate(el => el.scrollIntoView({ block: "center", behavior: "instant" }));
    const y = await frame.evaluate(() => scrollY);
    assert.ok(y > 0);
    await link.press("Enter");
    await frame.waitForFunction(() => location.pathname.endsWith("/verticals.html") && location.hash === "#resilience");
    await page.goBack();
    await frame.locator("#operational-evidence").waitFor({ state: "attached" });
    await frame.waitForFunction(expected => {
      const details = document.getElementById("operational-evidence");
      return details?.open && Math.abs(scrollY - expected) < 2;
    }, y);
    assert.equal(await link.evaluate(el => document.activeElement === el), true);
    assert.equal(await page.evaluate(() => history.state.unrelated), "preserve-me");
    const state = await page.evaluate(() => history.state.fdaiMockView);
    assert.equal(state.disclosures[0].id, "operational-evidence");
    assert.equal(state.disclosures[0].open, true);
    assert.ok(!JSON.stringify(state).includes("input"));
    await page.goForward();
    await frame.waitForFunction(() => location.pathname.endsWith("/verticals.html") && location.hash === "#resilience");
    await page.goBack();
    await frame.waitForFunction(expected => document.getElementById("operational-evidence")?.open &&
      Math.abs(scrollY - expected) < 2, y);
    await summary.click();
    const resourceLink = frame.locator('a[href="dashboard-v2.html"]');
    await resourceLink.click();
    await frame.waitForFunction(() => location.pathname.endsWith("/dashboard-v2.html"));
    await page.goBack();
    await frame.locator("#operational-evidence").waitFor({ state: "attached" });
    await frame.waitForFunction(() => !document.getElementById("operational-evidence").open);
    assert.equal(await resourceLink.evaluate(el => document.activeElement === el), true);
    await summary.click();
    const modeLink = frame.locator('.de-audit-summary a[href="audit.html?window=30d&mode=shadow"]');
    await modeLink.click();
    await frame.waitForFunction(() => location.pathname.endsWith("/audit.html") &&
      new URLSearchParams(location.search).get("mode") === "shadow");
    await page.locator('.rail-button[data-nav-target="overview"]').click();
    await page.locator('.side a[data-page="mocks/ui/dashboard.html"]').click();
    await frame.locator("#operational-evidence").waitFor({ state: "attached" });
    assert.equal(await frame.locator("#operational-evidence").evaluate(el => el.open), false);
    await page.goBack();
    await frame.waitForFunction(() => location.pathname.endsWith("/audit.html") &&
      new URLSearchParams(location.search).get("window") === "30d");
    await page.goBack();
    await frame.waitForFunction(() => document.getElementById("operational-evidence")?.open);
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
});

for (const savedTarget of ["none", "summary"]) {
  test(`reload restores presentation without moving focus (${savedTarget})`, { timeout: 30000 }, async () => {
    const browser = await chromium.launch({ headless: true });
    try {
      const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
      await context.route("**/*", route => new URL(route.request().url()).origin === origin
        ? route.continue() : route.abort());
      await context.addInitScript(() => {
        const originalFocus = HTMLElement.prototype.focus;
        window.previewFocusCalls = [];
        HTMLElement.prototype.focus = function (...args) {
          window.previewFocusCalls.push({ tag: this.tagName, id: this.id });
          return originalFocus.apply(this, args);
        };
      });
      const page = await context.newPage();
      page.setDefaultTimeout(6000);
      await page.goto(`${origin}/#mocks/ui/dashboard.html`);
      let frame = await (await page.locator("#preview-frame").elementHandle()).contentFrame();
      await frame.waitForLoadState("load");
      await frame.locator("#operational-evidence > summary").click();
      if (savedTarget === "none") await frame.locator("#evidence-context-title").click();
      await page.waitForFunction(target => {
        const saved = history.state?.fdaiMockView;
        return saved?.disclosures[0].open && (target === "none" ? saved.focus === null : saved.focus?.tag === "SUMMARY");
      }, savedTarget);
      const saved = await page.evaluate(() => history.state.fdaiMockView);
      await page.reload();
      frame = await (await page.locator("#preview-frame").elementHandle()).contentFrame();
      await frame.waitForLoadState("load");
      await frame.waitForFunction(y => document.getElementById("operational-evidence")?.open &&
        Math.abs(scrollY - y) < 2, saved.y);
      assert.deepEqual(await frame.evaluate(() => window.previewFocusCalls), []);
      assert.equal(await frame.evaluate(() => document.activeElement.id === "dashboard-main"), false);

      if (savedTarget === "none") {
        await page.locator('.side a[data-page="mocks/ui/operating-outcomes.html"]').click();
        await frame.waitForFunction(() => location.pathname.endsWith("/operating-outcomes.html"));
        await page.goBack();
        await frame.waitForFunction(() => document.getElementById("operational-evidence")?.open);
        assert.deepEqual(await frame.evaluate(() => window.previewFocusCalls), []);
      } else {
        const link = frame.locator('.de-verticals a[href="verticals.html#resilience"]');
        await link.focus();
        await link.press("Enter");
        await frame.waitForFunction(() => location.pathname.endsWith("/verticals.html"));
        await page.goBack();
        await frame.waitForFunction(() => document.getElementById("operational-evidence")?.open &&
          document.activeElement?.getAttribute("href") === "verticals.html#resilience");
        assert.equal(await link.evaluate(el => document.activeElement === el), true);
      }
      const skip = frame.getByRole("link", { name: "Skip to dashboard content" });
      await skip.focus();
      await skip.press("Enter");
      await frame.waitForFunction(() => document.activeElement.id === "dashboard-main");
      assert.equal(await frame.locator("#dashboard-main").evaluate(el => getComputedStyle(el).outlineStyle), "solid");
    } finally {
      await browser.close();
    }
  });
}

test("light menu tooltips are white, hoverable and dismissible without losing keyboard focus", { timeout: 20000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
    await page.route("**/*", route => new URL(route.request().url()).origin === origin
      ? route.continue() : route.abort());
    await page.goto(`${origin}/#mocks/ui/dashboard.html`);
    const toggle = page.getByRole("button", { name: "Toggle design navigation", exact: true });
    await toggle.click();
    await toggle.hover();
    const colors = await toggle.evaluate(el => {
      const style = getComputedStyle(el, "::after");
      return { background: style.backgroundColor, color: style.color, visibility: style.visibility };
    });
    assert.deepEqual(colors, { background: "rgb(255, 255, 255)", color: "rgb(44, 51, 58)", visibility: "visible" });
    const bounds = await toggle.boundingBox();
    await page.mouse.move(bounds.x + bounds.width + 20, bounds.y + bounds.height / 2);
    assert.equal(await toggle.evaluate(el => getComputedStyle(el, "::after").visibility), "visible");
    await page.keyboard.press("Escape");
    assert.equal(await toggle.evaluate(el => getComputedStyle(el, "::after").visibility), "hidden");
    await page.mouse.move(500, 24);
    await toggle.focus();
    await toggle.press("Tab");
    await page.keyboard.press("Shift+Tab");
    assert.equal(await toggle.evaluate(el => getComputedStyle(el, "::after").visibility), "visible");
    await toggle.press("Escape");
    assert.equal(await toggle.evaluate(el => getComputedStyle(el, "::after").visibility), "hidden");
    assert.equal(await toggle.evaluate(el => document.activeElement === el), true);
  } finally {
    await browser.close();
  }
});
