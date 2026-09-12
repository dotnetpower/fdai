/** Local visual census of the master iframe; an optional fifth argument expands a details selector. */
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const require = createRequire(join(root, "console/package.json"));
const { chromium } = require("playwright");
const [label = "baseline", widthArg = "1440", heightArg = "900", filter = "", disclosureSelector = ""] = process.argv.slice(2);
if (!/^[a-z0-9-]+$/.test(label)) throw new Error("Use an ASCII audit label.");
const width = Number(widthArg);
const height = Number(heightArg);
if (![width, height].every(value => Number.isInteger(value) && value >= 320 && value <= 2400)) {
  throw new Error("Viewport dimensions must be integers between 320 and 2400.");
}
const origin = "http://127.0.0.1:5373";
const output = join(root, ".fdai/visual-review", label);
await mkdir(output, { recursive: true });
const markup = await readFile(join(root, "index.html"), "utf8");
const routes = [...markup.split("<script>")[0].matchAll(/data-page="([^"]+)"\s+data-title="([^"]+)"/g)]
  .map(([, path, title]) => ({ path, title }))
  .filter(route => !filter || new RegExp(filter).test(route.path));

/** Measure visible text and layout; findings are review leads, not automatic design verdicts. */
function measureDocument() {
  const visible = element => {
    if (!element.checkVisibility({ checkVisibilityCSS: true, checkOpacity: true })) return false;
    const box = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return box.width > 0 && box.height > 0 && style.visibility !== "hidden" && style.opacity !== "0" &&
      !["inset(50%)", "rect(0px, 0px, 0px, 0px)"].includes(style.clipPath) && style.clip !== "rect(0px, 0px, 0px, 0px)" &&
      !element.closest('[hidden], [aria-hidden="true"]');
  };
  const describe = element => ({
    tag: element.tagName.toLowerCase(),
    class: typeof element.className === "string" ? element.className : "",
    text: (element.textContent || element.getAttribute("aria-label") || "").trim().replace(/\s+/g, " ").slice(0, 100),
  });
  const all = [...document.querySelectorAll("body *")].filter(visible);
  const text = all.filter(element => !element.matches("script, style, svg, svg *, option") &&
    [...element.childNodes].some(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim()));
  const rgba = color => {
    const values = (color.match(/[\d.]+/g) || [0, 0, 0]).map(Number);
    return color.startsWith("color(srgb ") ? values.map((value, index) => index < 3 ? value * 255 : value) : values;
  };
  const luminance = rgb => rgb.slice(0, 3).map(value => {
    const v = value / 255;
    return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4;
  }).reduce((sum, value, i) => sum + value * [.2126, .7152, .0722][i], 0);
  const lowContrast = text.flatMap(element => {
    const style = getComputedStyle(element);
    if (style.color.startsWith("color(") || element.closest("canvas,svg")) return [];
    if (style.webkitTextFillColor === "transparent") return [];
    const fg = rgba(style.color);
    let current = element;
    let background = [255, 255, 255];
    while (current) {
      if (getComputedStyle(current).backgroundImage !== "none") return [];
      const bg = rgba(getComputedStyle(current).backgroundColor);
      if (bg.length === 3 || bg[3] === 1) { background = bg; break; }
      if (bg[3] > 0) return []; // Translucent stacking needs a separate pixel-level review.
      current = current.parentElement;
    }
    const a = luminance(fg), b = luminance(background);
    const ratio = (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
    const large = parseFloat(style.fontSize) >= 24 ||
      (parseFloat(style.fontSize) >= 18.66 && Number(style.fontWeight) >= 700);
    return ratio < (large ? 3 : 4.5) - .02 ? [{ ...describe(element), ratio: +ratio.toFixed(2), color: style.color }] : [];
  });
  const controls = all.filter(element => element.matches('button, input:not([type="hidden"]), select, textarea, [role="button"]'));
  const unnamed = controls.filter(element => !element.getAttribute("aria-label") &&
    !element.getAttribute("aria-labelledby") && !element.labels?.length &&
    !element.textContent.trim() && !element.getAttribute("title"));
  const overflow = all.filter(element => {
    const box = element.getBoundingClientRect();
    if (element.closest("svg,canvas,.cs-sr-only,.sr-only")) return false;
    if (box.right <= document.documentElement.clientWidth + 1 && box.left >= -1) return false;
    let parent = element.parentElement;
    while (parent && parent !== document.body) {
      if (["auto", "scroll", "hidden", "clip"].includes(getComputedStyle(parent).overflowX)) return false;
      parent = parent.parentElement;
    }
    return true;
  });
  const clipped = text.filter(element => {
    const style = getComputedStyle(element);
    if (element.closest(".cs-sr-only,.sr-only") || style.clipPath === "inset(50%)") return false;
    return ["hidden", "clip"].includes(style.overflowX) && element.scrollWidth > element.clientWidth + 2 &&
      style.textOverflow !== "ellipsis";
  });
  const heading = document.querySelector("h1");
  const main = document.querySelector("main") || document.body;
  return {
    title: document.title,
    document: { clientWidth: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth },
    main: { clientWidth: main.clientWidth, scrollWidth: main.scrollWidth },
    heading: heading ? { ...describe(heading), x: heading.getBoundingClientRect().x, y: heading.getBoundingClientRect().y } : null,
    smallText: text.filter(element => parseFloat(getComputedStyle(element).fontSize) < 12)
      .map(element => ({ ...describe(element), size: getComputedStyle(element).fontSize })).slice(0, 15),
    lowContrast: lowContrast.slice(0, 20),
    unnamed: unnamed.map(describe).slice(0, 15),
    shortControls: controls.filter(element => element.getBoundingClientRect().height < 32).map(describe).slice(0, 15),
    overflow: overflow.map(describe).slice(0, 15),
    clipped: clipped.map(describe).slice(0, 15),
    brokenImages: [...document.images].filter(image => visible(image) && image.complete && !image.naturalWidth).map(image => image.getAttribute("src")),
    textLength: document.body.innerText.length,
  };
}

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width, height }, reducedMotion: "reduce" });
const page = await context.newPage();
page.setDefaultTimeout(6000);
const blocked = new Set();
await context.route("**/*", route => {
  const url = new URL(route.request().url());
  if (url.origin === origin || ["data:", "blob:"].includes(url.protocol)) return route.continue();
  blocked.add(url.origin);
  return route.abort("blockedbyclient");
});
const results = [];
const started = Date.now();
const deadline = setTimeout(() => { console.error("Visual census exceeded its 240-second deadline."); process.exit(2); }, 240_000);
try {
  for (const route of routes) {
    const errors = [];
    const onError = error => errors.push(error.message.slice(0, 200));
    page.on("pageerror", onError);
    blocked.clear();
    try {
      await page.goto(`${origin}/#${route.path}`, { waitUntil: "load", timeout: 10000 });
      await page.waitForFunction(path => {
        const preview = document.querySelector("#preview-frame");
        return preview?.contentDocument?.readyState === "complete" &&
          preview.contentWindow.location.pathname === `/${path}`;
      }, route.path);
      const element = await page.locator("#preview-frame").elementHandle();
      const frame = await element.contentFrame();
      await frame.waitForLoadState("load", { timeout: 6000 });
      if (disclosureSelector) {
        const disclosure = frame.locator(disclosureSelector);
        if (!(await disclosure.evaluate(node => node.tagName === "DETAILS"))) {
          throw new Error("Expanded-state audit requires a native details element.");
        }
        if (!(await disclosure.evaluate(node => node.open))) {
          await disclosure.locator(":scope > summary").click();
        }
      }
      await frame.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      const measurements = await frame.evaluate(measureDocument);
      const shell = await page.evaluate(() => ({
        width: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth,
        active: document.querySelector('.side [aria-current="page"]')?.getAttribute("data-page"),
        sampleLabel: document.querySelector("[data-preview-boundary]")?.textContent || null,
      }));
      const assertions = {
        exactRoute: shell.active === route.path,
        shellFits: shell.scrollWidth <= shell.width,
        documentFits: measurements.document.scrollWidth <= measurements.document.clientWidth,
        mainFits: measurements.main.scrollWidth <= measurements.main.clientWidth,
        noVisibleClipping: measurements.clipped.length === 0,
        noEscapedContent: measurements.overflow.length === 0,
        namedControls: measurements.unnamed.length === 0,
        loadedVisibleImages: measurements.brokenImages.length === 0,
        normalTextContrast: measurements.lowContrast.length === 0,
        noUncaughtErrors: errors.length === 0,
      };
      const disposition = Object.values(assertions).every(Boolean) ? "passed" : "failed";
      const name = route.path.replace(/[^a-z0-9-]/gi, "-");
      await page.screenshot({ path: join(output, `${name}.png`), animations: "disabled", timeout: 6000 });
      results.push({ ...route, ...measurements, shell, assertions, disposition, errors, expandedDisclosure: disclosureSelector || null, blocked: [...blocked],
        limitations: [disclosureSelector ? "Named expanded state and geometry only; not every hidden interaction." : "Initial visible route and geometry only; not every hidden interaction.",
          "Contrast excludes gradients, translucent backgrounds, canvas, and SVG text.",
          ...([...blocked].length ? ["External resources blocked; no external rendering or live-readiness claim."] : [])] });
      console.log(`${results.length}/${routes.length} ${route.path} overflow=${measurements.document.scrollWidth - measurements.document.clientWidth} contrast=${measurements.lowContrast.length} unnamed=${measurements.unnamed.length} errors=${errors.length}`);
    } catch (error) {
      results.push({ ...route, disposition: "needs-infrastructure", error: error.message.slice(0, 300), errors, blocked: [...blocked] });
      console.log(`${results.length}/${routes.length} ${route.path} needs-infrastructure`);
    } finally {
      page.off("pageerror", onError);
    }
  }
} finally {
  clearTimeout(deadline);
  await writeFile(join(output, "measurements.json"), JSON.stringify({ label, viewport: { width, height }, durationMs: Date.now() - started, scope: "synthetic-local-mocks", results }, null, 2) + "\n");
  await browser.close();
}
console.log(`Evidence: .fdai/visual-review/${label}/measurements.json`);
if (label.startsWith("final-") && results.some(result => result.disposition !== "passed")) process.exitCode = 1;
