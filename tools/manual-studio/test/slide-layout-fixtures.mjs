/** Regression fixtures for real overflow versus the ontology's intentional external connectors. */
import assert from "node:assert/strict";
import { inspectTextGeometry, verifyTextGeometry } from "./target-architecture-text-geometry.mjs";
import { inspectSlideLayout } from "./slide-layout-geometry.mjs";
import { inspectSlideConnectors } from "./slide-connector-geometry.mjs";

/** Require clean rendered fixtures and reject both box overflow and painted text escaping a fixed box. */
export async function verifySlideLayout(page) {
  const textFixtures = await verifyTextGeometry(page);
  await page.setContent(`<!doctype html><html><head><style>
    * { box-sizing: border-box; }
    #fixture { position: relative; width: 800px; height: 600px; overflow: hidden;
      transform-origin: top left; font: 24px/32px sans-serif; }
    .slide-copy { width: 720px; }
    h2 { font: 40px/48px sans-serif; margin: 12px 0; }
    p { margin: 12px 0; }
    article { position: absolute; left: 20px; top: 200px; width: 320px; height: 120px; padding: 20px; }
    .content { display: block; height: 40px; }
    .oe-bus-connector { position: absolute; width: 1px; height: 30px; top: 100%; left: 50%; }
    .manual-draft-overlay { position: absolute; left: -20px; bottom: 20px; }
  </style></head><body><main id="fixture" data-index="0">
    <div class="slide-copy"><h2>Decision evidence</h2><p>Keep the effect independently verified.</p></div>
    <article class="oe-agent-port"><span class="content">Evidence owner</span><i class="oe-bus-connector" aria-hidden="true"></i></article>
    <div class="manual-draft-overlay">DRAFT</div>
  </main></body></html>`);
  await page.addScriptTag({ content: `${inspectTextGeometry}\n${inspectSlideLayout}` });
  const inspect = () => page.evaluate(() => inspectSlideLayout(document.querySelector("#fixture")));
  const results = [];
  for (const scale of [1, .65, .22]) {
    await page.locator("#fixture").evaluate((element, value) => {
      element.style.transform = `scale(${value})`;
    }, scale);
    assert.deepEqual((await inspect()).findings, [], `Intended connector at ${scale}`);
    await page.locator(".content").evaluate(element => { element.style.height = "150px"; });
    assert.ok((await inspect()).findings.some(f => f.kind === "card-overflow"), `Box overflow at ${scale}`);
    await page.locator(".content").evaluate(element => {
      element.style.height = "40px";
      element.textContent = "Independent evidence must remain readable inside the agent port even when a fixed child box hides its actual text height.";
    });
    assert.ok((await inspect()).findings.some(f => f.kind === "card-overflow"), `Painted overflow at ${scale}`);
    await page.locator(".content").evaluate(element => { element.textContent = "Evidence owner"; });
    await page.locator("article").evaluate(element => { element.className = "ordinary-card"; });
    assert.ok((await inspect()).findings.some(f => f.kind === "card-overflow"), `Unrelated card at ${scale}`);
    await page.locator("article").evaluate(element => { element.className = "oe-agent-port"; });
    assert.deepEqual((await inspect()).findings, []);
    results.push({ scale, rejectedCardRegressions: 3, cleanFindings: 0 });
  }
  await page.locator("h2").evaluate(element => {
    element.style.width = "100px";
    element.textContent = "Verify every decision with evidence";
  });
  assert.ok((await inspect()).findings.some(f => f.kind === "title-density"));
  await page.setContent(`<!doctype html><html><head><style>
    #fixture { width: 800px; height: 200px; transform-origin: top left; }
    .rm-graph { display: grid; grid-template-columns: 200px 40px 200px; align-items: center; }
    [data-rm-node] { height: 100px; }
    .rm-link { display: flex; align-items: center; height: 100px; }
    .rm-link i { display: block; width: 100%; height: 2px; background: #222; }
  </style></head><body><main id="fixture"><section class="rm-graph">
    <div data-rm-node="source">Evidence</div>
    <div class="rm-link" data-rm-from="source" data-rm-to="decision"><i></i></div>
    <div data-rm-node="decision">Decision</div>
  </section></main></body></html>`);
  const readinessConnectorFixtures = [];
  for (const scale of [1, .65, .22]) {
    await page.locator("#fixture").evaluate((element, value) => {
      element.style.transform = `scale(${value})`;
    }, scale);
    const clean = await page.locator("#fixture").evaluate(inspectSlideConnectors);
    assert.equal(clean.checkedConnectors, 1);
    assert.deepEqual(clean.findings, []);
    await page.locator(".rm-link i").evaluate(element => { element.style.width = "20px"; });
    const broken = await page.locator("#fixture").evaluate(inspectSlideConnectors);
    assert.ok(broken.findings.some(f => f.kind === "detached-connector"));
    await page.locator(".rm-link i").evaluate(element => { element.style.removeProperty("width"); });
    readinessConnectorFixtures.push({ scale, shortenedLineRejected: true, cleanFindings: 0 });
  }
  return { textFixtures, connectorFixtures: results, readinessConnectorFixtures, titleDensityRejected: true };
}
