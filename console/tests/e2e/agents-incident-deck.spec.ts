import { expect, test, type Page, type Route } from "@playwright/test";

const correlationId = "local-parity:incident-selected";
const incidentId = `INC-${correlationId}`;

const incident = {
  correlation_id: correlationId,
  incident_id: incidentId,
  ticket_id: null,
  title: "Environment tag required",
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
  options: { readonly executionTimeline?: boolean } = {},
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
      await json(route, { items: [incident], next_cursor: null });
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
        mode: "test",
        model: "narrator-test",
        endpoint: null,
      });
      return;
    }
    if (path === "/chat/stream") {
      capturedChatBody = request.postDataJSON() as Record<string, unknown>;
      const answer =
        `${correlationId} (Environment tag required) is investigating and was last updated ` +
        "at 2026-07-22T00:01:00Z, but no grounded root cause with citations is recorded. " +
        "The cause cannot be confirmed.\n\nCurrent recorded agent activity:\n" +
        "- Var: hil.requested at 2026-07-22T00:01:00Z\n" +
        "- Forseti: risk_gate.decided at 2026-07-22T00:00:30Z";
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
            output: "7 resource groups",
            output_truncated: false,
            exit_code: null,
            started_at: "2026-07-22T00:01:00Z",
            completed_at: "2026-07-22T00:01:00.008Z",
            duration_ms: 8,
          },
        })}`,
      ] : [];
      frames.push(
        `event: done\ndata: ${JSON.stringify({
          seq: options.executionTimeline ? 3 : 1,
          revision: 1,
          answer,
          model: "narrator-test",
          source: "evidence:corrected",
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
        })}`,
      );
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

test("defaults to the right dock and restores the last display mode", async ({ page }) => {
  await installOperatorApiFixture(page);
  await page.goto(
    `/agents?view=org&agent=Var&correlation=${encodeURIComponent(correlationId)}`,
  );

  await page.getByRole("button", { name: "Open command deck" }).click();
  let deck = page.getByRole("complementary", { name: "Command deck" });
  await expect(deck).toHaveClass(/deck-overlay-mode-dock/);
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

test("keeps a mock-aligned execution timeline in full workspace", async ({ page }) => {
  await installOperatorApiFixture(page, { executionTimeline: true });
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
  await expect(investigation.locator(".deck-investigation-head strong")).toHaveText("Investigation");
  await expect(investigation.locator(".deck-investigation-badge")).toHaveText("Completed");
  await expect(investigation.locator(".deck-branch-item")).toHaveCount(0);
  await expect(investigation.locator(".deck-investigation-item")).toHaveCount(1);
  await expect(investigation.locator(".deck-investigation-kind-badge")).toHaveText("QUERY");

  const metrics = await workspace.evaluate((root) => {
    const transcript = root.querySelector<HTMLElement>(".deck-transcript");
    const command = root.querySelector<HTMLElement>(".deck-investigation-command");
    const code = command?.querySelector<HTMLElement>("code");
    return {
      viewportWidth: window.innerWidth,
      transcriptWidth: transcript?.clientWidth ?? 0,
      bodyOverflow: document.body.scrollWidth > document.body.clientWidth,
      investigationOverflow: (() => {
        const investigation = root.querySelector<HTMLElement>(".deck-investigation");
        return investigation
          ? investigation.scrollWidth > investigation.clientWidth
          : true;
      })(),
      commandBackground: command ? getComputedStyle(command).backgroundColor : "",
      codeBackground: code ? getComputedStyle(code).backgroundColor : "",
    };
  });
  if (metrics.viewportWidth >= 900) {
    expect(metrics.transcriptWidth).toBeGreaterThanOrEqual(760);
  } else {
    expect(metrics.transcriptWidth).toBeGreaterThanOrEqual(metrics.viewportWidth - 1);
  }
  expect(metrics.bodyOverflow).toBe(false);
  expect(metrics.investigationOverflow).toBe(false);
  expect(metrics.commandBackground).toBe("rgb(31, 36, 40)");
  expect(metrics.codeBackground).toBe("rgba(0, 0, 0, 0)");
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
  await expect(deck.getByText(`Var / ${incidentId}`, { exact: true }).first()).toBeVisible();
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
