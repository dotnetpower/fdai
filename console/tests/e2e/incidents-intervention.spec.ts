import { expect, test, type Page, type Route } from "@playwright/test";

const correlationId = "incident-intervention-e2e";
const incidentId = "00000000-0000-0000-0000-000000000201";
const targetRef = `sha256:${"b".repeat(64)}`;

const incident = {
  correlation_id: correlationId,
  incident_id: incidentId,
  incident_number: "INC-202608-0201",
  lifecycle_state: "triaging",
  target_ref: targetRef,
  ticket_id: null,
  title: "Checkout latency during development rollout",
  title_source: "recorded_title",
  source: null,
  response_plan: null,
  severity: "high",
  status: "in_progress",
  status_source: "incident_lifecycle",
  disposition: "investigating",
  verdict: "hil",
  vertical: "change_safety",
  opened_at: "2026-08-24T11:00:00Z",
  last_updated_at: "2026-08-24T11:01:00Z",
  latest_mode: "shadow",
  history_count: 1,
  involved_agents: ["Huginn", "Forseti"],
};

const metrics = {
  source: "deterministic browser fixture",
  snapshot_seq: 1,
  denominator: 1,
  matched_total: 1,
  truncated: false,
  window_from: "2026-08-24T11:00:00Z",
  window_to: "2026-08-24T11:01:00Z",
  cohorts: {
    agent_mitigated: 0,
    agent_assisted: 0,
    human_mitigated: 0,
    pending: 1,
    integrity_excluded: 0,
  },
  drilldown: {
    agent_mitigated: [],
    agent_assisted: [],
    human_mitigated: [],
    pending: [correlationId],
    integrity_excluded: [],
  },
  drilldown_truncated: {
    agent_mitigated: false,
    agent_assisted: false,
    human_mitigated: false,
    pending: false,
    integrity_excluded: false,
  },
  median_time_to_mitigate_seconds: null,
  time_to_mitigate_sample_size: 0,
  terminal_rule: "resolved_and_independently_verified",
};

function json(route: Route, payload: unknown, status = 200): Promise<void> {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(payload),
  });
}

async function installFixture(
  page: Page,
  options: { failFirstPost?: boolean; paginatedAudit?: boolean } = {},
): Promise<{
  body: () => Record<string, unknown> | null;
  idempotencyKey: () => string | null;
  bodies: () => readonly Record<string, unknown>[];
  idempotencyKeys: () => readonly string[];
  auditCursors: () => readonly (string | null)[];
}> {
  const capturedBodies: Record<string, unknown>[] = [];
  const capturedIdempotencyKeys: string[] = [];
  const capturedAuditCursors: (string | null)[] = [];
  const handle = async (route: Route): Promise<void> => {
    const request = route.request();
    if (request.isNavigationRequest()) {
      await route.continue();
      return;
    }
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api(?=\/)/, "");
    if (path === "/system/data-sources") {
      await json(route, {
        surface: "read-data-sources",
        sources: [{
          key: "incident-browser-fixture",
          source: "deterministic browser fixture",
          routes: ["/incidents", "/audit"],
          availability: "available",
          configured: true,
          reachable: true,
          authoritative: true,
          durable: true,
          synthetic: true,
          reason: null,
          last_observed_at: "2026-08-24T11:01:00Z",
        }],
      });
      return;
    }
    if (request.method() === "POST" && path.endsWith("/interventions")) {
      capturedBodies.push(request.postDataJSON() as Record<string, unknown>);
      capturedIdempotencyKeys.push(request.headers()["idempotency-key"] ?? "");
      if (options.failFirstPost === true && capturedBodies.length === 1) {
        await json(route, { error: { message: "Temporary intervention transport failure." } }, 503);
        return;
      }
      await json(route, {
        request_id: "00000000-0000-0000-0000-000000000301",
        correlation_id: correlationId,
        dispatch_status: "pending",
        accepted_at: "2026-08-24T11:02:00Z",
        durably_queued: true,
      }, 202);
      return;
    }
    if (path === "/incidents") {
      await json(route, {
        items: [{ ...incident, history_count: options.paginatedAudit === true ? 4 : 1 }],
        next_cursor: null,
        metrics,
      });
      return;
    }
    if (path === "/audit") {
      const cursor = url.searchParams.get("cursor");
      capturedAuditCursors.push(cursor);
      const auditItem = (seq: number, actionKind: string) => ({
        seq,
        event_id: `event-${seq}`,
        correlation_id: correlationId,
        actor: seq === 1 ? "Huginn" : "Saga",
        action_kind: actionKind,
        mode: "shadow",
        entry: { kind: actionKind },
        entry_hash: `hash-${seq}`,
        previous_hash: `hash-${seq - 1}`,
        recorded_at: `2026-08-24T11:0${seq}:00Z`,
      });
      if (options.paginatedAudit === true && cursor === null) {
        await json(route, {
          items: [auditItem(4, "event.four"), auditItem(3, "event.three")],
          next_cursor: "older",
        });
        return;
      }
      if (options.paginatedAudit === true && cursor === "older") {
        await json(route, {
          items: [auditItem(2, "event.two"), auditItem(1, "event.one")],
          next_cursor: null,
        });
        return;
      }
      await json(route, { items: [], next_cursor: null });
      return;
    }
    await json(route, { error: { message: `unmocked route: ${path}` } }, 404);
  };
  await page.route("**/api/**", handle);
  await page.route("**/system/data-sources*", handle);
  await page.route("**/incidents?*", handle);
  await page.route("**/incidents/*/interventions", handle);
  await page.route("**/audit?*", handle);
  return {
    body: () => capturedBodies.at(-1) ?? null,
    idempotencyKey: () => capturedIdempotencyKeys.at(-1) ?? null,
    bodies: () => capturedBodies,
    idempotencyKeys: () => capturedIdempotencyKeys,
    auditCursors: () => capturedAuditCursors,
  };
}

test("submits a bounded Incident intervention without claiming it was applied", async ({
  page,
}, testInfo) => {
  const fixture = await installFixture(page);
  await page.goto(`/incidents?correlation=${encodeURIComponent(correlationId)}`);

  const summary = page.getByRole("region", { name: "Incident operational summary" });
  await expect(summary).toContainText("1Loaded now");
  await expect(summary).toContainText("1Pending outcomes");
  await expect(page.locator(".incident-roster-stage").first()).toHaveAttribute(
    "aria-label",
    "Approval, step 2 of 4",
  );
  const outcome = page.locator("details.incident-outcome-analytics");
  await expect(outcome).not.toHaveAttribute("open", "");
  const outcomeSummary = outcome.locator(":scope > summary");
  await outcomeSummary.focus();
  await page.keyboard.press("Enter");
  await expect(outcome).toHaveAttribute("open", "");
  await page.keyboard.press("Enter");
  await expect(outcome).not.toHaveAttribute("open", "");

  const trigger = page.getByRole("button", { name: "Intervene", exact: true });
  await expect(trigger).toBeVisible();
  await trigger.click();

  const dialog = page.getByRole("dialog", { name: "Intervene in this incident" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("INC-202608-0201", { exact: true })).toBeVisible();
  await expect(dialog).not.toContainText(targetRef);

  await dialog.getByLabel("Request type").selectOption("create_development_exception");
  await dialog.getByLabel("Duration").selectOption("one_week");
  await dialog.getByLabel("Operator context and justification").fill(
    "The service is under active development for this rollout window.",
  );
  await dialog.getByRole("button", { name: "Review request" }).click();
  await expect(dialog.getByText("One week", { exact: true })).toBeVisible();
  await expect(dialog).toContainText("This request grants no execution authority");
  await dialog.getByRole("button", { name: "Submit request" }).click();

  await expect(dialog.getByText("Intervention durably queued", { exact: true })).toBeVisible();
  await expect(dialog).toContainText("Acceptance does not claim that the Incident changed");
  await expect.poll(fixture.body).toMatchObject({
    action: "create_development_exception",
    incident_id: incidentId,
    correlation_id: correlationId,
    expected_state: "triaging",
    duration: "one_week",
    comment: "The service is under active development for this rollout window.",
  });
  expect(fixture.idempotencyKey()).toMatch(/^[0-9a-f-]{36}$/);

  const geometry = await dialog.evaluate((element) => {
    const bounds = element.getBoundingClientRect();
    return {
      documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      dialogOverflow: element.scrollWidth - element.clientWidth,
      left: bounds.left,
      right: bounds.right,
      top: bounds.top,
      bottom: bounds.bottom,
      viewportWidth: innerWidth,
      viewportHeight: innerHeight,
    };
  });
  expect(geometry.documentOverflow).toBe(0);
  expect(geometry.dialogOverflow).toBe(0);
  expect(geometry.left).toBeGreaterThanOrEqual(0);
  expect(geometry.right).toBeLessThanOrEqual(geometry.viewportWidth);
  expect(geometry.top).toBeGreaterThanOrEqual(0);
  expect(geometry.bottom).toBeLessThanOrEqual(geometry.viewportHeight);

  await page.screenshot({
    path: testInfo.outputPath(`incident-intervention-${testInfo.project.name}.png`),
    fullPage: true,
  });
  await dialog.getByRole("button", { name: "Done" }).click();
  await expect(dialog).not.toBeVisible();
  await expect(trigger).toBeFocused();
});

test("rotates idempotency when exception parameters change after failure", async ({ page }) => {
  const fixture = await installFixture(page, { failFirstPost: true });
  await page.goto(`/incidents?correlation=${encodeURIComponent(correlationId)}`);
  await page.getByRole("button", { name: "Intervene", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Intervene in this incident" });

  await dialog.getByLabel("Request type").selectOption("create_development_exception");
  await dialog.getByLabel("Duration").selectOption("one_week");
  await dialog.getByLabel("Operator context and justification").fill(
    "Development rollout requires a bounded exception.",
  );
  await dialog.getByRole("button", { name: "Review request" }).click();
  await dialog.getByRole("button", { name: "Submit request" }).click();
  await expect(dialog.getByRole("alert")).toContainText("Temporary intervention transport failure");

  await dialog.getByRole("button", { name: "Back" }).click();
  await expect(dialog.getByRole("alert")).toHaveCount(0);
  await dialog.getByLabel("Duration").selectOption("one_month");
  await dialog.getByRole("button", { name: "Review request" }).click();
  await dialog.getByRole("button", { name: "Submit request" }).click();
  await expect(dialog.getByText("Intervention durably queued", { exact: true })).toBeVisible();

  expect(fixture.bodies()).toHaveLength(2);
  expect(fixture.bodies()[0]).toMatchObject({ duration: "one_week" });
  expect(fixture.bodies()[1]).toMatchObject({ duration: "one_month" });
  expect(fixture.idempotencyKeys()).toHaveLength(2);
  expect(fixture.idempotencyKeys()[0]).not.toBe(fixture.idempotencyKeys()[1]);
});

test("loads older Incident activity without losing chronological order", async ({ page }) => {
  const fixture = await installFixture(page, { paginatedAudit: true });
  await page.goto(`/incidents?correlation=${encodeURIComponent(correlationId)}`);

  const timeline = page.locator(".incident-timeline");
  await expect(timeline.locator(".incident-timeline-event")).toHaveCount(2);
  const handoff = page.getByRole("region", { name: "Agent response handoff" });
  await expect(handoff).toBeVisible();
  await expect(handoff.locator("li")).toHaveCount(1);
  await expect(page.getByText("2 of 4 records - chronological order.")).toBeVisible();
  await page.getByRole("button", { name: "Load older activity" }).click();
  await expect(timeline.locator(".incident-timeline-event")).toHaveCount(4);
  await expect(page.getByRole("button", { name: "Load older activity" })).toHaveCount(0);
  await expect(timeline.locator(".incident-timeline-kind")).toHaveText([
    "event.one",
    "event.two",
    "event.three",
    "event.four",
  ]);
  await expect(handoff.locator("li")).toHaveCount(2);
  await expect(handoff.locator("li strong")).toHaveText(["Huginn", "Saga"]);
  expect(fixture.auditCursors()).toEqual([null, "older"]);
  expect(await page.evaluate(() => (
    document.documentElement.scrollWidth - document.documentElement.clientWidth
  ))).toBe(0);
});
