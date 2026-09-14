import { expect, test, type Locator, type Page, type Route } from "@playwright/test";

const correlationId = "demo-correlation-001";
const TRACE_FEEDBACK_BUDGET_MS = 1_000;
const TRACE_READY_BUDGET_MS = 2_000;
const actionIdentity = {
  action_id: "00000000-0000-0000-0000-000000000101",
  attempt: 1,
  execution_path: "direct_api",
} as const;
const trace = {
  correlation_id: correlationId,
  step_count: 6,
  steps: [
    {
      ...actionIdentity,
      seq: 192441,
      event_id: "event-1",
      source_correlation_id: correlationId,
      actor: "Bragi",
      recorded_at: "2026-09-14T02:00:01Z",
      stage: "plan",
      decision: null,
      reason: "proposal recorded",
      action_kind: "action.proposal.recorded",
      outcome: null,
      mode: "enforce",
      entry_hash: "hash-1",
      previous_hash: "hash-0",
    },
    {
      ...actionIdentity,
      seq: 192442,
      event_id: "event-2",
      source_correlation_id: correlationId,
      actor: "Forseti",
      recorded_at: "2026-09-14T02:00:02Z",
      stage: "risk-gate",
      decision: "hil",
      reason: "human approval required",
      action_kind: "risk_gate.unified",
      outcome: null,
      mode: "enforce",
      entry_hash: "hash-2",
      previous_hash: "hash-1",
    },
    {
      ...actionIdentity,
      seq: 192443,
      event_id: "event-3",
      source_correlation_id: correlationId,
      actor: "Var",
      recorded_at: "2026-09-14T02:00:03Z",
      stage: null,
      decision: null,
      reason: "approval recorded",
      action_kind: "hil.approved.execution_pending",
      outcome: "awaiting_effect_evidence",
      mode: "enforce",
      entry_hash: "hash-3",
      previous_hash: "hash-2",
    },
    {
      ...actionIdentity,
      seq: 192444,
      event_id: "event-4",
      source_correlation_id: correlationId,
      actor: "Thor",
      recorded_at: "2026-09-14T02:00:04Z",
      stage: "execute",
      decision: "pending",
      reason: "independent effect evidence pending",
      action_kind: "executor.remote.awaiting_effect_evidence",
      outcome: "awaiting_effect_evidence",
      mode: "enforce",
      entry_hash: "hash-4",
      previous_hash: "hash-3",
    },
    {
      ...actionIdentity,
      seq: 192445,
      event_id: "event-5",
      source_correlation_id: correlationId,
      actor: "Heimdall",
      recorded_at: "2026-09-14T02:00:05Z",
      stage: "verify",
      decision: "done",
      reason: "authoritative state matched",
      action_kind: "effect_observation.recorded",
      outcome: "observation_recorded",
      mode: "enforce",
      entry_hash: "hash-5",
      previous_hash: "hash-4",
    },
    {
      ...actionIdentity,
      seq: 192446,
      event_id: "event-6",
      source_correlation_id: "executor-correlation-006",
      actor: "Saga",
      recorded_at: "2026-09-14T02:00:06Z",
      stage: "audit",
      decision: "done",
      reason: "recovery receipt recorded",
      action_kind: "t2.proposer.route.rolled_back",
      outcome: "rollback_succeeded",
      mode: "enforce",
      entry_hash: "hash-6",
      previous_hash: "hash-5",
    },
  ],
  terminal_stage: "audit",
  trace_kind: "decision",
  source_authority: "operator-audit-log",
  complete: true,
  first_recorded_at: "2026-09-14T02:00:01Z",
  last_recorded_at: "2026-09-14T02:00:06Z",
  latest_sequence: 192446,
  latest_activity_stage: "audit",
  latest_action_kind: "t2.proposer.route.rolled_back",
  latest_actor: "Saga",
  latest_decision: "done",
  latest_outcome: "rollback_succeeded",
  latest_mode: "enforce",
  target_resource_ref: null,
  target_count: 0,
  action_attempt_count: 1,
  effect_observation_count: 1,
  incident_evidence_recorded: false,
  rca_evidence_recorded: false,
} as const;

const auditPage = {
  items: [...trace.steps].reverse().map((step) => ({
    seq: step.seq,
    event_id: step.event_id,
    correlation_id: step.source_correlation_id,
    actor: step.actor,
    action_kind: step.action_kind,
    mode: step.mode,
    entry: {
      stage: step.stage,
      decision: step.decision,
      reason: step.reason,
      action_id: step.action_id,
      attempt: step.attempt,
      execution_path: step.execution_path,
      outcome: step.outcome,
    },
    entry_hash: step.entry_hash,
    previous_hash: step.previous_hash,
    recorded_at: step.recorded_at,
  })),
  next_cursor: "older-audit",
} as const;

const readTrace = {
  correlation_id: correlationId,
  step_count: 2,
  steps: [
    {
      seq: 192446,
      event_id: correlationId,
      source_correlation_id: correlationId,
      recorded_at: "2026-09-14T08:52:01.859635+00:00",
      actor: "fdai.core.control_loop",
      stage: "t0_evaluate",
      decision: null,
      reason: "no_rule_denied",
      action_kind: "control_loop.compliant",
      mode: "shadow",
      action_id: null,
      attempt: null,
      execution_path: null,
      outcome: null,
      entry_hash: "hash-read-1",
      previous_hash: "hash-read-0",
    },
    {
      seq: 192449,
      event_id: correlationId,
      source_correlation_id: null,
      recorded_at: "2026-09-14T08:52:02.160953+00:00",
      actor: "fdai.measurement",
      stage: null,
      decision: null,
      reason: null,
      action_kind: "measurement.control_loop.v1",
      mode: "shadow",
      action_id: null,
      attempt: null,
      execution_path: null,
      outcome: null,
      entry_hash: "hash-read-2",
      previous_hash: "hash-read-1",
    },
  ],
  terminal_stage: "t0_evaluate",
  trace_kind: "read",
  source_authority: "operator-audit-log",
  complete: true,
  first_recorded_at: "2026-09-14T08:52:01.859635+00:00",
  last_recorded_at: "2026-09-14T08:52:02.160953+00:00",
  latest_sequence: 192449,
  latest_activity_stage: null,
  latest_action_kind: "measurement.control_loop.v1",
  latest_actor: "fdai.measurement",
  latest_decision: null,
  latest_outcome: null,
  latest_mode: "shadow",
  target_resource_ref: "checkout-api",
  target_count: 1,
  action_attempt_count: 0,
  effect_observation_count: 0,
  incident_evidence_recorded: false,
  rca_evidence_recorded: false,
} as const;

interface TraceFixtureOptions {
  readonly body?: unknown;
  readonly delayMs?: number;
  readonly status?: number;
}

async function installFixture(
  page: Page,
  options: TraceFixtureOptions = {},
): Promise<string[]> {
  const requestedPaths: string[] = [];
  const handle = async (route: Route): Promise<void> => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/, "");
    requestedPaths.push(path);
    if (path === "/system/data-sources") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          surface: "read-data-sources",
          sources: [
            {
              key: "audit",
              source: "browser-test-fixture",
              routes: ["/audit"],
              availability: "available",
              configured: true,
              reachable: true,
              authoritative: true,
              durable: true,
              synthetic: true,
              reason: null,
            },
          ],
        }),
      });
      return;
    }
    if (path === `/audit/${correlationId}/trace`) {
      if (options.delayMs !== undefined) {
        await new Promise((resolve) => setTimeout(resolve, options.delayMs));
      }
      const status = options.status ?? 200;
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(
          status === 200 ? options.body ?? trace : { detail: "trace projection failed" },
        ),
      });
      return;
    }
    if (path === "/audit") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(auditPage),
      });
      return;
    }
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: `unmocked browser-test route: ${path}` }),
    });
  };
  await page.route("**/api/**", handle);
  await page.route("**/system/data-sources", handle);
  await page.route("**/audit*", handle);
  await page.route("**/audit/**", handle);
  return requestedPaths;
}

async function contrastRatio(
  locator: Locator,
  property: "color" | "borderTopColor",
): Promise<number> {
  return locator.evaluate((element, cssProperty) => {
    type Rgba = [number, number, number, number];
    const canvas = document.createElement("canvas");
    canvas.width = 1;
    canvas.height = 1;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (context === null) throw new Error("canvas color parser is unavailable");

    const parse = (value: string): Rgba => {
      context.clearRect(0, 0, 1, 1);
      context.fillStyle = value;
      context.fillRect(0, 0, 1, 1);
      const [red = 0, green = 0, blue = 0, alpha = 0] =
        context.getImageData(0, 0, 1, 1).data;
      return [red, green, blue, alpha / 255];
    };
    const over = (front: Rgba, back: Rgba): Rgba => {
      const alpha = front[3] + back[3] * (1 - front[3]);
      if (alpha === 0) return [0, 0, 0, 0];
      return [
        (front[0] * front[3] + back[0] * back[3] * (1 - front[3])) / alpha,
        (front[1] * front[3] + back[1] * back[3] * (1 - front[3])) / alpha,
        (front[2] * front[3] + back[2] * back[3] * (1 - front[3])) / alpha,
        alpha,
      ];
    };
    const backgrounds: Rgba[] = [];
    let current: Element | null = element;
    while (current !== null) {
      backgrounds.push(parse(getComputedStyle(current).backgroundColor));
      current = current.parentElement;
    }
    let background: Rgba = [255, 255, 255, 1];
    for (let index = backgrounds.length - 1; index >= 0; index -= 1) {
      background = over(backgrounds[index]!, background);
    }
    const style = getComputedStyle(element);
    const foreground = over(
      parse(cssProperty === "color" ? style.color : style.borderTopColor),
      background,
    );
    const luminance = ([red, green, blue]: Rgba): number => {
      const channels = [red, green, blue].map((channel) => {
        const normalized = channel / 255;
        return normalized <= 0.04045
          ? normalized / 12.92
          : ((normalized + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * channels[0]! + 0.7152 * channels[1]! + 0.0722 * channels[2]!;
    };
    const lighter = Math.max(luminance(foreground), luminance(background));
    const darker = Math.min(luminance(foreground), luminance(background));
    return (lighter + 0.05) / (darker + 0.05);
  }, property);
}

function rgbContrastRatio(foreground: string, background: string): number {
  const parse = (value: string): readonly number[] =>
    value.match(/[\d.]+/g)?.slice(0, 3).map(Number) ?? [];
  const luminance = (value: string): number => {
    const channels = parse(value).map((channel) => {
      const normalized = channel / 255;
      return normalized <= 0.04045
        ? normalized / 12.92
        : ((normalized + 0.055) / 1.055) ** 2.4;
    });
    if (channels.length !== 3) throw new Error(`unrecognized RGB color: ${value}`);
    return 0.2126 * channels[0]! + 0.7152 * channels[1]! + 0.0722 * channels[2]!;
  };
  const foregroundLuminance = luminance(foreground);
  const backgroundLuminance = luminance(background);
  const lighter = Math.max(foregroundLuminance, backgroundLuminance);
  const darker = Math.min(foregroundLuminance, backgroundLuminance);
  return (lighter + 0.05) / (darker + 0.05);
}

async function assertLifecycle(
  page: Page,
  labels: readonly string[],
): Promise<void> {
  const [heading, ...stageLabels] = labels;
  if (heading === undefined) throw new Error("lifecycle labels are required");
  await expect(page.getByRole("heading", { name: heading })).toBeVisible();
  const lifecycleGroup = page.locator(".trace-action-lifecycle-group").first();
  await expect(lifecycleGroup).toContainText(actionIdentity.action_id);
  await expect(lifecycleGroup).toContainText(/Attempt 1|시도 1/);
  const lifecycle = page.locator(".trace-action-lifecycle");
  await expect(lifecycle.locator("li")).toHaveCount(6);
  for (const label of stageLabels) await expect(lifecycle).toContainText(label);
  await expect(lifecycle).toContainText("effect_observation.recorded");
  for (const selector of ["html", "main", ".trace-action-lifecycle"]) {
    const dimensions = await page.locator(selector).evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(
      dimensions.scrollWidth,
      `${selector} overflowed: ${dimensions.scrollWidth} > ${dimensions.clientWidth}`,
    ).toBeLessThanOrEqual(dimensions.clientWidth);
  }
}

async function assertTraceWorkbench(page: Page): Promise<void> {
  const metrics = page.locator(".trace-metric");
  await expect(metrics).toHaveCount(4);
  await expect(metrics.first()).toContainText(/Response decision|대응 결정/);

  const stages = page.locator(".trace-stage-select");
  await expect(stages).toHaveCount(trace.step_count);
  await expect(stages.last()).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".trace-stage-index")).toHaveText(["1", "2", "3", "4", "5", "6"]);
  const indexWidths = await page.locator(".trace-stage-index").evaluateAll((elements) =>
    elements.map((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    })),
  );
  expect(indexWidths.every(({ clientWidth, scrollWidth }) => scrollWidth <= clientWidth)).toBe(true);
  await stages.nth(3).focus();
  await expect(stages.nth(3)).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(stages.nth(3)).toHaveAttribute("aria-pressed", "true");
  const focusStyle = await stages.nth(3).evaluate((element) => {
    const style = getComputedStyle(element);
    return { outlineStyle: style.outlineStyle, outlineWidth: parseFloat(style.outlineWidth) };
  });
  expect(focusStyle.outlineStyle).not.toBe("none");
  expect(focusStyle.outlineWidth).toBeGreaterThanOrEqual(2);
  await page.keyboard.press("ArrowDown");
  await expect(stages.nth(4)).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("ArrowUp");
  await expect(stages.nth(3)).toHaveAttribute("aria-pressed", "true");

  const detail = page.locator("#trace-selected-stage-detail");
  await expect(detail.getByRole("heading", {
    name: /Independent effect evidence pending|독립 효과 근거 대기/,
  })).toBeVisible();
  await expect(detail).toContainText("executor.remote.awaiting_effect_evidence");
  await expect(detail).toContainText("independent effect evidence pending");
  await expect(detail).toContainText("event-4");
  await expect(detail).toContainText("Thor");
  await expect(detail.getByRole("heading", {
    name: /Audit references - chain not verified|감사 참조 - 체인 미검증/,
  })).toBeVisible();
  await expect(detail).toContainText(correlationId);
  const displayedTimestamp = detail.locator(".trace-step-facts time");
  await expect(displayedTimestamp).toHaveAttribute("datetime", "2026-09-14T02:00:04Z");
  expect(await displayedTimestamp.textContent()).not.toContain("T02:00:04Z");
  await expect(page.getByText(
    /Complete audit timeline \(6 records\)|전체 감사 타임라인 \(기록 6개\)/,
  )).toBeVisible();
  expect(await contrastRatio(detail.locator(".status-pill"), "color")).toBeGreaterThanOrEqual(4.5);
  expect(await contrastRatio(stages.nth(3), "borderTopColor")).toBeGreaterThanOrEqual(3);

  for (const selector of ["html", "main", ".trace-workbench"]) {
    const dimensions = await page.locator(selector).evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(
      dimensions.scrollWidth,
      `${selector} overflowed: ${dimensions.scrollWidth} > ${dimensions.clientWidth}`,
    ).toBeLessThanOrEqual(dimensions.clientWidth);
  }
  const timeline = page.locator(".trace-timeline-details");
  await timeline.locator("summary").click();
  await expect(timeline.locator("tbody tr")).toHaveCount(trace.step_count);
}

test.describe.configure({ mode: "serial" });

test("shows the correlated action lifecycle at desktop width", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium");
  await page.setViewportSize({ width: 1904, height: 900 });
  const requestedPaths = await installFixture(page);

  await page.goto(`/trace?correlation=${correlationId}`);
  await expect.poll(() => requestedPaths).toContain("/audit");

  await assertTraceWorkbench(page);
  const discovery = page.locator(".trace-discovery");
  await expect(discovery.locator("summary")).toContainText("2 recent correlations");
  await discovery.locator("summary").click();
  await expect(discovery.locator(".trace-discovery-list li")).toHaveCount(2);
  await discovery.getByRole("button", { name: "Decision / action" }).click();
  await expect(discovery.locator(".trace-discovery-list li")).toHaveCount(2);
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"], {
    origin: new URL(page.url()).origin,
  });
  await page.getByRole("button", { name: "Copy correlation id", exact: true }).click();
  await expect(page.getByRole("button", { name: "Copied" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh trace" })).toBeVisible();
  await expect(page.getByText("Evidence recorded", { exact: true })).toBeVisible();
  await discovery.locator("summary").click();
  const geometry = await page.locator(".trace-workbench").evaluate((workbench) => {
    const rail = workbench.querySelector(".trace-stage-rail");
    const detail = workbench.querySelector(".trace-step-detail");
    const route = workbench.closest(".trace-route");
    if (!(rail instanceof HTMLElement) || !(detail instanceof HTMLElement)) {
      throw new Error("trace workbench columns are missing");
    }
    return {
      workbenchWidth: workbench.getBoundingClientRect().width,
      railWidth: rail.getBoundingClientRect().width,
      detailWidth: detail.getBoundingClientRect().width,
      routeWidth: route?.getBoundingClientRect().width ?? 0,
    };
  });
  expect(geometry.routeWidth).toBeCloseTo(1320, 0);
  expect(geometry.railWidth).toBeCloseTo(276, 0);
  expect(geometry.detailWidth).toBeGreaterThan(500);
  expect(Math.abs(
    geometry.workbenchWidth - geometry.railWidth - geometry.detailWidth,
  )).toBeLessThanOrEqual(2);
  await page.locator(".page-header").scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath("trace-workspace-desktop.png") });

  await assertLifecycle(page, [
    "Action lifecycle evidence",
    "Proposal",
    "Decision",
    "Approval",
    "Dispatch",
    "Observation",
    "Recovery",
  ]);
});

test("compresses a read-only technical trace without inventing an action path", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium");
  await page.setViewportSize({ width: 1440, height: 900 });
  await installFixture(page, { body: readTrace });

  await page.goto(`/trace?correlation=${correlationId}`);

  await expect(page.locator(".trace-metric").filter({
    hasText: "Operational effect",
  })).toContainText("Not applicable");
  await expect(page.getByText("This trace contains no action attempt")).toBeVisible();
  await expect(page.getByText("checkout-api", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Control loop measurement" })).toBeVisible();
  await expect(page.getByText("Measurement service", { exact: true })).toBeVisible();
  await expect(page.getByText("No action path", { exact: true })).toBeVisible();
  await expect(page.getByText(
    "Joined into this trace through the matching event id; the source correlation may differ or be absent.",
  )).toBeVisible();
  await expect(page.locator(".trace-lifecycle-section.is-empty")).toBeVisible();
  await expect(page.locator(".trace-action-lifecycle-group")).toHaveCount(0);
  await expect(page.locator(".trace-workbench")).toHaveClass(/is-compact/);
});

test("preserves the two-column trace workbench at constrained desktop width", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium");
  await page.setViewportSize({ width: 993, height: 641 });
  await installFixture(page);

  await page.goto(`/trace?correlation=${correlationId}`);

  await assertTraceWorkbench(page);
  const geometry = await page.locator(".trace-workbench").evaluate((workbench) => {
    const rail = workbench.querySelector(".trace-stage-rail");
    const detail = workbench.querySelector(".trace-step-detail");
    if (!(rail instanceof HTMLElement) || !(detail instanceof HTMLElement)) {
      throw new Error("trace workbench columns are missing");
    }
    const railRect = rail.getBoundingClientRect();
    const detailRect = detail.getBoundingClientRect();
    return {
      railRight: railRect.right,
      detailLeft: detailRect.left,
      railWidth: railRect.width,
      detailWidth: detailRect.width,
    };
  });
  expect(geometry.railWidth).toBeCloseTo(276, 0);
  expect(geometry.detailWidth).toBeGreaterThan(400);
  expect(Math.abs(geometry.detailLeft - geometry.railRight)).toBeLessThanOrEqual(1);

  await page.locator(".trace-workbench").screenshot({
    path: testInfo.outputPath("trace-workbench-constrained.png"),
  });
});

test("keeps lookup context when trace evidence is unavailable", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium");
  await page.setViewportSize({ width: 1440, height: 900 });
  await installFixture(page);
  await page.goto("/trace");

  const lookup = page.getByRole("form", { name: "Look up a correlation id" });
  const input = lookup.getByRole("textbox", { name: "Correlation id" });
  await expect(page.locator(".trace-readonly-boundary summary"))
    .toContainText("Read-only reconstruction");
  await expect(page.locator(".trace-metric")).toHaveCount(4);
  await expect(page.locator(".trace-workbench")).toBeVisible();
  await expect(page.locator(".trace-discovery")).toHaveAttribute("open", "");
  await expect(page.locator(".trace-discovery-list li")).toHaveCount(2);
  await expect(page.getByRole("heading", {
    name: "Select a correlation to inspect its recorded path",
  })).toBeVisible();
  await expect(page.getByText("No stages selected")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("trace-idle-desktop.png") });

  await input.fill("missing-correlation");
  await lookup.getByRole("button", { name: "Fetch trace" }).click();

  await expect(page.getByText("No audit steps for this correlation id.")).toBeVisible();
  await expect(page.getByRole("heading", {
    name: "No trace evidence is available for this correlation",
  })).toBeVisible();
  await expect(page.locator(".trace-workbench")).toBeVisible();
  await expect(input).toHaveValue("missing-correlation");
  await expect(lookup.getByRole("link", { name: "Audit" })).toHaveAttribute(
    "href",
    /correlation=missing-correlation/,
  );
});

test("preserves the mock-aligned workspace while loading and after an unexpected error", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium");
  await page.setViewportSize({ width: 1440, height: 900 });
  await installFixture(page, { delayMs: 700, status: 500 });

  await page.goto(`/trace?correlation=${correlationId}`);

  const workbench = page.locator(".trace-workbench");
  await expect(workbench).toHaveAttribute("aria-busy", "true");
  await expect(page.getByRole("heading", { name: "Loading the recorded path" })).toBeVisible();
  await expect(page.locator(".trace-metric")).toHaveCount(4);
  await expect(page.locator(".trace-stage-rail")).toBeVisible();

  await expect(page.getByRole("heading", { name: "The trace could not be loaded" }))
    .toBeVisible();
  await expect(workbench).toHaveAttribute("aria-busy", "false");
  await expect(page.locator(".trace-toolbar input")).toHaveValue(correlationId);
  await expect(page.getByRole("alert")).toContainText("Trace could not be loaded: HTTP 500");
});

test("meets the local trace feedback and ready-state budgets without losing input", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium");
  await page.setViewportSize({ width: 1440, height: 900 });
  await installFixture(page, { delayMs: 700 });

  const startedAt = Date.now();
  await page.goto(`/trace?correlation=${correlationId}`);
  await expect(page.getByRole("heading", { name: "Loading the recorded path" }))
    .toBeVisible({ timeout: TRACE_FEEDBACK_BUDGET_MS });
  const feedbackMs = Date.now() - startedAt;
  await expect(page.locator(".trace-stage-select")).toHaveCount(trace.step_count, {
    timeout: TRACE_READY_BUDGET_MS,
  });
  const readyMs = Date.now() - startedAt;

  expect(feedbackMs).toBeLessThanOrEqual(TRACE_FEEDBACK_BUDGET_MS);
  expect(readyMs).toBeLessThanOrEqual(TRACE_READY_BUDGET_MS);
  await expect(page.locator(".trace-toolbar input")).toHaveValue(correlationId);
});

test("renders a successful empty response as unavailable rather than collapsing the workbench", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium");
  await page.setViewportSize({ width: 1440, height: 900 });
  await installFixture(page, {
    body: {
      correlation_id: correlationId,
      step_count: 0,
      steps: [],
      terminal_stage: null,
    },
  });

  await page.goto(`/trace?correlation=${correlationId}`);

  await expect(page.getByRole("heading", {
    name: "No trace evidence is available for this correlation",
  })).toBeVisible();
  await expect(page.locator(".trace-workbench")).toBeVisible();
  await expect(page.locator(".trace-stage-select")).toHaveCount(0);
  await expect(page.locator(".trace-toolbar input")).toHaveValue(correlationId);
});

test("keeps the newest stage visible in a bounded long trace rail", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium");
  await page.setViewportSize({ width: 1440, height: 900 });
  const steps = Array.from({ length: 24 }, (_, index) => ({
    action_id: null,
    attempt: null,
    execution_path: null,
    outcome: null,
    seq: 193000 + index,
    event_id: `event-${index + 1}`,
    source_correlation_id: correlationId,
    actor: "Saga",
    recorded_at: `2026-09-14T02:00:${String(index).padStart(2, "0")}Z`,
    stage: index === 23 ? "audit" : `stage-${index + 1}`,
    decision: null,
    reason: `recorded step ${index + 1}`,
    action_kind: `test.stage.${index + 1}`,
    mode: "shadow",
    entry_hash: `hash-${index + 1}`,
    previous_hash: `hash-${index}`,
  }));
  await installFixture(page, {
    body: {
      correlation_id: correlationId,
      step_count: steps.length,
      steps,
      terminal_stage: "audit",
    },
  });

  await page.goto(`/trace?correlation=${correlationId}`);

  const rail = page.locator(".trace-stage-list");
  const stages = page.locator(".trace-stage-select");
  await expect(stages).toHaveCount(24);
  expect(await rail.evaluate((element) => {
    const selected = element.querySelector(".trace-stage-select[aria-pressed=\"true\"]");
    if (!(selected instanceof HTMLElement)) return false;
    const railRect = element.getBoundingClientRect();
    const selectedRect = selected.getBoundingClientRect();
    return selectedRect.top >= railRect.top && selectedRect.bottom <= railRect.bottom;
  })).toBe(true);
  expect(await rail.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true);
  expect(await rail.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  await stages.last().press("Home");
  await expect(stages.first()).toHaveAttribute("aria-pressed", "true");
  expect(await rail.evaluate((element) => {
    const selected = element.querySelector(".trace-stage-select[aria-pressed=\"true\"]");
    if (!(selected instanceof HTMLElement)) return false;
    const railRect = element.getBoundingClientRect();
    const selectedRect = selected.getBoundingClientRect();
    return selectedRect.top >= railRect.top && selectedRect.bottom <= railRect.bottom;
  })).toBe(true);
});

test("keeps trace meaning in dark, reduced-motion, and forced-color preferences", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
  await installFixture(page);
  await page.goto(`/trace?correlation=${correlationId}`);
  await page.evaluate(() => localStorage.setItem("fdai:console:theme", "dark"));
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.locator(".trace-stage-select")).toHaveCount(trace.step_count);

  for (const { foreground, background } of [
    { foreground: ".trace-step-head h3", background: ".trace-workbench" },
    { foreground: ".trace-stage-copy strong", background: ".trace-stage-rail" },
    { foreground: ".trace-stage-state", background: ".trace-stage-rail" },
    { foreground: ".trace-metric small", background: "body" },
  ]) {
    const foregroundColor = await page.locator(foreground).first()
      .evaluate((element) => getComputedStyle(element).color);
    const backgroundColor = await page.locator(background).first()
      .evaluate((element) => getComputedStyle(element).backgroundColor);
    expect(
      rgbContrastRatio(foregroundColor, backgroundColor),
      `${foreground} on ${background}`,
    ).toBeGreaterThanOrEqual(4.5);
  }
  expect(await page.locator(".trace-route *").evaluateAll((elements) =>
    elements.every((element) => {
      const style = getComputedStyle(element);
      return style.animationDuration === "0s" || style.animationName === "none";
    }),
  )).toBe(true);

  await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
  await page.reload();
  await expect(page.locator(".trace-stage-select[aria-pressed=\"true\"]")).toBeVisible();
  const forcedColorState = await page.locator(".trace-stage-select[aria-pressed=\"true\"]")
    .evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        active: matchMedia("(forced-colors: active)").matches,
        borderStyle: style.borderTopStyle,
        borderWidth: parseFloat(style.borderTopWidth),
        outlineWidth: parseFloat(style.outlineWidth),
      };
    });
  expect(forcedColorState.active).toBe(true);
  expect(forcedColorState.borderStyle).not.toBe("none");
  expect(forcedColorState.borderWidth).toBeGreaterThanOrEqual(1);
  expect(forcedColorState.outlineWidth).toBeGreaterThanOrEqual(2);
});

test("survives 200 percent equivalent width and user text spacing", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium");
  await page.setViewportSize({ width: 952, height: 900 });
  await installFixture(page);
  await page.goto(`/trace?correlation=${correlationId}`);
  await page.locator(".trace-stage-select").nth(3).click();
  await page.addStyleTag({
    content: `
      .trace-route, .trace-route * {
        line-height: 1.5 !important;
        letter-spacing: .12em !important;
        word-spacing: .16em !important;
      }
      .trace-route p { margin-bottom: 2em !important; }
    `,
  });

  await expect(page.getByRole("heading", {
    name: /Independent effect evidence pending|독립 효과 근거 대기/,
  })).toBeVisible();
  for (const selector of ["html", "main", ".trace-route", ".trace-workbench"]) {
    const dimensions = await page.locator(selector).evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(
      dimensions.scrollWidth,
      `${selector} overflowed with enlarged text spacing`,
    ).toBeLessThanOrEqual(dimensions.clientWidth);
  }
});

test("reflows the correlated action lifecycle at mobile width", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile-chromium");
  await page.setViewportSize({ width: 390, height: 844 });
  await installFixture(page);

  await page.goto(`/trace?correlation=${correlationId}&locale=ko`);

  await assertTraceWorkbench(page);
  const metricRows = await page.locator(".trace-metric").evaluateAll((metrics) =>
    [...new Set(metrics.map((metric) => Math.round(metric.getBoundingClientRect().top)))]
  );
  expect(metricRows).toHaveLength(2);
  await expect(page.locator(".trace-context-details > summary")).toBeVisible();
  await expect(page.locator(".trace-context-strip")).toBeHidden();
  const workbenchDistance = await page.evaluate(() => {
    const route = document.querySelector(".trace-route")?.getBoundingClientRect();
    const workbench = document.querySelector(".trace-workbench")?.getBoundingClientRect();
    return route && workbench ? workbench.top - route.top : Number.POSITIVE_INFINITY;
  });
  expect(workbenchDistance).toBeLessThan(844 * 2);
  const geometry = await page.locator(".trace-workbench").evaluate((workbench) => {
    const rail = workbench.querySelector(".trace-stage-rail");
    const detail = workbench.querySelector(".trace-step-detail");
    if (!(rail instanceof HTMLElement) || !(detail instanceof HTMLElement)) {
      throw new Error("trace workbench sections are missing");
    }
    const railRect = rail.getBoundingClientRect();
    const detailRect = detail.getBoundingClientRect();
    return {
      railBottom: railRect.bottom,
      detailTop: detailRect.top,
      stageTargetHeight: workbench.querySelector(".trace-stage-select")?.getBoundingClientRect().height,
    };
  });
  expect(geometry.detailTop).toBeGreaterThanOrEqual(geometry.railBottom - 1);
  expect(geometry.stageTargetHeight).toBeGreaterThanOrEqual(44);
  const targetHeights = await page.locator(
    ".trace-toolbar input, .trace-toolbar a, .trace-toolbar button, .trace-stage-select",
  ).evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().height));
  expect(Math.min(...targetHeights)).toBeGreaterThanOrEqual(44);
  await page.locator(".page-header").scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath("trace-workspace-mobile-ko.png") });

  await assertLifecycle(page, [
    "액션 수명 주기 근거",
    "제안",
    "판단",
    "승인",
    "전달",
    "관측",
    "복구",
  ]);
  await page.setViewportSize({ width: 320, height: 844 });
  for (const selector of ["html", "main", ".trace-workbench"]) {
    const dimensions = await page.locator(selector).evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(
      dimensions.scrollWidth,
      `${selector} overflowed at 320px: ${dimensions.scrollWidth} > ${dimensions.clientWidth}`,
    ).toBeLessThanOrEqual(dimensions.clientWidth);
  }
});
