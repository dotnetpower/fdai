import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const require = createRequire(join(root, "console/package.json"));
const { chromium } = require("playwright");
const origin = "http://127.0.0.1:5373";
const output = join(root, ".fdai/visual-review/lineage");
const evidence = [];
const errors = [];
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
await context.route("**/*", route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
const page = await context.newPage();
page.setDefaultTimeout(6000);
page.on("pageerror", error => errors.push(error.message));
await mkdir(output, { recursive: true });

async function measure(frame, name) {
  await frame.evaluate(async () => {
    await Promise.all([...document.images].map(image => image.decode()));
  });
  const result = await frame.evaluate(() => {
    const main = document.querySelector("main");
    const visible = element => element.getClientRects().length && !element.closest("[hidden]");
    const controls = [...document.querySelectorAll("button, input, select")].filter(visible);
    const images = [...document.images].filter(visible);
    const nodes = [...document.querySelectorAll(".ln-node")];
    const overlaps = nodes.flatMap((node, index) => nodes.slice(index + 1).filter(other => {
      const box = node.getBoundingClientRect(), otherBox = other.getBoundingClientRect();
      return box.left < otherBox.right && box.right > otherBox.left && box.top < otherBox.bottom && box.bottom > otherBox.top;
    }).map(other => [node.dataset.node, other.dataset.node]));
    return {
      width: innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      mainWidth: main.clientWidth,
      mainScrollWidth: main.scrollWidth,
      brokenImages: images.filter(image => !image.complete || !image.naturalWidth).map(image => image.src),
      unnamedControls: controls.filter(control => !control.textContent.trim() && !control.getAttribute("aria-label") && !control.labels?.length).length,
      clippedNodes: nodes.filter(node => node.scrollHeight > node.clientHeight + 1 || node.scrollWidth > node.clientWidth + 1).map(node => node.dataset.node),
      overlaps,
    };
  });
  assert.equal(result.width, result.documentWidth, `${name}: document overflow`);
  assert.equal(result.mainWidth, result.mainScrollWidth, `${name}: main overflow`);
  assert.deepEqual(result.brokenImages, [], `${name}: broken assets`);
  assert.equal(result.unnamedControls, 0, `${name}: unnamed controls`);
  assert.deepEqual(result.clippedNodes, [], `${name}: clipped nodes`);
  assert.deepEqual(result.overlaps, [], `${name}: overlapping nodes`);
  evidence.push({ name, disposition: "passed", result });
}

try {
  const started = performance.now();
  await page.goto(`${origin}/#mocks/ui/lineage.html`, { waitUntil: "load" });
  await page.waitForFunction(() => {
    const frame = document.querySelector("#preview-frame");
    return frame?.contentWindow.location.pathname === "/mocks/ui/lineage.html" &&
      frame.contentDocument?.querySelector('[data-node="forseti"]');
  });
  const frame = await (await page.locator("#preview-frame").elementHandle()).contentFrame();
  await frame.locator('[data-node="forseti"]').waitFor();
  const loadMs = performance.now() - started;
  assert.ok(loadMs < 5000, `initial local render ${loadMs}ms exceeds 5s budget`);
  assert.equal(await frame.locator(".ln-node").count(), 17);
  assert.equal(await frame.locator(".ln-edge").count(), 16);
  assert.equal(await frame.locator(".ln-edge.is-missing").count(), 2);
  assert.match(await frame.locator("#caseState").innerText(), /Held/);
  assert.match(await frame.locator(".ln-boundary").innerText(), /No live sources/);
  await measure(frame, "Desktop default, master shell");
  await page.screenshot({ path: join(output, "desktop.png"), fullPage: true });

  await frame.locator('[data-node="aks"]').focus();
  await page.keyboard.press("Enter");
  assert.match(await frame.locator("#lineageInspector h2").innerText(), /Kubernetes API/);
  assert.equal(await frame.locator('[data-node="aks"]').getAttribute("aria-pressed"), "true");
  assert.notEqual(await frame.locator('[data-node="aks"]').evaluate(element => getComputedStyle(element).outlineStyle), "none");
  await frame.locator("#lineageFocus").click();
  assert.equal(await frame.locator(".ln-node").count(), 2);
  await frame.locator("#lineageReset").click();
  assert.equal(await frame.locator(".ln-node").count(), 17);
  await frame.locator("#lineageZoomIn").click();
  assert.equal(await frame.locator("#lineageZoom").innerText(), "113%");
  await frame.locator("#lineageZoomOut").click();
  assert.equal(await frame.locator("#lineageZoom").innerText(), "100%");
  await frame.locator("#lineageSearch").fill("no-matching-record");
  assert.equal(await frame.locator(".ln-node").count(), 0);
  assert.equal(await frame.locator("#lineageEmpty").isVisible(), true);
  await frame.locator("#lineageSearch").fill("");
  await frame.locator("#lineageScenario").selectOption("complete");
  assert.equal(await frame.locator(".ln-edge.is-missing").count(), 0);
  assert.match(await frame.locator("#caseState").innerText(), /shadow review only/);
  await frame.locator('[data-node="decision"]').click();
  assert.match(await frame.locator("#lineageInspector").innerText(), /no approval, dispatch or effect-verification/);
  await measure(frame, "Desktop qualified alternate, no execution");
  await frame.locator("#lineageScenario").selectOption("held");
  await frame.locator('[data-view="sources"]').click();
  assert.equal(await frame.locator(".ln-source-row").count(), 12);
  await frame.locator("#lineageSearch").fill("Prometheus");
  assert.equal(await frame.locator(".ln-source-row").count(), 1);
  await frame.locator('[data-select="prom"]').click();
  assert.equal(await frame.locator("#lineageLayout").isVisible(), true);
  assert.match(await frame.locator("#lineageInspector h2").innerText(), /Prometheus/);
  evidence.push({ name: "Keyboard selection, neighborhood, zoom, search, source drill-down and scenario controls", disposition: "passed", loadMs });

  await frame.locator('[data-node="forseti"]').click();
  const textContrast = await frame.evaluate(() => {
    function luminance(color) {
      return color.match(/[\d.]+/g).slice(0, 3).map(Number).map(value => value / 255).map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4).reduce((total, value, index) => total + value * [.2126, .7152, .0722][index], 0);
    }
    return [...document.querySelectorAll(".ln-node strong, .ln-node small, .ln-node-state, .ln-column, .ln-warning, .ln-inspector p")].map(element => {
      let parent = element;
      let background = getComputedStyle(parent).backgroundColor;
      while (background === "rgba(0, 0, 0, 0)" && parent.parentElement) { parent = parent.parentElement; background = getComputedStyle(parent).backgroundColor; }
      const foregroundValue = luminance(getComputedStyle(element).color), backgroundValue = luminance(background);
      return { text: element.textContent.trim(), ratio: (Math.max(foregroundValue, backgroundValue) + .05) / (Math.min(foregroundValue, backgroundValue) + .05) };
    });
  });
  assert.deepEqual(textContrast.filter(item => item.ratio < 4.5), []);
  evidence.push({ name: "Graph and inspector text contrast", disposition: "passed", minimum: Math.min(...textContrast.map(item => item.ratio)) });

  for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }, { width: 320, height: 844 }]) {
    await page.setViewportSize(viewport);
    await measure(frame, `${viewport.width}px master frame`);
    await frame.locator('[data-view="sources"]').click();
    await measure(frame, `${viewport.width}px source register`);
    await frame.locator('[data-view="graph"]').click();
    await page.screenshot({ path: join(output, `${viewport.width}.png`), fullPage: true });
  }
  await context.close();
  assert.deepEqual(errors, []);
  const rootIndex = await readFile(join(root, "index.html"), "utf8");
  const nestedIndex = await readFile(join(root, "mocks/ui/index.html"), "utf8");
  assert.match(rootIndex, /data-page="mocks\/ui\/lineage.html"/);
  assert.match(nestedIndex, /data-page="lineage.html"/);
  await writeFile(join(output, "evidence.json"), JSON.stringify({ venue: "static-mock", customerData: false, evidence }, null, 2));
  console.log(JSON.stringify({ result: "passed", checks: evidence.length, output, errors }, null, 2));
} finally {
  await browser.close();
}
