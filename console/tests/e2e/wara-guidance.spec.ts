import { writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";
import type { WaraControl } from "../../src/routes/wara-controls.model";
import { guidanceText, type GuidanceReferenceImage } from "../../src/routes/wara-guidance.model";
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
    const edgeNumbers = [...graph.querySelectorAll<SVGTextElement>(".wara-guidance-edge-number")].map((label) => {
      const box = label.getBBox();
      return { text: label.textContent, x: box.x, y: box.y, width: box.width, height: box.height };
    });
    const obscuredEdgeNumbers = edgeNumbers.filter((label) => nodes.some((node) =>
      label.x < node.x + node.width && label.x + label.width > node.x
      && label.y < node.y + node.height && label.y + label.height > node.y,
    )).map((label) => label.text);
    const overlappingEdgeNumbers = edgeNumbers.flatMap((label, index) => edgeNumbers.slice(index + 1).filter((other) =>
      label.x < other.x + other.width && label.x + label.width > other.x
      && label.y < other.y + other.height && label.y + label.height > other.y,
    ).map((other) => `${label.text}/${other.text}`));
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
    const edgeNumberStyle = getComputedStyle(graph.querySelector(".wara-guidance-edge-number")!);
    const figureStyle = getComputedStyle(figure);
    const contrastRatios = {
      body: contrast(figureStyle.color, figureStyle.backgroundColor),
      nodeLabel: contrast(nodeStyle.color, nodeStyle.backgroundColor),
      nodeRole: contrast(getComputedStyle(graph.querySelector(".wara-guidance-node-role")!).color, nodeStyle.backgroundColor),
      edgeNumber: contrast(edgeNumberStyle.fill, edgeNumberStyle.stroke),
      nodeBoundary: contrast(nodeStyle.borderColor, nodeStyle.backgroundColor),
      arrows: contrast(getComputedStyle(graph.querySelector("svg")!).color, figureStyle.backgroundColor),
    };
    return { nodes, crossings: [...new Set(crossings)], clipped, edgeNumbers, obscuredEdgeNumbers, overlappingEdgeNumbers, surfaces, contrastRatios, hero, width: graph.clientWidth, height: graph.clientHeight };
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
        await expect(drawer.locator(".wara-guidance-lead")).toHaveText(guidanceText(guidance.summary, locale));
        await expect(drawer.locator(".wara-guidance-unavailable")).toHaveCount(0);
        const figure = drawer.locator(".wara-guidance-figure");
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
        expect(measured.edgeNumbers).toHaveLength(guidance.diagram.edges.length);
        expect(measured.obscuredEdgeNumbers).toEqual([]);
        expect(measured.overlappingEdgeNumbers).toEqual([]);
        for (const key of ["body", "nodeLabel", "nodeRole", "edgeNumber"] as const) expect(measured.contrastRatios[key]).toBeGreaterThanOrEqual(4.5);
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
        await expect(relationships).toHaveAttribute("open");
        await relationships.locator("summary").focus();
        await page.keyboard.press("Enter");
        await expect(relationships).not.toHaveAttribute("open");
        await page.keyboard.press("Enter");
        await expect(relationships).toHaveAttribute("open");
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

for (const locale of ["en", "ko"] as const) test(`smokes all 456 installed guides across all 45 diagram families on desktop (${locale} isolated fixtures)`, async ({ page }, testInfo) => {
  test.setTimeout(240_000);
  const controls = waraCorpusControls();
  expect(controls).toHaveLength(456);
  expect(new Set(controls.map((control) => control.guidance!.diagram.kind)).size).toBe(45);
  await installFixture(page, controls);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/rules?view=controls&framework=azure-wara&locale=${locale}`);
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
      await expect(drawer.locator("h2")).toHaveText(guidanceText(control.guidance!.title, locale));
      await expect(drawer.getByRole("alert")).toHaveCount(0);
      await expect(drawer.locator(".wara-guidance-unavailable")).toHaveCount(0);
      await expect(drawer.locator(".wara-guidance-history")).toHaveCount(control.lifecycle === "disabled" ? 1 : 0);
      if (control.lifecycle === "disabled") {
        disabled += 1;
        await expect(drawer.locator(".wara-guidance-history")).toContainText(locale === "ko" ? "카탈로그 이력" : "catalog history only");
      }
      if (control.guidance!.reference_image) {
        const supplement = drawer.locator(".wara-guidance-supplement");
        await supplement.locator(":scope > summary").click();
        await expect(supplement).toHaveAttribute("open");
      }
      const figure = drawer.locator(".wara-guidance-figure");
      await expect(figure.locator("[data-guidance-edge]")).toHaveCount(control.guidance!.diagram.edges.length);
      await figure.evaluate((element) => element.scrollIntoView({ block: "start", behavior: "instant" }));
      const geometry = await measure(page);
      expect(geometry.surfaces.every((surface) => surface.scrollWidth <= surface.clientWidth), control.id).toBe(true);
      expect(geometry.clipped, control.id).toEqual([]);
      expect(geometry.crossings, control.id).toEqual([]);
      expect(geometry.edgeNumbers).toHaveLength(control.guidance!.diagram.edges.length);
      expect(geometry.obscuredEdgeNumbers, control.id).toEqual([]);
      expect(geometry.overlappingEdgeNumbers, control.id).toEqual([]);
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
      rows.push({ id: control.id, locale, kind, lifecycle: control.lifecycle, contentDigest: control.guidance!.content_digest, ...geometry });
      if ((index + 1) % 32 === 0) console.info(`WARA desktop smoke: ${index + 1}/456; ${families.size}/45 families`);
    }
    expect(rows).toHaveLength(456);
    expect(disabled).toBe(63);
    expect(families.size).toBe(45);
  } finally {
    const path = testInfo.outputPath("full-corpus-desktop-smoke.json");
    writeFileSync(path, JSON.stringify({
      scope: `${locale} desktop automated geometry/contract smoke; not a human visual review of all items`,
      viewport: { width: 1440, height: 900 }, completed: rows.length, requested: 456,
      families: [...families], disabledHistoryChecked: disabled, rows,
    }, null, 2));
    await testInfo.attach("full-corpus-desktop-smoke", { path, contentType: "application/json" });
  }
});

test("serves the packaged official VM backup image without a remote image request", async ({ page }, testInfo) => {
  const control = waraCorpusControls().find((item) => item.title === "Backup VMs with Azure Backup service")!;
  const image = control.guidance!.reference_image!;
  expect(image).toBeDefined();
  await installFixture(page, [control]);
  const externalImages: string[] = [];
  page.on("request", (request) => {
    if (request.resourceType() === "image" && !["localhost", "127.0.0.1"].includes(new URL(request.url()).hostname)) externalImages.push(request.url());
  });
  for (const viewport of [{ width: 1440, height: 900 }, { width: 993, height: 641 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    for (const locale of ["en", "ko"] as const) {
      const [response] = await Promise.all([
        page.waitForResponse((response) => response.url().endsWith(`/wara-guidance-assets/${image.asset_id}.png`)),
        page.goto(`/rules?view=controls&framework=azure-wara&locale=${locale}&recommendation=${control.id}`),
      ]);
      expect(response.ok()).toBe(true);
      expect(response.headers()["content-type"]).toContain("image/png");
      expect(`sha256:${createHash("sha256").update(await response.body()).digest("hex")}`).toBe(image.digest);
      const figure = page.locator(".wara-guidance-source-figure");
      const picture = figure.getByRole("img", { name: guidanceText(image.alt, locale), exact: true });
      await expect(picture).toBeVisible();
      expect(await picture.evaluate((element) => ({ width: (element as HTMLImageElement).naturalWidth, height: (element as HTMLImageElement).naturalHeight }))).toEqual({ width: 898, height: 400 });
      await expect(figure.locator("header a")).toHaveAttribute("href", image.source_document_url);
      await expect(figure).toContainText(guidanceText(image.caption, locale));
      expect(await figure.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
      const rights = figure.locator(".wara-guidance-image-rights");
      await expect(rights).not.toHaveAttribute("open");
      await rights.locator("summary").click();
      await expect(rights).toContainText(image.attribution);
      await rights.locator("summary").click();
      const enlarge = figure.getByRole("button", { name: locale === "ko" ? "이미지 확대" : "Enlarge image", exact: true });
      await enlarge.focus();
      await page.keyboard.press("Enter");
      const preview = page.locator("dialog.wara-guidance-image-preview");
      await expect(preview).toBeVisible();
      await expect(preview.getByRole("img")).toBeVisible();
      expect(await preview.locator("img").evaluate((element) => element.getBoundingClientRect().width)).toBe(898);
      const pan = preview.locator(".wara-guidance-image-viewport");
      if (viewport.width === 390) {
        expect(await pan.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);
        await pan.focus();
        await page.keyboard.press("ArrowRight");
        await expect.poll(() => pan.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0);
      }
      await page.screenshot({ animations: "disabled", path: testInfo.outputPath(`official-backup-expanded-${locale}-${viewport.width}.png`) });
      await page.keyboard.press("Escape");
      await expect(preview).not.toBeVisible();
      await expect(enlarge).toBeFocused();
      await expect(page.locator("#wara-control-detail")).toBeVisible();
      const procedureBounds = await page.locator(".wara-guidance-procedures > section").evaluateAll((sections) => sections.map((section) => ({ top: section.getBoundingClientRect().top, bottom: section.getBoundingClientRect().bottom })));
      const [implementation, verification] = procedureBounds;
      if (!implementation || !verification) throw new Error("Missing implementation or verification section");
      if (viewport.width <= 993) expect(verification.top).toBeGreaterThanOrEqual(implementation.bottom);
      await figure.scrollIntoViewIfNeeded();
      await page.screenshot({ animations: "disabled", path: testInfo.outputPath(`official-backup-${locale}-${viewport.width}.png`) });
      const supplement = page.locator(".wara-guidance-supplement");
      await supplement.locator(":scope > summary").click();
      await expect(supplement).toHaveAttribute("open");
      await expect.poll(async () => (await measure(page)).crossings).toEqual([]);
      expect((await measure(page)).surfaces.every((surface) => surface.scrollWidth <= surface.clientWidth)).toBe(true);
    }
  }
  expect(externalImages).toEqual([]);
  await expect(page.locator(".wara-guidance-image-print-attribution")).not.toBeVisible();
  await page.emulateMedia({ media: "print" });
  await expect(page.locator(".wara-guidance-image-print-attribution")).toBeVisible();
  await expect(page.locator(".wara-guidance-image-print-attribution")).toHaveText(image.attribution);
  await expect(page.locator(".wara-guidance-image-actions button")).not.toBeVisible();
  await page.emulateMedia({ media: "screen" });
});

test("renders attributed images and explicit asset failures (synthetic transport fixture, not approved Microsoft artwork)", async ({ page }, testInfo) => {
  const control = waraCorpusControls().find((item) => item.title === "Backup VMs with Azure Backup service");
  expect(control).toBeDefined();
  const png = Buffer.from(await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 720;
    canvas.height = 240;
    const context = canvas.getContext("2d")!;
    context.fillStyle = "#eef2f6";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = "#25364a";
    context.font = "24px sans-serif";
    context.fillText("Synthetic image transport fixture", 32, 96);
    context.fillText("No Microsoft artwork is bundled.", 32, 144);
    return canvas.toDataURL("image/png").split(",")[1]!;
  }), "base64");
  const digest = createHash("sha256").update(png).digest("hex");
  const image: GuidanceReferenceImage = {
    asset_id: `sha256-${digest}`,
    digest: `sha256:${digest}`,
    source_document_url: "https://learn.microsoft.com/en-us/azure/backup/backup-azure-vms-introduction",
    image_url: "https://learn.microsoft.com/en-us/azure/backup/media/synthetic-reference-image.png",
    source_revision: "a".repeat(40),
    attribution: "Synthetic fixture only; no Microsoft image is bundled.",
    license: "CC-BY-4.0",
    license_url: "https://creativecommons.org/licenses/by/4.0/",
    alt: { en: "Synthetic image transport fixture", ko: "이미지 전송 검증용 합성 자료" },
    caption: { en: "Synthetic fixture, not Microsoft artwork.", ko: "Microsoft 그림이 아닌 합성 검증 자료입니다." },
    english_in_image_notice: { en: "Fixture labels are English.", ko: "검증용 그림의 표시는 영어입니다." },
  };
  await installFixture(page, [{ ...control!, guidance: signFixtureGuidance({ ...control!.guidance!, reference_image: image }) }]);
  const path = `/wara-guidance-assets/${image.asset_id}.png`;
  await page.route(`**${path}`, (route) => route.fulfill({ contentType: "image/png", body: png }));
  for (const viewport of [{ width: 1440, height: 900 }, { width: 993, height: 641 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    for (const locale of ["en", "ko"] as const) {
      const [response] = await Promise.all([
        page.waitForResponse((response) => response.url().endsWith(path)),
        page.goto(`/rules?view=controls&framework=azure-wara&locale=${locale}&recommendation=${control!.id}`),
      ]);
      expect(response.ok()).toBe(true);
      expect(response.headers()["content-type"]).toContain("image/png");
      expect(`sha256:${createHash("sha256").update(await response.body()).digest("hex")}`).toBe(image.digest);
      const figure = page.locator(".wara-guidance-source-figure");
      const picture = figure.getByRole("img", { name: guidanceText(image!.alt, locale), exact: true });
      await expect(picture).toBeVisible();
      await expect.poll(() => picture.evaluate((element) => (element as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
      await expect(figure).toContainText(guidanceText(image!.caption, locale));
      await expect(figure).toContainText(guidanceText(image!.english_in_image_notice, locale));
      await expect(figure).toContainText(image!.attribution);
      const originalDocument = figure.locator("header a");
      await expect(originalDocument).toHaveAttribute("href", image.source_document_url);
      await expect(originalDocument).toHaveText(locale === "ko" ? "원본 문서 열기" : "Open original document");
      await expect(figure.locator(`a[href="${path}"], a[href="${image.image_url}"]`)).toHaveCount(0);
      await expect(figure.locator(`figcaption a[href="${image!.license_url}"]`)).toHaveText("CC-BY-4.0");
      await expect(page.locator(".wara-guidance-supplement")).not.toHaveAttribute("open");
      expect(await figure.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
      await figure.scrollIntoViewIfNeeded();
      await page.screenshot({ animations: "disabled", path: testInfo.outputPath(`synthetic-image-${locale}-${viewport.width}.png`) });
      const supplement = page.locator(".wara-guidance-supplement");
      await supplement.locator(":scope > summary").focus();
      await page.keyboard.press("Enter");
      await expect(supplement).toHaveAttribute("open");
      await expect(page.locator("[data-guidance-edge]")).toHaveCount(control!.guidance!.diagram.edges.length);
      const geometry = await measure(page);
      expect(geometry.crossings).toEqual([]);
      expect(geometry.obscuredEdgeNumbers).toEqual([]);
      expect(geometry.surfaces.every((surface) => surface.scrollWidth <= surface.clientWidth)).toBe(true);
    }
  }
  await page.route(`**${path}`, (route) => route.fulfill({ status: 404 }));
  await page.reload();
  await expect(page.locator(".wara-guidance-source-figure").getByRole("alert")).toBeVisible();
  await expect(page.locator(".wara-guidance-source-figure")).toContainText(guidanceText(image!.alt, "ko"));
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
  const figure = drawer.locator(".wara-guidance-figure");
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
