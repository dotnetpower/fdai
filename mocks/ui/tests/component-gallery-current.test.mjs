/** Current-theme and responsive regressions for every Component Gallery view. */
import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const uiRoot = join(root, "mocks/ui");
const output = join(root, ".fdai/visual-review/component-gallery-current");
const registry = JSON.parse(await readFile(join(uiRoot, "assets/component-registry.json"), "utf8"));
const require = createRequire(join(root, "console/package.json"));
const { chromium } = require("playwright");
const origin = "http://127.0.0.1:5373";

async function openView(page, id) {
  await page.goto(
    `${origin}/?gallery-current=${encodeURIComponent(id)}#mocks/ui/components.html::${id}`,
    { waitUntil: "load" },
  );
  await page.waitForFunction(expected => {
    const frame = document.querySelector("#preview-frame");
    return frame?.contentDocument?.body?.classList.contains("is-gallery-ready")
      && frame.contentDocument.getElementById(expected)?.checkVisibility();
  }, id);
  return (await page.locator("#preview-frame").elementHandle()).contentFrame();
}

test("all registered Component Gallery views use the current light theme", { timeout: 120000 }, async () => {
  await mkdir(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const results = [];
  try {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      reducedMotion: "reduce",
    });
    await context.route("**/*", route => new URL(route.request().url()).origin === origin
      ? route.continue() : route.abort("blockedbyclient"));
    const page = await context.newPage();
    for (const spec of registry.components) {
      const frame = await openView(page, spec.id);
      const section = frame.locator(`#${spec.id}`);
      const measurement = await section.evaluate((element) => {
        const visible = node => node.checkVisibility({ checkVisibilityCSS: true, checkOpacity: true })
          && !node.closest('[hidden], [aria-hidden="true"]');
        const surfaces = [...element.querySelectorAll(
          ".cs-card, .cs-chart-card, .cs-chart-family, .cs-chart-composition-card, .cs-grid-item, .cs-state-block, .cs-notice",
        )].filter(visible);
        const selects = [...element.querySelectorAll("select")].filter(visible);
        return {
          status: element.dataset.galleryStatus,
          issues: element.dataset.galleryIssues,
          bodyBackground: getComputedStyle(document.body).backgroundColor,
          documentFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
          sectionFits: element.scrollWidth <= element.clientWidth,
          elevatedSurfaces: surfaces.filter(node => getComputedStyle(node).boxShadow !== "none").length,
          contrastBelowTarget: element.querySelectorAll('[data-result="below"]').length,
          selects: selects.map(select => {
            const style = getComputedStyle(select);
            return {
              appearance: style.appearance,
              paddingRight: parseFloat(style.paddingRight),
              backgroundImage: style.backgroundImage,
              backgroundPosition: style.backgroundPosition,
            };
          }),
        };
      });
      assert.equal(measurement.status, "Documented", spec.id);
      assert.equal(measurement.issues, "", spec.id);
      assert.equal(measurement.bodyBackground, "rgb(255, 255, 255)", spec.id);
      assert.equal(measurement.documentFits, true, spec.id);
      assert.equal(measurement.sectionFits, true, spec.id);
      assert.equal(measurement.elevatedSurfaces, 0, spec.id);
      assert.equal(measurement.contrastBelowTarget, 0, spec.id);
      for (const select of measurement.selects) {
        assert.equal(select.appearance, "none", `${spec.id}: ${JSON.stringify(select)}`);
        assert.ok(select.paddingRight >= 40, `${spec.id}: ${JSON.stringify(select)}`);
        assert.match(select.backgroundImage, /linear-gradient/, spec.id);
        assert.match(select.backgroundPosition, /100% - 20px/, spec.id);
      }
      results.push({ id: spec.id, category: spec.category, ...measurement });
      if (registry.components.find(item => item.category === spec.category)?.id === spec.id) {
        await page.screenshot({
          path: join(output, `${spec.category}-light.png`),
          animations: "disabled",
        });
      }
    }
    await writeFile(join(output, "light-measurements.json"), JSON.stringify(results, null, 2) + "\n");
    await context.close();
  } finally {
    await browser.close();
  }
});

test("Gallery dark theme reaches every category and nested current specimens", { timeout: 60000 }, async () => {
  await mkdir(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const results = [];
  try {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      reducedMotion: "reduce",
    });
    await context.route("**/*", route => new URL(route.request().url()).origin === origin
      ? route.continue() : route.abort("blockedbyclient"));
    const page = await context.newPage();
    const representatives = [
      "colors",
      "date-time-values",
      "controls",
      "tabs-meters",
      "alerts",
      "data-views",
      "drawers-command-menus",
      "settings-preferences",
    ];
    for (const id of representatives) {
      const frame = await openView(page, id);
      await frame.evaluate(() => {
        document.body.dataset.theme = "dark";
        const toggle = document.querySelector("[data-cs-theme-toggle]");
        toggle.setAttribute("aria-pressed", "true");
        toggle.textContent = "Light preview";
      });
      await frame.waitForFunction(() =>
        getComputedStyle(document.body).backgroundColor === "rgb(29, 32, 35)");
      const measurement = await frame.evaluate((sectionId) => {
        const section = document.getElementById(sectionId);
        const select = section.querySelector("select");
        return {
          bodyBackground: getComputedStyle(document.body).backgroundColor,
          bodyColor: getComputedStyle(document.body).color,
          sectionFits: section.scrollWidth <= section.clientWidth,
          selectBackground: select ? getComputedStyle(select).backgroundColor : null,
          selectImage: select ? getComputedStyle(select).backgroundImage : null,
          settingsBackground: section.querySelector(".cs-settings-specimen")
            ? getComputedStyle(section.querySelector(".cs-settings-specimen")).backgroundColor
            : null,
        };
      }, id);
      assert.equal(measurement.bodyBackground, "rgb(29, 32, 35)", id);
      assert.equal(measurement.bodyColor, "rgb(229, 227, 223)", id);
      assert.equal(measurement.sectionFits, true, id);
      if (measurement.selectBackground !== null) {
        assert.equal(measurement.selectBackground, "rgb(29, 32, 35)", id);
        assert.match(measurement.selectImage, /linear-gradient/, id);
      }
      if (measurement.settingsBackground !== null) {
        assert.notEqual(measurement.settingsBackground, "rgb(255, 255, 255)", id);
      }
      results.push({ id, ...measurement });
      if (id === "controls" || id === "data-views" || id === "settings-preferences") {
        await page.screenshot({
          path: join(output, `${id}-dark.png`),
          animations: "disabled",
        });
      }
    }
    await writeFile(join(output, "dark-measurements.json"), JSON.stringify(results, null, 2) + "\n");
    await context.close();
  } finally {
    await browser.close();
  }
});

test("Gallery chart catalog renders every FDAI and Datadog reference entry", { timeout: 60000 }, async () => {
  await mkdir(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      reducedMotion: "reduce",
    });
    await context.route("**/*", route => new URL(route.request().url()).origin === origin
      ? route.continue() : route.abort("blockedbyclient"));
    const page = await context.newPage();
    const frame = await openView(page, "data-views");
    const root = frame.locator("[data-chart-catalog-root]");
    await root.locator('[data-chart-catalog-ready="true"]');
    await frame.waitForFunction(() =>
      document.querySelector("[data-chart-catalog-root]")?.dataset.chartCatalogReady === "true");

    const measurement = await frame.evaluate(() => {
      const section = document.getElementById("data-views");
      const cards = [...section.querySelectorAll("[data-chart-entry]")];
      const visible = element => element.checkVisibility({ checkVisibilityCSS: true, checkOpacity: true })
        && !element.closest('[hidden], [aria-hidden="true"]');
      const text = [...section.querySelectorAll("*")].filter(element =>
        visible(element)
        && !element.matches("script, style, svg, svg *")
        && [...element.childNodes].some(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim()));
      const smallText = [...section.querySelectorAll("*")].filter(element =>
        element.children.length === 0
        && element.textContent.trim()
        && visible(element)
        && parseFloat(getComputedStyle(element).fontSize) > 0
        && parseFloat(getComputedStyle(element).fontSize) < 12);
      const rgb = value => (value.match(/[\d.]+/g) || []).slice(0, 3).map(Number);
      const luminance = value => rgb(value).map(channel => {
        const normalized = channel / 255;
        return normalized <= 0.04045 ? normalized / 12.92
          : ((normalized + 0.055) / 1.055) ** 2.4;
      }).reduce((sum, channel, index) => sum + channel * [0.2126, 0.7152, 0.0722][index], 0);
      const lowContrast = text.filter(element => {
        const style = getComputedStyle(element);
        if (!style.color.startsWith("rgb")) return false;
        let current = element;
        let background = "rgb(255, 255, 255)";
        while (current) {
          const candidate = getComputedStyle(current).backgroundColor;
          if (candidate.startsWith("rgb") && !candidate.endsWith(", 0)")) {
            background = candidate;
            break;
          }
          current = current.parentElement;
        }
        const foregroundLuminance = luminance(style.color);
        const backgroundLuminance = luminance(background);
        const ratio = (Math.max(foregroundLuminance, backgroundLuminance) + 0.05)
          / (Math.min(foregroundLuminance, backgroundLuminance) + 0.05);
        return ratio < 4.48;
      });
      const unnamedControls = [...section.querySelectorAll("button, input, select, [role=button]")]
        .filter(visible)
        .filter(element => !element.getAttribute("aria-label")
          && !element.getAttribute("aria-labelledby")
          && !element.labels?.length
          && !element.textContent.trim());
      const sources = Object.fromEntries([...new Set(cards.map(card => card.dataset.chartSource))]
        .map(source => [source, cards.filter(card => card.dataset.chartSource === source).length]));
      return {
        galleryCount: document.querySelector("[data-cs-gallery-count]").value,
        specimenTotal: document.querySelector("[data-chart-specimen-total]").textContent,
        catalogResult: document.querySelector("[data-chart-catalog-result]").value,
        cards: cards.length,
        sources,
        roleImages: cards.filter(card => {
          const image = card.querySelector('[role="img"]');
          return image && image.getAttribute("aria-label");
        }).length,
        smallText: smallText.map(element => element.textContent.trim()),
        lowContrast: lowContrast.map(element => element.textContent.trim()),
        unnamedControls: unnamedControls.length,
        documentFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
        sectionFits: section.scrollWidth <= section.clientWidth,
        detailsOpen: document.getElementById("chart-family").open,
        plotTargetSizes: [...section.querySelectorAll(".cs-chart-spot")]
          .map(element => Math.min(element.getBoundingClientRect().width, element.getBoundingClientRect().height)),
      };
    });
    assert.equal(measurement.galleryCount, "190 visualization entries");
    assert.equal(measurement.specimenTotal, "190");
    assert.equal(measurement.catalogResult, "140 of 140 catalog entries");
    assert.equal(measurement.cards, 140);
    assert.deepEqual(measurement.sources, {
      fdai: 19,
      "datadog-widgets": 39,
      "datadog-products": 61,
      "datadog-containers": 4,
      "datadog-interactions": 10,
      "datadog-delivery": 7,
    });
    assert.equal(measurement.roleImages, 140);
    assert.deepEqual(measurement.smallText, []);
    assert.deepEqual(measurement.lowContrast, []);
    assert.equal(measurement.unnamedControls, 0);
    assert.equal(measurement.documentFits, true);
    assert.equal(measurement.sectionFits, true);
    assert.equal(measurement.detailsOpen, true);
    assert.equal(measurement.plotTargetSizes.every(size => size >= 36), true);

    const workflow = frame.locator('[data-chart-entry][data-chart-search*="run workflow"]');
    assert.match(await workflow.innerText(), /Reference only - no Console action/);
    assert.equal(await workflow.locator("button").count(), 0);

    const search = frame.locator("[data-chart-catalog-search]");
    await search.fill("waterfall");
    assert.equal(await frame.locator("[data-chart-entry]:not([hidden])").count(), 3);
    assert.equal(await frame.locator("[data-chart-catalog-result]").evaluate(element => element.value),
      "3 of 140 catalog entries");
    await frame.locator("[data-chart-catalog-clear]").click();
    await frame.locator("[data-chart-catalog-source]").selectOption("datadog-widgets");
    assert.equal(await frame.locator("[data-chart-entry]:not([hidden])").count(), 39);
    assert.equal(await frame.locator("[data-chart-catalog-section]:not([hidden])").count(), 1);
    await frame.locator("[data-chart-catalog-clear]").click();
    const filterElapsed = await frame.evaluate(async () => {
      const input = document.querySelector("[data-chart-catalog-search]");
      const started = performance.now();
      input.value = "topology";
      input.dispatchEvent(new Event("input", { bubbles: true }));
      await new Promise(requestAnimationFrame);
      return performance.now() - started;
    });
    assert.ok(filterElapsed <= 100, `chart catalog filtered in ${filterElapsed.toFixed(1)}ms`);
    await frame.locator("[data-chart-catalog-clear]").click();
    await search.fill("not-a-visualization");
    assert.equal(await frame.locator("[data-chart-entry]:not([hidden])").count(), 0);
    assert.equal(await frame.locator("[data-chart-catalog-empty]").isVisible(), true);
    await frame.locator("[data-chart-catalog-clear]").click();

    await frame.locator("#chart-fdai-surfaces").scrollIntoViewIfNeeded();
    await page.screenshot({
      path: join(output, "charts-fdai-light.png"),
      animations: "disabled",
    });
    await frame.locator("#chart-datadog-widgets").scrollIntoViewIfNeeded();
    await page.screenshot({
      path: join(output, "charts-datadog-light.png"),
      animations: "disabled",
    });
    await frame.locator("[data-cs-theme-toggle]").click();
    await frame.waitForFunction(() => getComputedStyle(
      document.querySelector(".cg-chart-entry"),
    ).backgroundColor === "rgb(29, 32, 35)");
    assert.equal(await frame.locator(".cg-chart-entry").first().evaluate(element =>
      getComputedStyle(element).backgroundColor), "rgb(29, 32, 35)");
    const darkLowContrast = await frame.evaluate(() => {
      const visible = element => element.checkVisibility({ checkVisibilityCSS: true, checkOpacity: true })
        && !element.closest('[hidden], [aria-hidden="true"]');
      const rgb = value => {
        const values = (value.match(/[\d.]+/g) || []).map(Number);
        return value.startsWith("color(srgb ")
          ? values.slice(0, 3).map(channel => channel * 255)
          : values.slice(0, 3);
      };
      const luminance = value => rgb(value).map(channel => {
        const normalized = channel / 255;
        return normalized <= 0.04045 ? normalized / 12.92
          : ((normalized + 0.055) / 1.055) ** 2.4;
      }).reduce((sum, channel, index) => sum + channel * [0.2126, 0.7152, 0.0722][index], 0);
      return [...document.querySelectorAll("#data-views *")].filter(element => {
        if (!visible(element)
          || element.matches("script, style, svg, svg *")
          || ![...element.childNodes].some(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim())) {
          return false;
        }
        const style = getComputedStyle(element);
        let current = element;
        let background = getComputedStyle(document.body).backgroundColor;
        while (current) {
          const candidate = getComputedStyle(current).backgroundColor;
          if (!["rgba(0, 0, 0, 0)", "transparent"].includes(candidate)) {
            background = candidate;
            break;
          }
          current = current.parentElement;
        }
        const foregroundLuminance = luminance(style.color);
        const backgroundLuminance = luminance(background);
        const ratio = (Math.max(foregroundLuminance, backgroundLuminance) + 0.05)
          / (Math.min(foregroundLuminance, backgroundLuminance) + 0.05);
        return ratio < 4.48;
      }).map(element => element.textContent.trim());
    });
    assert.deepEqual(darkLowContrast, []);
    await page.screenshot({
      path: join(output, "charts-datadog-dark.png"),
      animations: "disabled",
    });
    await context.close();
  } finally {
    await browser.close();
  }
});

test("Gallery chart catalog reflows at constrained and mobile widths", { timeout: 60000 }, async () => {
  await mkdir(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const results = [];
  try {
    for (const viewport of [
      { name: "constrained", width: 993, height: 641 },
      { name: "mobile", width: 390, height: 844 },
    ]) {
      const context = await browser.newContext({
        viewport: { width: viewport.width, height: viewport.height },
        reducedMotion: "reduce",
      });
      await context.route("**/*", route => new URL(route.request().url()).origin === origin
        ? route.continue() : route.abort("blockedbyclient"));
      const page = await context.newPage();
      const frame = await openView(page, "data-views");
      await frame.waitForFunction(() =>
        document.querySelector("[data-chart-catalog-root]")?.dataset.chartCatalogReady === "true");
      const measurement = await frame.evaluate(() => {
        const section = document.getElementById("data-views");
        const grid = document.querySelector(".cg-chart-catalog-grid");
        const controls = [...section.querySelectorAll(
          ".cg-chart-catalog-controls input, .cg-chart-catalog-controls select, .cg-chart-catalog-controls button, .cg-chart-jump a, .cg-chart-entry footer a",
        )].filter(element => element.checkVisibility());
        return {
          innerWidth,
          documentFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
          sectionFits: section.scrollWidth <= section.clientWidth,
          gridColumns: getComputedStyle(grid).gridTemplateColumns.split(" ").length,
          cardWidth: Math.round(grid.querySelector("[data-chart-entry]").getBoundingClientRect().width),
          controlColumns: getComputedStyle(document.querySelector(".cg-chart-catalog-controls"))
            .gridTemplateColumns.split(" ").length,
          shortControls: controls.filter(element => element.getBoundingClientRect().height < 44)
            .map(element => (element.textContent || element.getAttribute("placeholder") || "").trim()),
        };
      });
      assert.equal(measurement.documentFits, true, viewport.name);
      assert.equal(measurement.sectionFits, true, viewport.name);
      assert.equal(measurement.gridColumns, 1, viewport.name);
      assert.equal(measurement.controlColumns, 1, viewport.name);
      assert.ok(measurement.cardWidth >= 280, `${viewport.name}: ${measurement.cardWidth}px`);
      if (viewport.name === "mobile") {
        assert.deepEqual(measurement.shortControls, [], viewport.name);
      }
      results.push({ viewport, ...measurement });
      await frame.locator(".cg-chart-catalog-intro").scrollIntoViewIfNeeded();
      await page.screenshot({
        path: join(output, `charts-${viewport.name}.png`),
        animations: "disabled",
      });
      await context.close();
    }
    await writeFile(join(output, "chart-responsive-measurements.json"),
      JSON.stringify(results, null, 2) + "\n");
  } finally {
    await browser.close();
  }
});

test("Gallery select indicators are inset and rich menus remain keyboard operable", { timeout: 30000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      reducedMotion: "reduce",
    });
    await context.route("**/*", route => new URL(route.request().url()).origin === origin
      ? route.continue() : route.abort("blockedbyclient"));
    const page = await context.newPage();
    const frame = await openView(page, "advanced");
    const themeToggle = frame.locator("[data-cs-theme-toggle]");
    await themeToggle.click();
    assert.equal(await themeToggle.getAttribute("aria-pressed"), "true");
    assert.equal(await frame.locator("body").getAttribute("data-theme"), "dark");
    await themeToggle.click();
    assert.equal(await themeToggle.getAttribute("aria-pressed"), "false");
    assert.equal(await frame.locator("body").getAttribute("data-theme"), null);
    const nativeSelect = frame.locator("#native-agent-select");
    const nativeStyle = await nativeSelect.evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        appearance: style.appearance,
        paddingRight: parseFloat(style.paddingRight),
        backgroundPosition: style.backgroundPosition,
      };
    });
    assert.equal(nativeStyle.appearance, "none");
    assert.ok(nativeStyle.paddingRight >= 40, JSON.stringify(nativeStyle));
    assert.match(nativeStyle.backgroundPosition, /100% - 20px/);

    const trigger = frame.locator("[data-cs-select-trigger]");
    const chevronGap = await trigger.evaluate((button) => {
      const chevron = button.querySelector(".cs-rich-select-chevron").getBoundingClientRect();
      const bounds = button.getBoundingClientRect();
      return Math.round(bounds.right - chevron.right);
    });
    assert.ok(chevronGap >= 12 && chevronGap <= 20, `rich select caret gap ${chevronGap}px`);
    await trigger.focus();
    await page.keyboard.press("Enter");
    assert.equal(await trigger.getAttribute("aria-expanded"), "true");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    assert.equal(await trigger.getAttribute("aria-expanded"), "false");

    const preview = frame.locator("[data-gallery-preview]");
    await preview.selectOption("zoom");
    assert.equal(await frame.locator("body").getAttribute("data-preview"), "zoom");
    assert.equal(await frame.evaluate(() =>
      document.documentElement.scrollWidth <= document.documentElement.clientWidth), true);
    assert.equal(await frame.locator("#advanced").evaluate(element =>
      element.scrollWidth <= element.clientWidth), true);
    await preview.selectOption("reduced");
    assert.equal(await frame.locator("body").getAttribute("data-preview"), "reduced");
    assert.equal(
      await frame.locator(".cs-rich-select-button").evaluate(element =>
        parseFloat(getComputedStyle(element).transitionDuration) <= 0.01),
      true,
    );
    await preview.selectOption("default");

    await page.emulateMedia({ forcedColors: "active" });
    const forced = await nativeSelect.evaluate((element) => {
      const style = getComputedStyle(element);
      return { appearance: style.appearance, backgroundImage: style.backgroundImage };
    });
    assert.notEqual(forced.appearance, "none");
    assert.equal(forced.backgroundImage, "none");
    await context.close();
  } finally {
    await browser.close();
  }
});

test("Gallery categories reflow with current controls at mobile width", { timeout: 60000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({
      viewport: { width: 390, height: 844 },
      reducedMotion: "reduce",
    });
    await context.route("**/*", route => new URL(route.request().url()).origin === origin
      ? route.continue() : route.abort("blockedbyclient"));
    const page = await context.newPage();
    const representatives = [
      "colors",
      "date-time-values",
      "controls",
      "tabs-meters",
      "alerts",
      "data-views",
      "drawers-command-menus",
      "settings-preferences",
    ];
    for (const id of representatives) {
      const frame = await openView(page, id);
      const measurement = await frame.evaluate((sectionId) => {
        const visible = element => element.checkVisibility({ checkVisibilityCSS: true, checkOpacity: true });
        const controls = [...document.querySelectorAll("button, select, input, textarea, summary")]
          .filter(visible);
        return {
          documentFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
          sectionFits: document.getElementById(sectionId).scrollWidth <= document.getElementById(sectionId).clientWidth,
          shortControls: controls.filter(element => element.getBoundingClientRect().height < 44)
            .map(element => (element.textContent || element.getAttribute("aria-label") || "").trim()),
        };
      }, id);
      assert.equal(measurement.documentFits, true, id);
      assert.equal(measurement.sectionFits, true, id);
      assert.deepEqual(measurement.shortControls, [], `${id}: ${JSON.stringify(measurement.shortControls)}`);
    }
    await context.close();
  } finally {
    await browser.close();
  }
});

test("Gallery category changes meet the local feedback budget", { timeout: 30000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      reducedMotion: "reduce",
    });
    await context.route("**/*", route => new URL(route.request().url()).origin === origin
      ? route.continue() : route.abort("blockedbyclient"));
    const page = await context.newPage();
    const frame = await openView(page, "colors");
    for (const category of [
      "foundations",
      "inputs",
      "actions",
      "selection",
      "feedback",
      "data",
      "overlays",
      "patterns",
    ]) {
      const started = performance.now();
      await frame.locator(`.cs-gallery-index [data-gallery-category="${category}"]`).click();
      await frame.locator(`main > .cs-section[data-gallery-category="${category}"]:visible`).first().waitFor();
      const elapsed = performance.now() - started;
      assert.ok(elapsed <= 250, `${category} switched in ${elapsed.toFixed(1)}ms`);
    }
    await context.close();
  } finally {
    await browser.close();
  }
});
