/** Local English-deck rendering regression. Captures and reports are never written into the checkout. */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { inspectTextGeometry } from "./target-architecture-text-geometry.mjs";
import { inspectSlideLayout } from "./slide-layout-geometry.mjs";
import { inspectSlideConnectors } from "./slide-connector-geometry.mjs";
import { verifySlideLayout } from "./slide-layout-fixtures.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const sourceRoot = join(root, "tools/manual-studio");
const output = process.argv[2];
assert.ok(output && isAbsolute(output), "Provide an absolute artifact directory outside the repository.");
const outputRelation = relative(root, resolve(output));
assert.ok(outputRelation === ".." || outputRelation.startsWith(`..${sep}`) || isAbsolute(outputRelation),
  "Rendering artifacts must stay outside the repository.");
const modes = (process.argv[3] || "desktop,tablet,mobile,fullscreen,print").split(",");
const viewports = {
  desktop: { width: 1440, height: 900 }, tablet: { width: 993, height: 641 },
  mobile: { width: 390, height: 844 }, fullscreen: { width: 1440, height: 900 },
  print: { width: 1536, height: 864 },
};
assert.ok(modes.every(mode => mode in viewports), "Unknown rendering mode.");
const catalog = JSON.parse(await readFile(join(sourceRoot, "catalog.json"), "utf8"));
const selectedIds = process.argv[4]?.split(",");
const manuals = catalog.manuals.filter(manual => !selectedIds || selectedIds.includes(manual.id));
assert.equal(manuals.length, selectedIds?.length ?? catalog.manuals.length, "Unknown or duplicated manual.");
const require = createRequire(join(root, "console/package.json"));
const { chromium } = require("playwright");
const origin = "http://127.0.0.1:5474";
const results = [], failures = [], pageErrors = [], failedRequests = [];
const startedAt = Date.now();
let lastProgressAt = startedAt, stageStartedAt = startedAt;
const browser = await chromium.launch({ headless: true, timeout: 15000 });
const deadline = setInterval(() => {
  const now = Date.now();
  if (now - startedAt > 600000 || now - stageStartedAt > 90000 || now - lastProgressAt > 30000) {
    console.error("English visual validation exceeded its total, stage, or no-progress deadline.");
    void browser.close();
    clearInterval(deadline);
    process.exitCode = 1;
  }
}, 1000).unref();

/** Record the actual runtime and checker bytes, including artwork and fonts. */
async function sourceDigests(directory = sourceRoot, prefix = "") {
  const digests = {};
  for (const item of (await readdir(directory, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))) {
    if (item.name === "node_modules") continue;
    const name = `${prefix}${item.name}`;
    if (item.isDirectory()) Object.assign(digests, await sourceDigests(join(directory, item.name), `${name}/`));
    else if (/\.(?:js|mjs|css|html|woff2?|ttf|otf|png|jpe?g|svg)$/.test(item.name) ||
      ["catalog.json", "messages.en.json", "messages.ko.json", "package.json"].includes(name)) {
      digests[name] = createHash("sha256").update(await readFile(join(directory, item.name))).digest("hex");
    }
  }
  return digests;
}

/** Create comparison-only sheets from screenshots that were captured at the asserted viewport. */
async function contactSheet(directory, count, name) {
  const images = await Promise.all(Array.from({ length: count }, async (_, index) => {
    const number = String(index + 1).padStart(2, "0");
    const image = await readFile(join(directory, `${number}.png`));
    return `<figure><img src="data:image/png;base64,${image.toString("base64")}"><figcaption>${number}</figcaption></figure>`;
  }));
  const sheet = await browser.newPage({ viewport: { width: 1560, height: 1100 } });
  try {
    await sheet.setContent(`<html><head><style>body{margin:0;padding:16px;background:#e9eef2;display:grid;grid-template-columns:repeat(5,1fr);gap:12px;font:14px/1.4 sans-serif}figure{margin:0}img{display:block;width:100%}figcaption{padding:4px 0}</style></head><body>${images.join("")}</body></html>`);
    await sheet.screenshot({ path: join(output, `${name}.png`), fullPage: true });
  } finally { await sheet.close(); }
}

/** Wait for actual painted text and image decoding rather than sampling hidden animation frames. */
async function settle(page) {
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all([...document.images].map(image => image.decode()));
    await Promise.all(document.getAnimations().map(animation => animation.finished));
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
}

try {
  await mkdir(output, { recursive: true });
  const beforeDigests = await sourceDigests();
  const page = await browser.newPage({ viewport: viewports.desktop, reducedMotion: "reduce", locale: "en-US" });
  page.setDefaultTimeout(10000);
  const geometryFixtures = await verifySlideLayout(page);
  await page.route("**/*", route => {
    if (new URL(route.request().url()).origin === origin) return route.continue();
    failedRequests.push("External request blocked");
    return route.abort();
  });
  page.on("pageerror", error => pageErrors.push(error.message));
  page.on("console", message => { if (message.type() === "error") pageErrors.push(message.text()); });
  page.on("requestfailed", request => failedRequests.push(new URL(request.url()).pathname));
  page.on("response", response => {
    if (response.status() >= 400) failedRequests.push(`${response.status()} ${new URL(response.url()).pathname}`);
  });

  for (const manual of manuals) for (const mode of modes) {
    stageStartedAt = Date.now();
    lastProgressAt = stageStartedAt;
    console.log(`English visual: ${manual.id} / ${mode} / ${manual.slideCount} slides`);
    await page.emulateMedia({ media: "screen", reducedMotion: "reduce" });
    await page.setViewportSize(viewports[mode]);
    await page.goto(`${origin}/${manual.id}.html?slide=1&locale=en`, { waitUntil: "load", timeout: 15000 });
    await page.locator("#viewer[open] .manual-slide.active").waitFor();
    await settle(page);
    assert.equal(await page.locator(".manual-slide").count(), manual.slideCount);
    assert.equal(await page.locator("html").getAttribute("lang"), "en");
    assert.deepEqual(await page.evaluate(() => ({ width: innerWidth, height: innerHeight })), viewports[mode]);
    await page.addScriptTag({ content: `${inspectTextGeometry}\n${inspectSlideLayout}\n${inspectSlideConnectors}` });
    if (mode === "fullscreen") {
      await page.locator("#fullscreen-manual").click();
      await page.waitForFunction(() => document.fullscreenElement?.id === "slide-stage");
    } else if (mode === "print") await page.emulateMedia({ media: "print", reducedMotion: "reduce" });
    await settle(page);
    const directory = join(output, manual.id, mode);
    await mkdir(directory, { recursive: true });

    for (let index = 0; index < manual.slideCount; index += 1) {
      if (index && mode !== "print") {
        await page.keyboard.press("ArrowRight");
        await page.waitForFunction(expected => document.querySelector(".manual-slide.active")?.dataset.index === String(expected), index);
        await settle(page);
      }
      const slide = page.locator(`.manual-slide[data-index="${index}"]`);
      const result = await slide.evaluate((element, renderingMode) => {
        const layout = inspectSlideLayout(element);
        const connectors = inspectSlideConnectors(element);
        layout.findings.push(...connectors.findings);
        const rect = element.getBoundingClientRect();
        const stage = document.querySelector("#slide-stage").getBoundingClientRect();
        if (element.offsetWidth !== 1536 || element.offsetHeight !== 864) {
          layout.findings.push({ kind: "canvas-size", detail: `${element.offsetWidth}x${element.offsetHeight}` });
        }
        if (renderingMode !== "print" && (rect.left < stage.left - 1 || rect.right > stage.right + 1 ||
            rect.top < stage.top - 1 || rect.bottom > stage.bottom + 1)) {
          layout.findings.push({ kind: "stage-overflow", detail: "Slide does not fit its stage." });
        }
        return { ...layout, checkedConnectors: connectors.checkedConnectors, maximumConnectorGapPx: connectors.maximumGapPx };
      }, mode);
      result.manual = manual.id;
      result.mode = mode;
      results.push(result);
      failures.push(...result.findings.map(finding => ({ manual: manual.id, mode, slide: index + 1, ...finding })));
      assert.ok(result.checkedTextRuns > 0, "A rendered slide must contain painted text.");
      if (mode !== "print") await slide.screenshot({ path: join(directory, `${String(index + 1).padStart(2, "0")}.png`), animations: "disabled" });
      if ((index + 1) % 10 === 0) console.log(`  ${index + 1}/${manual.slideCount}; findings=${failures.length}`);
      lastProgressAt = Date.now();
    }
    if (mode === "print") await page.pdf({ path: join(output, manual.id, `${manual.id}.pdf`), preferCSSPageSize: true, printBackground: true });
    if (mode === "desktop") await contactSheet(directory, manual.slideCount, `${manual.id}-contact-sheet`);
    if (mode === "fullscreen") await page.evaluate(() => document.exitFullscreen());
    await writeFile(join(output, "measurements.json"), `${JSON.stringify(results, null, 2)}\n`);
  }
  const afterDigests = await sourceDigests();
  assert.deepEqual(afterDigests, beforeDigests, "Relevant source changed during validation.");
  const summary = {
    completedAt: new Date().toISOString(), browser: browser.version(), locale: "en", modes,
    manuals: manuals.map(({ id, slideCount }) => ({ id, slideCount })),
    slideModeChecks: results.length, sourceDigests: afterDigests,
    sourceDigest: createHash("sha256").update(JSON.stringify(afterDigests)).digest("hex"),
    geometryFixtures, checkedConnectors: results.reduce((total, result) => total + result.checkedConnectors, 0),
    maximumConnectorGapPx: Math.max(...results.map(result => result.maximumConnectorGapPx)),
    failures, failedRequests, pageErrors,
  };
  await writeFile(join(output, "summary.json"), `${JSON.stringify(summary, null, 2)}\n`);
  console.log(JSON.stringify({ slideModeChecks: results.length, failures: failures.length,
    failedRequests: failedRequests.length, pageErrors: pageErrors.length, output }));
  assert.deepEqual(failedRequests, []);
  assert.deepEqual(pageErrors, []);
  assert.equal(failures.length, 0, "English layout regression findings remain; inspect the report and captures.");
} finally {
  clearInterval(deadline);
  await browser.close();
}
