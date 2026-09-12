/** Ensure the redesigned Resource page does not reuse pre-upgrade asset identities. */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const require = createRequire(join(root, "console/package.json"));
const { chromium } = require("playwright");
const origin = "http://127.0.0.1:5373";

test("Resource workspace loads current styles and controllers with legacy payloads retained", { timeout: 20000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  const legacyRequests = [];
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
    page.setDefaultTimeout(6000);
    await page.route("**/*", route => {
      const url = new URL(route.request().url());
      if (url.origin !== origin) return route.abort("blockedbyclient");
      const legacyStyle = url.pathname.endsWith("/dashboard-resource-essential.css") ||
        url.pathname.endsWith("/dashboard-essential.css") ||
        (url.pathname.endsWith("/dashboard-resource-workspace.css") && ["1", "2", "3"].includes(url.searchParams.get("v"))) ||
        (url.pathname.endsWith("/calm-slate.css") && url.searchParams.get("v") === "page-context-v3");
      const legacyController =
        (url.pathname.endsWith("/dashboard-resources.js") && ["resource-map-v1", "resource-workspace-v1", "resource-workspace-v2"].includes(url.searchParams.get("v"))) ||
        (url.pathname.endsWith("/dashboard-resource-views.js") && ["resource-map-v2", "resource-workspace-v1", "resource-workspace-v2"].includes(url.searchParams.get("v"))) ||
        (url.pathname.endsWith("/dashboard-v2-workspace.js") && ["2", "resource-workspace-v1", "resource-workspace-v2"].includes(url.searchParams.get("v"))) ||
        (url.pathname.endsWith("/dashboard-resource-preview.js") && url.searchParams.get("v") === "resource-map-v3") ||
        (url.pathname.endsWith("/preview-history.js") && ["1", "2", "3"].includes(url.searchParams.get("v")));
      if (legacyStyle || legacyController) {
        legacyRequests.push(url.pathname);
        return route.fulfill({
          contentType: legacyStyle ? "text/css" : "text/javascript",
          body: "/* Retained pre-workspace revision. */",
        });
      }
      return route.continue();
    });
    await page.goto(`${origin}/#mocks/ui/dashboard-v2.html`);
    const frame = await (await page.locator("#preview-frame").elementHandle()).contentFrame();
    await frame.waitForLoadState("load");
    await frame.waitForFunction(() => window.FdaiDashboardV2Snapshot?.resources.length === 24 &&
      document.querySelectorAll(".dr-cell").length === 24);
    assert.deepEqual(legacyRequests, []);
    const styles = await frame.evaluate(() => ({
      scope: getComputedStyle(document.querySelector(".rd-snapshot")).backgroundColor,
      map: getComputedStyle(document.querySelector(".rd-map-surface")).backgroundColor,
      summaries: [...document.querySelectorAll(".dr-summary > div")].map(el => ({
        background: getComputedStyle(el).backgroundColor,
        display: getComputedStyle(el).display,
      })),
    }));
    assert.equal(styles.scope, "rgba(0, 0, 0, 0)");
    assert.equal(styles.map, "rgb(255, 255, 255)");
    assert.equal(styles.summaries.length, 4);
    assert.ok(styles.summaries.every(row => row.display === "grid" && row.background === "rgb(255, 255, 255)"));
  } finally {
    await browser.close();
  }
});
