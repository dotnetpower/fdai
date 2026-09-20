import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const require = createRequire(join(root, "console/package.json"));
const { chromium } = require("playwright");
const origin = "http://127.0.0.1:5373";
const output = join(root, ".fdai/visual-review/lineage");
const evidence = [];
const errors = [];
const inputPaths = ["index.html", "ui/calm-slate-tokens.css", "ui/calm-slate-primitives.css", "console/package-lock.json", "mocks/ui/lineage.html", "mocks/ui/assets/calm-slate.css", "mocks/ui/assets/calm-slate.js", "mocks/ui/assets/lineage.css", "mocks/ui/assets/lineage.js", "mocks/ui/assets/lineage-ontology.js", "mocks/ui/assets/lineage-icons.js", "mocks/ui/tests/lineage.test.mjs"];
const inputHashes = async () => Object.fromEntries(await Promise.all(inputPaths.map(async path => [path, createHash("sha256").update(await readFile(join(root, path))).digest("hex")])));
const inputsBefore = await inputHashes();
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

async function assertClearCurves(frame) {
  const collisions = await frame.evaluate(() => {
    const nodes = [...document.querySelectorAll(".ln-node")];
    return [...document.querySelectorAll(".ln-edge")].flatMap(path => {
      const collisions = new Set();
      for (let distance = 0; distance <= path.getTotalLength(); distance += 2) {
        const point = path.getPointAtLength(distance);
        nodes.filter(node => ![path.dataset.from, path.dataset.to].includes(node.dataset.node)).forEach(node => {
          if (point.x > node.offsetLeft && point.x < node.offsetLeft + node.offsetWidth && point.y > node.offsetTop && point.y < node.offsetTop + node.offsetHeight) collisions.add(node.dataset.node);
        });
      }
      return [...collisions].map(node => `${path.dataset.from} -> ${path.dataset.to} crosses ${node}`);
    });
  });
  assert.deepEqual(collisions, [], "curves must not pass through unrelated nodes");
}

try {
  const started = performance.now();
  await page.goto(`${origin}/#mocks/ui/lineage.html`, { waitUntil: "load" });
  await page.waitForFunction(() => {
    const frame = document.querySelector("#preview-frame");
    return frame?.contentWindow.location.pathname === "/mocks/ui/lineage.html" &&
      frame.contentDocument?.querySelector('[data-node="forseti"]');
  });
  let frame = await (await page.locator("#preview-frame").elementHandle()).contentFrame();
  await frame.locator('[data-node="forseti"]').waitFor();
  const loadMs = performance.now() - started;
  assert.ok(loadMs < 5000, `initial local render ${loadMs}ms exceeds 5s budget`);
  assert.equal(await frame.locator(".ln-node").count(), 38);
  assert.equal(await frame.locator('[data-kind="ontology"]').count(), 8);
  assert.equal(await frame.locator('[data-kind="resource-group"]').count(), 10);
  assert.equal(await frame.locator('[data-kind="type"]').count(), 3);
  assert.equal(await frame.locator('[data-relation="example instance"]').count(), 8);
  const fit = await frame.locator("#lineageViewport").evaluate(element => ({ width: element.clientWidth, height: element.clientHeight, scrollWidth: element.scrollWidth, scrollHeight: element.scrollHeight }));
  assert.ok(fit.scrollWidth <= fit.width + 1 && fit.scrollHeight <= fit.height + 1, "default camera must fit the entire graph");
  await page.screenshot({ path: join(output, "overview.png"), fullPage: true });
  const ontology = await frame.evaluate(() => window.fdaiLineageOntology);
  const aggregation = await frame.evaluate(() => {
    const { nodes, edges, buildResourceTypeGraph } = window.fdaiLineageOntology;
    const original = JSON.stringify({ nodes, edges });
    const collapsed = buildResourceTypeGraph(nodes, edges);
    const pods = collapsed.groups.find(group => group.resourceType === "kubernetes.pod");
    const otherScope = { ...nodes.find(node => node.id === "pod-resource"), id: "other-scope-pod", scope: "example-other-subscription / example-other-cluster" };
    const scoped = buildResourceTypeGraph([...nodes, otherScope], edges);
    const expectedEdges = edges.filter(([from, to, relation]) => !(from === "resource-type" && collapsed.membership.has(to) && relation === "example instance"));
    return {
      inputUnchanged: original === JSON.stringify({ nodes, edges }),
      resources: collapsed.groups.reduce((sum, group) => sum + group.members.length, 0),
      health: pods.health,
      scopedPods: scoped.groups.filter(group => group.resourceType === "kubernetes.pod").map(group => ({ scope: group.scope, count: group.members.length })),
      expected: expectedEdges.map(edge => JSON.stringify(edge)).sort(),
      preserved: collapsed.edges.flatMap(edge => edge[3]).map(edge => JSON.stringify(edge)).sort(),
    };
  });
  assert.equal(aggregation.inputUnchanged, true);
  assert.equal(aggregation.resources, 16);
  assert.deepEqual(aggregation.health, { current: 1, stale: 1, conflicting: 0, unknown: 1 });
  assert.equal(aggregation.scopedPods.length, 2);
  assert.deepEqual(aggregation.scopedPods.map(group => group.count), [3, 1]);
  assert.deepEqual(aggregation.preserved, aggregation.expected);
  evidence.push({ name: "Scope isolation, honest state counts and lossless original relationship references", disposition: "passed", aggregation });
  assert.equal(new Set(ontology.nodes.map(node => node.id)).size, ontology.nodes.length);
  const types = ontology.nodes.filter(node => node.kind === "type");
  assert.deepEqual(types.map(node => node.title), ["Resource", "Observation", "Rule"]);
  types.forEach(type => assert.equal(type.properties.example_count, ontology.nodes.filter(node => node.kind === "ontology" && node.objectType === type.objectType).length));
  ontology.nodes.filter(node => node.objectType === "Observation" && node.kind === "ontology").forEach(observation => {
    const target = ontology.nodes.find(node => node.properties?.id === observation.properties.target_ref);
    assert.equal(target?.objectType, "Resource");
    assert.ok(ontology.edges.some(edge => edge[0] === observation.id && edge[1] === target.id && edge[2] === "observation_targets_resource"));
  });
  await frame.locator('[data-node="resource-type"]').click();
  assert.match(await frame.locator("#lineageInspector").innerText(), /OBJECT TYPE \/ DECLARATION/);
  assert.equal(await frame.locator('#lineageInspector [data-select="pod-resource"]').count(), 0);
  await frame.locator('[data-resource-type="kubernetes.pod"]').click();
  assert.match(await frame.locator("#lineageInspector").innerText(), /RESOURCE TYPE \/ SCOPED AGGREGATE/);
  assert.match(await frame.locator("#lineageInspector").innerText(), /3 recorded \/ 2 evidence gaps/);
  assert.equal(await frame.locator('[data-health="current"] dd').innerText(), "1");
  assert.equal(await frame.locator('[data-health="stale"] dd').innerText(), "1");
  assert.equal(await frame.locator('[data-health="unknown"] dd').innerText(), "1");
  await frame.locator(".ln-property-details > summary").click();
  assert.equal(await frame.locator(".ln-properties").isVisible(), true);
  await frame.locator("#lineageActual").click();
  for (const direction of ["incoming", "outgoing"]) {
    await frame.locator("#lineageDirection").selectOption(direction);
    const selectedId = await frame.locator('.ln-node[aria-pressed="true"]').getAttribute("data-node");
    const ends = await frame.locator(".ln-edge.is-selected").evaluateAll(elements => elements.map(element => ({ from: element.dataset.from, to: element.dataset.to })));
    assert.ok(ends.length > 0);
    assert.ok(ends.every(edge => edge[direction === "incoming" ? "to" : "from"] === selectedId));
    assert.ok(await frame.locator(".ln-edge.is-muted").count() > 0);
  }
  await frame.locator("#lineageDirection").selectOption("both");
  const beforeArrow = await frame.locator('.ln-node[aria-pressed="true"]').getAttribute("data-node");
  await frame.locator('.ln-node[aria-pressed="true"]').focus();
  await page.keyboard.press("ArrowLeft");
  const afterArrow = await frame.locator('.ln-node[aria-pressed="true"]').getAttribute("data-node");
  assert.notEqual(afterArrow, beforeArrow);
  assert.equal(await frame.evaluate(() => document.activeElement.dataset.node), afterArrow);
  assert.ok(await frame.locator('.ln-node[aria-pressed="true"]').getAttribute("aria-label"));
  await frame.locator('[data-resource-type="kubernetes.pod"]').click();
  const paths = await frame.locator(".ln-edge").evaluateAll(elements => elements.map(element => element.getAttribute("d")));
  paths.forEach(path => {
    assert.match(path, /^M[\d. -]+ C/);
    assert.doesNotMatch(path, /[HLVQ]/i, "every connection must use cubic curves, not orthogonal segments");
  });
  const lineWeights = await frame.locator(".ln-edge").evaluateAll(elements => elements.map(element => ({
    selected: element.classList.contains("is-selected"),
    aggregate: element.classList.contains("is-aggregate"),
    membership: element.classList.contains("is-membership"),
    width: Number.parseFloat(getComputedStyle(element).strokeWidth),
    marker: getComputedStyle(element).markerEnd,
  })));
  lineWeights.forEach(edge => {
    assert.equal(edge.width, edge.selected ? 1.5 : edge.aggregate ? 1.2 : edge.membership ? .75 : 1);
    assert.match(edge.marker, /lineageArrow/);
  });
  const grid = await frame.locator("#lineageViewport").evaluate(element => ({ image: getComputedStyle(element).backgroundImage, size: getComputedStyle(element).backgroundSize }));
  assert.match(grid.image, /radial-gradient/);
  assert.equal(grid.size, "20px 20px");
  await assertClearCurves(frame);
  assert.equal(await frame.locator(".ln-edge.is-missing").count(), 2);
  assert.match(await frame.locator("#caseState").innerText(), /Held/);
  assert.match(await frame.locator(".ln-boundary").innerText(), /No live sources/);
  await measure(frame, "Desktop default, master shell");
  await page.screenshot({ path: join(output, "desktop.png"), fullPage: true });

  await frame.locator('[data-resource-type="kubernetes.pod"]').click();
  const podGroup = await frame.locator('[data-resource-type="kubernetes.pod"]').getAttribute("data-node");
  assert.equal(await frame.locator(`.ln-edge[data-from="${podGroup}"][data-relation="kubernetes_scheduled_on"]`).getAttribute("data-count"), "3");
  const scheduled = frame.locator("#lineageInspector .ln-related > div").filter({ has: frame.locator('button', { hasText: "kubernetes_scheduled_on" }) });
  await scheduled.locator("summary").click();
  assert.equal(await scheduled.locator("li").count(), 3);
  assert.match(await scheduled.innerText(), /example-api-01/);
  assert.match(await scheduled.innerText(), /example-worker-01/);
  const groups = await frame.locator('[data-kind="resource-group"]').evaluateAll(elements => elements.map(element => element.dataset.node));
  for (const group of groups) {
    await frame.locator(`[data-node="${group}"]`).click();
    await frame.locator('#lineageInspector [data-expand]').click();
    await assertClearCurves(frame);
    assert.equal(await frame.locator('#lineageInspector [data-expand]').getAttribute("aria-expanded"), "true");
  }
  await frame.locator('[data-resource-type="kubernetes.pod"]').click();
  await frame.locator('#lineageInspector [data-expand]').click();
  assert.equal(await frame.locator(".ln-node").count(), 41);
  assert.equal(await frame.locator('[data-node="pod-resource"]').count(), 1);
  await measure(frame, "Expanded Pod resources, same canvas");
  assert.equal(await frame.locator('[data-node="api-endpoints"]').count(), 0, "only the selected type stays expanded");
  await frame.locator("#lineageFit").click();
  const expansionFit = await frame.evaluate(() => {
    const viewport = document.querySelector("#lineageViewport"), canvas = document.querySelector("#lineageCanvas");
    return { scale: canvas.getBoundingClientRect().width / canvas.offsetWidth, displayed: Number.parseInt(document.querySelector("#lineageZoom").value) / 100, fitted: viewport.scrollWidth <= viewport.clientWidth + 1 && viewport.scrollHeight <= viewport.clientHeight + 1 };
  });
  assert.equal(expansionFit.fitted, true);
  assert.ok(Math.abs(expansionFit.scale - expansionFit.displayed) < .006, "displayed zoom must match the rendered canvas immediately");
  await frame.evaluate(() => scrollTo(0, 0));
  await page.screenshot({ path: join(output, "expanded-pods.png"), fullPage: true });
  await frame.locator("#lineageActual").click();
  await frame.locator('[data-node="pod-resource"]').click();
  assert.match(await frame.locator("#lineageInspector").innerText(), /RESOURCE \/ ONTOLOGY INSTANCE/);
  await frame.locator('#lineageInspector [data-expand]').click();
  assert.equal(await frame.locator(".ln-node").count(), 38);

  await frame.locator('[data-node="memory-observation"]').click();
  assert.equal(await frame.locator("#lineageInspector").evaluate(element => element.scrollTop), 0);
  await frame.locator(".ln-property-details > summary").click();
  assert.match(await frame.locator("#lineageInspector").innerText(), /OBSERVATION \/ ONTOLOGY INSTANCE/);
  assert.match(await frame.locator(".ln-properties").innerText(), /sample-pod-01/);
  assert.match(await frame.locator(".ln-properties").innerText(), /742391808/);
  const targetRelation = frame.locator(`#lineageInspector [data-select="${podGroup}"]`);
  assert.match(await targetRelation.innerText(), /observation_targets_resource/);
  await targetRelation.click();
  assert.match(await frame.locator("#lineageInspector").innerText(), /RESOURCE TYPE \/ SCOPED AGGREGATE/);
  await frame.locator(".ln-property-details > summary").click();
  assert.match(await frame.locator(".ln-properties").innerText(), /kubernetes.pod/);
  await frame.locator("#lineageSearch").fill("sample-observation-m9");
  assert.equal(await frame.locator(".ln-node").count(), 1);
  await frame.locator("#lineageSearch").fill("");
  evidence.push({ name: "Cubic connections, dot grid and canonical ontology instance drill-down", disposition: "passed", grid, connections: paths.length });

  await frame.locator('[data-node="aks"]').focus();
  await page.keyboard.press("Enter");
  assert.match(await frame.locator("#lineageInspector h2").innerText(), /Kubernetes API/);
  assert.equal(await frame.locator('[data-node="aks"]').getAttribute("aria-pressed"), "true");
  assert.notEqual(await frame.locator('[data-node="aks"]').evaluate(element => getComputedStyle(element).outlineStyle), "none");
  await frame.locator("#lineageFocus").click();
  assert.equal(await frame.locator(".ln-node").count(), 2);
  await frame.locator("#lineageReset").click();
  assert.equal(await frame.locator(".ln-node").count(), 38);
  await frame.locator("#lineageActual").click();
  await frame.locator("#lineageZoomIn").click();
  assert.equal(await frame.locator("#lineageZoom").innerText(), "113%");
  await frame.locator("#lineageZoomOut").click();
  assert.equal(await frame.locator("#lineageZoom").innerText(), "100%");
  await frame.locator("#lineageInspectorToggle").click();
  assert.equal(await frame.locator("#lineageInspector").isVisible(), false);
  await frame.locator("#lineageCanvasMode").click();
  assert.equal(await frame.locator(".ln-heading").isVisible(), false);
  assert.equal(await frame.locator(".ln-canvas-badge").isVisible(), true);
  await frame.locator("#lineageCanvasMode").click();
  await frame.locator("#lineageInspectorToggle").click();
  await frame.locator("#lineageRecordPicker").selectOption("memory-observation");
  assert.match(await frame.locator("#lineageInspector h2").innerText(), /API 01 memory/);
  await frame.locator("#lineageActual").click();
  await frame.locator("#lineageCenter").click();
  assert.ok(Number.parseInt(await frame.locator("#lineageZoom").innerText()) >= 85);
  await frame.locator("#lineageMap").click({ position: { x: 135, y: 60 } });
  assert.ok(await frame.locator("#lineageViewport").evaluate(element => element.scrollLeft) > 0);
  const mapWindow = await frame.locator("#lineageMapWindow").evaluate(element => ({ width: Number(element.getAttribute("width")), height: Number(element.getAttribute("height")) }));
  assert.ok(mapWindow.width > 0 && mapWindow.width <= 2010 && mapWindow.height > 0 && mapWindow.height <= 1060);
  await frame.locator("#lineageMapToggle").click();
  assert.equal(await frame.locator("#lineageMap").isVisible(), false);
  await frame.locator("#lineageMapToggle").click();
  await frame.locator("#lineageActual").click();
  const viewport = frame.locator("#lineageViewport");
  await viewport.evaluate(element => { element.scrollLeft = 300; element.scrollTop = 0; });
  const viewportBox = await viewport.boundingBox();
  await page.mouse.move(viewportBox.x + 180, viewportBox.y + 30);
  await page.mouse.down();
  await page.mouse.move(viewportBox.x + 100, viewportBox.y + 30, { steps: 5 });
  await page.mouse.up();
  assert.ok(await viewport.evaluate(element => element.scrollLeft) >= 375, "background drag pans the canvas");
  assert.equal(await viewport.evaluate(element => element.classList.contains("is-dragging")), false);
  await page.keyboard.down("Control");
  await page.mouse.wheel(0, -100);
  await page.keyboard.up("Control");
  await frame.waitForFunction(() => Number.parseInt(document.querySelector("#lineageZoom").value) > 100);
  await viewport.focus();
  await page.keyboard.press("0");
  await frame.waitForFunction(() => {
    const viewport = document.querySelector("#lineageViewport");
    return viewport.scrollWidth <= viewport.clientWidth + 1 && viewport.scrollHeight <= viewport.clientHeight + 1;
  });
  assert.ok(await viewport.evaluate(element => element.scrollWidth <= element.clientWidth + 1 && element.scrollHeight <= element.clientHeight + 1), "keyboard fit restores the complete canvas");
  await frame.locator("#lineageActual").click();
  evidence.push({ name: "Unified types and instances, initial fit, drag pan, wheel zoom and keyboard fit", disposition: "passed", fit, types: types.map(node => node.title), instances: 24 });
  await frame.locator("#lineageSearch").fill("no-matching-record");
  assert.equal(await frame.locator(".ln-node").count(), 0);
  assert.equal(await frame.locator("#lineageEmpty").isVisible(), true);
  assert.equal(await frame.locator("#lineageMatchCount").innerText(), "0 matching records");
  await frame.locator("#lineageEmptyClear").click();
  assert.equal(await frame.locator(".ln-node").count(), 38);
  await frame.locator("#lineageSearch").fill("Pod");
  assert.ok(await frame.locator(".ln-node mark").count() > 0);
  await frame.locator("#lineageSearch").press("Enter");
  assert.equal(await frame.locator("#lineageSearch").inputValue(), "");
  await frame.locator("#lineageSearch").fill("<script>");
  await frame.locator("#lineageSearch").press("Escape");
  assert.equal(await frame.locator("#lineageSearch").inputValue(), "");
  await frame.locator("#lineageScenario").selectOption("complete");
  assert.equal(await frame.locator(".ln-edge.is-missing").count(), 0);
  assert.match(await frame.locator("#caseState").innerText(), /shadow review only/);
  assert.match(await frame.locator('[data-resource-type="kubernetes.pod"]').innerText(), /2 evidence gaps/, "available logs must not erase stale or unknown Resource evidence");
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
  await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
  assert.ok(await frame.locator(".ln-edge").evaluateAll(elements => elements.every(element => getComputedStyle(element).opacity === "1")));
  assert.equal(await frame.locator(".ln-node").first().evaluate(element => getComputedStyle(element).animationName), "none");
  await page.emulateMedia({ forcedColors: "none", reducedMotion: "reduce" });

  await page.setViewportSize({ width: 1920, height: 1200 });
  await page.locator(".nav-collapse").click();
  await frame.locator("#lineageFit").click();
  await frame.locator('[data-resource-type="kubernetes.pod"]').click();
  await frame.locator("#lineageViewport").evaluate(element => { element.scrollLeft = 0; });
  await measure(frame, "Wide desktop ontology inspector");
  await page.screenshot({ path: join(output, "desktop-wide.png"), fullPage: true });

  for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }, { width: 320, height: 844 }]) {
    await page.setViewportSize(viewport);
    if (viewport.width <= 390) {
      await frame.waitForFunction(() => !document.querySelector("#lineageCaseDetails").open);
      assert.equal(await frame.locator("#lineageCaseDetails").getAttribute("open"), null);
      await frame.locator("#lineageCaseDetails > summary").click();
      assert.equal(await frame.locator(".ln-case").isVisible(), true);
      await frame.locator("#lineageCaseDetails > summary").click();
    }
    await frame.locator("#lineageRecordPicker").selectOption("resource-type");
    assert.match(await frame.locator("#lineageInspector h2").innerText(), /^Resource$/);
    await measure(frame, `${viewport.width}px master frame`);
    await frame.locator('[data-view="sources"]').click();
    await measure(frame, `${viewport.width}px source register`);
    await frame.locator('[data-view="graph"]').click();
    await page.screenshot({ path: join(output, `${viewport.width}.png`), fullPage: true });
    if (viewport.width <= 390) {
      assert.ok((await frame.locator("#lineageRecordPicker").boundingBox()).width >= 180);
      await frame.locator("#lineageCanvasMode").click();
      assert.equal(await frame.locator("#lineageCaseDetails").isVisible(), false);
      await page.screenshot({ path: join(output, `${viewport.width}-canvas.png`), fullPage: true });
      await frame.locator("#lineageCanvasMode").click();
    }
  }
  await page.setViewportSize({ width: 1920, height: 1200 });
  await frame.locator("#lineageReset").click();
  await frame.locator('[data-resource-type="kubernetes.pod"]').click();
  await frame.locator('#lineageInspector [data-expand]').click();
  await frame.locator('[data-node="pod-resource"]').click();
  await frame.locator("#lineageActual").click();
  await frame.locator("#lineageDirection").selectOption("incoming");
  await page.reload({ waitUntil: "load" });
  await page.waitForFunction(() => document.querySelector("#preview-frame")?.contentDocument?.querySelector('[data-node="pod-resource"][aria-pressed="true"]'));
  frame = await (await page.locator("#preview-frame").elementHandle()).contentFrame();
  assert.equal(await frame.locator(".ln-node").count(), 41);
  assert.equal(await frame.locator("#lineageDirection").inputValue(), "incoming");
  assert.equal(await frame.locator("#lineageZoom").innerText(), "100%");
  evidence.push({ name: "Workspace reload restores selected record, expansion, direction and camera", disposition: "passed" });
  await frame.locator("#lineageReset").click();
  await frame.locator('[data-resource-type="kubernetes.pod"]').click();
  await frame.locator("#lineageFit").click();
  await frame.evaluate(() => { document.querySelector("#lineageInspector").scrollTop = 0; scrollTo(0, 0); });
  await page.screenshot({ path: join(output, "final-desktop.png"), fullPage: true });
  await frame.locator("#lineageCanvasMode").click();
  await frame.locator("#lineageInspectorToggle").click();
  await page.screenshot({ path: join(output, "final-canvas.png"), fullPage: true });
  await frame.locator("#lineageInspectorToggle").click();
  await frame.locator("#lineageCanvasMode").click();
  await page.addInitScript(() => {
    if (location.pathname.endsWith("/lineage.html")) sessionStorage.setItem("fdai:lineage-preview:workspace-v1", "{invalid-json");
  });
  await page.reload({ waitUntil: "load" });
  await page.waitForFunction(() => document.querySelector("#preview-frame")?.contentDocument?.querySelector('[data-resource-type="kubernetes.pod"][aria-pressed="true"]'));
  frame = await (await page.locator("#preview-frame").elementHandle()).contentFrame();
  assert.equal(await frame.locator(".ln-node").count(), 38);
  await page.addInitScript(() => {
    if (location.pathname.endsWith("/lineage.html")) Object.defineProperty(window, "sessionStorage", { get() { throw new DOMException("Blocked", "SecurityError"); } });
  });
  await page.reload({ waitUntil: "load" });
  await page.waitForFunction(() => document.querySelector("#preview-frame")?.contentDocument?.querySelector('[data-node="forseti"]'));
  frame = await (await page.locator("#preview-frame").elementHandle()).contentFrame();
  assert.equal(await frame.locator(".ln-node").count(), 38);
  await frame.locator('[data-node="forseti"]').click();
  assert.match(await frame.locator("#lineageInspector h2").innerText(), /Forseti/);
  evidence.push({ name: "Malformed or denied browser storage preserves a usable default graph", disposition: "passed" });
  await context.close();
  assert.deepEqual(errors, []);
  const rootIndex = await readFile(join(root, "index.html"), "utf8");
  const nestedIndex = await readFile(join(root, "mocks/ui/index.html"), "utf8");
  assert.match(rootIndex, /data-page="mocks\/ui\/lineage.html"/);
  assert.match(nestedIndex, /data-page="lineage.html"/);
  assert.deepEqual(await inputHashes(), inputsBefore, "validation inputs changed during the run");
  await writeFile(join(output, "evidence.json"), JSON.stringify({ venue: "static-mock", customerData: false, inputs: inputsBefore, evidence }, null, 2));
  console.log(JSON.stringify({ result: "passed", checks: evidence.length, output, errors }, null, 2));
} finally {
  await browser.close();
}
