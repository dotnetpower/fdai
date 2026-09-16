import { expect, test, type Page, type Route } from "@playwright/test";

const correlation = "correlation-audit-review";
const rows = [
  {
    seq: 42, event_id: "event-42", correlation_id: correlation,
    actor: "Saga", action_kind: "risk_gate.unified", mode: "shadow",
    entry: { decision: "hil", tier: "t0", idempotency_key: "idem-42", reason: "Independent approval required" },
    context: {
      record_kind: "action_lifecycle", action_lifecycle_applicable: true,
      target: null, correlation_id: correlation, phase: null, stage: null,
      outcome: null, tier: "t0", decision: "hil", idempotency_key: "idem-42",
      rollback_reference: null, owner_agent: "Forseti", domain: null,
    },
    entry_hash: "hash-42", previous_hash: "hash-41", recorded_at: "2026-09-15T06:00:00Z",
  },
  {
    seq: 41, event_id: "event-41", correlation_id: correlation,
    actor: "Thor", action_kind: "executor.dispatch.recorded", mode: "enforce",
    entry: { stage: "dispatch", outcome: "accepted", idempotency_key: "idem-41" },
    context: {
      record_kind: "action_lifecycle", action_lifecycle_applicable: true,
      target: null, correlation_id: correlation, phase: "dispatch", stage: "dispatch",
      outcome: "accepted", tier: null, decision: null, idempotency_key: "idem-41",
      rollback_reference: null, owner_agent: "Thor", domain: null,
    },
    entry_hash: "hash-41", previous_hash: "hash-40", recorded_at: "2026-09-15T05:59:00Z",
  },
];

const sourceObservation = {
  seq: 43, event_id: "event-43", correlation_id: "campaign-one",
  actor: "fdai.delivery.observation_campaign",
  action_kind: "observation-campaign.source-transition", mode: "shadow",
  entry: {
    source_id: "metrics", domain: "metrics", campaign_id: "campaign-one",
    owner_agent: "Heimdall", status: "completed", execution_authority: false,
  },
  context: {
    record_kind: "source_observation", action_lifecycle_applicable: false,
    target: "metrics", correlation_id: "campaign-one", phase: null, stage: null,
    outcome: "completed", tier: null, decision: null, idempotency_key: null,
    rollback_reference: null, owner_agent: "Heimdall", domain: "metrics",
  },
  entry_hash: "hash-43", previous_hash: "hash-42", recorded_at: "2026-09-15T06:01:00Z",
};

async function fixture(page: Page, options: {
  empty?: boolean; fail?: boolean; delay?: number; long?: boolean; paginated?: boolean;
  count?: number; observation?: boolean;
} = {}) {
  const requests: URL[] = [];
  let olderAttempts = 0;
  const handler = async (route: Route) => {
    if (route.request().isNavigationRequest()) return route.continue();
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api(?=\/)/, "");
    if (path === "/system/data-sources") {
      return route.fulfill({ json: {
        surface: "read-data-sources", sources: [{
          key: "audit-browser-fixture", source: "deterministic browser fixture", routes: ["/audit"],
          availability: "available", configured: true, reachable: true, authoritative: true,
          durable: true, synthetic: true, reason: null, last_observed_at: "2026-09-15T06:00:00Z",
        }],
      } });
    }
    if (path !== "/audit") return route.fulfill({ status: 404, json: { error: { message: "Not provided by fixture" } } });
    requests.push(url);
    if (options.delay) await new Promise(resolve => setTimeout(resolve, options.delay));
    if (options.fail || (url.searchParams.has("cursor") && ++olderAttempts === 1)) {
      return route.fulfill({ status: 503, json: { error: { message: "Audit source unavailable" } } });
    }
    const base = options.observation ? [sourceObservation] : options.count ? Array.from({length: options.count}, (_, index) => ({
      ...rows[0]!, seq: 100 - index, event_id: `event-many-${index}`,
      action_kind: index === options.count! - 1 ? "last.audit.record" : "record.review",
    })) : options.long ? rows.map(row => ({
      ...row, actor: `service.${"long-identity-".repeat(12)}`, event_id: "e".repeat(200),
      entry: { ...row.entry, resource_id: "resource/".repeat(28), reason: "긴 감사 기록 근거 ".repeat(25) },
    })) : rows;
    const entry = url.searchParams.get("from_seq");
    const items = options.empty ? [] : url.searchParams.has("cursor") ? [
      { ...rows[1]!, seq: 40, event_id: "event-40", action_kind: "older.audit.record" },
    ] : entry ? base.filter(row => String(row.seq) === entry) : base;
    return route.fulfill({ json: {
      items, next_cursor: options.paginated && !url.searchParams.has("cursor") ? "older" : null,
      summary: {
        observed_at: "2026-09-15T06:02:00Z",
        matching_record_count: options.empty ? 0 : options.count ?? base.length,
        terminal_record_count: options.empty ? 0 : 1,
        human_review_record_count: options.empty || options.observation ? 0 : 1,
        rollback_record_count: 0,
        integrity: {
          status: "verified", reason: null, verified_at: "2026-09-15T06:00:00Z",
          current_record_count: options.empty ? 0 : options.count ?? base.length,
          current_link_gap_count: 0,
        },
        redaction_applied: true,
      },
    } });
  };
  await page.route("**/api/**", handler);
  await page.route("**/audit?*", handler);
  await page.route("**/system/data-sources*", handler);
  return requests;
}

test("desktop mock hierarchy preserves selection, raw evidence, and exact record links", async ({ page }, testInfo) => {
  const requests = await fixture(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/audit?correlation=${correlation}&mode=shadow&vertical=resilience`);
  await expect(page.locator(".audit-record")).toHaveCount(2);
  await expect(page.locator(".audit-record").first()).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#audit-selected-title")).toHaveText("risk_gate.unified");
  await expect(page.locator(".audit-metrics")).toContainText("Terminal records");
  await expect(page.locator(".audit-metrics")).toContainText("Verified at startup");
  await expect(page.locator(".audit-phases [data-recorded=true]")).toHaveCount(0);
  await expect(page.locator(".audit-ledger")).toContainText("Linked");
  await expect(page.locator(".audit-json")).toContainText('"decision": "hil"');
  await page.screenshot({ path: testInfo.outputPath("audit-workspace-desktop-default.png") });
  const second = page.locator(".audit-record").nth(1);
  await second.focus();
  await page.keyboard.press("Enter");
  await expect(second).toBeFocused();
  await expect(second).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#audit-selected-title")).toHaveText("executor.dispatch.recorded");
  await expect(page.locator(".audit-phases [data-recorded=true]")).toHaveCount(1);
  await expect(page.locator(".audit-context")).toContainText("Dispatch stage recorded");
  await expect(page.locator(".audit-context")).not.toContainText("Independently verified");
  expect(requests.length).toBe(1);
  expect(requests[0]?.searchParams.get("summary")).toBe("true");
  expect(await page.locator(".audit-workspace").evaluate(e => getComputedStyle(e).gridTemplateColumns))
    .toMatch(/^290px /);
  await expect(page.locator(".audit-evidence-links a").first())
    .toHaveAttribute("href", `/audit?correlation=${correlation}&mode=shadow&vertical=resilience&entry=41`);
  await page.getByText("Record provenance", { exact: true }).click();
  await expect(page.locator(".audit-provenance")).toContainText("hash-41");
  await expect(page.locator(".audit-provenance")).toContainText("does not verify ledger integrity");
  await page.screenshot({ path: testInfo.outputPath("audit-workspace-desktop.png"), fullPage: true });
  await page.locator(".audit-evidence-links a").first().click();
  await expect(page.locator(".audit-record")).toHaveCount(1);
  expect(requests.at(-1)?.searchParams.get("from_seq")).toBe("41");
  expect(requests.at(-1)?.searchParams.get("through_seq")).toBe("41");
});

test("source observation records show recorded source evidence without action placeholders", async ({ page }, testInfo) => {
  await fixture(page, { observation: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/audit");

  await expect(page.locator("#audit-selected-title"))
    .toHaveText("observation-campaign.source-transition");
  await expect(page.locator(".audit-context")).toContainText("metrics");
  await expect(page.locator(".audit-context")).toContainText("campaign-one");
  await expect(page.locator(".audit-context")).toContainText("Source observation");
  await expect(page.locator(".audit-context")).toContainText("Completed");
  await expect(page.locator(".audit-facts")).toContainText("Heimdall");
  await expect(page.locator(".audit-evidence")).toContainText("Source observation evidence");
  await expect(page.locator(".audit-evidence")).toContainText("Read-only");
  await expect(page.locator(".audit-evidence")).not.toContainText("Not recorded");
  await expect(page.locator(".audit-phases")).toHaveCount(0);
  await page.screenshot({
    path: testInfo.outputPath("audit-source-observation.png"),
    fullPage: true,
  });
  await page.goto("/audit?locale=ko");
  await expect(page.locator(".audit-context")).toContainText("소스 관측");
  await expect(page.locator(".audit-context")).toContainText("완료");
  await expect(page.locator(".audit-evidence")).toContainText("소스 관측 근거");
  await expect(page.locator(".audit-evidence")).toContainText("읽기 전용");
  await expect(page.locator(".audit-evidence")).not.toContainText("기록 없음");
  expect(await page.locator(".audit-route").evaluate(element =>
    element.scrollWidth <= element.clientWidth
  )).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("audit-source-observation-ko.png"),
    fullPage: true,
  });
});

test("many records keep a bounded rail and selected detail without truncating loaded rows", async ({ page }) => {
  await fixture(page, { count: 50 });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/audit");
  await expect(page.locator(".audit-record")).toHaveCount(50);
  const workspace = page.locator(".audit-workspace");
  const geometry = await workspace.evaluate(node => ({
    width: node.getBoundingClientRect().width,
    height: node.getBoundingClientRect().height,
  }));
  expect(geometry).toEqual({ width: 1232, height: 620 });
  const rail = page.locator(".audit-record-list");
  expect(await rail.evaluate(node => node.scrollHeight > node.clientHeight)).toBe(true);
  await page.locator(".audit-record").last().focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#audit-selected-title")).toHaveText("last.audit.record");
  await expect(page.locator(".audit-record").last()).toBeFocused();
  await expect(page.locator(".audit-record")).toHaveCount(50);
  await workspace.scrollIntoViewIfNeeded();
  await expect(page.locator("#audit-selected-title")).toBeInViewport();
  await page.locator(".audit-record-detail").focus();
  await expect(page.locator(".audit-record-detail")).toBeFocused();
  await page.keyboard.press("PageDown");
  await expect.poll(async () =>
    page.locator(".audit-record-detail").evaluate(node => node.scrollTop),
  ).toBeGreaterThan(0);
  await page.locator(".audit-record").first().click();
  await expect.poll(async () =>
    page.locator(".audit-record-detail").evaluate(node => node.scrollTop),
  ).toBeLessThanOrEqual(1);
  await expect(page.locator("#audit-selected-title")).toBeInViewport();
});

test("query controls retain deep-link bounds and distinguish loaded search from server filters", async ({ page }) => {
  const requests = await fixture(page);
  await page.goto(`/audit?correlation=${correlation}&action=risk_gate.unified&from_seq=41&through_seq=42`);
  await expect(page.locator(".audit-record")).toHaveCount(1);
  await page.getByRole("searchbox").fill("not-loaded");
  await page.getByLabel("Decision / outcome").selectOption("hil");
  await page.getByRole("combobox", { name: "Window", exact: true }).selectOption("7d");
  await page.getByRole("button", { name: "Apply query" }).click();
  await expect(page.getByText("No loaded records match this search. Load more or change the query.")).toBeVisible();
  const params = requests.at(-1)!.searchParams;
  expect(params.get("correlation_id")).toBe(correlation);
  expect(params.get("action")).toBe("risk_gate.unified");
  expect(params.get("from_seq")).toBe("41");
  expect(params.get("through_seq")).toBe("42");
  expect(params.get("outcome")).toBe("hil");
  expect(params.get("window")).toBe("7d");
  expect(params.has("q")).toBe(false);
  await page.getByText("More filters", { exact: true }).click();
  await page.getByRole("button", { name: "Clear filters" }).click();
  await expect(page).toHaveURL(/\/audit$/);
  await expect(page.locator(".audit-record")).toHaveCount(2);
});

test("pagination failure preserves the selected evidence and retry appends without duplicates", async ({ page }) => {
  await fixture(page, { paginated: true });
  await page.goto("/audit");
  await expect(page.locator(".audit-record")).toHaveCount(2);
  await page.locator(".audit-record").nth(1).click();
  await page.getByRole("button", { name: "Load more", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Audit source unavailable");
  await expect(page.locator("#audit-selected-title")).toHaveText("executor.dispatch.recorded");
  await page.getByRole("button", { name: "Load more", exact: true }).click();
  await expect(page.locator(".audit-record")).toHaveCount(3);
  await expect(page.locator("#audit-selected-title")).toHaveText("executor.dispatch.recorded");
});

test("loading, empty, unavailable exact record, and invalid filters do not fabricate records", async ({ page }) => {
  await fixture(page, { empty: true, delay: 350 });
  await page.goto("/audit");
  await expect(page.locator(".loading-skeleton[aria-busy=true]")).toBeVisible();
  await expect(page.getByText("Audit log is empty.")).toBeVisible();
  await expect(page.locator(".audit-record")).toHaveCount(0);
  await page.goto("/audit?entry=99");
  await expect(page.getByRole("alert")).toContainText("Audit entry #99 is unavailable");
  await expect(page.locator("#audit-selected-title")).toHaveCount(0);
  await page.goto("/audit?mode=invalid");
  await expect(page.getByRole("alert")).toContainText("Invalid audit filter");
  await expect(page.locator(".audit-query")).toBeVisible();
});

test("initial transport failure remains an error with editable recovery controls", async ({ page }) => {
  await fixture(page, { fail: true });
  await page.goto("/audit");
  await expect(page.getByRole("alert")).toContainText("Audit source unavailable");
  await expect(page.getByRole("button", { name: "Apply query" })).toBeVisible();
  await expect(page.locator(".audit-record")).toHaveCount(0);
});

for (const locale of ["en", "ko"]) {
  test(`desktop then constrained/mobile audit evidence reflows with long identities (${locale})`, async ({ page }, testInfo) => {
    await fixture(page, { long: true });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/audit?correlation=${correlation}&locale=${locale}`);
    await expect(page.locator(".audit-record")).toHaveCount(2);
    for (const viewport of [
      { width: 1440, height: 900 }, { width: 993, height: 641 },
      { width: 390, height: 844 }, { width: 320, height: 844 },
    ]) {
      await page.setViewportSize(viewport);
      await expect(page.locator("#audit-selected-title")).toBeVisible();
      for (const selector of ["html", "main", ".audit-route", ".audit-workspace", ".audit-record-detail"]) {
        expect(await page.locator(selector).evaluate(e => e.scrollWidth <= e.clientWidth), `${selector} at ${viewport.width}`).toBe(true);
      }
    }
    await page.locator(".audit-json-disclosure summary").focus();
    await page.keyboard.press("Enter");
    await expect(page.locator(".audit-json-disclosure")).not.toHaveAttribute("open", "");
    await page.keyboard.press("Enter");
    await expect(page.locator(".audit-json-disclosure")).toHaveAttribute("open", "");
    await page.screenshot({ path: testInfo.outputPath(`audit-workspace-${locale}-mobile.png`), fullPage: true });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.addStyleTag({ content: ".audit-route { --cs-type-body-size:28px; --cs-type-compact-size:26px; --cs-type-label-size:24px; --cs-type-section-title-size:36px; --cs-type-panel-title-size:30px; } .audit-route * { line-height:1.5!important; letter-spacing:.12em!important; word-spacing:.16em!important; }" });
    expect(await page.locator(".audit-route").evaluate(e => e.scrollWidth <= e.clientWidth)).toBe(true);
    await page.emulateMedia({ reducedMotion: "reduce", forcedColors: "active" });
    await page.locator(".audit-record").nth(1).focus();
    await page.keyboard.press("Enter");
    await expect(page.locator("#audit-selected-title")).toHaveText("executor.dispatch.recorded");
  });
}
