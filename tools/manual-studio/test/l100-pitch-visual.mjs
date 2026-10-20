/** Bounded local rendering checks; artifacts stay outside the repository. */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { createServer } from "node:net";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { inspectTextGeometry } from "./target-architecture-text-geometry.mjs";
import { inspectSlideLayout } from "./slide-layout-geometry.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const source = join(root, "tools/manual-studio");
const output = process.argv[2];
assert.ok(output && isAbsolute(output), "Provide an absolute artifact directory.");
const outputRelation = relative(root, resolve(output));
assert.ok(outputRelation === ".." || outputRelation.startsWith(`..${sep}`), "Artifacts must stay outside the repository.");
const modes = (process.argv[3] ?? "desktop,tablet,mobile,fullscreen,print").split(",");
const viewports = {
  desktop: { width: 1440, height: 900 }, tablet: { width: 993, height: 641 },
  mobile: { width: 390, height: 844 }, fullscreen: { width: 1440, height: 900 },
  print: { width: 1536, height: 864 },
};
assert.ok(modes.every(mode => Object.hasOwn(viewports, mode)), "Unknown rendering mode.");
const { chromium } = createRequire(join(root, "console/package.json"))("playwright");
const results = [], findings = [], failedRequests = [], pageErrors = [];
let browser, server;
const started = Date.now();
let lastProgress = started, stageStarted = started;
const deadline = setInterval(() => {
  const now = Date.now();
  if (now - started > 600000 || now - stageStarted > 120000 || now - lastProgress > 45000) {
    console.error("L100 rendering exceeded its total, stage, or no-progress deadline.");
    void browser?.close();
    server?.kill("SIGTERM");
    clearInterval(deadline);
    process.exitCode = 1;
  }
}, 1000).unref();

function inspectPitch(root) {
  const failures = [];
  let connectors = 0, maximumGap = 0, minimumBody = Infinity, minimumContrast = Infinity;
  const box = element => element.getBoundingClientRect();
  const visual = root.querySelector(".lp-visual");
  const visualBox = box(visual);
  const regions = [...visual.children].map(element => ({ element, rect: box(element) }));
  for (const { element, rect } of regions) {
    if (rect.left < visualBox.left - 1 || rect.right > visualBox.right + 1 ||
        rect.top < visualBox.top - 1 || rect.bottom > visualBox.bottom + 1) {
      failures.push({ kind: "visual-region-overflow", detail: element.className || element.tagName });
    }
  }
  for (let a = 0; a < regions.length; a += 1) {
    for (let b = a + 1; b < regions.length; b += 1) {
      const x = regions[a].rect, y = regions[b].rect;
      if (Math.min(x.right, y.right) - Math.max(x.left, y.left) > 1 &&
          Math.min(x.bottom, y.bottom) - Math.max(x.top, y.top) > 1) {
        failures.push({ kind: "visual-region-overlap", detail: `${regions[a].element.tagName}/${regions[b].element.tagName}` });
      }
    }
  }
  const ratio = (a, b) => {
    const luminance = color => {
      const values = color.slice(0, 3).map(v => v / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4);
      return values.reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
    };
    const x = luminance(a), y = luminance(b);
    return (Math.max(x, y) + .05) / (Math.min(x, y) + .05);
  };
  const rgba = value => {
    const values = value.match(/[\d.]+/g).map(Number);
    return [...values.slice(0, 3), values[3] ?? 1];
  };
  for (const link of root.querySelectorAll("[data-lp-from]")) {
    const from = root.querySelector(`[data-lp-node="${link.dataset.lpFrom}"]`);
    const to = root.querySelector(`[data-lp-node="${link.dataset.lpTo}"]`);
    if (!from || !to) {
      failures.push({ kind: "missing-connector-node" });
      continue;
    }
    const a = box(from), b = box(to);
    let start, end;
    if (link instanceof SVGLineElement) {
      const matrix = link.getScreenCTM();
      start = new DOMPoint(link.x1.baseVal.value, link.y1.baseVal.value).matrixTransform(matrix);
      end = new DOMPoint(link.x2.baseVal.value, link.y2.baseVal.value).matrixTransform(matrix);
    } else {
      const c = box(link);
      start = { x: c.left, y: c.top + c.height / 2 };
      end = { x: c.right, y: c.top + c.height / 2 };
    }
    const gap = Math.max(Math.abs(start.x - a.right), Math.abs(start.y - (a.top + a.height / 2)),
      Math.abs(end.x - b.left), Math.abs(end.y - (b.top + b.height / 2)));
    maximumGap = Math.max(maximumGap, gap);
    connectors += 1;
    if (gap > 1) failures.push({ kind: "connector-gap", detail: gap });
  }
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const text = walker.currentNode;
    const element = text.parentElement;
    if (!text.textContent.trim() || element.closest("[aria-hidden=true], .manual-draft-overlay, script, style")) continue;
    const style = getComputedStyle(element);
    const secondary = element.closest("header, footer, .l100-source, .lp-example, .lp-kicker, figcaption, .slide-deck-title, .lp-domain-list dt span");
    if (!secondary) {
      const font = Number.parseFloat(style.fontSize);
      minimumBody = Math.min(minimumBody, font);
      if (font < 24) failures.push({ kind: "primary-font", detail: `${font}px: ${text.textContent.trim()}` });
    }
    let bg = [255, 255, 255, 1];
    const chain = [];
    for (let ancestor = element; ancestor; ancestor = ancestor.parentElement) chain.unshift(ancestor);
    for (const ancestor of chain) {
      const color = rgba(getComputedStyle(ancestor).backgroundColor);
      bg = color.slice(0, 3).map((v, i) => v * color[3] + bg[i] * (1 - color[3]));
    }
    const color = rgba(style.color);
    const painted = color.slice(0, 3).map((v, i) => v * color[3] + bg[i] * (1 - color[3]));
    const contrast = ratio(painted, bg);
    minimumContrast = Math.min(minimumContrast, contrast);
    if (contrast < 4.5) failures.push({ kind: "text-contrast", detail: `${contrast}: ${text.textContent.trim()}` });
  }
  return { findings: failures, connectors, maximumGap, minimumBody, minimumContrast };
}

async function digests(directory = source, prefix = "") {
  const values = {};
  for (const entry of (await readdir(directory, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))) {
    if (entry.name === "node_modules") continue;
    const name = `${prefix}${entry.name}`;
    if (entry.isDirectory()) Object.assign(values, await digests(join(directory, entry.name), `${name}/`));
    else if (/\.(js|mjs|css|html|png|jpeg|woff2?)$/.test(name) || /(?:catalog|messages\.(?:en|ko))\.json$/.test(name)) {
      values[name] = createHash("sha256").update(await readFile(join(directory, entry.name))).digest("hex");
    }
  }
  return values;
}

async function settle(page) {
  await page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
}

try {
  await mkdir(output, { recursive: true });
  const before = await digests();
  const probe = createServer();
  await new Promise((done, reject) => { probe.once("error", reject); probe.listen(0, "127.0.0.1", done); });
  const port = probe.address().port;
  await new Promise(done => probe.close(done));
  server = spawn(process.execPath, [join(source, "server.mjs")], { env: { ...process.env, PORT: String(port) }, stdio: ["ignore", "pipe", "inherit"] });
  await new Promise((done, reject) => {
    const timer = setTimeout(() => reject(new Error("Local server readiness timed out.")), 10000);
    server.once("error", reject);
    server.once("exit", code => reject(new Error(`Local server exited before readiness: ${code}`)));
    server.stdout.on("data", bytes => {
      if (bytes.toString().includes("Manual Studio prototype ready")) { clearTimeout(timer); done(); }
    });
  });
  const origin = `http://127.0.0.1:${port}`;
  assert.equal((await fetch(`${origin}/catalog.json`)).status, 200);
  browser = await chromium.launch({ headless: true, timeout: 15000 });
  const page = await browser.newPage({ reducedMotion: "reduce" });
  page.setDefaultTimeout(10000);
  page.on("pageerror", error => pageErrors.push(error.message));
  page.on("requestfailed", request => failedRequests.push({ url: request.url(), error: request.failure() }));
  page.on("response", response => {
    if (response.status() >= 400) failedRequests.push({ url: response.url(), status: response.status() });
  });
  await page.route("**/*", route => {
    const url = route.request().url();
    return url.startsWith(origin) || url.startsWith("data:") ? route.continue() : route.abort();
  });
  await page.setViewportSize(viewports.desktop);
  await page.goto(`${origin}/library.html?locale=ko`, { waitUntil: "networkidle" });
  await page.locator("#journey-stages button").first().click();
  const book = page.locator(".coverflow-item").filter({ hasText: "FDAI L100 Pitch Deck" });
  await book.click();
  assert.equal(await book.getAttribute("data-active"), "true");
  await book.click();
  await page.locator(".manual-slide.active").waitFor();
  assert.equal(await page.locator(".manual-slide").count(), 15);
  const selfTests = [];
  for (const locale of ["ko", "en"]) {
    for (const mode of modes) {
      stageStarted = lastProgress = Date.now();
      console.log(`L100 ${locale}/${mode}: starting 15 slides`);
      await page.setViewportSize(viewports[mode]);
      await page.emulateMedia({ media: "screen", reducedMotion: "reduce" });
      await page.goto(`${origin}/l100-pitch-deck.html?locale=${locale}`, { waitUntil: "networkidle" });
      await page.locator(".manual-slide.active").waitFor();
      await settle(page);
      assert.equal(await page.locator(".manual-slide").count(), 15);
      assert.equal(await page.locator("html").getAttribute("lang"), locale);
      assert.equal(await page.locator(".manual-slide.active").getAttribute("data-index"), "0");
      assert.equal(await page.locator(".manual-slide .manual-draft-overlay").count(), 1);
      await page.addScriptTag({ content: `${inspectTextGeometry}\n${inspectSlideLayout}\n${inspectPitch}` });
      if (mode === "fullscreen") {
        await page.locator("#fullscreen-manual").click();
        await page.waitForFunction(() => document.fullscreenElement?.id === "slide-stage");
      }
      if (mode === "print") await page.emulateMedia({ media: "print" });
      const directory = join(output, locale, mode);
      await mkdir(directory, { recursive: true });
      for (let index = 0; index < 15; index += 1) {
        if (index && mode !== "print") {
          await page.keyboard.press("ArrowRight");
          await page.waitForFunction(expected => document.querySelector(".manual-slide.active")?.dataset.index === String(expected), index);
        }
        await settle(page);
        const slide = page.locator(`.manual-slide[data-index="${index}"]`);
        const measurement = await slide.evaluate((element, mode) => {
          const layout = inspectSlideLayout(element), pitch = inspectPitch(element);
          const rect = element.getBoundingClientRect(), stage = document.querySelector("#slide-stage").getBoundingClientRect();
          const failures = [...layout.findings, ...pitch.findings];
          if (element.offsetWidth !== 1536 || element.offsetHeight !== 864) failures.push({ kind: "canvas-size" });
          if (mode !== "print" && (rect.left < stage.left - 1 || rect.right > stage.right + 1 || rect.top < stage.top - 1 || rect.bottom > stage.bottom + 1)) failures.push({ kind: "stage-overflow" });
          if (document.documentElement.scrollWidth > innerWidth + 1) failures.push({ kind: "document-overflow" });
          return { ...layout, ...pitch, findings: failures };
        }, mode);
        results.push({ locale, mode, slide: index + 1, ...measurement });
        findings.push(...measurement.findings.map(finding => ({ locale, mode, slide: index + 1, ...finding })));
        if (mode === "desktop" && [4, 5].includes(index)) {
          const test = await slide.evaluate(async element => {
            const node = element.querySelector("[data-lp-node]");
            const svg = node instanceof SVGGraphicsElement;
            const originalX = node.getAttribute("x");
            if (svg) node.setAttribute("x", String(Number(originalX) + 8));
            else { node.style.position = "relative"; node.style.left = "8px"; }
            await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
            const detachedResult = inspectPitch(element);
            if (svg) node.setAttribute("x", originalX);
            else { node.style.position = ""; node.style.left = ""; }
            await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
            return {
              detached: detachedResult.findings.filter(finding => finding.kind === "connector-gap").length,
              restored: inspectPitch(element).findings.filter(finding => finding.kind === "connector-gap").length,
              connectors: detachedResult.connectors, maximumDetachedGap: detachedResult.maximumGap,
            };
          });
          assert.ok(test.detached > 0, `The connector checker must detect a deliberately detached node on slide ${index + 1}: ${JSON.stringify(test)}`);
          assert.equal(test.restored, 0);
          selfTests.push({ locale, slide: index + 1, ...test });
        }
        if (mode !== "print") await slide.screenshot({ path: join(directory, `${String(index + 1).padStart(2, "0")}.png`), animations: "disabled" });
        lastProgress = Date.now();
      }
      if (mode === "print") await page.pdf({ path: join(output, `${locale}.pdf`), preferCSSPageSize: true, printBackground: true });
      if (mode === "fullscreen") await page.evaluate(() => document.exitFullscreen());
      console.log(`L100 ${locale}/${mode}: 15 slides; findings=${findings.length}`);
    }
  }
  assert.deepEqual(await digests(), before, "Rendering inputs changed during verification.");
  const summary = {
    validatedAt: new Date().toISOString(), browser: browser.version(), modes, locales: ["ko", "en"],
    slideModeChecks: results.length, findings, failedRequests, pageErrors, selfTests,
    connectorsChecked: results.reduce((sum, result) => sum + result.connectors, 0),
    maximumConnectorGapPx: Math.max(...results.map(result => result.maximumGap)),
    minimumPrimaryFontPx: Math.min(...results.map(result => result.minimumBody)),
    minimumTextContrast: Math.min(...results.map(result => result.minimumContrast)),
    sourceDigests: before, results,
  };
  await writeFile(join(output, "measurements.json"), `${JSON.stringify(summary, null, 2)}\n`);
  console.log(JSON.stringify({ ...summary, sourceDigests: undefined, results: undefined }, null, 2));
  assert.equal(failedRequests.length, 0, "Unexpected request failures.");
  assert.equal(pageErrors.length, 0, "Unexpected page errors.");
  assert.equal(findings.length, 0, "Rendering findings must be resolved.");
} finally {
  clearInterval(deadline);
  await browser?.close();
  if (server && server.exitCode === null) {
    const stopped = new Promise(done => server.once("exit", done));
    server.kill("SIGTERM");
    await stopped;
  }
}
