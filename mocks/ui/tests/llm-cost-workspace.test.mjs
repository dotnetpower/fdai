/** LLM cost's frozen fixtures, scoped navigation state and accessible mock interactions. */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const origin = "http://127.0.0.1:5373";
const expectedLedger = [
  ["2026-08-04T14:32:01Z", "Control plane", "gpt-4o", "t2.reasoner.primary", "T2 / enforce", "100", "21", "121", "run-cross-check-0142"],
  ["2026-08-04T14:31:58Z", "Control plane", "text-embedding-3-small", "t1.embedding", "T1 / enforce", "5", "0", "5", "run-embedding-0141"],
  ["2026-08-04T14:30:44Z", "Operator chat", "gpt-4.1-mini", "t1.narrator", "T1 / enforce", "545", "24", "569", "chat-incident-0087"],
  ["2026-08-04T14:28:19Z", "Control plane", "gpt-5-mini", "t1.judge", "T1 / shadow", "544", "700", "1,244", "shadow-judge-0314"],
  ["2026-08-04T14:25:03Z", "Operator chat", "gpt-4o-mini", "t1.narrator", "T1 / enforce", "612", "36", "648", "chat-change-0062"],
  ["2026-08-04T14:21:47Z", "Control plane", "claude-opus-4", "t2.reasoner.cross-check", "T2 / enforce", "312", "27", "339", "run-cross-check-0139"],
];

test("source: LLM cost uses shared hierarchy, versioned assets and explicit evidence boundaries", async () => {
  const html = await readFile(join(root, "mocks/ui/llm-cost.html"), "utf8");
  const css = await readFile(join(root, "mocks/ui/assets/llm-cost-workspace.css"), "utf8");
  const js = await readFile(join(root, "mocks/ui/assets/llm-cost-workspace.js"), "utf8");
  assert.match(html, /id="llm-cost-main" data-preview-view="llm-cost-v1" tabindex="-1"/);
  assert.match(html, /cs-operator-neutral cs-overview-quality/);
  assert.match(html, /class="oq-skip-link" href="#llm-cost-main"/);
  assert.doesNotMatch(html, /<style>|<script>|overview-workspace\.css|operator-workspace\.css|class="lc-card"/);
  const styles = [...html.matchAll(/href="([^"]+\.css[^"]*)"/g)].map(match => match[1]);
  assert.deepEqual(styles, ["assets/calm-slate.css?v=overview-quality-v1", "assets/llm-cost-workspace.css?v=overview-quality-v2", "assets/overview-quality.css?v=overview-quality-v3"]);
  assert.match(html, /llm-cost-workspace\.js\?v=overview-quality-v3/);
  assert.match(html, /Synthetic usage preview; no live actions/);
  assert.match(html, /reference cost is unavailable/);
  assert.match(html, /Invoice amounts are not connected/);
  assert.match(html, /reference[^.]*not invoice reconciliation/i);
  assert.equal((html.match(/<th scope="col"/g) || []).length, 45);
  assert.equal((html.match(/<details[^>]*data-preview-persist/g) || []).length, 2);
  assert.doesNotMatch(html, /style="[^"]*font-size/);
  assert.match(css, /prefers-reduced-motion: reduce/);
  assert.match(css, /forced-colors: active/);
  assert.match(css, /overflow-x: auto/);
  assert.match(js, /root\.dispatchEvent\(new Event\("fdai-preview-state-change"\)\)/);
  assert.match(js, /history\.replaceState\(history\.state,/);
  assert.doesNotMatch(js, /localStorage|sessionStorage|fetch\(|XMLHttpRequest|updateLedgerTimes|history\.replaceState\(null/);
  for (const record of expectedLedger) {
    assert.ok(html.includes(`datetime="${record[0]}"`));
    assert.ok(html.includes(`href="audit.html?correlation=${record[8]}"`));
  }
});

async function setup(t) {
  const { chromium } = createRequire(join(root, "console/package.json"))("playwright");
  const browser = await chromium.launch({ headless: true });
  const errors = [];
  t.after(async () => { try { assert.deepEqual(errors, []); } finally { await browser.close(); } });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
  await context.route("**/*", route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
  const page = await context.newPage();
  page.setDefaultTimeout(8000);
  page.on("pageerror", error => errors.push(error.message));
  let entry = 0;
  async function currentFrame(name = "llm-cost") {
    await page.waitForFunction(name => {
      const frame = document.querySelector("#preview-frame");
      return frame?.contentDocument?.readyState === "complete" && frame.contentWindow.location.pathname === `/mocks/ui/${name}.html`;
    }, name);
    const frame = await (await page.locator("#preview-frame").elementHandle()).contentFrame();
    await frame.waitForLoadState("load");
    if (name === "llm-cost") await frame.waitForFunction(() => Boolean(document.querySelector("main").fdaiPreviewState));
    return frame;
  }
  async function open(suffix = "") {
    await page.goto(`${origin}/?llm-review=${++entry}#mocks/ui/llm-cost.html${suffix}`);
    return currentFrame();
  }
  return { page, context, open, currentFrame };
}

const capture = frame => frame.locator("main").evaluate(el => el.fdaiPreviewState.capture());
const ledger = frame => frame.locator(".lc-ledger-table tbody tr").evaluateAll(rows =>
  rows.map(row => [row.querySelector("time").dateTime, ...[...row.cells].slice(1).map(cell => cell.textContent.trim())]));

async function totals(frame) {
  const result = await frame.evaluate(() => {
    const numeric = value => Number(value.replaceAll(",", ""));
    const modelRows = [...document.querySelectorAll(".lc-model-usage tbody tr")];
    const sum = key => modelRows.reduce((total, row) => total + numeric(row.querySelector(`.model-${key}`).textContent), 0);
    const calendar = [...document.querySelectorAll("#daily-rollup tr")].map(row => [...row.cells].slice(1).map(cell => numeric(cell.textContent)));
    return {
      input: numeric(document.getElementById("input-tokens").textContent), output: numeric(document.getElementById("output-tokens").textContent),
      calls: numeric(document.getElementById("kpi-calls").textContent), models: [sum("calls"), sum("input"), sum("output"), sum("total")],
      daily: [0, 1, 2, 3].map(index => calendar.reduce((total, row) => total + row[index], 0)),
      modelSums: modelRows.every(row => numeric(row.querySelector(".model-total").textContent) ===
        numeric(row.querySelector(".model-input").textContent) + numeric(row.querySelector(".model-output").textContent)),
    };
  });
  assert.deepEqual(result.models, [result.calls, result.input, result.output, result.input + result.output]);
  assert.deepEqual(result.daily, result.models);
  assert.equal(result.modelSums, true);
  return result;
}

test("browser: LLM cost desktop ranges, exact records, chart keyboard, drilldowns and recovery", { timeout: 90000 }, async t => {
  const { page, open } = await setup(t);
  const frame = await open();
  assert.deepEqual(await capture(frame), { version: 1, range: "7d", from: "", to: "" });
  assert.deepEqual(await ledger(frame), expectedLedger);
  const initial = await totals(frame);
  assert.deepEqual([initial.calls, initial.input, initial.output], [1842, 1158000, 102000]);
  assert.equal(await frame.locator("#kpi-total").textContent(), "1.26M");
  assert.equal(await frame.locator(".lc-model-usage tbody tr").count(), 6);
  assert.equal(await frame.locator(".oq-surface .oq-surface").count(), 0);
  const skip = frame.locator(".oq-skip-link");
  await skip.focus(); await skip.press("Enter");
  assert.equal(await frame.locator("main").evaluate(el => el === document.activeElement), true);
  const point = frame.locator("#llm-token-point-0");
  await point.hover();
  await frame.locator("#token-tooltip").hover();
  assert.match(await frame.locator("#token-tooltip").textContent(), /148,000 tokens/);
  await page.keyboard.press("Escape");
  assert.equal(await frame.locator("#token-tooltip").evaluate(el => el.classList.contains("is-visible")), false);
  await point.focus();
  assert.match(await frame.locator("#token-tooltip").textContent(), /148,000 tokens.*12,000 tokens.*160,000 tokens/);
  await point.press("ArrowRight");
  assert.equal(await frame.locator("#llm-token-point-1").evaluate(el => el === document.activeElement), true);
  await frame.locator("#llm-token-point-1").press("End");
  assert.match(await frame.locator("#token-tooltip").textContent(), /201,000 tokens.*19,000 tokens.*220,000 tokens/);
  await frame.locator("#llm-token-point-6").press("Escape");
  assert.equal(await frame.locator("#token-tooltip").evaluate(el => el.classList.contains("is-visible")), false);
  await frame.locator("#llm-token-point-6").press(" ");
  assert.equal(await frame.locator("#token-tooltip").evaluate(el => el.classList.contains("is-visible")), true);
  await frame.locator("#llm-token-point-6").press("Home");
  assert.equal(await point.evaluate(el => el === document.activeElement), true);
  for (const [key, count, calls] of [["24h", 6, 263], ["30d", 30, 7934], ["7d", 7, 1842]]) {
    await frame.locator(`#range-${key}`).click();
    assert.equal(await frame.locator("#token-points .hit").count(), count);
    assert.equal(await frame.locator(`#range-${key}`).getAttribute("aria-pressed"), "true");
    assert.equal((await totals(frame)).calls, calls);
    assert.deepEqual(await ledger(frame), expectedLedger);
    if (key === "30d") {
      await frame.locator("#llm-token-point-0").focus();
      await frame.locator("#llm-token-point-0").press("End");
      assert.equal(await frame.locator("#llm-token-point-29").evaluate(el => el === document.activeElement), true);
      assert.ok(await frame.locator("#llm-chart-scroll").evaluate(el => el.scrollLeft > 0));
    }
  }
  await frame.locator("#llm-chat-link").click();
  assert.equal(await frame.locator("#llm-rollups").evaluate(el => el.open), true);
  await frame.locator("#llm-price-link").click();
  assert.equal(await frame.locator("#llm-price-reference").evaluate(el => el.open), true);
  assert.match(await frame.locator("#llm-price-reference").innerText(), /reference cost is unavailable/);
  assert.equal(await frame.locator("#llm-model-reference-link").getAttribute("href"), "settings-models.html#models-catalog");
  await frame.locator("#range-custom").click();
  await frame.locator("#range-start").fill("2026-08-03");
  await frame.locator("#range-end").fill("2026-08-01");
  await frame.locator("#range-apply").click();
  assert.match(await frame.locator("#range-error").innerText(), /must not precede/);
  assert.equal((await capture(frame)).range, "7d");
  assert.equal(await frame.locator("#range-start").inputValue(), "2026-08-03");
  await frame.locator("#range-end").press("Escape");
  assert.equal(await frame.locator("#range-custom").evaluate(el => el === document.activeElement), true);
  for (const [from, to] of [["", "2026-08-04"], ["2026-05-06", "2026-08-04"], ["2026-05-07", "2026-08-05"]]) {
    await frame.locator("#range-custom").click();
    await frame.locator("#range-start").fill(from); await frame.locator("#range-end").fill(to);
    await frame.locator("#range-apply").click();
    assert.match(await frame.locator("#range-error").innerText(), /Choose 1 to 90 days/);
    await frame.locator("#range-cancel").click();
  }
  await frame.locator("#range-custom").click();
  await frame.locator("#range-start").fill("2026-08-01"); await frame.locator("#range-end").fill("2026-08-01");
  await frame.locator("#range-apply").click();
  assert.equal(await frame.locator("#token-points .hit").count(), 1);
  assert.equal(await frame.locator("#ledger-empty").isVisible(), true);
  assert.equal(await frame.locator("#export-invocations").isDisabled(), true);
  assert.equal(await frame.locator("#kpi-latest-time").textContent(), "Unavailable");
  assert.equal(await frame.locator("#conversation-rollup tr:visible").count(), 0);
  assert.deepEqual(await ledger(frame), expectedLedger);
  assert.deepEqual((({ calls, input, output }) => [calls, input, output])(await totals(frame)), [202, 128000, 10000]);
  await frame.locator("#range-custom").click();
  await frame.locator("#range-start").fill("2026-05-07"); await frame.locator("#range-end").fill("2026-08-04");
  await frame.locator("#range-apply").click();
  assert.equal(await frame.locator("#daily-rollup tr").count(), 90);
  assert.equal(await frame.locator("#monthly-rollup tr").count(), 4);
  assert.equal(await frame.locator(".lc-ledger-table tbody tr:visible").count(), 6);
  await totals(frame);
  await frame.locator("#range-7d").click();
  const downloadPromise = page.waitForEvent("download");
  await frame.locator("#export-invocations").click();
  const download = await downloadPromise;
  const stream = await download.createReadStream();
  const chunks = [];
  for await (const chunk of stream) chunks.push(chunk);
  const csv = Buffer.concat(chunks).toString("utf8");
  assert.equal(csv.trim().split("\r\n").length, 7);
  assert.match(csv, /"occurred_at","correlation_id","capability_id","model_key","tier","mode","usage_scope","prompt_tokens","completion_tokens","total_tokens"/);
  assert.match(csv, /"2026-08-04T14:32:01Z","run-cross-check-0142","t2.reasoner.primary","gpt-4o","T2","enforce","control_plane","100","21","121"/);
  assert.match(await frame.locator("#export-status").textContent(), /download requested/);
});

test("browser: LLM cost committed range survives immediate navigation and reload without draft or focus leakage", { timeout: 90000 }, async t => {
  const { page, open, currentFrame } = await setup(t);
  let frame = await open("?from=2026-07-29&to=2026-08-04");
  await page.evaluate(() => history.replaceState({ ...history.state, unrelated: "retained" }, "", location.href));
  await frame.evaluate(() => history.replaceState({ unrelatedChild: "retained" }, "", location.href));
  await frame.locator("#range-30d").click();
  assert.equal(await frame.evaluate(() => history.state.unrelatedChild), "retained");
  assert.equal(await page.evaluate(() => history.state.unrelated), "retained");
  assert.equal(await page.evaluate(() => history.state.fdaiMockView.pageState.range), "30d");
  await frame.locator("#llm-rollups-toggle").click();
  await frame.locator("#llm-audit-primary").focus();
  await frame.locator("#llm-audit-primary").press("Enter");
  await currentFrame("audit");
  await page.goBack();
  frame = await currentFrame();
  assert.equal((await capture(frame)).range, "30d");
  assert.equal(await frame.locator("#llm-rollups").evaluate(el => el.open), true);
  assert.equal(await frame.locator("#llm-audit-primary").evaluate(el => el === document.activeElement), true);
  const current = await capture(frame);
  await frame.locator("#range-custom").click();
  await frame.locator("#range-start").fill("2026-05-07");
  assert.deepEqual(await capture(frame), current);
  await page.reload();
  frame = await currentFrame();
  assert.deepEqual(await capture(frame), current);
  assert.equal(await frame.locator("#custom-range").isVisible(), false);
  assert.equal(await frame.locator("main").evaluate(el => el.contains(document.activeElement)), false);
  assert.equal(await frame.locator("#llm-rollups").evaluate(el => el.open), true);
  const payloadResult = await frame.evaluate(() => {
    const api = document.querySelector("main").fdaiPreviewState;
    const accepted = [null, {}, { version: 1, range: "custom", from: "2026-02-30", to: "2026-08-04" },
      { version: 1, range: "7d", from: "", to: "", extra: true }, { version: 1, range: "constructor", from: "", to: "" }]
      .map(payload => api.restore(payload));
    return { accepted, value: api.capture(), bytes: new TextEncoder().encode(JSON.stringify(api.capture())).length };
  });
  assert.deepEqual(payloadResult.accepted, [false, false, false, false, false]);
  assert.deepEqual(payloadResult.value, current);
  assert.ok(payloadResult.bytes <= 2048);
  assert.match(await frame.locator("#range-state-error").textContent(), /Saved range is incompatible/);
  frame = await open();
  assert.deepEqual(await capture(frame), { version: 1, range: "7d", from: "", to: "" });
  assert.equal(await frame.locator("#llm-rollups").evaluate(el => el.open), false);
  for (const suffix of ["?range=unknown", "?from=2026-07-01", "?from=2026-02-30&to=2026-08-04", "?range=7d&range=24h"]) {
    frame = await open(suffix);
    assert.equal((await capture(frame)).range, "7d");
    assert.match(await frame.locator("#range-state-error").textContent(), /URL range is invalid/);
    assert.equal(await frame.locator("#custom-range").isVisible(), false);
  }
});

test("browser: desktop gate precedes constrained and mobile LLM layouts, targets and preferences", { timeout: 90000 }, async t => {
  const { page, open } = await setup(t);
  const frame = await open();
  await frame.locator("#llm-rollups-toggle").click();
  for (const viewport of [{ width: 1440, height: 900 }, { width: 993, height: 641 }, { width: 390, height: 844 }, { width: 320, height: 844 }]) {
    await page.setViewportSize(viewport);
    const geometry = await frame.evaluate(() => {
      const main = document.querySelector("main");
      const controls = [...main.querySelectorAll(".lc-range-option, #export-invocations, .lc-chart .hit")];
      return {
        documentFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1,
        mainFits: main.scrollWidth <= main.clientWidth + 1,
        headingsOpen: [...main.querySelectorAll(".oq-page-header, .oq-section-head")].every(el => getComputedStyle(el).backgroundColor === "rgba(0, 0, 0, 0)"),
        targets: controls.every(el => { const box = el.getBoundingClientRect(); return box.width >= 44 && box.height >= 44; }),
        tableBounded: [...main.querySelectorAll(".cs-table-wrap")].every(el => ["auto", "scroll"].includes(getComputedStyle(el).overflowX) && el.clientWidth <= main.clientWidth),
        readable: [...main.querySelectorAll("td, button")].every(el => parseFloat(getComputedStyle(el).fontSize) >= 13),
      };
    });
    for (const [key, value] of Object.entries(geometry)) assert.equal(value, true, `${viewport.width}: ${key}`);
  }
  await frame.locator("#range-custom").click();
  await frame.locator("#range-start").fill("2026-05-07"); await frame.locator("#range-end").fill("2026-08-04");
  await frame.locator("#range-apply").click();
  const chartScroll = frame.locator(".lc-chart-scroll");
  assert.equal(await chartScroll.evaluate(el => el.scrollWidth > el.clientWidth && el.scrollWidth <= 4800), true);
  await frame.locator("#llm-token-point-0").focus();
  await frame.locator("#llm-token-point-0").press("End");
  assert.equal(await frame.locator("#llm-token-point-89").evaluate(el => el === document.activeElement), true);
  assert.equal(await frame.locator("#daily-rollup").evaluate(el => el.closest(".cs-table-wrap").clientHeight <= 440), true);
  await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
  assert.equal(await frame.evaluate(() => matchMedia("(forced-colors: active)").matches), true);
  assert.equal(await frame.locator(".lc-chart .line").evaluate(el => getComputedStyle(el).stroke), "rgb(0, 0, 0)");
  await frame.locator("#llm-token-point-89").press("Escape");
  assert.equal(await frame.locator("#token-tooltip").evaluate(el => el.classList.contains("is-visible")), false);
});
