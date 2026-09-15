/** Focused quality checks for the 14 Operations previews inside the real mock shell. */
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const require = createRequire(join(root, "console/package.json"));
const { chromium } = require("playwright");
const origin = process.env.FDAI_MOCK_ORIGIN || "http://127.0.0.1:5373";
const routes = [
  ["live", "Live"],
  ["incidents", "Incidents"],
  ["hil", "Approvals"],
  ["provision", "Provisioning"],
  ["onboarding", "Onboarding readiness"],
  ["detection-coverage", "Detection coverage"],
  ["configuration-baselines", "Configuration baselines"],
  ["processes", "Processes"],
  ["workflow-apps", "Workflow apps"],
  ["scheduler-runs", "Scheduler runs"],
  ["background-tasks", "Background tasks"],
  ["automation-blueprints", "Automation blueprints"],
  ["scheduled-continuations", "Scheduled continuations"],
  ["conversation-delivery", "Conversation delivery"],
];
const generatedRoutes = routes.slice(5).map(([name]) => name);
let navigationSequence = 0;

async function openRoute(page, name) {
  const started = performance.now();
  navigationSequence += 1;
  await page.goto(`${origin}/?operations-audit=${navigationSequence}#mocks/ui/${name}.html`, {
    waitUntil: "load",
  });
  await page.waitForFunction(expected => {
    const frame = document.querySelector("#preview-frame");
    return frame?.contentDocument?.readyState === "complete" &&
      frame.contentWindow.location.pathname === `/mocks/ui/${expected}.html`;
  }, name);
  const frame = await (await page.locator("#preview-frame").elementHandle()).contentFrame();
  if (generatedRoutes.includes(name)) {
    await frame.locator('[data-operator-ready="true"]').waitFor();
  }
  await frame.evaluate(() => new Promise(resolveFrame =>
    requestAnimationFrame(() => requestAnimationFrame(resolveFrame))));
  return { frame, readyMs: performance.now() - started };
}

async function routeMeasurements(page, frame, route, readyMs) {
  const shell = await page.evaluate(() => ({
    active: document.querySelector('.side [aria-current="page"]')?.getAttribute("data-page"),
    fits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    previewLeft: document.querySelector(".preview").getBoundingClientRect().left,
    navigationRight: document.querySelector(".side").getBoundingClientRect().right,
  }));
  const surface = await frame.evaluate(() => {
    const visible = element => {
      if (!element.checkVisibility({ checkVisibilityCSS: true, checkOpacity: true })) return false;
      const box = element.getBoundingClientRect();
      return box.width > 0 && box.height > 0 && !element.closest('[hidden], [aria-hidden="true"]');
    };
    const name = element =>
      (element.getAttribute("aria-label") || element.textContent || "").trim().replace(/\s+/g, " ");
    const interactive = [...document.querySelectorAll("a[href], button, summary, input, select, textarea")]
      .filter(visible);
    const operationalText = [...document.querySelectorAll(
      ".cs-sev, .cs-tile-mode, .cs-tile-scope, .in-summary-foot, .in-view-row em, " +
      ".in-evidence-scope, .in-history-title > span, .pv-stage-index, .ob-role-table th, .ob-role-table code",
    )].filter(visible);
    const tables = [...document.querySelectorAll("table")].filter(visible);
    return {
      documentFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      mainFits: document.querySelector("main").scrollWidth <= document.querySelector("main").clientWidth,
      headingCount: document.querySelectorAll("h1").length,
      heading: document.querySelector("h1")?.textContent.trim() || "",
      language: document.documentElement.lang,
      unnamed: interactive.filter(element => !name(element) &&
        !element.labels?.length && !element.getAttribute("aria-labelledby")).length,
      unlabeledFields: interactive.filter(element => element.matches("input, select, textarea") &&
        !element.labels?.length && !element.getAttribute("aria-label") &&
        !element.getAttribute("aria-labelledby")).length,
      nestedInteractive: document.querySelectorAll(
        "a a, a button, a input, a select, button a, button button, button input, button select",
      ).length,
      undersizedOperationalText: operationalText.filter(element =>
        parseFloat(getComputedStyle(element).fontSize) < 12).map(element => name(element)),
      inaccessibleTables: tables.filter(table =>
        !table.querySelector("caption") && !table.getAttribute("aria-label") &&
        !table.getAttribute("aria-labelledby")).length,
      unscopedHeaders: tables.flatMap(table => [...table.querySelectorAll("th")])
        .filter(header => !header.getAttribute("scope")).length,
      undersizedIconLinks: [...document.querySelectorAll(
        'a[href][aria-label]:not([aria-label=""])',
      )].filter(visible).filter(element => {
        const box = element.getBoundingClientRect();
        return box.width < 24 || box.height < 24;
      }).map(element => ({ name: name(element), width: element.clientWidth, height: element.clientHeight })),
    };
  });
  return { route, readyMs, shell, surface };
}

test("Onboarding uses the neutral Operations summary hierarchy", { timeout: 30000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      reducedMotion: "reduce",
    });
    const page = await context.newPage();
    const { frame } = await openRoute(page, "onboarding");
    const presentation = await frame.evaluate(() => {
      const summary = getComputedStyle(document.querySelector(".ob-summary"));
      const kpi = getComputedStyle(document.querySelector(".ob-kpi"));
      const count = getComputedStyle(document.querySelector(".ob-count"));
      return {
        summaryBorder: summary.borderTopWidth,
        kpiRadius: kpi.borderRadius,
        kpiShadow: kpi.boxShadow,
        countRadius: count.borderRadius,
      };
    });
    assert.deepEqual(presentation, {
      summaryBorder: "1px",
      kpiRadius: "0px",
      kpiShadow: "none",
      countRadius: "0px",
    });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await frame.evaluate(() =>
      document.documentElement.scrollWidth <= document.documentElement.clientWidth), true);
  } finally {
    await browser.close();
  }
});

test("Operations previews meet the scoped quality gates", { timeout: 240000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  const output = join(root, ".fdai/visual-review/operations-rubric");
  const stages = [];
  const errors = [];
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
    page.on("pageerror", error => errors.push(error.message));
    page.setDefaultTimeout(7000);

    for (const [route, title] of routes) {
      const { frame, readyMs } = await openRoute(page, route);
      const measured = await routeMeasurements(page, frame, route, readyMs);
      assert.equal(measured.shell.active, `mocks/ui/${route}.html`, route);
      assert.equal(measured.shell.fits, true, route);
      assert.ok(measured.shell.previewLeft >= measured.shell.navigationRight, route);
      assert.equal(measured.surface.documentFits, true, route);
      assert.equal(measured.surface.mainFits, true, route);
      assert.equal(measured.surface.headingCount, 1, route);
      assert.match(measured.surface.heading, new RegExp(title, "i"), route);
      assert.equal(measured.surface.language, "en", route);
      assert.equal(measured.surface.unnamed, 0, route);
      assert.equal(measured.surface.unlabeledFields, 0, route);
      assert.equal(measured.surface.nestedInteractive, 0, route);
      assert.deepEqual(measured.surface.undersizedOperationalText, [], route);
      assert.equal(measured.surface.inaccessibleTables, 0, route);
      assert.equal(measured.surface.unscopedHeaders, 0, route);
      assert.deepEqual(measured.surface.undersizedIconLinks, [], route);
      assert.ok(readyMs <= 1500, `${route} ready in ${readyMs.toFixed(1)}ms`);
      stages.push({ name: "desktop-route", ...measured });
    }

    for (const route of generatedRoutes) {
      const { frame } = await openRoute(page, route);
      const tabs = frame.getByRole("tab");
      assert.ok(await tabs.count() >= 2, route);
      await tabs.first().focus();
      await tabs.first().press("ArrowRight");
      assert.equal(await tabs.nth(1).getAttribute("aria-selected"), "true", route);
      assert.equal(await tabs.nth(1).evaluate(element => element === document.activeElement), true, route);
      const state = frame.getByLabel("Preview state");
      for (const [mode, pattern] of [
        ["loading", /Loading projection/],
        ["unavailable", /Missing evidence is not zero/],
        ["error", /No successful result/],
        ["empty", /not proof of absence/],
      ]) {
        const started = performance.now();
        await state.selectOption(mode);
        assert.match(await frame.locator(".op-state").innerText(), pattern, route);
        assert.equal(await frame.locator("[data-op-content]").isVisible(), false, route);
        assert.ok(performance.now() - started <= 250, `${route} ${mode} feedback exceeded 250ms`);
      }
      await state.selectOption("sample-data");
      assert.equal(await frame.locator("[data-op-content]").isVisible(), true, route);
      await tabs.first().click();
      const records = frame.locator("[data-op-record]:visible");
      if (await records.count() > 1) {
        await records.nth(1).click();
        assert.equal(await records.nth(1).getAttribute("aria-pressed"), "true", route);
        assert.ok(await frame.locator("[data-op-record-detail] h3:visible").count() > 0, route);
      }
      stages.push({ name: "generated-route-states-and-keyboard-tabs", route });
    }

    {
      const { frame } = await openRoute(page, "hil");
      const search = frame.locator("[data-approval-search]");
      await search.fill("no matching approval");
      assert.equal(await frame.locator("[data-approval-empty]").isVisible(), true);
      await frame.locator("[data-clear-approvals]").click();
      assert.equal(await search.evaluate(element => element === document.activeElement), true);
      const disclosure = frame.locator("[data-approval] details").first();
      await disclosure.locator("summary").press("Enter");
      assert.equal(await disclosure.getAttribute("open"), "");
      assert.match(await disclosure.innerText(), /Independent effect observation/);
      stages.push({ name: "approval-filter-recovery-and-safeguard-disclosure" });
    }

    {
      const { frame } = await openRoute(page, "onboarding");
      const state = frame.getByLabel("Preview state");
      await state.selectOption("ready");
      assert.equal(await frame.locator("#onboarding-resource-list").isVisible(), false);
      assert.equal(await frame.locator("#onboarding-no-resources").isVisible(), true);
      await state.selectOption("unconfigured");
      assert.match(await frame.locator("#onboarding-preview-note").innerText(), /not configured/i);
      await state.selectOption("failed");
      assert.equal(await frame.locator("#onboarding-preview-note").getAttribute("role"), "alert");
      await frame.locator("#refresh-button").click();
      assert.equal(await state.inputValue(), "blocked");
      assert.equal(await frame.locator("#onboarding-resource-list li").count(), 3);
      assert.equal(await frame.locator("#onboarding-role-list tbody tr").count(), 2);
      stages.push({ name: "onboarding-success-unavailable-error-and-recovery" });
    }

    {
      const { frame } = await openRoute(page, "incidents");
      const search = frame.locator("[data-incident-search]");
      await search.fill("no matching incident");
      assert.equal(await frame.locator(".op-empty").isVisible(), true);
      await frame.locator("[data-clear-incident-scope]").click();
      assert.equal(await search.evaluate(element => element === document.activeElement), true);
      const opener = frame.locator("[data-open-intervention]");
      await opener.click();
      const dialog = frame.locator("[data-intervention-dialog]");
      await dialog.waitFor({ state: "visible" });
      await frame.locator("[data-intervention-form]").getByRole("button", { name: "Review request" }).click();
      const comment = frame.locator('textarea[name="intervention-comment"]');
      assert.equal(await comment.getAttribute("aria-invalid"), "true");
      assert.equal(await comment.evaluate(element => element === document.activeElement), true);
      await comment.fill("Keep the response in observation while the rollout evidence is reviewed.");
      assert.equal(await comment.getAttribute("aria-invalid"), "false");
      await frame.locator("[data-intervention-form]").getByRole("button", { name: "Review request" }).click();
      assert.equal(await frame.locator("[data-review-panel]").isVisible(), true);
      await frame.locator("[data-confirm-intervention]").press("Escape");
      await dialog.waitFor({ state: "hidden" });
      assert.equal(await opener.evaluate(element => element === document.activeElement), true);
      stages.push({ name: "incident-filter-form-validation-dialog-and-focus-recovery" });
    }

    {
      const { frame } = await openRoute(page, "provision");
      await frame.locator('[data-operator-ready="true"]').waitFor();
      const tabs = frame.getByRole("tab");
      await tabs.first().focus();
      await tabs.first().press("ArrowRight");
      assert.equal(await tabs.nth(1).getAttribute("aria-selected"), "true");
      const pause = frame.locator("#pv-pause");
      await pause.click();
      assert.equal(await pause.getAttribute("aria-pressed"), "true");
      assert.match(await pause.innerText(), /Resume/);
      await pause.click();
      assert.equal(await pause.getAttribute("aria-pressed"), "false");
      stages.push({ name: "provisioning-view-navigation-and-replay-control" });
    }

    {
      const { frame } = await openRoute(page, "live");
      const pause = frame.locator("#live-pause");
      await pause.click();
      assert.equal(await pause.getAttribute("aria-pressed"), "true");
      const chartPoint = frame.locator("[data-gate-segment]").first();
      await chartPoint.focus();
      assert.match(await chartPoint.getAttribute("aria-label"), /finalized decisions/);
      assert.equal(await frame.locator("#live-chart-tooltip").isVisible(), true);
      const chartTotals = await frame.evaluate(() => ({
        gateCounts: ["k-auto-count", "k-hil-count", "k-abstain-count", "k-deny-count"]
          .map(id => Number(document.getElementById(id).textContent)),
        gateTotal: Number(document.getElementById("k-gate-meta").textContent.match(/\d+/)?.[0]),
        tierPercentages: ["k-t0", "k-t1", "k-t2"]
          .map(id => Number(document.getElementById(id).textContent.replace("%", ""))),
      }));
      assert.equal(chartTotals.gateCounts.reduce((sum, value) => sum + value, 0), chartTotals.gateTotal);
      assert.ok(Math.abs(chartTotals.tierPercentages.reduce((sum, value) => sum + value, 0) - 100) <= 1);
      const tile = frame.locator("[data-event-id]:visible").first();
      await tile.waitFor();
      await tile.focus();
      await tile.press("Enter");
      const dialog = frame.getByRole("dialog");
      await dialog.waitFor({ state: "visible" });
      await frame.locator("#detail-close").press("Escape");
      await dialog.waitFor({ state: "hidden" });
      await frame.waitForFunction(element => document.activeElement === element, await tile.elementHandle());
      assert.equal(await tile.evaluate(element => element === document.activeElement), true);
      stages.push({ name: "live-freeze-chart-alternative-dialog-and-focus-recovery" });
    }

    {
      const { frame } = await openRoute(page, "scheduler-runs");
      const summary = await frame.locator(".cp-kpi strong").evaluateAll(elements =>
        elements.map(element => element.textContent.trim()));
      assert.deepEqual(summary, ["4", "25.0%", "2", "3.0 s", "5.0 s"]);
      assert.equal(await frame.locator("#scheduler-dispatch-history tbody tr").count(), 4);
      assert.match(await frame.locator(".cp-kpis").innerText(), /1 \/ 4/);
      stages.push({ name: "scheduler-quantitative-fidelity" });
    }

    for (const viewport of [
      { width: 390, height: 844 },
      { width: 320, height: 844 },
    ]) {
      await page.setViewportSize(viewport);
      for (const [route] of routes) {
        const { frame } = await openRoute(page, route);
        const measure = await frame.evaluate(() => {
          const visible = element => element.checkVisibility({ checkVisibilityCSS: true, checkOpacity: true }) &&
            element.getBoundingClientRect().width > 0 && element.getBoundingClientRect().height > 0;
          const touchControls = [...document.querySelectorAll(
            'button, summary, input:not([type="checkbox"]):not([type="radio"]), select, a.cs-btn',
          )].filter(visible);
          const iconControls = [...document.querySelectorAll(
            'a[aria-label]:not([aria-label=""]), button[aria-label]:not([aria-label=""])',
          )].filter(visible);
          return {
            documentFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
            mainFits: document.querySelector("main").scrollWidth <= document.querySelector("main").clientWidth,
            shortTouchControls: touchControls.filter(element =>
              element.getBoundingClientRect().height < 44).length,
            narrowIconControls: iconControls.filter(element =>
              element.getBoundingClientRect().width < 44 ||
              element.getBoundingClientRect().height < 44).length,
            liveKpisFit: !document.querySelector(".cs-live-kpis") ||
              document.querySelector(".cs-live-kpis").scrollWidth <=
              document.querySelector(".cs-live-kpis").clientWidth,
          };
        });
        assert.deepEqual(measure, {
          documentFits: true,
          mainFits: true,
          shortTouchControls: 0,
          narrowIconControls: 0,
          liveKpisFit: true,
        }, `${route} at ${viewport.width}px`);
        stages.push({ name: "mobile-reflow-and-targets", route, viewport, ...measure });
      }
    }

    await page.setViewportSize({ width: 1440, height: 900 });
    for (const [route] of routes) {
      const { frame } = await openRoute(page, route);
      await frame.evaluate(() => { document.documentElement.style.zoom = "2"; });
      const enlarged = await frame.evaluate(() => ({
        documentFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
        mainFits: document.querySelector("main").scrollWidth <= document.querySelector("main").clientWidth,
        documentWidth: document.documentElement.clientWidth,
        documentScrollWidth: document.documentElement.scrollWidth,
        mainWidth: document.querySelector("main").clientWidth,
        mainScrollWidth: document.querySelector("main").scrollWidth,
      }));
      assert.equal(enlarged.documentFits, true, `${route} at 200%: ${JSON.stringify(enlarged)}`);
      assert.equal(enlarged.mainFits, true, `${route} at 200%: ${JSON.stringify(enlarged)}`);
      stages.push({ name: "two-hundred-percent-layout-zoom", route, ...enlarged });
    }

    await page.setViewportSize({ width: 390, height: 844 });
    for (const [route] of routes) {
      const { frame } = await openRoute(page, route);
      await frame.addStyleTag({ content: `
        main, main * {
          line-height: 1.5 !important;
          letter-spacing: .12em !important;
          word-spacing: .16em !important;
        }
        main p { margin-bottom: 2em !important; }
      ` });
      const original = await frame.locator("h1").innerText();
      await frame.locator("h1").evaluate(element => {
        element.textContent = "운영 작업 검토와 독립적인 효과 확인";
        document.documentElement.lang = "ko";
      });
      const spaced = await frame.evaluate(() => ({
        documentFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
        mainFits: document.querySelector("main").scrollWidth <= document.querySelector("main").clientWidth,
      }));
      assert.deepEqual(spaced, { documentFits: true, mainFits: true }, `${route} with text spacing`);
      await frame.locator("h1").evaluate((element, text) => {
        element.textContent = text;
        document.documentElement.lang = "en";
      }, original);
      stages.push({ name: "text-spacing-and-korean-copy-stress", route, ...spaced });
    }

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
    for (const [route] of routes) {
      const { frame } = await openRoute(page, route);
      const keyboardTarget = frame.locator("summary:visible, [role=tab]:visible, button:visible").first();
      await keyboardTarget.focus();
      await keyboardTarget.press("Tab");
      await page.keyboard.press("Shift+Tab");
      const adaptive = await keyboardTarget.evaluate(element => ({
        focused: element === document.activeElement,
        focusVisible: element.matches(":focus-visible"),
        focus: getComputedStyle(element).outlineStyle,
        width: parseFloat(getComputedStyle(element).outlineWidth),
      }));
      assert.equal(adaptive.focused, true, `${route}: ${JSON.stringify(adaptive)}`);
      assert.equal(adaptive.focusVisible, true, `${route}: ${JSON.stringify(adaptive)}`);
      assert.equal(adaptive.focus, "solid", `${route}: ${JSON.stringify(adaptive)}`);
      stages.push({ name: "forced-colors-focus-and-reduced-motion", route, ...adaptive });
    }

    assert.deepEqual(errors, []);
    completed = true;
  } finally {
    await writeFile(join(output, "checks.json"), JSON.stringify({
      completed,
      scope: "all-14-operations-static-mocks-in-master-shell",
      conditions: {
        browser: "Playwright Chromium",
        data: "synthetic",
        language: "English with Korean layout stress fixture",
        theme: "clear-neutral",
        viewports: ["1440x900", "390x844", "320x844"],
        feedbackBudgetMs: 250,
        routeReadyBudgetMs: 1500,
      },
      stages,
      errors,
      limitations: [
        "Static mock evidence only; no authenticated Console, backend, deployment, or operational-success claim.",
        "Automated semantic and keyboard checks are not a WCAG certification or assistive-technology user study.",
        "CSS zoom is a repeatable enlargement check, not a native-browser zoom certification.",
      ],
    }, null, 2) + "\n");
    await browser.close();
  }
});
