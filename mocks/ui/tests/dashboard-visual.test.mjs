/** Local dashboard layout and keyboard checks; not a complete WCAG certification. */
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const require = createRequire(join(root, "console/package.json"));
const { chromium } = require("playwright");
const origin = "http://127.0.0.1:5373";

test("Dashboard prioritizes review and posture with readable spacing, keyboard and reflow", {
  timeout: 90000,
}, async () => {
  const browser = await chromium.launch({ headless: true });
  const output = join(root, ".fdai/visual-review/dashboard-premium-checks");
  const stages = [];
  let completed = false;
  await mkdir(output, { recursive: true });
  try {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      reducedMotion: "reduce",
    });
    await context.route("**/*", route => new URL(route.request().url()).origin === origin
      ? route.continue() : route.abort("blockedbyclient"));
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    page.setDefaultTimeout(6000);
    await page.goto(`${origin}/#mocks/ui/dashboard.html`);
    const frame = await (await page.locator("#preview-frame").elementHandle()).contentFrame();
    await frame.locator(".de-preview-note").waitFor();
    await frame.waitForLoadState("load");

    const desktop = await frame.evaluate(() => ({
      width: innerWidth,
      height: innerHeight,
      scrollHeight: document.documentElement.scrollHeight,
      overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      primaryBottom: document.querySelector(".de-outcomes").getBoundingClientRect().bottom,
      attentionBottom: document.querySelector(".de-attention").getBoundingClientRect().bottom,
      postureBottom: document.querySelector(".de-posture").getBoundingClientRect().bottom,
      disclosureBottom: document.querySelector(".de-evidence summary").getBoundingClientRect().bottom,
      rhythm: {
        rowGap: getComputedStyle(document.querySelector(".de-page")).rowGap,
        cardGap: getComputedStyle(document.querySelector(".de-attention-grid > a")).rowGap,
        cardPadding: getComputedStyle(document.querySelector(".de-attention-grid > a")).paddingTop,
        repeatedInstructions: document.querySelectorAll(".de-attention-grid small").length,
        unavailableWeight: getComputedStyle(document.querySelector(".de-value-unknown")).fontWeight,
      },
      emptyNames: [...document.querySelectorAll("a, button, summary")].filter(el =>
        !el.textContent.trim() && !el.getAttribute("aria-label")).length,
      timedDisclosure: document.querySelectorAll(".de-toast").length,
      outcomeLayout: {
        gridDisplay: getComputedStyle(document.querySelector(".de-outcome-grid")).display,
        cards: [...document.querySelectorAll(".de-outcome-grid > a")].map(el => ({
          display: getComputedStyle(el).display,
          background: getComputedStyle(el).backgroundColor,
          border: parseFloat(getComputedStyle(el).borderTopWidth),
        })),
      },
    }));
    assert.equal(desktop.overflow, false);
    assert.ok(desktop.attentionBottom <= desktop.height, JSON.stringify(desktop));
    assert.ok(desktop.postureBottom <= desktop.height, JSON.stringify(desktop));
    assert.deepEqual(desktop.rhythm, {
      rowGap: "32px", cardGap: "8px", cardPadding: "16px",
      repeatedInstructions: 0, unavailableWeight: "400",
    });
    assert.equal(desktop.emptyNames, 0);
    assert.equal(desktop.timedDisclosure, 0);
    assert.equal(desktop.outcomeLayout.gridDisplay, "grid");
    assert.equal(desktop.outcomeLayout.cards.length, 4);
    assert.ok(desktop.outcomeLayout.cards.every(card =>
      card.display === "grid" && card.background === "rgb(255, 255, 255)" && card.border >= 1));
    const shell = await page.evaluate(() => ({
      navigationRight: document.querySelector(".side").getBoundingClientRect().right,
      previewLeft: document.querySelector(".preview").getBoundingClientRect().left,
    }));
    assert.ok(shell.previewLeft >= shell.navigationRight, JSON.stringify(shell));
    stages.push({ name: "desktop-review-priority-and-unobscured-navigation", ...desktop, ...shell });
    await page.screenshot({ path: join(output, "desktop.png"), animations: "disabled" });

    const toggle = page.getByRole("button", { name: "Toggle design navigation", exact: true });
    await toggle.click();
    await page.setViewportSize({ width: 1108, height: 921 });
    const actual = await frame.evaluate(() => ({
      height: innerHeight,
      scrollHeight: document.documentElement.scrollHeight,
      attentionBottom: document.querySelector(".de-attention").getBoundingClientRect().bottom,
      postureBottom: document.querySelector(".de-posture").getBoundingClientRect().bottom,
    }));
    assert.ok(actual.attentionBottom <= actual.height, JSON.stringify(actual));
    assert.ok(actual.postureBottom <= actual.height, JSON.stringify(actual));
    stages.push({ name: "collaborator-viewport-review-priority", ...actual });

    const skip = frame.getByRole("link", { name: "Skip to dashboard content" });
    await skip.focus();
    await skip.press("Enter");
    await frame.waitForFunction(() => document.activeElement?.id === "dashboard-main");
    assert.equal(await frame.evaluate(() => document.activeElement.id), "dashboard-main");
    const inspect = frame.getByRole("button", { name: "Inspect trust tier distribution" });
    await inspect.focus();
    const focus = await inspect.evaluate(el => ({
      style: getComputedStyle(el).outlineStyle,
      width: parseFloat(getComputedStyle(el).outlineWidth),
      height: el.getBoundingClientRect().height,
      targetWidth: el.getBoundingClientRect().width,
    }));
    assert.equal(focus.style, "solid");
    assert.ok(focus.width >= 3);
    assert.ok(focus.height >= 44);
    assert.ok(focus.targetWidth >= 44);
    await inspect.press("Enter");
    const dialog = frame.getByRole("dialog", { name: "Trust tier distribution" });
    await dialog.waitFor({ state: "visible" });
    assert.equal(await dialog.locator("tbody tr").count(), 3);
    await frame.getByRole("button", { name: "Close", exact: true }).press("Escape");
    await dialog.waitFor({ state: "hidden" });
    assert.equal(await inspect.evaluate(el => document.activeElement === el), true);
    const summary = frame.locator(".de-evidence > summary");
    await summary.focus();
    await summary.press("Enter");
    assert.equal(await frame.locator(".de-evidence").evaluate(el => el.open), true);
    assert.equal(await frame.locator(".de-evidence table caption").count(), 2);
    assert.equal(await frame.locator(".de-evidence th:not([scope])").count(), 0);
    const expanded = await frame.evaluate(() => ({
      sections: [...document.querySelectorAll(".de-evidence-body > section h2")].map(el => el.textContent),
      sourceFields: document.querySelectorAll(".de-source-facts > div").length,
      numericCellsAligned: [...document.querySelectorAll(".de-breakdowns .de-count")]
        .every(el => getComputedStyle(el).textAlign === "right"),
      verticalFacts: [...document.querySelectorAll(".de-vertical-facts")]
        .map(list => [...list.querySelectorAll("dd")].map(el => el.textContent)),
      summaryLinks: document.querySelectorAll(".de-audit-summary > a").length,
      intervalDays: (Date.parse(document.querySelector("[data-window-end]").dateTime) -
        Date.parse(document.querySelector("[data-window-start]").dateTime)) / 86400000,
      linkedMetricLabels: [...document.querySelectorAll(".cs-metric-link > span:first-child, .cs-data-link > span:first-child")]
        .every(el => getComputedStyle(el).textDecorationLine.includes("underline")),
      primaryBodySize: parseFloat(getComputedStyle(document.querySelector(".de-attention-grid strong")).fontSize),
    }));
    assert.deepEqual(expanded.sections, ["Evidence context", "Vertical outcomes", "Audit and control detail"]);
    assert.equal(expanded.sourceFields, 8);
    assert.equal(expanded.numericCellsAligned, true);
    assert.deepEqual(expanded.verticalFacts, [["10", "1", "USD 0"], ["8", "2", "USD 0"], ["4", "3", "USD 0"]]);
    assert.equal(expanded.summaryLinks, 4);
    assert.equal(expanded.intervalDays, 30);
    assert.equal(expanded.linkedMetricLabels, true);
    assert.ok(expanded.primaryBodySize >= 14);
    stages.push({ name: "expanded-evidence-organization-and-preserved-facts", ...expanded });
    await frame.locator("#evidence-context-title").evaluate(el =>
      el.scrollIntoView({ block: "start", behavior: "instant" }));
    await page.screenshot({
      path: join(output, "expanded-evidence-desktop.png"),
      animations: "disabled",
    });
    await frame.locator("#audit-detail-title").evaluate(el =>
      el.scrollIntoView({ block: "start", behavior: "instant" }));
    await page.screenshot({
      path: join(output, "expanded-evidence-audit-desktop.png"),
      animations: "disabled",
    });
    await summary.press("Space");
    assert.equal(await frame.locator(".de-evidence").evaluate(el => el.open), false);
    stages.push({ name: "keyboard-skip-dialog-return-disclosure-and-table-semantics", ...focus });

    for (const viewport of [
      { width: 993, height: 641 },
      { width: 390, height: 844 },
      { width: 372, height: 824 },
      { width: 320, height: 844 },
    ]) {
      await page.setViewportSize(viewport);
      const measure = await frame.evaluate(() => ({
        width: innerWidth,
        rootFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
        mainFits: document.querySelector("main").scrollWidth <= document.querySelector("main").clientWidth,
        smallMobileControls: [...document.querySelectorAll(".de-inspect, .de-page-header .cs-control-button, .de-chart-links a")]
          .filter(el => el.getBoundingClientRect().height < 44 || el.getBoundingClientRect().width < 44).length,
        metricsStyled: getComputedStyle(document.querySelector(".de-outcome-grid")).display === "grid" &&
          [...document.querySelectorAll(".de-outcome-grid > a")].every(el => getComputedStyle(el).display === "grid"),
      }));
      assert.equal(measure.rootFits, true, JSON.stringify(measure));
      assert.equal(measure.mainFits, true, JSON.stringify(measure));
      assert.equal(measure.metricsStyled, true, JSON.stringify(measure));
      if (viewport.width <= 390) assert.equal(measure.smallMobileControls, 0);
      await summary.click();
      assert.equal(await frame.locator(".de-evidence").evaluate(el => el.open), true);
      assert.equal(await frame.evaluate(() =>
        document.documentElement.scrollWidth <= document.documentElement.clientWidth), true);
      if (viewport.width === 390) {
        await frame.locator(".de-breakdowns").screenshot({
          path: join(output, "expanded-evidence-mobile-tables.png"),
          animations: "disabled",
        });

      }
      await summary.click();
      stages.push({ name: "responsive-and-expanded-evidence", viewport, ...measure });
      if (viewport.width === 390) {
        await frame.locator(".de-routing").screenshot({
          path: join(output, "mobile-charts.png"),
          animations: "disabled",
        });
        await inspect.click();
        await dialog.waitFor({ state: "visible" });
        assert.equal(await frame.evaluate(() =>
          document.documentElement.scrollWidth <= document.documentElement.clientWidth), true);
        await frame.getByRole("button", { name: "Close", exact: true }).click();
        await dialog.waitFor({ state: "hidden" });
      }
    }

    await page.setViewportSize({ width: 1440, height: 900 });
    await frame.evaluate(() => { document.documentElement.style.zoom = "2"; });
    const enlarged = await frame.evaluate(() => ({
      rootFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      mainFits: document.querySelector("main").scrollWidth <= document.querySelector("main").clientWidth,
      allPrimarySectionsPresent: document.querySelectorAll("main > section").length === 4,
    }));
    assert.equal(enlarged.rootFits, true);
    assert.equal(enlarged.mainFits, true);
    assert.equal(enlarged.allPrimarySectionsPresent, true);
    await frame.evaluate(() => { document.documentElement.style.zoom = ""; });
    stages.push({ name: "200-percent-layout-zoom", ...enlarged });

    await summary.click();
    const originalFonts = await frame.locator("main, main *").evaluateAll(elements => {
      const sizes = elements.map(el => getComputedStyle(el).fontSize);
      const originals = elements.map(el => el.style.cssText);
      elements.forEach((el, index) => {
        if (!el.closest("svg")) el.style.setProperty("font-size", `${parseFloat(sizes[index]) * 2}px`, "important");
      });
      return originals;
    });
    const textResize = await frame.evaluate(() => ({
      rootFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      clippedText: [...document.querySelectorAll("main a,main button,main p,main dd,main strong")]
        .filter(el => el.checkVisibility() && (el.scrollWidth > el.clientWidth + 2 ||
          (["hidden", "clip"].includes(getComputedStyle(el).overflowY) && el.scrollHeight > el.clientHeight + 2))).length,
    }));
    assert.equal(textResize.rootFits, true);
    assert.equal(textResize.clippedText, 0);
    await frame.locator("main, main *").evaluateAll((elements, originals) => {
      elements.forEach((el, index) => { el.style.cssText = originals[index]; });
    }, originalFonts);
    await summary.click();
    stages.push({ name: "200-percent-text-size", ...textResize });

    await frame.addStyleTag({ content: `
      .de-page * { line-height: 1.5 !important; letter-spacing: .12em !important; word-spacing: .16em !important; }
      .de-page p { margin-bottom: 2em !important; }
    ` });
    assert.equal(await frame.evaluate(() =>
      document.documentElement.scrollWidth <= document.documentElement.clientWidth), true);
    await summary.click();
    assert.equal(await frame.evaluate(() =>
      document.documentElement.scrollWidth <= document.documentElement.clientWidth), true);
    await summary.click();
    stages.push({ name: "user-text-spacing-without-horizontal-overflow" });

    const koreanCopy = await frame.evaluate(() => {
      const replacements = [
        ["#attention-title", "검토할 항목"],
        [".de-attention .de-section-head p", "승인 대기와 근거 누락을 먼저 확인하세요."],
        [".de-attention-grid > a:nth-child(1) strong", "대기 2건"],
        [".de-attention-grid > a:nth-child(2) strong", "신뢰도 근거 없음"],
        [".de-attention-grid > a:nth-child(3) strong", "조치 효과 미확인"],
        ["#posture-title", "운영 상태"],
        ["#outcomes-title", "운영 성과"],
      ];
      const original = replacements.map(([selector, text]) => {
        const element = document.querySelector(selector);
        const value = element.textContent;
        element.textContent = text;
        return [selector, value];
      });
      document.documentElement.lang = "ko";
      return original;
    });
    for (const width of [1108, 390, 320]) {
      await page.setViewportSize({ width, height: 921 });
      assert.equal(await frame.evaluate(() =>
        document.documentElement.scrollWidth <= document.documentElement.clientWidth), true);
    }
    await frame.evaluate(original => {
      original.forEach(([selector, text]) => { document.querySelector(selector).textContent = text; });
      document.documentElement.lang = "en";
    }, koreanCopy);
    stages.push({ name: "korean-copy-stress-fixture-with-spacing-overrides", widths: [1108, 390, 320] });
    await page.setViewportSize({ width: 1440, height: 900 });

    await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
    await inspect.focus();
    await inspect.press("Tab");
    await page.keyboard.press("Shift+Tab");
    assert.equal(await inspect.evaluate(el => document.activeElement === el), true);
    assert.equal(await inspect.evaluate(el => getComputedStyle(el).outlineStyle), "solid");
    assert.equal(await frame.locator(".de-attention-grid > a").first().evaluate(el =>
      getComputedStyle(el).transitionDuration), "0s");
    stages.push({ name: "forced-colors-focus-and-reduced-motion" });
    assert.deepEqual(errors, []);
    completed = true;
  } finally {
    await writeFile(join(output, "checks.json"), JSON.stringify({
      completed,
      scope: "synthetic-local-dashboard-and-master-navigation",
      stages,
      limitations: [
        "No full WCAG certification or assistive-technology user testing.",
        "Layout zoom is a CSS enlargement check, not a native-browser zoom conformance claim.",
      ],
    }, null, 2) + "\n");
    await browser.close();
  }
});
