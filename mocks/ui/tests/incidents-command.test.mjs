/** Focused regressions for the agent-owned Incidents command workspace. */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const uiRoot = join(root, "mocks/ui");
const require = createRequire(join(root, "console/package.json"));
const { chromium } = require("playwright");
const origin = "http://127.0.0.1:5373";

async function openIncidents(page, query = "status=active") {
  await page.goto(`${origin}/#mocks/ui/incidents.html?${query}`, { waitUntil: "load" });
  await page.waitForFunction(() => {
    const frame = document.querySelector("#preview-frame");
    return frame?.contentDocument?.readyState === "complete"
      && frame.contentWindow.location.pathname === "/mocks/ui/incidents.html";
  });
  return (await page.locator("#preview-frame").elementHandle()).contentFrame();
}

test("incident command markup keeps IDs, urgency, and pantheon ownership explicit", async () => {
  const [html, css] = await Promise.all([
    readFile(join(uiRoot, "incidents.html"), "utf8"),
    readFile(join(uiRoot, "assets/incidents-command.css"), "utf8"),
  ]);
  for (const id of ["INC-240715-01", "INC-240715-02", "INC-240715-03", "INC-240715-04"]) {
    assert.match(html, new RegExp(`in-incident-id[^>]*>${id}<`), id);
    assert.match(html, new RegExp(`in-detail-id[^>]*>${id}<`), id);
  }
  for (const agent of ["Huginn", "Forseti", "Thor", "Vidar", "Heimdall", "Var", "Njord", "Saga"]) {
    assert.match(html, new RegExp(`in-plan-agent[^]*?<strong>${agent}</strong>`), agent);
  }
  assert.match(html, /each agent owns one typed state transition/);
  assert.match(html, /they do not call one another directly/);
  assert.match(html, /Prioritize by Incident ID and urgency/);
  assert.match(html, /placeholder="Incident ID, title, target, or evidence"/);
  assert.match(html, /Available only after terminal effect verification/);
  assert.match(html, /Human time saved<\/dt><dd>Unavailable/);
  assert.equal((html.match(/data-notification-panel/g) || []).length, 4);
  assert.equal((html.match(/class="in-notification-row"/g) || []).length, 9);
  const recipients = [...html.matchAll(/data-recipient="([^"]+)"/g)].map((match) => match[1]);
  assert.equal(recipients.length, 9);
  assert.ok(recipients.every((recipient) => recipient.endsWith("@example.com")), recipients);
  assert.match(html, /provider publication proves delivery to a channel, not that a user read it/);
  assert.match(html, /only authenticated approve or reject decisions contribute to Var's quorum/);
  assert.match(html, /broker acceptance is not provider delivery/);
  assert.match(html, /They do not rewrite Saga's immutable verified outcome/);
  assert.match(css, /\.in-response-plan ol \{[^}]*grid-template-columns: repeat\(3/);
  assert.match(css, /\.in-notification-row \{[^}]*grid-template-columns:/);
  assert.match(css, /@media \(max-width: 620px\)/);
  assert.doesNotMatch(css, /border-(?:top|left):\s*[2-9]px/);
});

test("incident command states preserve accountable agents and bounded recovery", { timeout: 60000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      reducedMotion: "reduce",
    });
    await context.route("**/*", route => new URL(route.request().url()).origin === origin
      ? route.continue() : route.abort("blockedbyclient"));
    const page = await context.newPage();
    page.setDefaultTimeout(7000);
    const frame = await openIncidents(page);

    assert.equal(await frame.locator(".in-incident-id").first().innerText(), "INC-240715-01");
    assert.equal(await frame.locator(".in-detail-id").first().innerText(), "INC-240715-01");
    assert.equal(
      await frame.locator(".in-detail-id").first().evaluate(
        element => getComputedStyle(element).fontSize,
      ),
      "24px",
    );
    assert.deepEqual(
      await frame.locator('[data-incident-detail="inc-api-latency"] .in-plan-agent strong').allTextContents(),
      ["Huginn", "Forseti", "Thor", "Vidar", "Heimdall", "Saga"],
    );
    assert.equal(
      await frame.locator('[data-incident-detail="inc-api-latency"] .in-plan-step.is-current .in-plan-agent strong').innerText(),
      "Heimdall",
    );
    assert.match(
      await frame.locator('[data-incident-detail="inc-api-latency"] .in-current-state').innerText(),
      /Next state transition[\s\S]*Close condition/,
    );
    assert.deepEqual(
      await frame.locator('[data-incident-detail="inc-api-latency"] [data-recipient]').evaluateAll(
        (rows) => rows.map((row) => ({
          recipient: row.dataset.recipient,
          response: row.querySelector("[data-user-response]")?.getAttribute("data-user-response"),
        })),
      ),
      [
        { recipient: "incident.commander@example.com", response: "acknowledged" },
        { recipient: "checkout.owner@example.com", response: "guidance" },
      ],
    );
    assert.match(
      await frame.locator('[data-incident-detail="inc-api-latency"] .in-notification-panel').innerText(),
      /2 observed delivered[\s\S]*change approvers were excluded[\s\S]*neither grants execution authority/,
    );
    assert.equal(
      await frame.locator('[data-incident-detail="inc-api-latency"] .in-notification-row').first()
        .evaluate(element => getComputedStyle(element).gridTemplateColumns.split(" ").length),
      2,
    );

    await frame.locator("[data-incident-priority]").selectOption("p1");
    assert.equal(await frame.locator("[data-incident]:visible").count(), 2);
    assert.match(page.url(), /priority=p1/);
    await frame.locator('[data-incident="inc-pitr-disabled"]').focus();
    await page.keyboard.press("Enter");
    assert.equal(await frame.locator('[data-incident="inc-pitr-disabled"]').getAttribute("aria-pressed"), "true");
    assert.equal(
      await frame.locator('[data-incident-detail="inc-pitr-disabled"] .in-plan-step.is-current .in-plan-agent strong').innerText(),
      "Var",
    );
    assert.match(
      await frame.locator('[data-incident-detail="inc-pitr-disabled"] .in-response-plan').innerText(),
      /silence grants nothing[\s\S]*Thor never accepts a visual control state as authority/,
    );
    assert.deepEqual(
      await frame.locator('[data-incident-detail="inc-pitr-disabled"] [data-user-response]')
        .evaluateAll((elements) => elements.map((element) => element.getAttribute("data-user-response"))),
      ["approved", "awaiting", "acknowledged"],
    );
    assert.match(
      await frame.locator('[data-incident-detail="inc-pitr-disabled"] .in-notification-panel').innerText(),
      /approval 1\/2[\s\S]*quorum remains incomplete[\s\S]*not an approval/,
    );

    await frame.locator("[data-clear-incident-scope]").click();
    await frame.locator('[data-incident="inc-cost-spike"]').click();
    assert.equal(
      await frame.locator('[data-incident-detail="inc-cost-spike"] .in-plan-step.is-current .in-plan-agent strong').innerText(),
      "Njord",
    );
    assert.match(
      await frame.locator('[data-incident-detail="inc-cost-spike"] .in-current-state').innerText(),
      /Urgency[\s\S]*Unavailable[\s\S]*no action is eligible/i,
    );
    assert.match(
      await frame.locator('[data-incident-detail="inc-cost-spike"] .in-notification-panel').innerText(),
      /1 observed delivered[\s\S]*provider delivery observation unavailable[\s\S]*No response recorded/,
    );

    await frame.locator('[data-incident-filter="resolved"]').click();
    assert.equal(await frame.locator("[data-incident]:visible").count(), 1);
    assert.equal(
      await frame.locator('[data-incident-detail="inc-secret-expiry"] .in-plan-step.is-current .in-plan-agent strong').innerText(),
      "Saga",
    );
    assert.match(
      await frame.locator('[data-incident-detail="inc-secret-expiry"] .in-value-panel').innerText(),
      /Agent mitigated[\s\S]*29m 27s[\s\S]*4 \/ 5[\s\S]*Unavailable/,
    );
    assert.match(
      await frame.locator('[data-incident-detail="inc-secret-expiry"] .in-notification-panel').innerText(),
      /Closure acknowledged[\s\S]*terminal record unchanged[\s\S]*Handback confirmed/,
    );

    assert.equal(await frame.evaluate(() =>
      document.documentElement.scrollWidth <= document.documentElement.clientWidth), true);
    await context.close();
  } finally {
    await browser.close();
  }
});

test("incident command layout reflows without losing agent ownership", { timeout: 60000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({
      viewport: { width: 993, height: 641 },
      reducedMotion: "reduce",
    });
    await context.route("**/*", route => new URL(route.request().url()).origin === origin
      ? route.continue() : route.abort("blockedbyclient"));
    const page = await context.newPage();
    page.setDefaultTimeout(7000);
    let frame = await openIncidents(page);
    assert.equal(await frame.evaluate(() =>
      document.documentElement.scrollWidth <= document.documentElement.clientWidth), true);
    assert.equal(
      await frame.locator('[data-incident-detail="inc-api-latency"] .in-response-plan ol')
        .evaluate(element => getComputedStyle(element).gridTemplateColumns.split(" ").length),
      2,
    );
    assert.equal(
      await frame.locator('[data-incident-detail="inc-api-latency"] .in-notification-row').first()
        .evaluate(element => getComputedStyle(element).gridTemplateColumns.split(" ").length),
      2,
    );

    await page.setViewportSize({ width: 390, height: 844 });
    frame = await openIncidents(page);
    assert.equal(await frame.evaluate(() =>
      document.documentElement.scrollWidth <= document.documentElement.clientWidth), true);
    assert.equal(
      await frame.locator('[data-incident-detail="inc-api-latency"] .in-response-plan ol')
        .evaluate(element => getComputedStyle(element).gridTemplateColumns.split(" ").length),
      1,
    );
    assert.equal(
      await frame.locator('[data-incident-detail="inc-api-latency"] .in-notification-row').first()
        .evaluate(element => getComputedStyle(element).gridTemplateColumns.split(" ").length),
      1,
    );
    const shortTargets = await frame.locator("button, select, input, summary, .in-detail-primary-link")
      .evaluateAll(elements => elements
        .filter(element => element.checkVisibility({ checkVisibilityCSS: true, checkOpacity: true }))
        .filter(element => element.getBoundingClientRect().height < 44)
        .map(element => ({
          name: (element.textContent || element.getAttribute("aria-label") || "").trim(),
          height: element.getBoundingClientRect().height,
        })));
    assert.deepEqual(shortTargets, []);
    await context.close();
  } finally {
    await browser.close();
  }
});
