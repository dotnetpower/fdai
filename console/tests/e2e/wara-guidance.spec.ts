import { writeFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import type { WaraControl } from "../../src/routes/wara-controls.model";
import { guidanceText } from "../../src/routes/wara-guidance.model";
import { signFixtureGuidance } from "../../src/routes/wara-guidance.fixture";
import { waraCorpusControls, waraPilotControls } from "./wara-guidance-fixtures";

async function installFixture(page: Page, controls: readonly WaraControl[], mutate?: (control: WaraControl) => unknown) {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.route(/\/(?:api\/)?(?:wara-controls|rules|incidents)(?:[/?]|$)/, async (route) => {
    if (route.request().resourceType() === "document") return route.continue();
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api(?=\/)/, "");
    if (path === "/wara-controls") {
      return route.fulfill({ json: {
        total: 456, filtered_total: controls.length, offset: 0, limit: 50,
        facets: { by_resource_type: Object.fromEntries(controls.map((control) => [control.resource_type, 1])), by_satisfaction: { unknown: 456 } },
        controls: controls.slice(0, 50).map(({ guidance: _guidance, ...control }) => control),
        inventory: { active_recommendations: 393, disabled_recommendations: 63, resource_types: 80, automated_recommendations: 143, manual_recommendations: 250 },
        evaluation_source: "not_connected", source_revision: controls[0]!.source_revision, crosswalk_digest: `sha256:${"b".repeat(64)}`,
      } });
    }
    if (path.startsWith("/wara-controls/")) {
      const control = controls.find((item) => item.id === decodeURIComponent(path.slice("/wara-controls/".length)));
      if (control) return route.fulfill({ json: mutate ? mutate(control) : control });
    }
    return route.fulfill({ status: 404, json: { detail: "Not mocked in the isolated WARA fixture" } });
  });
}

async function measure(page: Page) {
  return page.locator(".wara-drawer").evaluate((drawer) => {
    const drawerStyle = getComputedStyle(drawer);
    if (drawerStyle.animationName !== "none" || drawerStyle.opacity !== "1") {
      throw new Error("WARA geometry requires a steady, opaque drawer");
    }
    const figure = drawer.querySelector<HTMLElement>(".wara-guidance-figure")!;
    const graph = figure.querySelector<HTMLElement>(".wara-guidance-graph")!;
    const graphBox = graph.getBoundingClientRect();
    const bodyBox = drawer.querySelector(".rule-drawer-body")!.getBoundingClientRect();
    const figureBox = figure.getBoundingClientRect();
    const viewportTop = bodyBox.top;
    const viewportBottom = Math.min(bodyBox.bottom, window.innerHeight);
    const hero = {
      figureTop: figureBox.top, figureBottom: figureBox.bottom, figureHeight: figureBox.height,
      viewportTop, viewportBottom, availableHeight: viewportBottom - viewportTop,
      visibleGraphFraction: Math.max(0, Math.min(graphBox.bottom, viewportBottom) - Math.max(graphBox.top, viewportTop)) / graphBox.height,
      visibleNodes: [...graph.querySelectorAll<HTMLElement>("[data-guidance-node]")].filter((node) => {
        const box = node.getBoundingClientRect();
        return box.top >= viewportTop && box.bottom <= viewportBottom;
      }).length,
    };
    const nodes = [...graph.querySelectorAll<HTMLElement>("[data-guidance-node]")].map((node) => {
      const box = node.getBoundingClientRect();
      return { id: node.dataset["guidanceNode"], x: box.x - graphBox.x, y: box.y - graphBox.y, width: box.width, height: box.height };
    });
    const crossings: string[] = [];
    for (const path of graph.querySelectorAll<SVGPathElement>("path[data-guidance-edge]")) {
      const length = path.getTotalLength();
      for (let distance = 3; distance < length - 3; distance += 3) {
        const point = path.getPointAtLength(distance);
        for (const node of nodes) {
          if (point.x > node.x + 2 && point.x < node.x + node.width - 2 && point.y > node.y + 2 && point.y < node.y + node.height - 2) {
            crossings.push(node.id ?? "unknown");
          }
        }
      }
    }
    const clipped = [...figure.querySelectorAll<HTMLElement>("p, strong")].filter((element) => element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1).map((element) => element.tagName);
    const surfaces = [document.documentElement, drawer, drawer.querySelector<HTMLElement>(".rule-drawer-body")!, figure, graph].map((element) => ({ className: element.className, scrollWidth: element.scrollWidth, clientWidth: element.clientWidth }));
    const luminance = (color: string) => {
      const channels = color.match(/[\d.]+/g)!.slice(0, 3).map((part) => {
        const channel = Number(part) / 255;
        return channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4;
      });
      return channels[0]! * .2126 + channels[1]! * .7152 + channels[2]! * .0722;
    };
    const contrast = (foreground: string, background: string) => {
      const a = luminance(foreground), b = luminance(background);
      return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
    };
    const nodeStyle = getComputedStyle(graph.querySelector(".wara-guidance-node")!);
    const figureStyle = getComputedStyle(figure);
    const contrastRatios = {
      body: contrast(figureStyle.color, figureStyle.backgroundColor),
      nodeLabel: contrast(nodeStyle.color, nodeStyle.backgroundColor),
      nodeRole: contrast(getComputedStyle(graph.querySelector(".wara-guidance-node-role")!).color, nodeStyle.backgroundColor),
      nodeBoundary: contrast(nodeStyle.borderColor, nodeStyle.backgroundColor),
      arrows: contrast(getComputedStyle(graph.querySelector("svg")!).color, figureStyle.backgroundColor),
    };
    return { nodes, crossings: [...new Set(crossings)], clipped, surfaces, contrastRatios, hero, width: graph.clientWidth, height: graph.clientHeight };
  });
}

test("illustrates three public pilots in English and Korean, desktop before responsive (isolated fixtures)", async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const controls = waraPilotControls();
  await installFixture(page, controls);
  const measurements: unknown[] = [];
  for (const viewport of [{ width: 1440, height: 900 }, { width: 993, height: 641 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    for (const locale of ["en", "ko"] as const) {
      for (const [index, control] of controls.entries()) {
        const guidance = control.guidance!;
        await page.goto(`/rules?view=controls&framework=azure-wara&locale=${locale}&recommendation=${control.id}&impact=Medium`);
        const drawer = page.getByRole("dialog");
        await expect(drawer.getByRole("heading", { name: guidanceText(guidance.title, locale), exact: true })).toBeVisible();
        await expect(drawer.getByText(locale === "ko" ? "핵심 설명" : "Key explanation", { exact: true })).toBeVisible();
        await expect(drawer.locator(".wara-guidance-unavailable")).toHaveCount(0);
        const figure = drawer.locator("figure");
        await expect(figure.locator("[data-guidance-edge]")).toHaveCount(guidance.diagram.edges.length);
        const hero = (await measure(page)).hero;
        if (viewport.width === 1440) {
          expect(hero.figureTop).toBeLessThanOrEqual(360);
          expect(hero.visibleGraphFraction).toBeGreaterThanOrEqual(.75);
          expect(hero.visibleNodes).toBeGreaterThanOrEqual(Math.ceil(guidance.diagram.nodes.length * .75));
          await page.screenshot({ animations: "disabled", path: testInfo.outputPath(`synthetic-pilot-${index}-${locale}-hero.png`) });
        }
        await figure.evaluate((element) => element.scrollIntoView({ block: "start", behavior: "instant" }));
        await expect(figure).toBeVisible();
        await expect(figure.locator("[data-guidance-node]")).toHaveCount(guidance.diagram.nodes.length);
        await expect(figure.locator("[data-guidance-edge]")).toHaveCount(guidance.diagram.edges.length);
        await expect(figure.locator("[marker-end]")).toHaveCount(guidance.diagram.edges.length);
        await expect(figure.locator("figcaption")).toContainText(guidanceText(guidance.diagram.description, locale));
        if (index === 2) {
          expect(guidance.diagram.nodes.length).toBeGreaterThanOrEqual(5);
          await expect(figure.locator('[data-guidance-edge="dashed"]')).not.toHaveCount(0);
        }
        await expect.poll(async () => (await measure(page)).surfaces.every((surface) => surface.scrollWidth <= surface.clientWidth)).toBe(true);
        const measured = await measure(page);
        expect(measured.clipped).toEqual([]);
        expect(measured.crossings).toEqual([]);
        for (const key of ["body", "nodeLabel", "nodeRole"] as const) expect(measured.contrastRatios[key]).toBeGreaterThanOrEqual(4.5);
        for (const key of ["nodeBoundary", "arrows"] as const) expect(measured.contrastRatios[key]).toBeGreaterThanOrEqual(3);
        expect(measured.height).toBeGreaterThan(100);
        if (viewport.width === 1440) {
          expect(measured.hero.figureTop).toBeGreaterThanOrEqual(measured.hero.viewportTop - 1);
          expect(measured.hero.figureBottom).toBeLessThanOrEqual(measured.hero.viewportBottom + 1);
          expect(measured.hero.figureHeight).toBeLessThanOrEqual(measured.hero.availableHeight);
        }
        measurements.push({ viewport, locale, pilot: index, mode: "installed-public-catalog-with-synthetic-assessment", contentDigest: guidance.content_digest, initialHero: hero, ...measured });
        const links = await drawer.locator(".wara-guidance-sources a").evaluateAll((anchors) => anchors.map((anchor) => (anchor as HTMLAnchorElement).href));
        expect(links).toEqual(guidance.sources.map((source) => source.url));
        expect(links.some((url) => url.includes(control.source_revision))).toBe(true);
        await page.screenshot({ animations: "disabled", path: testInfo.outputPath(`synthetic-pilot-${index}-${locale}-${viewport.width}.png`) });
        const relationships = drawer.locator(".wara-guidance-relationships");
        await expect(relationships).not.toHaveAttribute("open");
        await relationships.locator("summary").focus();
        await page.keyboard.press("Enter");
        await expect(relationships.locator("li")).toHaveCount(guidance.diagram.edges.length);
        for (const edge of guidance.diagram.edges) await expect(relationships).toContainText(guidanceText(edge.label, locale));
        await page.keyboard.press("Enter");

        if (viewport.width === 1440) {
          const expand = figure.getByRole("button");
          const before = await drawer.boundingBox();
          await expand.focus();
          await page.keyboard.press("Enter");
          await expect(expand).toHaveAttribute("aria-pressed", "true");
          expect((await drawer.boundingBox())!.width).toBeGreaterThan(before!.width);
          await expect.poll(async () => (await measure(page)).surfaces.every((surface) => surface.scrollWidth <= surface.clientWidth)).toBe(true);
          await figure.evaluate((element) => element.scrollIntoView({ block: "start", behavior: "instant" }));
          const expandedFigure = (await measure(page)).hero;
          expect(expandedFigure.figureTop).toBeGreaterThanOrEqual(expandedFigure.viewportTop - 1);
          expect(expandedFigure.figureBottom).toBeLessThanOrEqual(expandedFigure.viewportBottom + 1);
          await page.screenshot({ animations: "disabled", path: testInfo.outputPath(`synthetic-pilot-${index}-${locale}-expanded.png`) });
          await page.keyboard.press("Enter");
          await expect(expand).toHaveAttribute("aria-pressed", "false");
        }
        const technical = drawer.locator(".wara-technical > summary");
        await technical.focus();
        await page.keyboard.press("Enter");
        await expect(drawer.locator(".wara-technical")).toContainText(control.source_digest);
        await expect(drawer.locator(".wara-technical")).toContainText(control.source_version);
        if (index === 1) {
          await expect(drawer.locator(".wara-technical")).toContainText("Medium");
          await expect(drawer.locator(".wara-guidance-comparison tbody tr")).toHaveCount(3);
          await expect(drawer.locator(".wara-guidance-comparison")).toContainText(/Host|호스트/);
          await expect(drawer.locator(".wara-guidance-comparison")).toContainText(/OS\s?(?:image|이미지)|OSImage/);
          await expect(drawer.locator(".wara-guidance-comparison")).toContainText(/Guest|게스트/);
          await expect(drawer.locator(".wara-runtime")).toContainText(locale === "ko" ? "차단됨" : "Blocked");
        }
        await page.keyboard.press("Escape");
        await expect(drawer).toHaveCount(0);
        expect(new URL(page.url()).searchParams.get("impact")).toBe("Medium");
      }
    }
  }
  const measurementPath = testInfo.outputPath("synthetic-guidance-geometry.json");
  writeFileSync(measurementPath, JSON.stringify(measurements, null, 2));
  await testInfo.attach("synthetic-guidance-geometry", { path: measurementPath, contentType: "application/json" });
});

test("missing guidance preserves base explanation; malformed or mismatched assets visibly fail", async ({ page }) => {
  const controls = waraPilotControls();
  const control = controls[0]!;
  await installFixture(page, controls, (item) => ({ ...item, guidance: null }));
  await page.goto(`/rules?view=controls&framework=azure-wara&recommendation=${control.id}`);
  const drawer = page.getByRole("dialog");
  await expect(drawer).toHaveCSS("animation-name", "none");
  await expect(drawer).toHaveCSS("opacity", "1");
  await expect(drawer.locator(".wara-guidance-unavailable")).toContainText("not yet available");
  await expect(drawer).toContainText(control.description!);
  await expect(drawer.locator("figure")).toHaveCount(0);
  await page.unrouteAll({ behavior: "wait" });
  for (const patch of [
    { schema_version: "2.0.0" },
    { recommendation_id: controls[1]!.id },
    { diagram: { ...control.guidance!.diagram, url: "https://example.test/untrusted.svg" } },
    { title: { en: "Tampered illustrated material" } },
  ]) {
    await installFixture(page, controls, (item) => ({ ...item, guidance: { ...item.guidance, ...patch } }));
    await page.reload();
    await expect(drawer.getByRole("alert")).toBeVisible();
    await expect(drawer.getByRole("alert")).toContainText("WARA guidance");
    await expect(drawer.locator("figure")).toHaveCount(0);
    await page.unrouteAll({ behavior: "wait" });
  }
});

test("supports keyboard return, readable print, enlarged text, and narrow reflow (isolated fixture)", async ({ page }, testInfo) => {
  const controls = waraPilotControls();
  await installFixture(page, controls);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/rules?view=controls&framework=azure-wara&impact=Medium");
  const row = page.locator(".wara-controls-view .data-table tbody button").last();
  await row.focus();
  await page.keyboard.press("Enter");
  const drawer = page.getByRole("dialog");
  await expect(drawer.locator("figure")).toBeVisible();
  const close = drawer.getByRole("button", { name: "Close", exact: true });
  await close.focus();
  await page.keyboard.press("Shift+Tab");
  await expect(drawer.locator(".wara-technical > summary")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(close).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(row).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(drawer.locator("figure")).toBeVisible();
  await page.emulateMedia({ media: "print" });
  await expect.poll(async () => (await measure(page)).crossings).toEqual([]);
  const print = await drawer.evaluate((element) => {
    const figure = element.querySelector<HTMLElement>("figure")!;
    return { drawerHeight: element.clientHeight, bodyHeight: element.querySelector<HTMLElement>(".rule-drawer-body")!.clientHeight, breakInside: getComputedStyle(figure).breakInside, overflow: getComputedStyle(element.querySelector(".rule-drawer-body")!).overflowY };
  });
  expect(print.drawerHeight).toBeGreaterThan(900);
  expect(print.bodyHeight).toBeGreaterThan(900);
  expect(print.breakInside).toBe("avoid");
  expect(print.overflow).toBe("visible");
  const printPath = testInfo.outputPath("print-geometry.json");
  writeFileSync(printPath, JSON.stringify(print));
  await testInfo.attach("print-geometry", { path: printPath, contentType: "application/json" });
  await page.emulateMedia({ media: "screen", reducedMotion: "reduce" });
  await page.addStyleTag({ content: `
    :root { --cs-type-page-title-size: 48px; --cs-type-section-title-size: 36px; --cs-type-panel-title-size: 30px; --cs-type-lead-size: 32px; --cs-type-body-size: 28px; --cs-type-compact-size: 26px; --cs-type-label-size: 24px; }
    .wara-guidance-content p, .wara-guidance-content li { line-height: 1.5; letter-spacing: .12em; word-spacing: .16em; }
    .wara-guidance-content p { margin-bottom: 2em; }
  ` });
  await expect.poll(async () => (await measure(page)).clipped).toEqual([]);
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    await expect.poll(async () => (await measure(page)).surfaces.every((surface) => surface.scrollWidth <= surface.clientWidth)).toBe(true);
    expect((await measure(page)).clipped).toEqual([]);
  }
});

test("smokes all 456 installed guides across all 45 diagram families on desktop (English isolated fixtures)", async ({ page }, testInfo) => {
  test.setTimeout(240_000);
  const controls = waraCorpusControls();
  expect(controls).toHaveLength(456);
  expect(new Set(controls.map((control) => control.guidance!.diagram.kind)).size).toBe(45);
  await installFixture(page, controls);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/rules?view=controls&framework=azure-wara&locale=en");
  await expect(page.locator(".wara-controls-view .data-table")).toBeVisible();
  const rows: unknown[] = [];
  const families = new Set<string>();
  let disabled = 0;
  try {
    for (const [index, control] of controls.entries()) {
      await page.evaluate((id) => {
        const url = new URL(location.href);
        url.searchParams.set("recommendation", id);
        history.replaceState(null, "", url);
        dispatchEvent(new PopStateEvent("popstate"));
      }, control.id);
      const drawer = page.getByRole("dialog");
      await expect(drawer.locator(".wara-guidance-content")).toHaveAttribute("data-recommendation-id", control.id);
      await expect(drawer.locator("h2")).toHaveText(control.guidance!.title.en);
      await expect(drawer.getByRole("alert")).toHaveCount(0);
      await expect(drawer.locator(".wara-guidance-unavailable")).toHaveCount(0);
      await expect(drawer.locator(".wara-guidance-history")).toHaveCount(control.lifecycle === "disabled" ? 1 : 0);
      if (control.lifecycle === "disabled") {
        disabled += 1;
        await expect(drawer.locator(".wara-guidance-history")).toContainText("catalog history only");
      }
      const figure = drawer.locator("figure");
      await expect(figure.locator("[data-guidance-edge]")).toHaveCount(control.guidance!.diagram.edges.length);
      await figure.evaluate((element) => element.scrollIntoView({ block: "start", behavior: "instant" }));
      const geometry = await measure(page);
      expect(geometry.surfaces.every((surface) => surface.scrollWidth <= surface.clientWidth), control.id).toBe(true);
      expect(geometry.clipped, control.id).toEqual([]);
      expect(geometry.crossings, control.id).toEqual([]);
      expect(geometry.hero.figureHeight, control.id).toBeLessThanOrEqual(geometry.hero.availableHeight);
      const clippedText = await drawer.locator(".wara-guidance-content").evaluate((root) =>
        [...root.querySelectorAll<HTMLElement>("p, li, th, td, h2, strong")]
          .filter((element) => element.checkVisibility() && element.scrollWidth > element.clientWidth + 1)
          .map((element) => element.tagName),
      );
      expect(clippedText, control.id).toEqual([]);
      const kind = control.guidance!.diagram.kind;
      if (!families.has(kind)) {
        await page.screenshot({ animations: "disabled", path: testInfo.outputPath(`synthetic-family-${kind}.png`) });
        families.add(kind);
      }
      rows.push({ id: control.id, kind, lifecycle: control.lifecycle, contentDigest: control.guidance!.content_digest, ...geometry });
      if ((index + 1) % 32 === 0) console.info(`WARA desktop smoke: ${index + 1}/456; ${families.size}/45 families`);
    }
    expect(rows).toHaveLength(456);
    expect(disabled).toBe(63);
    expect(families.size).toBe(45);
  } finally {
    const path = testInfo.outputPath("full-corpus-desktop-smoke.json");
    writeFileSync(path, JSON.stringify({
      scope: "English desktop automated geometry/contract smoke; not a human visual review of all items",
      viewport: { width: 1440, height: 900 }, completed: rows.length, requested: 456,
      families: [...families], disabledHistoryChecked: disabled, rows,
    }, null, 2));
    await testInfo.attach("full-corpus-desktop-smoke", { path, contentType: "application/json" });
  }
});

test("keeps complete long node explanations visible outside a steady primary figure (synthetic fixture)", async ({ page }, testInfo) => {
  const control = waraPilotControls()[2]!;
  const original = control.guidance!.diagram.nodes[0]!;
  const detail = "Every qualification needs independent verification. This deliberately long fixture is not runtime evidence. ".repeat(12);
  const guidance = signFixtureGuidance({
    ...control.guidance!,
    diagram: {
      ...control.guidance!.diagram,
      nodes: control.guidance!.diagram.nodes.map((node) => node.id === original.id ? { ...node, detail: { en: detail } } : node),
    },
  });
  await installFixture(page, [{ ...control, guidance }]);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/rules?view=controls&framework=azure-wara&locale=en&recommendation=${control.id}`);
  const drawer = page.getByRole("dialog");
  await expect(drawer.locator("[data-guidance-edge]")).toHaveCount(guidance.diagram.edges.length);
  await expect(drawer).toHaveCSS("animation-name", "none");
  await expect(drawer).toHaveCSS("opacity", "1");
  const explanation = drawer.locator(`[data-guidance-explanation="${original.id}"]`);
  await expect(explanation).toHaveText(detail);
  await expect(explanation).toBeVisible();
  const figure = drawer.locator("figure");
  await figure.evaluate((element) => element.scrollIntoView({ block: "start", behavior: "instant" }));
  const before = await measure(page);
  expect(before.hero.figureHeight).toBeLessThanOrEqual(before.hero.availableHeight);
  const node = figure.locator(`[data-guidance-node="${original.id}"]`);
  await expect(node.locator("strong")).toHaveCSS("font-size", "15px");
  await expect(node.locator("p")).toHaveCSS("font-size", "13px");
  await page.screenshot({ animations: "disabled", path: testInfo.outputPath("synthetic-long-detail-steady-figure.png") });
  await node.getByRole("button", { name: "Read full explanation", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(explanation).toBeFocused();
  expect((await measure(page)).hero.figureHeight).toBeCloseTo(before.hero.figureHeight, 1);
});
