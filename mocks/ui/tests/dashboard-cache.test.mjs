/** Verify the full stylesheet dependency chain against retained pre-metric payloads. */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const require = createRequire(join(root, "console/package.json"));
const { chromium } = require("playwright");
const origin = "http://127.0.0.1:5373";

test("Dashboard metric styles survive retained legacy parent and primitive CSS payloads", { timeout: 20000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
    await page.route("**/*", route => {
      const url = new URL(route.request().url());
      if (url.origin !== origin) return route.abort("blockedbyclient");
      if (url.pathname === "/mocks/ui/assets/calm-slate.css" && url.searchParams.get("v") === "page-context-v3") {
        return route.fulfill({
          contentType: "text/css",
          body: '@import url("../../../ui/calm-slate-tokens.css?v=semantic-type-v5");\n' +
            '@import url("../../../ui/calm-slate-primitives.css?v=semantic-type-v5");',
        });
      }
      if (url.pathname === "/ui/calm-slate-primitives.css" && url.searchParams.get("v") === "semantic-type-v5") {
        return route.fulfill({
          contentType: "text/css",
          body: "/* A retained revision before metric-grid and metric-link primitives existed. */",
        });
      }
      return route.continue();
    });
    await page.goto(`${origin}/#mocks/ui/dashboard.html`);
    const frame = await (await page.locator("#preview-frame").elementHandle()).contentFrame();
    await frame.locator(".de-outcome-grid").waitFor();
    await frame.waitForLoadState("load");
    const styles = await frame.locator(".de-outcome-grid").evaluate(el => ({
      display: getComputedStyle(el).display,
      cards: [...el.children].map(card => ({
        display: getComputedStyle(card).display,
        background: getComputedStyle(card).backgroundColor,
        width: card.getBoundingClientRect().width,
      })),
    }));
    assert.equal(styles.display, "grid");
    assert.equal(styles.cards.length, 4);
    assert.ok(styles.cards.every(card => card.display === "grid" && card.background === "rgb(255, 255, 255)"));
    assert.ok(Math.max(...styles.cards.map(card => card.width)) - Math.min(...styles.cards.map(card => card.width)) < 1);
    await page.setViewportSize({ width: 1920, height: 1080 });
    const wide = await frame.locator(".de-outcome-grid > a").evaluateAll(elements =>
      elements.map(el => ({ top: el.getBoundingClientRect().top, width: el.getBoundingClientRect().width })));
    assert.equal(wide.length, 4);
    assert.ok(Math.max(...wide.map(card => card.top)) - Math.min(...wide.map(card => card.top)) < 1);
    assert.ok(Math.max(...wide.map(card => card.width)) - Math.min(...wide.map(card => card.width)) < 1);
  } finally {
    await browser.close();
  }
});
