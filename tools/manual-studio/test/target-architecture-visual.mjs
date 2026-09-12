/** Local visual verification for the target-architecture deck. Artifacts stay outside the repository. */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { buildTargetArchitectureDeck } from "../target-architecture.js";
import { inspectTextGeometry, verifyTextGeometry } from "./target-architecture-text-geometry.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const output = process.argv[2];
assert.ok(output && isAbsolute(output), "Provide an absolute artifact directory outside the repository.");
const outputRelation = relative(root, resolve(output));
assert.ok(
  outputRelation === ".." || outputRelation.startsWith(`..${sep}`) || isAbsolute(outputRelation),
  "Rendering artifacts must stay outside the repository.",
);
const modes = (process.argv[3] ?? "desktop,tablet,mobile,fullscreen,print").split(",");
const viewports = {
  desktop: { width: 1440, height: 900 },
  tablet: { width: 993, height: 641 },
  mobile: { width: 390, height: 844 },
  fullscreen: { width: 1440, height: 900 },
  print: { width: 1536, height: 864 },
};
assert.ok(modes.every((mode) => mode in viewports), "Unknown rendering mode.");
const require = createRequire(join(root, "console/package.json"));
const { chromium } = require("playwright");
const slides = buildTargetArchitectureDeck();
const problems = [];
const failedRequests = [];
const pageErrors = [];
const results = [];
const startedAt = Date.now();
const browser = await chromium.launch({ headless: true, timeout: 15000 });

/** Reject the original fixed-row RiskGate regression before trusting a new deck measurement. */
async function verifyRiskGateRegression(page) {
  await page.goto("http://127.0.0.1:5474/target-architecture.html?slide=15", { waitUntil: "load", timeout: 15000 });
  const slide = page.locator('.manual-slide.active[data-index="14"]');
  await slide.waitFor();
  await page.evaluate(() => document.fonts.ready);
  await slide.evaluate((element) => Promise.all(element.getAnimations().map((animation) => animation.finished)));
  const boundaries = slide.locator('.ta-risk-inputs .ta-arch-boundary');
  await boundaries.evaluateAll((elements) => elements.forEach((element) => {
    element.style.height = "112px";
    element.style.maxHeight = "112px";
  }));
  try {
    const broken = await slide.evaluate(inspectTextGeometry);
    for (const boundary of ["risk-table", "risk-ceilings"]) {
      assert.ok(broken.findings.some((finding) => finding.kind === "text-clipped-by-ancestor" &&
        finding.detail.startsWith(`${boundary}:`)), `The original ${boundary} clipping must fail.`);
    }
  } finally {
    await boundaries.evaluateAll((elements) => elements.forEach((element) => element.removeAttribute("style")));
  }
  return { legacyHeightPx: 112, rejectedBoundaries: ["risk-table", "risk-ceilings"] };
}

/** Build a comparison sheet from actual slide captures, never a substitute for full-size review. */
async function createContactSheet(browser, directory, mode) {
  const images = await Promise.all(slides.map(async (slide, index) => {
    const number = String(index + 1).padStart(2, "0");
    const image = await readFile(join(directory, `${number}-${slide.architecture.id}.png`));
    return `<figure><img src="data:image/png;base64,${image.toString("base64")}"><figcaption>${number} · ${slide.architecture.id}</figcaption></figure>`;
  }));
  const sheet = await browser.newPage({ viewport: { width: 1560, height: 1100 } });
  try {
    await sheet.setContent(`<html><head><style>body{margin:0;padding:16px;background:#e9eef2;display:grid;grid-template-columns:repeat(5,1fr);gap:12px;font:12px/1.5 sans-serif}figure{margin:0}img{display:block;width:100%}figcaption{padding:6px 0;color:#233846}</style></head><body>${images.join("")}</body></html>`);
    await sheet.screenshot({ path: join(output, `contact-sheet-${mode}.png`), fullPage: true });
  } finally {
    await sheet.close();
  }
}

/** Measure visible content, contrast, and connector geometry on the fixed slide canvas. */
function inspectSlide(slide, mode) {
  const box = (element) => {
    const rect = element.getBoundingClientRect();
    return { x: rect.x, y: rect.y, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height };
  };
  const canvas = box(slide);
  const scale = canvas.width / 1536;
  const tolerance = 1.25 * scale;
  const textTolerance = 5 * scale;
  const findings = [];
  const add = (kind, detail) => findings.push({ kind, detail });
  const outside = (child, parent) => child.x < parent.x - tolerance || child.y < parent.y - tolerance ||
    child.right > parent.right + tolerance || child.bottom > parent.bottom + tolerance;
  const label = (element) => element?.textContent.trim().replace(/\s+/g, " ").slice(0, 100) ?? "";
  const isCover = slide.classList.contains("slide-briefing-target-cover");

  if (Math.round(parseFloat(getComputedStyle(slide).width)) !== 1536 ||
      Math.round(parseFloat(getComputedStyle(slide).height)) !== 864) add("canvas", "Canvas is not 1536x864.");
  if (mode !== "print") {
    if (document.documentElement.scrollWidth > innerWidth + 1) add("document-overflow", document.documentElement.scrollWidth);
    if (outside(canvas, box(document.querySelector("#slide-stage")))) add("stage-overflow", canvas);
  }

  const regionElements = [
    slide.querySelector(":scope > header"),
    slide.querySelector(".slide-copy"),
    ...slide.querySelectorAll(".ta-meta, .ta-visual, .ta-takeaway, .ta-source"),
  ];
  const regions = regionElements.filter((element) => element && box(element).height > 0);
  for (const region of regions) if (outside(box(region), canvas)) add("region-outside", region.className);
  if (!isCover) {
    for (let first = 0; first < regions.length; first += 1) {
      for (let second = first + 1; second < regions.length; second += 1) {
        const a = box(regions[first]);
        const b = box(regions[second]);
        const width = Math.min(a.right, b.right) - Math.max(a.x, b.x);
        const height = Math.min(a.bottom, b.bottom) - Math.max(a.y, b.y);
        if (width > tolerance && height > tolerance) add("region-overlap", `${regions[first].className} / ${regions[second].className}`);
      }
    }
  }

  const rgba = (value) => {
    const match = value.match(/^rgba?\(([^)]+)\)/);
    if (!match) return null;
    const values = match[1].split(/[, /]+/).map(Number);
    return [...values.slice(0, 3), values[3] ?? 1];
  };
  const luminance = (color) => color.slice(0, 3).map((value) => {
    const normalized = value / 255;
    return normalized <= .04045 ? normalized / 12.92 : ((normalized + .055) / 1.055) ** 2.4;
  }).reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0);
  const contrast = (first, second) =>
    (Math.max(luminance(first), luminance(second)) + .05) /
    (Math.min(luminance(first), luminance(second)) + .05);
  const backgrounds = (element) => {
    const colors = [];
    for (let current = element; current; current = current.parentElement) {
      const computed = getComputedStyle(current);
      if (computed.backgroundImage.includes("gradient")) {
        for (const match of computed.backgroundImage.matchAll(/rgba?\([^)]+\)/g)) {
          const color = rgba(match[0]);
          if (color && color[3] === 1) colors.push(color);
        }
        if (colors.length) return colors;
      }
      const color = rgba(computed.backgroundColor);
      if (color && color[3] === 1) return [color];
    }
    return [[255, 255, 255, 1]];
  };

  let minimumContrast = Infinity;
  let minimumPrimaryFont = Infinity;
  const textRanges = [];
  for (const element of slide.querySelectorAll("*")) {
    if (element.matches("img, svg, svg *, i") || element.closest('[aria-hidden="true"]')) continue;
    const computed = getComputedStyle(element);
    if (computed.display === "none" || computed.visibility === "hidden" || parseFloat(computed.opacity) === 0) continue;
    const nodes = [...element.childNodes].filter((node) => node.nodeType === Node.TEXT_NODE && node.textContent.trim());
    if (!nodes.length) continue;
    const foreground = rgba(computed.color);
    if (foreground) {
      const ratio = Math.min(...backgrounds(element).map((candidate) => contrast(foreground, candidate)));
      minimumContrast = Math.min(minimumContrast, ratio);
      if (ratio < 4.5) add("contrast", `${ratio.toFixed(2)}: ${label(element)}`);
    }
    for (const node of nodes) {
      const range = document.createRange();
      range.selectNodeContents(node);
      for (const rect of range.getClientRects()) {
        if (!rect.width || !rect.height) continue;
        const bounds = { x: rect.x, y: rect.y, right: rect.right, bottom: rect.bottom };
        if (outside(bounds, canvas)) add("text-outside-canvas", node.textContent.trim().slice(0, 80));
        const textOutside = (child, parent) => child.x < parent.x - textTolerance || child.y < parent.y - textTolerance ||
          child.right > parent.right + textTolerance || child.bottom > parent.bottom + textTolerance;
        const region = element.closest(".ta-visual, .ta-meta, .ta-takeaway, .ta-source, .slide-copy");
        if (region && textOutside(bounds, box(region))) add("text-outside-region", label(element));
        const architectureNode = element.closest(".ta-arch-node");
        if (architectureNode && textOutside(bounds, box(architectureNode))) {
          add("text-outside-node", `${architectureNode.dataset.taNode}: ${label(element)}`);
        }
        if (!(isCover && element.matches("h2")) &&
          element.matches("p, h2, h3, blockquote, td, th, dt, dd") &&
          textOutside(bounds, box(element))) add("text-outside-block", label(element));
        textRanges.push({ element, bounds, text: node.textContent.trim().slice(0, 60) });
      }
    }
  }
  for (const element of slide.querySelectorAll("[data-ta-primary], .ta-takeaway")) {
    const fontSize = parseFloat(getComputedStyle(element).fontSize);
    minimumPrimaryFont = Math.min(minimumPrimaryFont, fontSize);
    if (fontSize < 24) add("primary-font-floor", `${fontSize}px: ${label(element)}`);
  }
  for (let first = 0; first < textRanges.length; first += 1) {
    for (let second = first + 1; second < textRanges.length; second += 1) {
      const a = textRanges[first];
      const b = textRanges[second];
      if (a.element.contains(b.element) || b.element.contains(a.element)) continue;
      const aRegion = a.element.closest(".ta-visual, .ta-meta, .ta-takeaway, .ta-source, .slide-copy, .slide-header, .slide-footer");
      const bRegion = b.element.closest(".ta-visual, .ta-meta, .ta-takeaway, .ta-source, .slide-copy, .slide-header, .slide-footer");
      if (aRegion !== bRegion) continue;
      const width = Math.min(a.bounds.right, b.bounds.right) - Math.max(a.bounds.x, b.bounds.x);
      const height = Math.min(a.bounds.bottom, b.bounds.bottom) - Math.max(a.bounds.y, b.bounds.y);
      if (width > tolerance && height > tolerance) add("text-overlap", `${a.text} / ${b.text}`);
    }
  }

  let connectors = 0;
  let maximumConnectorGap = 0;
  for (const link of slide.querySelectorAll("[data-ta-link]")) {
    const from = slide.querySelector(`[data-ta-node="${link.dataset.taFrom}"]`);
    const to = slide.querySelector(`[data-ta-node="${link.dataset.taTo}"]`);
    if (!from || !to) {
      add("connector-node", `${link.dataset.taFrom} -> ${link.dataset.taTo}`);
      continue;
    }
    const fromBox = box(from);
    const toBox = box(to);
    const edge = box(link);
    const direction = link.dataset.taDirection ?? "right";
    const vertical = direction === "up" || direction === "down";
    const gap = (direction === "left"
      ? Math.max(Math.abs(edge.right - fromBox.x), Math.abs(edge.x - toBox.right))
      : direction === "down"
        ? Math.max(Math.abs(edge.y - fromBox.bottom), Math.abs(edge.bottom - toBox.y))
        : direction === "up"
          ? Math.max(Math.abs(edge.bottom - fromBox.y), Math.abs(edge.y - toBox.bottom))
          : Math.max(Math.abs(edge.x - fromBox.right), Math.abs(edge.right - toBox.x))) / scale;
    const aligned = vertical
      ? edge.x >= Math.max(fromBox.x, toBox.x) && edge.right <= Math.min(fromBox.right, toBox.right)
      : edge.y >= Math.max(fromBox.y, toBox.y) && edge.bottom <= Math.min(fromBox.bottom, toBox.bottom);
    maximumConnectorGap = Math.max(maximumConnectorGap, gap);
    if (gap > 1 || !aligned) add("connector", {
      from: link.dataset.taFrom,
      to: link.dataset.taTo,
      direction,
      gap,
      aligned,
    });
    connectors += 1;
  }

  const lineCount = (selector) => {
    const element = slide.querySelector(selector);
    return Math.round(element.clientHeight / parseFloat(getComputedStyle(element).lineHeight));
  };
  const titleLines = lineCount(".slide-copy h2");
  const leadLines = lineCount(".slide-copy > p");
  if (titleLines > 2) add("title-density", titleLines);
  if (leadLines > 2) add("lead-density", leadLines);

  return {
    slide: Number(slide.dataset.index) + 1,
    title: label(slide.querySelector("h2")),
    mode,
    nodes: slide.querySelectorAll("[data-ta-node]").length,
    titleLines,
    leadLines,
    minimumPrimaryFont: Number.isFinite(minimumPrimaryFont) ? minimumPrimaryFont : null,
    minimumContrast,
    connectors,
    maximumConnectorGap,
    findings,
  };
}

try {
  const page = await browser.newPage({ viewport: viewports.desktop, reducedMotion: "reduce", locale: "ko-KR" });
  page.setDefaultTimeout(10000);
  const textGeometrySelfTests = await verifyTextGeometry(page);
  await page.route("**/*", (route) => {
    if (new URL(route.request().url()).origin === "http://127.0.0.1:5474") return route.continue();
    failedRequests.push("External request blocked.");
    return route.abort();
  });
  page.on("requestfailed", (request) => failedRequests.push(new URL(request.url()).pathname));
  page.on("response", (response) => {
    if (response.status() >= 400) failedRequests.push(`${response.status()} ${new URL(response.url()).pathname}`);
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await mkdir(output, { recursive: true });
  const riskGateRegression = await verifyRiskGateRegression(page);

  for (const mode of modes) {
    console.log(`target-architecture-visual: ${mode} start (${slides.length} slides)`);
    await page.emulateMedia({ media: "screen", reducedMotion: "reduce" });
    await page.setViewportSize(viewports[mode]);
    await page.goto("http://127.0.0.1:5474/library?manual=target-architecture&slide=1", { waitUntil: "load", timeout: 15000 });
    await page.locator("#viewer[open] .manual-slide.active").waitFor();
    await page.evaluate(() => document.fonts.ready);
    assert.equal(await page.locator(".manual-slide").count(), slides.length);
    assert.deepEqual(await page.evaluate(() => ({ width: innerWidth, height: innerHeight })), viewports[mode]);
    if (mode === "fullscreen") {
      await page.locator("#fullscreen-manual").click();
      await page.waitForFunction(() => document.fullscreenElement?.id === "slide-stage");
    } else if (mode === "print") {
      await page.emulateMedia({ media: "print", reducedMotion: "reduce" });
    }

    const directory = join(output, mode);
    await mkdir(directory, { recursive: true });
    for (let index = 0; index < slides.length; index += 1) {
      const locator = page.locator(`.manual-slide[data-index="${index}"]`);
      if (mode !== "print") {
        if (index) await page.keyboard.press("ArrowRight");
        await page.waitForFunction((expected) => document.querySelector(".manual-slide.active")?.dataset.index === String(expected), index);
        await locator.evaluate((element) => Promise.all(element.getAnimations().map((animation) => animation.finished)));
      }
      const result = await locator.evaluate(inspectSlide, mode);
      const textGeometry = await locator.evaluate(inspectTextGeometry);
      result.checkedTextRuns = textGeometry.checkedTextRuns;
      result.checkedClipAncestors = textGeometry.checkedClipAncestors;
      result.findings.push(...textGeometry.findings);
      results.push(result);
      problems.push(...result.findings.map((finding) => ({ slide: index + 1, mode, ...finding })));
      if (mode !== "print") {
        await locator.screenshot({
          path: join(directory, `${String(index + 1).padStart(2, "0")}-${slides[index].architecture.id}.png`),
          animations: "disabled",
        });
      }
      if ((index + 1) % 5 === 0) console.log(`target-architecture-visual: ${mode} ${index + 1}/${slides.length}`);
      assert.ok(Date.now() - startedAt < 180000, "Visual review exceeded its three-minute total deadline.");
    }
    if (mode === "print") {
      await page.pdf({ path: join(output, "target-architecture.pdf"), preferCSSPageSize: true, printBackground: true });
    } else {
      await createContactSheet(browser, directory, mode);
    }
    if (mode === "fullscreen") await page.evaluate(() => document.exitFullscreen());
  }

  const files = [
    "target-architecture-plan.md",
    "target-architecture.js",
    "target-architecture-slide-kit.js",
    "target-architecture-diagram-kit.js",
    "target-architecture-review.js",
    "target-architecture-runtime.js",
    "target-architecture-decision.js",
    "target-architecture-execution.js",
    "target-architecture-deployment.js",
    "target-architecture.css",
    "target-architecture-visuals.css",
    "target-architecture-deployment.css",
    "test/target-architecture-visual.mjs",
    "test/target-architecture-text-geometry.mjs",
  ];
  const sourceDigests = Object.fromEntries(await Promise.all(files.map(async (file) => [
    file,
    createHash("sha256").update(await readFile(join(root, "tools/manual-studio", file))).digest("hex"),
  ])));
  const summary = {
    reviewedAt: new Date().toISOString(),
    browser: browser.version(),
    modes,
    slideCount: slides.length,
    slideModeChecks: results.length,
    deckDigest: createHash("sha256").update(JSON.stringify(slides)).digest("hex"),
    sourceDigests,
    textGeometrySelfTests,
    riskGateRegression,
    minimumPrimaryFont: Math.min(...results.map((result) => result.minimumPrimaryFont ?? Infinity)),
    minimumTextContrastRatio: Math.min(...results.map((result) => result.minimumContrast)),
    maximumTitleLines: Math.max(...results.map((result) => result.titleLines)),
    maximumLeadLines: Math.max(...results.map((result) => result.leadLines)),
    diagramNodeCount: results.filter((result) => result.mode === modes[0]).reduce((sum, result) => sum + result.nodes, 0),
    diagramConnectorsPerPass: results.filter((result) => result.mode === modes[0]).reduce((sum, result) => sum + result.connectors, 0),
    maximumConnectorGapPx: Math.max(...results.map((result) => result.maximumConnectorGap)),
    findings: problems,
    failedRequests,
    pageErrors,
  };
  await writeFile(join(output, `measurements-${modes.join("-")}.json`), `${JSON.stringify({ summary, results }, null, 2)}\n`);
  console.log(JSON.stringify(summary, null, 2));
  process.exitCode = problems.length || failedRequests.length || pageErrors.length ? 1 : 0;
} finally {
  await browser.close();
}
