import { expect, test, type Page, type Route } from "@playwright/test";

const correlationId = "local-parity:incident-selected";
const incidentId = `INC-${correlationId}`;

const incident = {
  correlation_id: correlationId,
  incident_id: incidentId,
  ticket_id: null,
  title: "Environment tag required",
  title_source: "recorded_title",
  source: null,
  response_plan: null,
  severity: "medium",
  status: "in_progress",
  status_source: "incident_lifecycle",
  disposition: "investigating",
  verdict: "hil",
  vertical: "change-safety",
  opened_at: "2026-07-22T00:00:00Z",
  last_updated_at: "2026-07-22T00:01:00Z",
  latest_mode: "shadow",
  history_count: 3,
  involved_agents: ["Var", "Forseti"],
};

const incidentMetrics = {
  source: "deterministic browser fixture",
  snapshot_seq: 1,
  denominator: 1,
  matched_total: 1,
  truncated: false,
  window_from: null,
  window_to: null,
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

function sse(route: Route, frames: readonly string[]): Promise<void> {
  return route.fulfill({
    status: 200,
    contentType: "text/event-stream",
    body: `${frames.join("\n\n")}\n\n`,
  });
}

async function installOperatorApiFixture(
  page: Page,
  options: {
    readonly answer?: string;
    readonly executionTimeline?: boolean;
    readonly modelTrace?: boolean;
    readonly presentationArtifact?: Record<string, unknown>;
    readonly source?: string;
    readonly streamDelayMs?: number;
  } = {},
): Promise<{
  readonly chatBody: () => Record<string, unknown> | null;
}> {
  let capturedChatBody: Record<string, unknown> | null = null;
  const handleApi = async (route: Route): Promise<void> => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api(?=\/)/, "");
    if (path === "/system/data-sources") {
      await json(route, {
        surface: "read-data-sources",
        sources: [{
          key: "browser-test-read-model",
          source: "deterministic browser fixture",
          routes: ["/incidents", "/agents"],
          availability: "available",
          configured: true,
          reachable: true,
          authoritative: true,
          durable: true,
          synthetic: true,
          reason: null,
          last_observed_at: "2026-07-22T00:01:00Z",
        }],
      });
      return;
    }
    if (path === "/incidents") {
      await json(route, { items: [incident], next_cursor: null, metrics: incidentMetrics });
      return;
    }
    if (path === "/agents/stream") {
      await sse(route, [
        `data: ${JSON.stringify({
          type: "agent.state",
          agent: "Var",
          state: "approving",
          ts: "2026-07-22T00:01:00Z",
          correlation_id: correlationId,
          detail: "Reviewing the incident approval evidence.",
          source: "runtime-observed",
        })}`,
      ]);
      return;
    }
    if (path === "/chat/health") {
      await json(route, {
        available: true,
        mode: "azure-ad-routed",
        model: "narrator-fast",
        endpoint: "https://chat.example.com",
        router: {
          chose: "narrator-fast",
          reason: "latency",
          candidates: [
            {
              deployment: "narrator-fast",
              p50_ms: 1149,
              p95_ms: 1390,
              samples: 2,
              history_ms: [1149, 1390],
            },
            {
              deployment: "narrator-safe",
              p50_ms: 5507,
              p95_ms: 6086,
              samples: 2,
              history_ms: [5507, 6086],
            },
          ],
        },
      });
      return;
    }
    if (path === "/chat/stream") {
      capturedChatBody = request.postDataJSON() as Record<string, unknown>;
      const answer = options.answer ?? (
        `${correlationId} (Environment tag required) is investigating and was last updated ` +
        "at 2026-07-22T00:01:00Z, but no grounded root cause with citations is recorded. " +
        "The cause cannot be confirmed.\n\nCurrent recorded agent activity:\n" +
        "- Var: hil.requested at 2026-07-22T00:01:00Z\n" +
        "- Forseti: risk_gate.decided at 2026-07-22T00:00:30Z"
      );
      const frames = options.executionTimeline ? [
        `event: branch\ndata: ${JSON.stringify({
          seq: 1,
          revision: 0,
          branch_id: "request-1:tool",
          branch_kind: "tool",
          parent_branch_id: null,
          status: "completed",
          summary: "tool evidence ready",
          started_at: "2026-07-22T00:01:00Z",
          completed_at: "2026-07-22T00:01:00.008Z",
          duration_ms: 8,
          evidence_refs: ["tool:inventory:1"],
        })}`,
        `event: activity\ndata: ${JSON.stringify({
          seq: 2,
          revision: 0,
          activity_id: "inspect-inventory",
          branch_id: "request-1:tool",
          kind: "inventory.querying",
          status: "completed",
          label: "Inspect server-owned read evidence",
          completed: 1,
          total: 1,
          authority: "server_inventory_graph",
          execution: {
            tool: "FDAI inventory",
            command: JSON.stringify({
              operation: "query_inventory",
              authority: "server_inventory_graph",
              query: { source: "current", kind: "list", predicates: [] },
            }, null, 2),
            input_kind: "query",
            redacted: true,
            output: JSON.stringify({
              status: "matched",
              matched_count: 1,
              resources: [{
                name: "vm-example",
                type: "virtual-machine",
                status: "running",
              }],
            }),
            output_truncated: false,
            exit_code: null,
            started_at: "2026-07-22T00:01:00Z",
            completed_at: "2026-07-22T00:01:00.008Z",
            duration_ms: 8,
          },
        })}`,
        `event: activity\ndata: ${JSON.stringify({
          seq: 3,
          revision: 0,
          activity_id: "semantic-planning",
          kind: "semantic_turn",
          status: "completed",
          label: "Waiting for a verified semantic plan.",
          completed: 1,
          total: 1,
          authority: "read_only",
        })}`,
      ] : [];
      frames.push(
        `event: done\ndata: ${JSON.stringify({
          seq: options.executionTimeline ? 4 : 1,
          revision: 1,
          answer,
          model: "narrator-test",
          source: options.source ?? "evidence:corrected",
          ...(options.modelTrace ? {
            model_trace: {
              schema_version: 1,
              redacted: true,
              omitted_calls: 0,
              calls: [{
                call_id: "call-1",
                kind: "answer-stream",
                model: "narrator-test",
                status: "completed",
                started_at: "2026-07-22T00:01:00Z",
                completed_at: "2026-07-22T00:01:02Z",
                duration_ms: 2000,
                request: {
                  messages: [
                    { role: "system", content: "Safety layer" },
                    { role: "system", content: '{"policy":{"status":"ready"}}' },
                    {
                      role: "user",
                      content: JSON.stringify({
                        untrusted_input: {
                          question: "List resource groups",
                          capabilities: [{ kind: "object_type", name: "Resource" }],
                        },
                      }),
                    },
                  ],
                  sha256: "a".repeat(64),
                },
                response: {
                  role: "assistant",
                  content: JSON.stringify({
                    result: JSON.stringify({ status: "ready", matched: 1 }),
                  }),
                  sha256: "b".repeat(64),
                },
                usage: { prompt_tokens: 100, completion_tokens: 20, total_tokens: 120 },
                redactions: [],
              }],
            },
          } : {}),
          verification: {
            status: "corrected",
            authority: "server_read_model",
            checks_completed: 1,
            checks_total: 1,
            evidence_refs: [`incident:${correlationId}`],
            reason_code: "no_grounded_rca",
            claims: [],
            failed_claim_ids: [],
          },
          ...(options.presentationArtifact
            ? { presentation_artifact: options.presentationArtifact }
            : {}),
        })}`,
      );
      if (options.streamDelayMs && options.streamDelayMs > 0) {
        await new Promise((resolve) => setTimeout(resolve, options.streamDelayMs));
      }
      await sse(route, frames);
      return;
    }
    await json(route, { detail: `unmocked browser-test route: ${url.pathname}` }, 404);
  };
  await page.route("**/api/**", handleApi);
  await page.route("**/system/data-sources*", handleApi);
  await page.route("**/incidents*", handleApi);
  return { chatBody: () => capturedChatBody };
}

const presentationRef = `incident:${correlationId}`;
const timeSeriesDescription = (
  "동일한 단위로 검증된 요청 수를 시간 순서대로 표시하며 누락된 값은 추론하지 않습니다."
);
const timeSeriesPresentation = {
  schema_version: 2,
  layout: "stack",
  evidence_refs: [presentationRef],
  blocks: [
    {
      slot_id: "trend",
      kind: "time_series",
      title: "검증된 요청 추세와 매우 긴 한국어 운영 설명",
      emphasis: "primary",
      collapsed: false,
      evidence_refs: [presentationRef],
      data: {
        description: timeSeriesDescription,
        metric: "requests",
        unit: "count",
        points: [
          { timestamp: "2026-08-19T00:00:00Z", value: 1 },
          { timestamp: "2026-08-19T00:01:00Z", value: 3 },
          { timestamp: "2026-08-19T00:02:00Z", value: 2 },
        ],
        exact_table: {
          columns: [
            { key: "c0", label: "timestamp" },
            { key: "c1", label: "value" },
            { key: "c2", label: "opaque id" },
          ],
          rows: [
            {
              c0: "2026-08-19T00:00:00Z",
              c1: "1",
              c2: "result_01J5R1GQ7RM8M7PPQ4TYG9WXYZ",
            },
            {
              c0: "2026-08-19T00:01:00Z",
              c1: "3",
              c2: "result_01J5R1GQ7RM8M7PPQ4TYG9WXYA",
            },
            {
              c0: "2026-08-19T00:02:00Z",
              c1: "2",
              c2: "result_01J5R1GQ7RM8M7PPQ4TYG9WXYB",
            },
          ],
          status_key: null,
        },
      },
    },
    {
      slot_id: "limitations",
      kind: "callout",
      title: "제한 사항",
      emphasis: "supporting",
      collapsed: false,
      evidence_refs: [presentationRef],
      data: {
        tone: "warning",
        lines: [
          "한 출처는 사용할 수 없어 부분 근거만 표시합니다.",
          "보조 출처에서 검증된 레코드는 0개입니다.",
        ],
      },
    },
  ],
};

test("keeps English workspace starter cards inside their bounds", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.addInitScript(() => {
    localStorage.setItem("fdai.deck.layout.v1", "workspace");
  });
  await installOperatorApiFixture(page);

  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 993, height: 641 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto(`/agents?view=org&agent=Var&correlation=${encodeURIComponent(correlationId)}`);
    await page.getByRole("button", { name: "Open command deck" }).click();
    const workspace = page.getByRole("dialog", { name: "Command deck" });
    const introCardOverflow = await workspace.locator(".deck-intro-card").evaluateAll((cards) =>
      cards.map((card) => ({
        horizontal: card.scrollWidth - card.clientWidth,
        vertical: card.scrollHeight - card.clientHeight,
      }))
    );

    expect(introCardOverflow).toHaveLength(5);
    expect(introCardOverflow).toEqual(
      introCardOverflow.map(() => ({ horizontal: 0, vertical: 0 })),
    );
  }
});

test("anchors the latest-message action above the composer", async ({ page }, testInfo) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.addInitScript(() => {
    localStorage.setItem("fdai.deck.layout.v1", "workspace");
  });
  await installOperatorApiFixture(page, {
    answer: "The verified request count changed from one to three and then two.",
    presentationArtifact: timeSeriesPresentation,
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/agents?view=org&agent=Var&correlation=${encodeURIComponent(correlationId)}`);
  await page.getByRole("button", { name: "Open command deck" }).click();

  const workspace = page.getByRole("dialog", { name: "Command deck" });
  await workspace.getByPlaceholder(/Ask anything/i).fill("Show request trend");
  await workspace.getByRole("button", { name: "Send" }).click();
  await expect(workspace.locator('.deck-presentation-block[data-kind="time_series"]')).toBeVisible();
  const jump = workspace.getByRole("button", { name: "Jump to latest message" });
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 993, height: 641 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await workspace.locator(".deck-transcript").evaluate((element) => {
      element.scrollTop = 0;
      element.dispatchEvent(new Event("scroll"));
    });

    await expect(jump).toBeVisible();
    const geometry = await workspace.evaluate((element) => {
      const jumpBox = element.querySelector(".deck-jump")!.getBoundingClientRect();
      const transcriptBox = element.querySelector(".deck-transcript-column")!.getBoundingClientRect();
      const composerBox = element.querySelector(".deck-input-row")!.getBoundingClientRect();
      return {
        centerDelta: Math.abs(
          jumpBox.left + jumpBox.width / 2 - (transcriptBox.left + transcriptBox.width / 2),
        ),
        composerGap: composerBox.top - jumpBox.bottom,
        documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      };
    });
    expect(geometry.centerDelta).toBeLessThanOrEqual(1);
    expect(geometry.composerGap).toBe(12);
    expect(geometry.documentOverflow).toBe(0);
  }

  await page.setViewportSize({ width: 993, height: 641 });
  await workspace.locator(".deck-transcript").evaluate((element) => {
    element.scrollTop = 0;
    element.dispatchEvent(new Event("scroll"));
  });
  await page.evaluate(() => {
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
  });
  await page.mouse.move(10, 10);
  await page.waitForTimeout(250);
  await page.screenshot({ path: testInfo.outputPath("latest-message-action.png") });

  await jump.click();
  await expect(jump).toBeHidden();
});

test("renders accessible v2 presentation at desktop constrained and mobile viewports", async ({
  page,
}, testInfo) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.addInitScript(() => {
    localStorage.setItem("fdai.deck.layout.v1", "workspace");
  });
  await installOperatorApiFixture(page, {
    answer: "세 시점의 검증된 요청 수는 1, 3, 2입니다.",
    presentationArtifact: timeSeriesPresentation,
  });

  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 993, height: 641 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto(`/agents?view=org&agent=Var&correlation=${encodeURIComponent(correlationId)}`);
    await page.getByRole("button", { name: "Open command deck" }).click();
    const workspace = page.getByRole("dialog", { name: "Command deck" });
    await workspace.getByRole("toolbar", { name: "Workspace tools" })
      .getByRole("button", { name: /New conversation/ }).click();
    await workspace.getByPlaceholder(/Ask anything/i).fill("Show request trend");
    const send = workspace.getByRole("button", { name: "Send" });
    const composerGeometry = await workspace.locator(".deck-composer-inner").evaluate((element) => {
      const sendElement = element.querySelector(".deck-btn-primary");
      const sendBox = sendElement?.getBoundingClientRect();
      const composerBox = element.getBoundingClientRect();
      const workspaceBox = element.closest(".deck-overlay")?.getBoundingClientRect();
      return {
        composerOverflow: element.scrollWidth - element.clientWidth,
        composerLeft: composerBox.left,
        composerRight: composerBox.right,
        workspaceLeft: workspaceBox?.left ?? null,
        workspaceRight: workspaceBox?.right ?? null,
        viewportWidth: innerWidth,
        sendInsideViewport: Boolean(sendBox && sendBox.left >= 0 && sendBox.right <= innerWidth),
      };
    });
    expect(composerGeometry.composerOverflow).toBe(0);
    expect(composerGeometry.workspaceLeft).toBeGreaterThanOrEqual(0);
    expect(composerGeometry.workspaceRight).toBeLessThanOrEqual(viewport.width);
    expect(composerGeometry.composerLeft).toBeGreaterThanOrEqual(0);
    expect(composerGeometry.composerRight).toBeLessThanOrEqual(viewport.width);
    expect(composerGeometry.sendInsideViewport).toBe(true);
    await send.click();

    const chart = workspace.locator('.deck-presentation-block[data-kind="time_series"]');
    await expect(chart).toBeVisible();
    await expect(workspace.getByRole("button", { name: "Send" })).toBeVisible();
    await expect(chart.getByText(timeSeriesDescription)).toBeVisible();
    await expect(workspace.getByText("한 출처는 사용할 수 없어 부분 근거만 표시합니다."))
      .toBeVisible();
    await expect(workspace.getByText("보조 출처에서 검증된 레코드는 0개입니다."))
      .toBeVisible();
    await expect(chart.locator(".deck-presentation-series-point")).toHaveCount(3);
    await chart.locator(".deck-presentation-series-point").first().focus();
    await expect(chart.locator(".deck-presentation-series-point").first()).toBeFocused();

    const details = chart.locator(".deck-presentation-exact-values");
    await expect(details).not.toHaveAttribute("open", "");
    await details.locator(":scope > summary").click();
    await expect(details.getByText("result_01J5R1GQ7RM8M7PPQ4TYG9WXYZ")).toBeVisible();
    await expect(details.locator('time[datetime="2026-08-19T00:00:00Z"]')).toBeVisible();

    const geometry = await workspace.evaluate((element) => ({
      documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      workspaceOverflow: element.scrollWidth - element.clientWidth,
      chartOverflow: element.querySelector(".deck-presentation")
        ? (element.querySelector(".deck-presentation") as HTMLElement).scrollWidth -
          (element.querySelector(".deck-presentation") as HTMLElement).clientWidth
        : -1,
      transitionMs: Number.parseFloat(getComputedStyle(
        element.querySelector(".deck-presentation-series-column > span")!,
      ).transitionDuration) * 1_000,
    }));
    expect(geometry.documentOverflow).toBe(0);
    expect(geometry.workspaceOverflow).toBe(0);
    expect(geometry.chartOverflow).toBe(0);
    expect(geometry.transitionMs).toBeLessThanOrEqual(1);
    if (viewport.width < 1_200) await details.locator(":scope > summary").click();
    await page.screenshot({
      path: testInfo.outputPath(`v2-presentation-${viewport.width}x${viewport.height}.png`),
      fullPage: true,
    });
  }
});

test("defaults to the right dock and restores the last display mode", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile-chromium", "Mobile uses one full-width Deck mode.");
  await installOperatorApiFixture(page);
  await page.goto(
    `/agents?view=org&agent=Var&correlation=${encodeURIComponent(correlationId)}`,
  );

  await page.getByRole("button", { name: "Open command deck" }).click();
  let deck = page.getByRole("complementary", { name: "Command deck" });
  await expect(deck).toHaveClass(/deck-overlay-mode-dock/);
  await deck.getByRole("button", { name: "Full workspace" }).click();
  const tooltipWorkspace = page.getByRole("dialog", { name: "Command deck" });
  await tooltipWorkspace.locator(".deck-backend-header").focus();
  const backendTooltip = page.locator('.app-tooltip[data-variant="backend"]');
  await expect(backendTooltip).toBeVisible();
  await expect(backendTooltip.locator(".deck-backend-tooltip-context")).toContainText(
    "chat mode",
  );
  await expect(backendTooltip.locator(".deck-backend-tooltip-context strong")).toHaveText(
    "azure-ad-routed",
  );
  await expect(backendTooltip.locator(".deck-backend-tooltip-endpoint")).toHaveText(
    "https://chat.example.com",
  );
  await expect(backendTooltip.locator(".deck-backend-tooltip-choice strong")).toHaveText(
    "narrator-fast",
  );
  await expect(backendTooltip.locator(".deck-backend-tooltip-candidate")).toHaveCount(2);
  await expect(backendTooltip).not.toContainText("{endpoint}");
  await expect(backendTooltip).not.toContainText("{candidates}");
  await tooltipWorkspace.getByRole("button", { name: "Dock right" }).click();
  deck = page.getByRole("complementary", { name: "Command deck" });
  await expect(deck.getByRole("button", { name: "Dock right" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  await deck.getByRole("button", { name: "Floating panel" }).click();
  await expect(deck).toHaveClass(/deck-overlay-mode-floating/);
  await expect.poll(() => page.evaluate(() => localStorage.getItem("fdai.deck.layout.v1")))
    .toBe("floating");
  await deck.getByRole("button", { name: "Close command deck" }).click();
  await page.reload();
  await page.getByRole("button", { name: "Open command deck" }).click();
  deck = page.getByRole("complementary", { name: "Command deck" });
  await expect(deck).toHaveClass(/deck-overlay-mode-floating/);

  await deck.getByRole("button", { name: "Full workspace" }).click();
  let workspace = page.getByRole("dialog", { name: "Command deck" });
  await expect(workspace).toHaveClass(/deck-overlay-mode-workspace/);
  await expect.poll(() => page.evaluate(() => localStorage.getItem("fdai.deck.layout.v1")))
    .toBe("workspace");
  await workspace.getByRole("button", { name: "Close command deck" }).click();
  await page.reload();
  await page.getByRole("button", { name: "Open command deck" }).click();
  workspace = page.getByRole("dialog", { name: "Command deck" });
  await expect(workspace).toHaveClass(/deck-overlay-mode-workspace/);
});

test("keeps a mock-aligned execution timeline in full workspace", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile-chromium", "Mobile hides workspace layout controls.");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.addInitScript(() => {
    localStorage.setItem("fdai:console:show-model-trace", "true");
  });
  await installOperatorApiFixture(page, { executionTimeline: true, modelTrace: true });
  await page.goto(
    `/agents?view=org&agent=Var&correlation=${encodeURIComponent(correlationId)}`,
  );

  await page.getByRole("button", { name: "Open command deck" }).click();
  const dock = page.getByRole("complementary", { name: "Command deck" });
  await dock.getByRole("button", { name: "Full workspace" }).click();
  const workspace = page.getByRole("dialog", { name: "Command deck" });
  const prompt = workspace.getByPlaceholder(/Ask anything/i);
  await prompt.fill("List resource groups");
  await workspace.getByRole("button", { name: "Send" }).click();

  await expect(workspace.getByText(/no grounded root cause with citations is recorded/i))
    .toBeVisible();
  const investigation = workspace.locator(".deck-investigation.is-settled");
  await expect(investigation).toBeVisible();
  await expect(investigation.locator(".deck-investigation-head strong")).toHaveText(
    "Observed work completed",
  );
  await expect(investigation.locator(".deck-investigation-badge")).toHaveText("Completed");
  await expect(investigation.locator(".deck-branch-item")).toHaveCount(0);
  await expect(investigation).toHaveClass(/is-answer-settled/);
  await expect(investigation).not.toHaveAttribute("open", "");
  await expect(investigation.locator(".deck-investigation-item")).toHaveCount(2);
  await expect(investigation.getByText("Inspect server-owned read evidence")).not.toBeVisible();
  const settledGeometry = await investigation.evaluate((root) => ({
    height: root.getBoundingClientRect().height,
    documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  }));
  expect(settledGeometry.height).toBeLessThanOrEqual(44);
  expect(settledGeometry.documentOverflow).toBe(0);
  await investigation.locator(":scope > summary").click();
  await expect(investigation).toHaveAttribute("open", "");
  await expect(investigation.getByText("Inspect server-owned read evidence")).toBeVisible();
  const queryDisclosure = investigation.locator(".deck-investigation-item-disclosure", {
    hasText: "Inspect server-owned read evidence",
  });
  await expect(queryDisclosure).not.toHaveAttribute("open", "");
  await queryDisclosure.locator(":scope > summary").click();
  await expect(queryDisclosure).toHaveAttribute("open", "");
  await expect(queryDisclosure.locator(".deck-investigation-command")).toBeVisible();
  await expect(queryDisclosure.locator(".deck-investigation-command")).toContainText(
    '"operation": "query_inventory"',
  );
  await expect(queryDisclosure.locator(".deck-investigation-output")).toBeVisible();
  await expect(queryDisclosure.locator(".deck-investigation-output")).toContainText(
    '"matched_count": 1',
  );
  const eventDisclosure = investigation.locator(".deck-investigation-item-disclosure", {
    hasText: "Waiting for a verified semantic plan.",
  });
  await eventDisclosure.locator(":scope > summary").click();
  await expect(eventDisclosure).toHaveAttribute("open", "");
  await expect(eventDisclosure.locator(".deck-investigation-no-execution")).toHaveText(
    "No external command or provider request was executed in this step.",
  );
  const activityGeometry = await investigation.evaluate((root) => {
    const list = root.querySelector<HTMLElement>(".deck-investigation-list")!;
    const rail = getComputedStyle(list, "::before");
    const listBounds = list.getBoundingClientRect();
    const railX = listBounds.left + Number.parseFloat(rail.left);
    const summaries = Array.from(
      root.querySelectorAll<HTMLElement>(".deck-investigation-item-disclosure > summary"),
    );
    const markerX = Array.from(
      root.querySelectorAll<HTMLElement>(
        ".deck-investigation-summary > .deck-investigation-state",
      ),
    ).map((marker) => {
      const bounds = marker.getBoundingClientRect();
      return bounds.left + bounds.width / 2;
    });
    return {
      railX,
      markerX,
      summaryHeights: summaries.map((summary) => summary.getBoundingClientRect().height),
    };
  });
  expect(activityGeometry.markerX.every((x) => Math.abs(x - activityGeometry.railX) <= 0.5))
    .toBe(true);
  expect(activityGeometry.summaryHeights.every((height) => height >= 44)).toBe(true);
  await expect(investigation.locator(".deck-investigation-session-summary")).toHaveCount(0);

  const runRecord = workspace.locator(".deck-trajectory");
  await expect(runRecord).not.toHaveAttribute("open", "");
  await expect(runRecord.locator(".deck-trajectory-question")).toHaveCount(0);
  await expect(runRecord.locator(".deck-trajectory-results")).toHaveCount(0);
  const sourceControl = workspace.locator(".deck-gr-source-status");
  const sourceButton = sourceControl.locator(".deck-gr-pill");
  const actionRow = workspace.locator(".deck-gr-actions:has(.deck-gr-pill)");
  await expect(actionRow.locator(".deck-trajectory-status-trigger")).toHaveCount(0);
  const initialFooter = await actionRow.evaluate((root) => {
    const button = root.querySelector<HTMLElement>(".deck-gr-pill")!.getBoundingClientRect();
    const review = root.querySelector<HTMLElement>(".deck-gr-review")!.getBoundingClientRect();
    const row = root.getBoundingClientRect();
    return {
      row: { width: row.width, height: row.height },
      button: {
        x: button.x - row.x,
        y: button.y - row.y,
        width: button.width,
        height: button.height,
      },
      review: {
        x: review.x - row.x,
        y: review.y - row.y,
        width: review.width,
        height: review.height,
      },
    };
  });
  await sourceButton.hover();
  const sourceTooltip = page.locator('.app-tooltip[data-state="delayed-open"]');
  await expect(sourceTooltip).toHaveCount(1);
  await expect(sourceTooltip).toContainText("Checked against 1 evidence reference(s)");
  await expect(sourceTooltip).not.toContainText("1 read queries / 0 commands");
  await page.waitForTimeout(250);
  await expect(sourceTooltip).toHaveCount(1);
  const hoveredFooter = await actionRow.evaluate((root) => {
    const button = root.querySelector<HTMLElement>(".deck-gr-pill")!.getBoundingClientRect();
    const review = root.querySelector<HTMLElement>(".deck-gr-review")!.getBoundingClientRect();
    const row = root.getBoundingClientRect();
    return {
      row: { width: row.width, height: row.height },
      button: {
        x: button.x - row.x,
        y: button.y - row.y,
        width: button.width,
        height: button.height,
      },
      review: {
        x: review.x - row.x,
        y: review.y - row.y,
        width: review.width,
        height: review.height,
      },
    };
  });
  expect(hoveredFooter).toEqual(initialFooter);
  expect(hoveredFooter.button.x).toBeGreaterThanOrEqual(0);
  expect(hoveredFooter.button.x + hoveredFooter.button.width).toBeLessThanOrEqual(
    hoveredFooter.row.width,
  );
  await workspace.getByRole("button", { name: /^Conversation history/ }).click();
  const conversationRow = workspace.locator(".deck-conversation-select", {
    hasText: "List resource groups",
  });
  await expect(conversationRow).toBeVisible();
  await conversationRow.locator("small").hover();
  const conversationTooltip = page.locator('.app-tooltip[data-state="delayed-open"]', {
    hasText: "List resource groups",
  });
  await expect(conversationTooltip).toHaveCount(1);
  await expect(conversationTooltip).toHaveText("List resource groups");
  await workspace.getByRole("button", { name: /^Conversation history/ }).click();
  await runRecord.locator(":scope > summary").click();
  await expect(runRecord).toHaveAttribute("open", "");
  await expect(runRecord.locator(".deck-trajectory-phase-strip")).toHaveCount(1);
  await expect(runRecord.locator(".deck-trajectory-phase-details > li")).toHaveCount(6);
  const unobservedPhases = runRecord.locator(
    '.deck-trajectory-phase-details > li[data-state="not_observed"]',
  );
  await expect(unobservedPhases).toHaveCount(2);
  await expect(unobservedPhases.first())
    .toContainText("No observable detail was recorded for this phase");
  await expect(runRecord.locator(".deck-trajectory-question strong")).toHaveText(
    "List resource groups",
  );
  await runRecord.locator(".deck-trajectory-records > summary").click();
  const evidencePhase = runRecord.locator('.deck-trajectory-event[data-phase="evidence"] > details');
  await evidencePhase.locator(":scope > summary").click();
  const queryActivity = evidencePhase.locator(".deck-trajectory-evidence > li > details", {
    hasText: "Inspect server-owned read evidence",
  });
  await queryActivity.locator(":scope > summary").click();
  const queryResult = queryActivity.locator(".deck-trajectory-nested");
  await queryResult.locator(":scope > summary").click();
  const queryResultCode = queryResult.locator("code");
  await expect(queryResultCode).toContainText('"resources": [');
  await expect(queryResultCode).toContainText('"name": "vm-example"');
  await expect(prompt).toBeVisible();
  const modelTrace = runRecord.locator(".deck-model-trace");
  await expect(modelTrace).toBeVisible();
  await modelTrace.locator(".deck-model-trace-lanes > li > details > summary").click();
  await expect(modelTrace.locator(".deck-model-trace-messages li > span", {
    hasText: /^system$/i,
  })).toHaveCount(1);
  await expect(modelTrace.locator(".deck-model-trace-messages li > span", {
    hasText: /^user$/i,
  })).toHaveCount(1);
  const groupedSystem = modelTrace.locator(".deck-model-trace-message-content").first();
  await expect(groupedSystem).toContainText('"policy": {');
  await expect(groupedSystem).toContainText('"status": "ready"');

  const metrics = await workspace.evaluate((root) => {
    const transcript = root.querySelector<HTMLElement>(".deck-transcript");
    const command = root.querySelector<HTMLElement>(
      '.deck-trajectory-event[data-phase="evidence"] .deck-code',
    );
    const commandScrollSurface = command?.querySelector<HTMLElement>(".deck-code-pre");
    const composer = root.querySelector<HTMLElement>(".deck-input-row");
    const code = commandScrollSurface?.querySelector<HTMLElement>("code");
    const output = root.querySelector<HTMLElement>(
      '.deck-trajectory-nested .deck-code-pre',
    );
    const modelMessage = root.querySelector<HTMLElement>(".deck-model-trace-message-content");
    const rootBounds = root.getBoundingClientRect();
    const composerBounds = composer?.getBoundingClientRect();
    return {
      viewportWidth: window.innerWidth,
      transcriptWidth: transcript?.clientWidth ?? 0,
      transcriptScrolls: transcript
        ? transcript.scrollHeight > transcript.clientHeight
        : false,
      bodyOverflow: document.body.scrollWidth > document.body.clientWidth,
      investigationOverflow: (() => {
        const investigation = root.querySelector<HTMLElement>(".deck-investigation");
        return investigation
          ? investigation.scrollWidth > investigation.clientWidth
          : true;
      })(),
      composerInsideDeck: composerBounds
        ? composerBounds.top >= rootBounds.top && composerBounds.bottom <= rootBounds.bottom
        : false,
      commandBackground: command ? getComputedStyle(command).backgroundColor : "",
      codeBackground: code ? getComputedStyle(code).backgroundColor : "",
      commandScrollbar: commandScrollSurface
        ? getComputedStyle(commandScrollSurface).scrollbarColor
        : "",
      outputScrollbar: output ? getComputedStyle(output).scrollbarColor : "",
      modelMessageScrollbar: modelMessage ? getComputedStyle(modelMessage).scrollbarColor : "",
    };
  });
  if (metrics.viewportWidth >= 900) {
    expect(metrics.transcriptWidth).toBeGreaterThanOrEqual(760);
  } else {
    expect(metrics.transcriptWidth).toBeGreaterThanOrEqual(metrics.viewportWidth - 1);
  }
  expect(metrics.transcriptScrolls).toBe(true);
  expect(metrics.bodyOverflow).toBe(false);
  expect(metrics.investigationOverflow).toBe(false);
  expect(metrics.composerInsideDeck).toBe(true);
  expect(metrics.commandBackground).toBe("rgb(13, 17, 23)");
  expect(metrics.codeBackground).toBe("rgba(0, 0, 0, 0)");
  expect(metrics.commandScrollbar).not.toBe("auto");
  expect(metrics.outputScrollbar).not.toBe("auto");
  expect(metrics.modelMessageScrollbar).not.toBe("auto");
});

test("pretty-prints nested serialized JSON in the model trace", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile-chromium", "Mobile hides workspace layout controls.");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.addInitScript(() => {
    localStorage.setItem("fdai:console:show-model-trace", "true");
  });
  await installOperatorApiFixture(page, { executionTimeline: true, modelTrace: true });
  await page.goto(
    `/agents?view=org&agent=Var&correlation=${encodeURIComponent(correlationId)}`,
  );

  await page.getByRole("button", { name: "Open command deck" }).click();
  const dock = page.getByRole("complementary", { name: "Command deck" });
  await dock.getByRole("button", { name: "Full workspace" }).click();
  const workspace = page.getByRole("dialog", { name: "Command deck" });
  await workspace.getByPlaceholder(/Ask anything/i).fill("List resource groups");
  await workspace.getByRole("button", { name: "Send" }).click();
  await expect(workspace.getByText(/no grounded root cause with citations is recorded/i))
    .toBeVisible();

  const runRecord = workspace.locator(".deck-trajectory");
  await runRecord.locator(":scope > summary").click();
  const modelTrace = runRecord.locator(".deck-model-trace");
  await modelTrace.locator(".deck-model-trace-lanes > li > details > summary").click();
  const systemMessage = modelTrace.locator(".deck-model-trace-message-content").first();
  await expect(systemMessage).toHaveAttribute("data-format", "mixed");
  await expect(systemMessage.locator(":scope > pre")).toContainText("Safety layer");
  await expect(systemMessage.locator(".deck-code-lang")).toHaveText("json");
  await expect(systemMessage.locator(".hljs-attr").first()).toBeVisible();
  const userMessage = modelTrace.locator(".deck-model-trace-message-content").nth(1);
  await expect(userMessage).toHaveAttribute("data-format", "json");
  await expect(userMessage.locator(".deck-code-lang")).toHaveText("json");
  await expect(userMessage.locator(".deck-code-copy")).toHaveText("Copy JSON");
  await expect(userMessage.locator(".hljs-attr").first()).toBeVisible();
  await expect(userMessage.locator(".hljs-string").first()).toBeVisible();
  await expect(userMessage).toContainText('"untrusted_input": {');
  await expect(userMessage).toContainText('"name": "Resource"');
  expect(await userMessage.textContent()).not.toContain('\\"untrusted_input\\"');
  const modelResponse = modelTrace.locator(".deck-model-trace-response .deck-code-pre code");
  await expect(modelResponse).toContainText('"result": {');
  await expect(modelResponse).toContainText('"matched": 1');
  expect(await modelResponse.textContent()).not.toContain('\\"status\\"');

  const geometry = await modelTrace.evaluate((root) => {
    const request = root.querySelector<HTMLElement>(".deck-model-trace-message-content");
    const response = root.querySelector<HTMLElement>(".deck-model-trace-response pre");
    return {
      documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      requestOverflow: request ? request.scrollWidth - request.clientWidth : 1,
      responseOverflow: response ? response.scrollWidth - response.clientWidth : 1,
    };
  });
  expect(geometry).toEqual({
    documentOverflow: 0,
    requestOverflow: 0,
    responseOverflow: 0,
  });
});

test("keeps a standalone direct-response model trace compact", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile-chromium", "Desktop owns the standalone trace baseline.");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.addInitScript(() => {
    localStorage.setItem("fdai:console:show-model-trace", "true");
  });
  await installOperatorApiFixture(page, {
    answer: "Hello. What would you like to check?",
    modelTrace: true,
    source: "semantic-direct-response",
  });
  await page.goto(`/agents?view=org&agent=Var&correlation=${encodeURIComponent(correlationId)}`);

  await page.getByRole("button", { name: "Open command deck" }).click();
  const deck = page.getByRole("complementary", { name: "Command deck" });
  await deck.getByPlaceholder(/Ask anything/i).fill("Hello");
  await deck.getByRole("button", { name: "Send" }).click();

  const modelTrace = deck.locator(".deck-model-trace");
  await expect(modelTrace).toBeVisible();
  await expect(deck.locator(".deck-trajectory")).toHaveCount(0);
  const metrics = await modelTrace.evaluate((root) => {
    const heading = root.querySelector<HTMLElement>(".deck-model-trace-head h4");
    const notice = root.querySelector<HTMLElement>(".deck-model-trace-head p");
    const model = root.querySelector<HTMLElement>(".deck-model-trace-model");
    return {
      headingSize: heading ? getComputedStyle(heading).fontSize : "",
      noticeSize: notice ? getComputedStyle(notice).fontSize : "",
      modelSize: model ? getComputedStyle(model).fontSize : "",
      overflow: root.scrollWidth - root.clientWidth,
    };
  });
  expect(metrics).toEqual({
    headingSize: "13px",
    noticeSize: "12px",
    modelSize: "12px",
    overflow: 0,
  });
});

test("keeps completed observed work compact across supported viewports", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("fdai.deck.layout.v1", "workspace");
  });
  await installOperatorApiFixture(page, { executionTimeline: true });

  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 993, height: 641 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto(`/agents?view=org&agent=Var&correlation=${encodeURIComponent(correlationId)}`);
    await page.getByRole("button", { name: "Open command deck" }).click();
    const workspace = page.getByRole("dialog", { name: "Command deck" });
    await workspace.getByRole("toolbar", { name: "Workspace tools" })
      .getByRole("button", { name: /New conversation/ }).click();
    await workspace.getByPlaceholder(/Ask anything/i).fill("List resource groups");
    await workspace.getByRole("button", { name: "Send" }).click();

    await expect(workspace.getByText(/no grounded root cause with citations is recorded/i))
      .toBeVisible();
    const investigation = workspace.locator(".deck-investigation.is-answer-settled");
    const runRecord = workspace.locator(".deck-trajectory");
    await expect(investigation).not.toHaveAttribute("open", "");
    await expect(runRecord).not.toHaveAttribute("open", "");

    const geometry = await workspace.evaluate((root) => {
      const answer = root.querySelector<HTMLElement>(".deck-turn.is-flow-end");
      const investigation = root.querySelector<HTMLElement>(
        ".deck-investigation.is-answer-settled",
      );
      const transcript = root.querySelector<HTMLElement>(".deck-transcript");
      const answerBody = root.querySelector<HTMLElement>(".deck-turn.is-flow-end .deck-turn-body");
      const runRecord = root.querySelector<HTMLElement>(".deck-trajectory");
      const runSummary = root.querySelector<HTMLElement>(".deck-trajectory-summary");
      const runStats = root.querySelector<HTMLElement>(".deck-trajectory-stats");
      const runDuration = root.querySelector<HTMLElement>(".deck-trajectory-duration");
      const actionControls = Array.from(root.querySelectorAll<HTMLElement>(
        ".deck-gr-actions button, .deck-gr-actions a",
      ));
      const composer = root.querySelector<HTMLElement>(".deck-input-row");
      const composerInput = root.querySelector<HTMLElement>(".deck-input");
      const agentSource = root.querySelector<HTMLElement>(".deck-turn-source");
      const timestamp = root.querySelector<HTMLElement>(".deck-turn-time");
      const answerBounds = answer?.getBoundingClientRect();
      const transcriptBounds = transcript?.getBoundingClientRect();
      const runRecordStyle = runRecord ? getComputedStyle(runRecord) : null;
      return {
        answerInsideViewport: Boolean(
          answerBounds && transcriptBounds &&
            answerBounds.bottom > transcriptBounds.top && answerBounds.top < transcriptBounds.bottom,
        ),
        investigationHeight: investigation?.getBoundingClientRect().height ?? Number.POSITIVE_INFINITY,
        answerWidth: answerBounds?.width ?? 0,
        answerFontSize: answerBody ? getComputedStyle(answerBody).fontSize : "",
        runRecordHeight: runRecord?.getBoundingClientRect().height ?? 0,
        runSummaryHeight: runSummary?.getBoundingClientRect().height ?? 0,
        runRecordBorderWidth: runRecordStyle?.borderTopWidth ?? "",
        runRecordRadius: runRecordStyle?.borderRadius ?? "",
        runStatsFontSize: runStats ? getComputedStyle(runStats).fontSize : "",
        runDurationFontSize: runDuration ? getComputedStyle(runDuration).fontSize : "",
        minimumActionHeight: Math.min(
          ...actionControls.map((control) => control.getBoundingClientRect().height),
        ),
        composerHeight: composer?.getBoundingClientRect().height ?? 0,
        composerInputHeight: composerInput?.getBoundingClientRect().height ?? 0,
        agentSourceFontSize: agentSource ? getComputedStyle(agentSource).fontSize : "",
        timestampFontSize: timestamp ? getComputedStyle(timestamp).fontSize : "",
        documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        transcriptOverflow: transcript ? transcript.scrollWidth - transcript.clientWidth : -1,
      };
    });
    expect(geometry.answerInsideViewport).toBe(true);
    expect(geometry.investigationHeight).toBeLessThanOrEqual(viewport.width <= 640 ? 72 : 44);
    if (viewport.width >= 993) expect(geometry.answerWidth).toBe(780);
    else expect(geometry.answerWidth).toBeLessThanOrEqual(viewport.width - 24);
    expect(geometry.answerFontSize).toBe("15px");
    expect(geometry.runRecordBorderWidth).toBe("1px");
    expect(geometry.runRecordRadius).toBe("8px");
    expect(geometry.runRecordHeight).toBeGreaterThanOrEqual(54);
    expect(geometry.runRecordHeight).toBeLessThanOrEqual(viewport.width <= 720 ? 82 : 56);
    expect(geometry.runSummaryHeight).toBeGreaterThanOrEqual(52);
    expect(geometry.runStatsFontSize).toBe(viewport.width <= 720 ? "12px" : "14px");
    expect(geometry.runDurationFontSize).toBe(viewport.width <= 720 ? "11px" : "13px");
    expect(geometry.minimumActionHeight).toBeGreaterThanOrEqual(viewport.width <= 640 ? 44 : 32);
    expect(geometry.composerHeight).toBeLessThanOrEqual(72);
    expect(geometry.composerInputHeight).toBeGreaterThanOrEqual(viewport.width <= 640 ? 44 : 40);
    expect(geometry.agentSourceFontSize).toBe("12px");
    expect(geometry.timestampFontSize).toBe("12px");
    expect(geometry.documentOverflow).toBe(0);
    expect(geometry.transcriptOverflow).toBe(0);
  }
});

test("uses shared preparation geometry before the terminal answer", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.addInitScript(() => {
    localStorage.setItem("fdai.deck.layout.v1", "workspace");
  });
  await installOperatorApiFixture(page, { streamDelayMs: 1000 });
  await page.goto(`/agents?view=org&agent=Var&correlation=${encodeURIComponent(correlationId)}`);
  await page.getByRole("button", { name: "Open command deck" }).click();
  const workspace = page.getByRole("dialog", { name: "Command deck" });
  await workspace.getByPlaceholder(/Ask anything/i).fill("List resource groups");
  await workspace.getByRole("button", { name: "Send" }).click();

  const preparation = workspace.locator(".deck-rt.cs-grounding-panel");
  await expect(preparation).toBeVisible();
  await expect(preparation.locator(".deck-rt-source.cs-grounding-source")).toHaveCount(3);
  const geometry = await preparation.evaluate((panel) => {
    const head = panel.querySelector<HTMLElement>(".cs-grounding-head");
    const stage = panel.querySelector<HTMLElement>(".cs-grounding-stage");
    const sourceWindow = panel.querySelector<HTMLElement>(".cs-grounding-source-window");
    const source = panel.querySelector<HTMLElement>(".cs-grounding-source");
    const agentSource = panel.closest(".deck-rt-turn")?.querySelector<HTMLElement>(
      ".cs-deck-agent-source",
    );
    const panelStyle = getComputedStyle(panel);
    return {
      width: panel.getBoundingClientRect().width,
      borderWidth: panelStyle.borderTopWidth,
      radius: panelStyle.borderRadius,
      headHeight: head?.getBoundingClientRect().height ?? 0,
      stageHeight: stage?.getBoundingClientRect().height ?? 0,
      sourceWindowHeight: sourceWindow?.getBoundingClientRect().height ?? 0,
      sourceHeight: source?.getBoundingClientRect().height ?? 0,
      agentSourceFontSize: agentSource ? getComputedStyle(agentSource).fontSize : "",
    };
  });
  expect(geometry.width).toBe(780);
  expect(geometry.borderWidth).toBe("1px");
  expect(geometry.radius).toBe("7px");
  expect(geometry.headHeight).toBeGreaterThanOrEqual(36);
  expect(geometry.stageHeight).toBeGreaterThanOrEqual(30);
  expect(geometry.sourceWindowHeight).toBe(88);
  expect(geometry.sourceHeight).toBeGreaterThanOrEqual(28);
  expect(geometry.agentSourceFontSize).toBe("12px");
  await expect(workspace.getByText(/no grounded root cause with citations is recorded/i))
    .toBeVisible();
});

test("keeps responsive table labels visual-only at 320px", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await installOperatorApiFixture(page, {
    answer: [
      "| Fact | Value | Description / Alias |",
      "| --- | --- | --- |",
      "| health | attention | Overall health status |",
      "| event_count | 500 | Events observed in the current window |",
      "| change_lead_time_seconds | unavailable | Change lead time |",
    ].join("\n"),
  });
  await page.goto(
    `/agents?view=org&agent=Var&correlation=${encodeURIComponent(correlationId)}`,
  );

  await page.getByRole("button", { name: "Open command deck" }).click();
  const deck = page.getByRole("complementary", { name: "Command deck" });
  await deck.getByPlaceholder(/Ask anything/i).fill("Show the evidence as a table");
  await deck.getByRole("button", { name: "Send" }).click();

  const table = deck.getByRole("table");
  await expect(table).toBeVisible();
  await expect(table.getByRole("columnheader", { name: "Fact" })).toHaveAttribute(
    "scope",
    "col",
  );
  await expect(table.getByRole("cell", { name: "health", exact: true })).toBeVisible();
  await expect(table.getByRole("cell", { name: "Fact health", exact: true })).toHaveCount(0);
  await expect(table.locator("tbody tr")).toHaveCount(3);

  const metrics = await deck.evaluate((root) => {
    const wrap = root.querySelector<HTMLElement>(".deck-table-wrap");
    const cell = root.querySelector<HTMLElement>(".deck-table td");
    const sourceReadiness = root.querySelector<HTMLElement>(".deck-source-readiness");
    const sourceItems = root.querySelector<HTMLElement>(".deck-source-readiness-items");
    const sourceSummary = root.querySelector<HTMLElement>(".deck-source-readiness-summary");
    const rootRect = root.getBoundingClientRect();
    const elementGeometry = (element: HTMLElement) => {
      const rect = element.getBoundingClientRect();
      return {
        left: Math.round(rect.left),
        right: Math.round(rect.right),
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
        overflowX: getComputedStyle(element).overflowX,
      };
    };
    const overflowers = Array.from(root.querySelectorAll<HTMLElement>("*"))
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          selector: `${element.tagName.toLowerCase()}.${element.className}`,
          left: Math.round(rect.left),
          right: Math.round(rect.right),
        };
      })
      .filter(({ left, right }) => left < rootRect.left - 1 || right > rootRect.right + 1)
      .slice(0, 12);
    return {
      deckOverflow: root.scrollWidth > root.clientWidth,
      rootClientWidth: root.clientWidth,
      rootScrollWidth: root.scrollWidth,
      sourceReadiness: sourceReadiness ? elementGeometry(sourceReadiness) : null,
      sourceItems: sourceItems ? elementGeometry(sourceItems) : null,
      sourceSummary: sourceSummary ? elementGeometry(sourceSummary) : null,
      tableOverflow: wrap ? wrap.scrollWidth > wrap.clientWidth : true,
      cellDisplay: cell ? getComputedStyle(cell).display : "",
      overflowers,
    };
  });
  expect(metrics.deckOverflow, JSON.stringify(metrics, null, 2)).toBe(false);
  expect(metrics.tableOverflow).toBe(false);
  expect(metrics.cellDisplay).toBe("grid");
});

test("pins a Var incident through the deck and renders a grounded Bragi answer", async ({
  page,
}) => {
  const fixture = await installOperatorApiFixture(page);
  await page.goto(
    `/agents?view=org&agent=Var&correlation=${encodeURIComponent(correlationId)}`,
  );

  const varRegion = page.getByRole("region", { name: "Var" });
  await expect(varRegion).toBeVisible();
  await expect(varRegion.getByRole("button", {
    name: /investigating Environment tag required/,
  })).toBeVisible();
  await varRegion.getByRole("button", { name: "Ask the deck about this incident" }).click();

  const deck = page.getByRole("complementary", { name: "Command deck" });
  await expect(deck).toBeVisible();
  await expect(deck.getByText(
    `Selected incident ${incidentId} (${correlationId}) from Var's Events view.`,
    { exact: true },
  )).toBeVisible();
  await expect(deck.getByLabel("Conversation").getByText("Bragi", { exact: true })).toBeVisible();

  const prompt = deck.getByPlaceholder(/Ask anything/i);
  await expect(prompt).toHaveValue(
    "What is the root cause status, and what are the involved agents doing?",
  );
  await deck.getByRole("button", { name: "Send" }).click();

  await expect(deck.getByText("Bragi", { exact: true }).last()).toBeVisible();
  await expect(deck.getByText(/no grounded root cause with citations is recorded/i)).toBeVisible();
  await expect(deck.getByText(/Var: hil\.requested/)).toBeVisible();
  await expect(deck.getByText(/Forseti: risk_gate\.decided/)).toBeVisible();
  await expect(deck.getByRole("status").filter({ hasText: /^Corrected$/ })).toBeVisible();
  await expect(deck.getByText(/Choose one to verify/i)).toHaveCount(0);

  await expect.poll(() => fixture.chatBody()).not.toBeNull();
  expect(fixture.chatBody()).toMatchObject({
    prompt: "What is the root cause status, and what are the involved agents doing?",
    conversation_context: {
      kind: "incident",
      incident_id: incidentId,
      correlation_id: correlationId,
      selected_agent: "Var",
    },
  });
});

test("renders a sent image inside the operator turn without caching its bytes", async ({
  page,
}, testInfo) => {
  const fixture = await installOperatorApiFixture(page, { answer: "The image is available." });
  await page.goto(
    `/agents?view=org&agent=Var&correlation=${encodeURIComponent(correlationId)}`,
  );
  await page.getByRole("button", { name: "Open command deck" }).click();
  const deck = page.getByRole("complementary", { name: "Command deck" });
  await deck.locator('input[type="file"]').setInputFiles({
    name: "screenshot.png",
    mimeType: "image/png",
    buffer: Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
      "base64",
    ),
  });
  const stagedImage = deck.locator(".deck-attach-item.is-image-preview");
  await expect(stagedImage).toHaveCount(1);
  await expect(stagedImage).not.toHaveClass(/is-scanning/);
  await expect(stagedImage.locator(
    ".deck-attach-name, .deck-attach-meta, .deck-attach-status",
  )).toHaveCount(0);
  const thumbnailBox = await stagedImage.boundingBox();
  expect(thumbnailBox?.width).toBe(54);
  expect(thumbnailBox?.height).toBe(54);

  if (testInfo.project.name !== "mobile-chromium") {
    await stagedImage.locator(".deck-attach-thumb").hover();
    const largePreview = page.locator(".deck-attach-preview-layer img");
    await expect(largePreview).toBeVisible();
    await expect(page.locator(
      '.app-tooltip[data-variant="image-preview"][data-state="instant-open"]',
    )).toHaveCount(1);
    await expect.poll(() => largePreview.evaluate((image: HTMLImageElement) => image.naturalWidth))
      .toBeGreaterThan(0);
    expect((await largePreview.boundingBox())?.width).toBeGreaterThan(300);
  }

  await deck.getByPlaceholder(/Ask anything/i).fill("What is shown?");
  await deck.getByRole("button", { name: "Send" }).click();

  const sentTurn = deck.locator(".deck-turn-operator").filter({ hasText: "What is shown?" });
  const sentImageButton = sentTurn.getByRole("button", { name: "Open attached image 1" });
  const sentImage = sentImageButton.getByRole("img", { name: "Attached image 1" });
  await expect(sentImageButton).toBeVisible();
  await expect(sentTurn.getByText("screenshot.png", { exact: true })).toHaveCount(0);
  expect(await sentTurn.evaluate((element) => {
    const attachments = element.querySelector(".deck-turn-attachment-block");
    const question = element.querySelector(".deck-turn-body");
    return Boolean(
      attachments
      && question
      && (attachments.compareDocumentPosition(question) & Node.DOCUMENT_POSITION_FOLLOWING),
    );
  })).toBe(true);
  await expect.poll(() => sentImage.evaluate((image: HTMLImageElement) => image.naturalWidth))
    .toBeGreaterThan(0);
  const thumbnailBounds = await sentImage.boundingBox();
  await sentImageButton.click();
  const imageDialog = page.getByRole("dialog", { name: "Attached image preview" });
  await expect(imageDialog).toBeVisible();
  const expandedImage = imageDialog.getByRole("img", { name: "Attached image 1" });
  await expect.poll(() => expandedImage.evaluate((image: HTMLImageElement) => image.naturalWidth))
    .toBeGreaterThan(0);
  expect((await expandedImage.boundingBox())?.width).toBeGreaterThan(thumbnailBounds?.width ?? 0);
  await page.keyboard.press("Escape");
  await expect(imageDialog).toHaveCount(0);
  await expect(sentImageButton).toBeFocused();
  await expect.poll(() => fixture.chatBody()).not.toBeNull();
  expect(fixture.chatBody()?.attachments).toMatchObject([{
    id: expect.stringMatching(/^att-/),
    name: "screenshot.png",
    media_type: "image/png",
  }]);

  const cachedTranscript = await page.evaluate(() =>
    Object.entries(localStorage)
      .filter(([key]) => key.startsWith("fdai.deck.transcript.v1"))
      .map(([, value]) => value)
      .join("\n"));
  expect(cachedTranscript).not.toContain("data:image/");
  expect(cachedTranscript).not.toContain("iVBORw0KGgo");
});
