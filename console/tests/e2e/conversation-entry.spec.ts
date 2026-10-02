import { expect, test, type Page } from "@playwright/test";
import answerEvidenceEn from "../../src/deck/i18n/answer-evidence.en.json" with { type: "json" };
import answerEvidenceKo from "../../src/deck/i18n/answer-evidence.ko.json" with { type: "json" };
import runRecordEn from "../../src/deck/i18n/run-record.en.json" with { type: "json" };
import runRecordKo from "../../src/deck/i18n/run-record.ko.json" with { type: "json" };
import en from "../../src/i18n/messages.en.json" with { type: "json" };
import ko from "../../src/i18n/messages.ko.json" with { type: "json" };

test.describe.configure({ mode: "serial" });

interface ChatRequest {
  readonly request_id: string;
  readonly session_id: string;
  readonly prompt: string;
  readonly view_context: Record<string, unknown>;
  readonly history: readonly { readonly content: string }[];
  readonly target_agent?: string;
  readonly conversation_context?: {
    readonly kind: string;
    readonly incident_id: string;
    readonly correlation_id: string;
  };
}

async function openConsole(
  page: Page,
  locale = "en",
  terminal?: (request: ChatRequest) => Record<string, unknown>,
  includeIncident = false,
) {
  const requests: ChatRequest[] = [];
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (includeIncident && path.endsWith("/incidents/stream")) {
      await route.fulfill({
        contentType: "text/event-stream",
        body: `data: ${JSON.stringify({
          event: "incident_attention.snapshot",
          ts: "2026-09-14T00:00:00Z",
          incidents: [{
            incident_id: "INC-1",
            correlation_id: "corr-1",
            title: "Pod restart detected",
            severity: "high",
            status: "open",
            opened_at: "2026-09-14T00:00:00Z",
            last_updated_at: "2026-09-14T00:01:00Z",
          }],
        })}\n\n`,
      });
    } else if (path.endsWith("/chat/stream")) {
      const request: ChatRequest = route.request().postDataJSON();
      requests.push(request);
      await route.fulfill({
        contentType: "text/event-stream",
        body: `event: done\ndata: ${JSON.stringify(terminal?.(request) ?? {
          seq: 1, revision: 1, answer: "Synthetic test answer.",
          source: "semantic:direct-response", model: "test",
        })}\n\n`,
      });
    } else if (path.endsWith("/chat/health")) {
      await route.fulfill({ json: { available: true, mode: "test", model: "test" } });
    } else {
      await route.fulfill({ status: 404, json: { detail: "Unavailable in entry-point fixture" } });
    }
  });
  await page.goto(`/overview?locale=${locale}`);
  await expect(page.locator(".deck-invoke")).toBeVisible();
  return requests;
}

for (const [locale, catalog, answerEvidence, runRecord] of [
  ["en", en, answerEvidenceEn, runRecordEn],
  ["ko", ko, answerEvidenceKo, runRecordKo],
] as const) {
  test(`separates elapsed time, cumulative models and input/output usage (${locale})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await openConsole(page, locale, (request) => ({
      seq: 1, revision: 1, request_id: request.request_id,
      answer: "Synthetic timing record.", source: "deterministic", execution_authority: false,
      usage: { prompt_tokens: 33905, completion_tokens: 1197, total_tokens: 35102 },
      latency_ms: 22416,
      turn_timing: {
        schema_version: 2, started_at: "2026-10-02T00:00:00Z",
        completed_at: "2026-10-02T00:00:12.800Z", duration_ms: 12800,
        phases: [{ phase: "durable_queue", status: "completed", duration_ms: 69,
          started_at: "2026-10-02T00:00:00Z", completed_at: "2026-10-02T00:00:00.069Z" }],
      },
    }));
    await page.getByRole("button", { name: catalog.deck.generalOpen, exact: true }).click();
    await page.locator(".deck-input").fill("Inspect synthetic usage.");
    await page.locator(".deck-input").press("Enter");
    await page.locator(".deck-trajectory > summary").click();
    const panel = page.locator(".deck-trajectory-performance");
    await expect(panel).toBeVisible();
    await expect(panel.locator('[data-metric="elapsed"] dt')).toHaveText(runRecord.serverElapsed);
    await expect(panel.locator('[data-metric="elapsed"] dd')).toHaveText("12.8 s");
    await expect(panel.locator('[data-metric="model"] dt')).toHaveText(runRecord.cumulativeModelTime);
    await expect(panel.locator('[data-metric="model"] dd')).toHaveText("22.4 s");
    await expect(panel.locator('[data-metric="input"] dd')).toHaveText("33,905");
    await expect(panel.locator('[data-metric="output"] dd')).toHaveText("1,197");
    await expect(panel.locator('[data-metric="total"] dd')).toHaveText("35,102");
    await expect(panel.locator('[data-metric="calls"] dd')).toHaveText(catalog.deck.trajectory.notRecorded);
    await expect(page.getByText(catalog.deck.trajectory.timingPhase.durable_queue, { exact: true })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`performance-${locale}-desktop.png`) });
    for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport);
      expect(await panel.evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
      expect(await page.locator(".deck-overlay").evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath(`performance-${locale}-${viewport.width}.png`) });
    }
  });

  test(`common answer evidence navigation and Markdown inspection (${locale})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    const answer = "## Finding\n\nObserved retention: **45 days**.\n\n| Measure | Value |\n|---|---|\n| Retention | 45 days |";
    await openConsole(page, locale, (request) => ({
      seq: 1, revision: 1, request_id: request.request_id,
      answer, source: "deterministic", execution_authority: false,
      verification: {
        status: "verified", authority: "server_read_model", checks_completed: 1, checks_total: 1,
        evidence_refs: ["sample:retention"], reason_code: "screen_claims_supported",
        claims: [{ claim_id: "claim-1", kind: "number", text: "45 days", span: { start: answer.indexOf("45 days"), end: answer.indexOf("45 days") + 7 }, raw_value: "45 days", normalized_value: "45 days", unit: "days", anchors: ["retention"], status: "supported", evidence_refs: ["sample:retention"], reason_code: null }],
        evidence_manifest: {
          schema_version: 1, manifest_id: "sample-manifest", authority: "server_read_model", route_id: null,
          captured_at: "2026-10-02T00:00:00Z", complete: true, source_entry_count: 1,
          entries: [{ ref: "sample:retention", path: "inventory.snapshot", field: "retention", kind: "number", raw_value: "45 days", normalized_value: "45 days", anchors: ["retention"] }],
        },
      },
      presentation_artifact: {
        schema_version: 1, layout: "stack", evidence_refs: ["sample:retention"],
        blocks: [{ slot_id: "limitations", kind: "callout", title: "Evidence limits", emphasis: "supporting", collapsed: true, evidence_refs: ["sample:retention"], data: { tone: "warning", lines: ["No execution was performed."] } }],
      },
    }));
    await page.getByRole("button", { name: catalog.deck.generalOpen, exact: true }).click();
    await page.locator(".deck-input").fill("Read the retained evidence.");
    await page.locator(".deck-input").press("Enter");
    await expect(page.locator(".deck-answer-posture")).toBeVisible();
    await expect(page.locator(".deck-overlay")).toHaveClass(/cs-deck-conversation/);
    expect(await page.locator(".deck-overlay").evaluate(node => getComputedStyle(node).getPropertyValue("--cs-deck-meta-text").trim())).not.toBe("");
    await expect(page.locator(".deck-rich.cs-deck-prose").first()).toBeVisible();
    await expect(page.locator(".deck-rich-heading").first()).toHaveText("Finding");
    await expect(page.locator('section.deck-presentation-block[data-slot="limitations"]')).toBeVisible();
    await expect(page.getByText("No execution was performed.", { exact: true })).toBeVisible();
    const cite = page.locator("button.deck-cite-chip").first();
    await cite.focus();
    const before = await page.locator(".deck-transcript").evaluate(node => node.scrollTop);
    await page.keyboard.press("Enter");
    await expect(page.locator(".deck-src-detail").first()).toHaveAttribute("open", "");
    await expect(page.locator(".deck-src-detail summary").first()).toBeFocused();
    await expect(page.locator(".deck-src-path")).toHaveText("inventory.snapshot");
    await page.getByRole("button", { name: answerEvidence.returnToAnswer, exact: true }).click();
    await expect(cite).toBeFocused();
    await expect(page.locator(".deck-gr-panel")).toHaveCount(0);
    expect(Math.abs(await page.locator(".deck-transcript").evaluate(node => node.scrollTop) - before)).toBeLessThanOrEqual(1);
    await page.locator(".deck-answer-original summary").focus();
    await page.keyboard.press("Enter");
    await expect(page.locator(".deck-answer-original pre code")).toHaveText(answer);
    await page.locator(".deck-answer-original summary").click();
    await page.keyboard.press("Control+k");
    await expect(page.getByRole("searchbox", { name: catalog.deck.searchConversation })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(page.locator(".deck-search-toggle")).toBeFocused();
    await expect(page.locator(".deck-search")).toBeHidden();
    await page.screenshot({ path: testInfo.outputPath(`common-answer-${locale}-desktop.png`) });
    for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport);
      await cite.click();
      await expect(page.locator(".deck-src-detail").first()).toHaveAttribute("open", "");
      if (await page.locator(".deck-jump").count() > 0) {
        await expect(page.locator(".deck-input-row .deck-composer-context .deck-jump")).toHaveCount(1);
      }
      const unobstructed = await page.locator(".deck-src-path").evaluate(node => {
        const path = node.getBoundingClientRect();
        const jump = document.querySelector(".deck-jump")?.getBoundingClientRect();
        return !jump || jump.width === 0 || path.bottom <= jump.top || path.top >= jump.bottom || path.right <= jump.left || path.left >= jump.right;
      });
      expect(unobstructed).toBe(true);
      const geometry = await page.locator(".deck-overlay").evaluate(node => ({
        fits: node.scrollWidth <= node.clientWidth,
        documentFits: document.documentElement.scrollWidth <= innerWidth,
        clipped: [...node.querySelectorAll(".deck-header,.deck-gr,.deck-gr-panel,.deck-src-row,.deck-answer-original")].filter(element => element.scrollWidth > element.clientWidth + 1).map(element => element.className),
      }));
      expect(geometry).toEqual({ fits: true, documentFits: true, clipped: [] });
      await page.screenshot({ path: testInfo.outputPath(`common-answer-${locale}-${viewport.width}.png`) });
      await page.getByRole("button", { name: answerEvidence.returnToAnswer, exact: true }).click();
    }
  });
}

test("loads the Command Deck implementation only after the operator invokes it", async ({
  page,
}) => {
  const deckModules: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/src/deck/command-deck.tsx") {
      deckModules.push(request.url());
    }
  });

  await openConsole(page);
  await page.waitForTimeout(100);
  expect(deckModules).toEqual([]);

  await page.locator(".deck-invoke").click();
  await expect(page.locator(".deck-overlay")).toBeVisible();
  expect(deckModules.length).toBeGreaterThan(0);
});

test("loads the deferred screen conversation from its keyboard shortcut", async ({ page }) => {
  await openConsole(page);

  await page.keyboard.press("Control+k");

  await expect(page.locator(".deck-overlay")).toBeVisible();
  await expect(page.locator(".deck-input")).toBeFocused();
});

test("opens incident attention over a preserved screen draft and submits its binding", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const requests = await openConsole(page, "en", undefined, true);

  await page.locator(".deck-invoke").click();
  await page.locator(".deck-input").fill("Preserve this screen draft");
  await page.locator(".deck-close").click();

  await page.getByRole("button", {
    name: "Open 1 active incident conversation(s)",
    exact: true,
  }).click();

  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0]?.conversation_context).toEqual({
    kind: "incident",
    incident_id: "INC-1",
    correlation_id: "corr-1",
  });
  expect(requests[0]?.view_context).not.toHaveProperty("routeId");
  expect(requests[0]?.target_agent).toBeUndefined();
  await expect(page.locator(".deck-header-conversation-title")).toHaveText("Incident INC-1");
  await expect(page.getByText("Synthetic test answer.", { exact: true })).toBeVisible();

  await page.locator(".deck-close").click();
  await page.locator(".deck-invoke").click();
  await expect(page.locator(".deck-input")).toHaveValue("Preserve this screen draft");
});

test("isolates general and screen drafts, history, context and layout", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const requests = await openConsole(page);
  const input = page.locator(".deck-input");
  const deck = page.locator(".deck-overlay");

  await page.getByRole("button", { name: "Open general conversation", exact: true }).focus();
  await expect(page.getByRole("tooltip")).toContainText("without including the current screen");
  await page.getByRole("button", { name: "Open general conversation", exact: true }).click();
  await expect(deck).toHaveClass(/deck-overlay-mode-workspace/);
  await expect(deck.getByRole("heading", { name: "How can I help?" })).toBeVisible();
  await expect(deck.locator(".deck-header-route")).toHaveText("General");
  await expect(deck.locator(".deck-intro-card")).toHaveCount(0);
  expect(requests).toHaveLength(0);
  await input.fill("General draft");
  await page.locator(".deck-close").click();
  await expect(page.getByRole("button", { name: "Open general conversation", exact: true })).toBeFocused();
  await page.locator(".deck-invoke").focus();
  await expect(page.getByRole("tooltip", { name: /Includes this screen/ })).toBeVisible();
  await page.locator(".deck-invoke").click();
  await expect(deck).toHaveClass(/deck-overlay-mode-dock/);
  await expect(input).toHaveValue("");
  await expect(page.getByRole("button", { name: "Remove reference screen: Dashboard" })).toBeVisible();
  await input.fill("Screen draft");
  await page.getByRole("button", { name: "Open general conversation", exact: true }).click();
  await expect(input).toHaveValue("General draft");
  await expect(deck).toHaveClass(/deck-overlay-mode-workspace/);
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0]?.view_context).not.toHaveProperty("routeId");
  expect(requests[0]?.view_context).not.toHaveProperty("facts");
  await expect(deck.getByText("Synthetic test answer.", { exact: true })).toBeVisible();

  await page.locator(".deck-close").click();
  await page.locator(".deck-invoke").click();
  await expect(input).toHaveValue("Screen draft");
  await input.press("Enter");
  await expect.poll(() => requests.length).toBe(2);
  expect(requests[1]?.view_context.routeId).toBeTruthy();
  expect(requests[1]?.session_id).not.toBe(requests[0]?.session_id);
  expect(requests[1]?.history).not.toContainEqual(expect.objectContaining({ content: "General draft" }));
  await expect(deck.getByText("Synthetic test answer.", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Open general conversation", exact: true }).click();
  await page.getByRole("button", { name: "Add current screen", exact: true }).click();
  await expect(page.getByRole("button", { name: "Remove reference screen: Dashboard" })).toBeVisible();
  await input.fill("Explicit screen question");
  await input.press("Enter");
  await expect.poll(() => requests.length).toBe(3);
  expect(requests[2]?.view_context.routeId).toBe(requests[1]?.view_context.routeId);
  expect(requests[2]?.session_id).toBe(requests[0]?.session_id);
  await expect(input).toHaveValue("");
  await expect(page.getByRole("button", { name: "Send", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Remove reference screen: Dashboard" }).click();
  await input.fill("Unscoped again");
  await input.press("Enter");
  await expect.poll(() => requests.length).toBe(4);
  expect(requests[3]?.view_context).not.toHaveProperty("routeId");
  await expect(page.getByRole("button", { name: "Send", exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("general-desktop.png") });

  await page.getByRole("button", { name: "Add current screen", exact: true }).click();
  await page.getByRole("button", { name: "Floating panel", exact: true }).click();
  await page.evaluate(() => {
    history.pushState(null, "", "/audit");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });

  await expect(deck).toHaveClass(/deck-overlay-mode-floating/);
  await expect(page.getByRole("button", { name: "Remove reference screen: Dashboard" })).toBeVisible();
  await input.fill("Still the attached screen");
  await input.press("Enter");
  await expect.poll(() => requests.length).toBe(5);
  expect(requests[4]?.view_context.routeId).toBe(requests[1]?.view_context.routeId);
  await expect(page.getByRole("button", { name: "Send", exact: true })).toBeVisible();
  await page.locator(".deck-close").click();
  await expect(deck).toBeHidden();
  await page.keyboard.press("Control+k");
  await expect(deck).toHaveClass(/deck-overlay-mode-dock/);
  await expect(input).toHaveValue("");
  await expect(page.getByRole("button", { name: /Remove reference screen:/ })).not.toHaveText(/Dashboard/);
});

for (const { locale, catalog } of [{ locale: "en", catalog: en }, { locale: "ko", catalog: ko }]) {
  test(`renders and restores ${locale} adaptive sources without a blanket receipt`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    const answer = locale === "ko"
      ? "블루-그린은 트래픽을 한 번에 전환하고, 카나리는 점진적으로 전환합니다."
      : "Blue-green switches traffic at once; canary shifts traffic gradually.";
    const requests = await openConsole(page, locale, (request) => ({
      v: 1, seq: 1, revision: 0, request_id: request.request_id,
      status: "advisory_response", source: "semantic-advisory-response",
      answer, execution_authority: false,
      adaptive_answer: {
        answer, role_agent: "Bragi", quality_status: "limited", refinements: 0,
        execution_authority: false,
        goals: [
          { goal_id: "explain", kind: "knowledge", required: true,
            status: "answered", evidence_refs: [], limitation: null },
          { goal_id: "example", kind: "environment_example", required: false,
            status: "unavailable", evidence_refs: [],
            limitation: "adaptive_evidence_budget_exhausted" },
        ],
      },
    }));
    await page.getByRole("button", { name: catalog.deck.generalOpen, exact: true }).click();
    await page.getByRole("button", {
      name: catalog.deck.generalStarters.compare.label, exact: true,
    }).click();
    await expect(page.getByText(answer, { exact: true })).toBeVisible();
    expect(requests).toHaveLength(1);
    expect(requests[0]?.view_context).not.toHaveProperty("facts");
    const sources = page.getByRole("region", { name: catalog.deck.adaptive.sources });
    await expect(sources.getByText(catalog.deck.adaptive.knowledge, { exact: true })).toBeVisible();
    await expect(sources.getByText(catalog.deck.adaptive.answered, { exact: true })).toHaveCount(0);
    const details = sources.locator('[data-goal-id="example"] details');
    await expect(details.locator("p")).toBeHidden();
    await details.locator("summary").focus();
    await page.keyboard.press("Enter");
    await expect(details.locator("p")).toHaveText("adaptive_evidence_budget_exhausted");
    await expect(details.locator("p")).toBeVisible();

    await page.locator(".deck-header-history").click();
    const savedTitle = await page.locator(
      ".deck-conversation-select[aria-current='true'] .deck-conversation-title",
    ).innerText();
    await page.reload();
    await page.getByRole("button", { name: catalog.deck.generalOpen, exact: true }).click();
    await page.locator(".deck-header-history").click();
    await page.locator(".deck-conversation-select").filter({
      has: page.getByText(savedTitle, { exact: true }),
    }).click();
    await expect(page.getByText(answer, { exact: true })).toBeVisible();
    await expect(sources.getByText(catalog.deck.adaptive.knowledge, { exact: true })).toBeVisible();
    expect(requests).toHaveLength(1);
    await expect(page.locator(".deck-overlay")).toHaveClass(/deck-overlay-mode-workspace/);
    if (await page.locator(".deck-conversations").isVisible()) {
      await page.locator(".deck-header-history").click();
    }
    await details.locator("summary").click();
    await expect(details.locator("p")).toBeVisible();

    for (const size of [
      { width: 1440, height: 900 },
      { width: 993, height: 641 },
      { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(size);
      await sources.scrollIntoViewIfNeeded();
      const geometry = await sources.evaluate((element) => ({
        width: element.clientWidth,
        scrollWidth: element.scrollWidth,
        documentWidth: document.documentElement.clientWidth,
        documentScrollWidth: document.documentElement.scrollWidth,
      }));
      expect(geometry.width).toBeGreaterThan(0);
      expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.width);
      expect(geometry.documentScrollWidth).toBeLessThanOrEqual(geometry.documentWidth);
      await page.screenshot({ path: testInfo.outputPath(`advisory-${locale}-${size.width}.png`) });
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    expect(await sources.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    await page.locator(".deck-input").fill("Compare again.");
    await page.locator(".deck-input").press("Enter");
    await expect.poll(() => requests.length).toBe(2);
    expect(requests[1]?.view_context).not.toHaveProperty("facts");
    expect(requests[1]?.view_context).not.toHaveProperty("routeId");
  });

  test(`recovers ${locale} stored answers when cache contains only the question`, async ({ page }) => {
    const answer = locale === "ko" ? "저장된 비교 답변입니다." : "This is the stored comparison.";
    const adaptive = {
      answer, role_agent: "Bragi", quality_status: "limited", refinements: 1,
      execution_authority: false,
      goals: [{
        goal_id: "explain", kind: "knowledge", required: true,
        status: "answered", evidence_refs: [], limitation: null,
      }],
    };
    const requests = await openConsole(page, locale, (request) => ({
      v: 1, seq: 1, revision: 0, request_id: request.request_id,
      status: "advisory_response", source: "semantic-advisory-response",
      answer, adaptive_answer: adaptive, execution_authority: false,
    }));
    await page.getByRole("button", { name: catalog.deck.generalOpen, exact: true }).click();
    await page.getByRole("button", {
      name: catalog.deck.generalStarters.compare.label, exact: true,
    }).click();
    await expect(page.getByText(answer, { exact: true })).toBeVisible();
    await page.locator(".deck-header-history").click();
    const savedTitle = await page.locator(
      ".deck-conversation-select[aria-current='true'] .deck-conversation-title",
    ).innerText();
    await page.reload();
    const cached = await page.evaluate((text) => {
      const key = Object.keys(localStorage).find((name) =>
        name.startsWith("fdai.deck.transcript.v1") &&
        (localStorage.getItem(name) ?? "").includes(text));
      if (!key) throw new Error("Expected isolated cached transcript");
      const turns = JSON.parse(localStorage.getItem(key) ?? "[]") as Array<{
        id: string; role: string; text: string; recordedAt: string;
      }>;
      localStorage.setItem(key, JSON.stringify(turns.filter((turn) => turn.role === "operator")));
      return turns;
    }, answer);
    let recoveryReads = 0;
    await page.route("**/me/conversations/*/turns?**", async (route) => {
      recoveryReads += 1;
      const pathname = new URL(route.request().url()).pathname;
      const conversationId = decodeURIComponent(pathname.split("/").at(-2) ?? "");
      await route.fulfill({ json: { turns: cached.map((turn, index) => ({
        turn_id: turn.id, conversation_id: conversationId, turn_index: index,
        role: turn.role === "operator" ? "operator" : "assistant",
        content: turn.text, recorded_at: turn.recordedAt,
        metadata: turn.role === "operator" ? {} : {
          source: "semantic-advisory-response",
          replay_payload: JSON.stringify({
            status: "advisory_response", source: "semantic-advisory-response",
            answer, adaptive_answer: adaptive, execution_authority: false,
          }),
        },
      })) } });
    });
    await page.getByRole("button", { name: catalog.deck.generalOpen, exact: true }).click();
    await page.locator(".deck-header-history").click();
    await page.locator(".deck-conversation-select").filter({
      has: page.getByText(savedTitle, { exact: true }),
    }).click();
    await expect(page.getByText(answer, { exact: true })).toBeVisible();
    expect(recoveryReads).toBeGreaterThan(0);
    expect(requests).toHaveLength(1);
  });

  for (const [key, starter] of Object.entries(catalog.deck.generalStarters)) {
    test(`sends ${locale} ${key} starter immediately through normal submission`, async ({ page }) => {
      const requests = await openConsole(page, locale);
      await page.getByRole("button", { name: catalog.deck.generalOpen, exact: true }).click();
      const button = page.getByRole("button", { name: starter.label, exact: true });
      await button.focus();
      await expect(page.getByRole("tooltip", {
        name: catalog.deck.generalStarterSendHint.replace("{prompt}", starter.prompt),
        exact: true,
      })).toBeVisible();
      if (key === "summarize") await button.press("Enter");
      else await button.click();
      await expect.poll(() => requests.length).toBe(1);
      expect(requests[0]?.prompt).toBe(starter.prompt);
      expect(requests[0]?.view_context).not.toHaveProperty("routeId");
      expect(requests[0]?.view_context).not.toHaveProperty("facts");
      await expect(page.locator(".deck-turn-operator")).toContainText(starter.prompt);
      await expect(page.locator(".deck-input")).toHaveValue("");
      await expect(page.getByText("Synthetic test answer.", { exact: true })).toBeVisible();
      expect(requests).toHaveLength(1);
    });
  }
}

test("keeps bilingual starters and context controls usable across viewport sizes", async ({ page }, testInfo) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await openConsole(page, "ko");
  await page.getByRole("button", { name: "일반 대화 열기", exact: true }).click();
  for (const size of [
    { width: 1440, height: 900 },
    { width: 993, height: 641 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(size);
    await expect(page.getByRole("heading", { name: "무엇을 도와드릴까요?" })).toBeVisible();
    await expect(page.getByRole("button", { name: "현재 화면 추가", exact: true })).toBeInViewport();
    await expect(page.locator(".deck-input")).toBeInViewport();
    const overflow = await page.locator("html, .deck-overlay, .deck-transcript").evaluateAll(
      (elements) => elements.map((element) => element.scrollWidth > element.clientWidth),
    );
    expect(overflow).toEqual([false, false, false]);
    await page.screenshot({ path: testInfo.outputPath(`general-ko-${size.width}.png`) });
    await page.locator(".deck-close").click();
    await expect(page.locator(".deck-overlay")).toBeHidden();
    await page.locator(".deck-invoke").click();
    await expect(page.getByRole("button", { name: "참고 화면 제거: 대시보드" })).toBeInViewport();
    await expect(page.locator(".deck-input")).toBeInViewport();
    expect(await page.locator("html, .deck-overlay").evaluateAll(
      (elements) => elements.every((element) => element.scrollWidth <= element.clientWidth),
    )).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`screen-ko-${size.width}.png`) });
    await page.locator(".deck-close").click();
    await page.getByRole("button", { name: "일반 대화 열기", exact: true }).click();
  }
});
