import { fileURLToPath, pathToFileURL } from "node:url";

import { expect, test, type FrameLocator, type Page } from "@playwright/test";

const mockUrl = pathToFileURL(fileURLToPath(
  new URL("../../../mocks/ui/deck-sources-v2.html", import.meta.url),
)).href;

async function openWorkspace(page: Page) {
  await page.goto(mockUrl);
  await page.locator("#ex-preview-controls > summary").click();
  await page.locator("#ex-demo-options > summary").click();
  await page.getByRole("button", { name: "Workspace shell" }).click();
  return page.getByRole("region", { name: "Adaptive Command deck response mock" });
}

const masterUrl = pathToFileURL(fileURLToPath(new URL("../../../index.html", import.meta.url))).href;

async function openAdaptiveChat(page: Page) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.clock.install();
  await page.goto(`${masterUrl}#mocks/ui/deck-sources-v2.html`);
  const frame = page.frameLocator("#preview-frame");
  await expect(frame.locator("#ex-workbench")).toHaveAttribute("data-stage", "complete");
  await frame.locator("#ex-preview-controls > summary").click();
  return frame;
}

async function advanceToStage(page: Page, frame: FrameLocator, stage: string) {
  for (let tick = 0; tick < 80; tick += 1) {
    if (await frame.locator("#ex-workbench").getAttribute("data-stage") === stage) return;
    await page.clock.runFor(200);
  }
  await expect(frame.locator("#ex-workbench")).toHaveAttribute("data-stage", stage);
}

test("keeps investigation continuous from pending through verification to the same retained record", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "Desktop gates precede responsive inspection.");
  const frame = await openAdaptiveChat(page);
  const workspace = frame.locator("#ex-workbench");
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await expect(frame.locator(".ex-thread > .is-bragi")).toBeVisible();
  await expect(frame.locator("#ex-final")).toHaveCSS("opacity", "1");
  await expect(frame.locator("#ex-pattern-applied")).toBeHidden();
  await expect(frame.locator(".ex-observed")).not.toHaveAttribute("open", "");
  await page.screenshot({ path: testInfo.outputPath("adaptive-answer-desktop.png") });
  await frame.getByRole("button", { name: "Replay investigation", exact: true }).click();
  await expect(workspace).toHaveAttribute("data-stage", "pending");
  await expect(workspace).toHaveAttribute("data-outcome", "pending");
  await expect(frame.locator(".ex-initial-skeleton")).toBeVisible();
  await expect(frame.locator(".ex-answer-preparing")).toHaveAttribute("aria-busy", "true");
  await expect(frame.locator("#ex-investigation")).toBeHidden();
  await expect(frame.locator("#ex-final")).toBeHidden();
  await page.screenshot({ path: testInfo.outputPath("adaptive-pending-desktop.png") });
  await advanceToStage(page, frame, "preparing");
  await expect(frame.locator(".ex-preparation-details")).not.toHaveAttribute("open", "");
  await advanceToStage(page, frame, "investigating");
  await expect(frame.locator(".ex-answer-preparing")).toBeHidden();
  await expect(frame.locator("#ex-investigation")).toHaveAttribute("open", "");
  await expect(frame.locator(".ex-step-detail.is-open")).toHaveCount(0);
  await expect(frame.locator("#ex-promotion")).toContainText("Simulation only");
  await expect(frame.locator("#ex-run .ex-step.is-complete")).toHaveCount(0);
  await frame.locator("#ex-run").evaluate((element) => { element.dataset.continuity = "same-record"; });
  await page.screenshot({ path: testInfo.outputPath("adaptive-investigation-desktop.png") });
  const firstStep = frame.locator("#ex-run .ex-step").first();
  await firstStep.locator(".ex-step-toggle").click();
  await expect(firstStep.locator(".ex-step-toggle")).toHaveAttribute("aria-expanded", "true");
  await frame.locator("#ex-promotion").click();
  await page.clock.runFor(600);
  await expect(frame.locator("#ex-investigation")).not.toHaveAttribute("open", "");
  await advanceToStage(page, frame, "verifying");
  await expect(frame.locator("#ex-final")).toBeHidden();
  await frame.locator("#ex-promotion").click();
  await expect(frame.locator("#ex-promotion")).toContainText("Verifying");
  await expect(firstStep.locator(".ex-step-toggle")).toHaveAttribute("aria-expanded", "true");
  await page.screenshot({ path: testInfo.outputPath("adaptive-verifying-desktop.png") });
  await advanceToStage(page, frame, "complete");
  await expect(frame.locator("#ex-investigation")).toBeHidden();
  await expect(frame.locator("#ex-final")).toHaveCSS("opacity", "1");
  await expect(frame.locator(".ex-observed #ex-run")).toHaveAttribute("data-continuity", "same-record");
  await expect(frame.locator(".ex-observed")).toHaveAttribute("open", "");
  await expect(firstStep.locator(".ex-step-toggle")).toHaveAttribute("aria-expanded", "true");
  await expect(frame.locator(".ex-observed .ex-step.is-complete")).toHaveCount(6);
  await expect(frame.locator(".ex-stream-answer")).toContainText("does not modify files or cloud resources");
  await expect(frame.locator(".ex-stream-answer")).toHaveAttribute("aria-busy", "false");
  await expect(frame.getByRole("button", { name: "Stop replay" })).toBeDisabled();
  expect(errors).toEqual([]);
});

test("cancels old replay generations and separates compact, unverified, and alternate replies", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium");
  const frame = await openAdaptiveChat(page);
  const workspace = frame.locator("#ex-workbench");
  await frame.getByRole("button", { name: "Replay investigation", exact: true }).click();
  await frame.getByRole("button", { name: "Stop replay" }).click();
  await expect(workspace).toHaveAttribute("data-stage", "cancelled");
  await expect(frame.locator(".ex-stream-answer")).toContainText("No verified conclusion");
  await page.clock.runFor(20000);
  await expect(workspace).toHaveAttribute("data-stage", "cancelled");
  await expect(frame.locator(".ex-step.is-complete")).toHaveCount(0);
  await frame.locator("#ex-demo-options > summary").click();
  await frame.getByRole("button", { name: "Show unverified" }).click();
  await expect(workspace).toHaveAttribute("data-stage", "unverified");
  await expect(frame.locator("#ex-promotion")).toBeHidden();
  await expect(frame.locator(".ex-verification-status")).toContainText("Unsupported claim");
  await expect(frame.locator(".ex-observed-summary")).toContainText("Not verified");
  await frame.getByRole("button", { name: "Replay investigation", exact: true }).click();
  await expect(workspace).toHaveAttribute("data-outcome", "pending");
  await advanceToStage(page, frame, "investigating");
  await page.clock.runFor(900);
  await frame.getByRole("button", { name: "Stop replay" }).click();
  const completedBeforeStop = await frame.locator(".ex-step.is-complete").count();
  expect(completedBeforeStop).toBeGreaterThan(0);
  expect(completedBeforeStop).toBeLessThan(6);
  await page.clock.runFor(20000);
  await expect(workspace).toHaveAttribute("data-stage", "cancelled");
  await expect(frame.locator(".ex-step.is-complete")).toHaveCount(completedBeforeStop);
  await expect(frame.locator(".ex-answer-preparing")).toHaveAttribute("aria-busy", "false");
  await frame.getByRole("button", { name: "Replay investigation", exact: true }).click();
  await advanceToStage(page, frame, "investigating");
  await frame.getByRole("button", { name: "Compact answer", exact: true }).click();
  await advanceToStage(page, frame, "compact");
  const compactAnswer = await frame.locator(".ex-stream-answer").innerText();
  await page.clock.runFor(20000);
  await expect(workspace).toHaveAttribute("data-stage", "compact");
  expect(await frame.locator(".ex-stream-answer").innerText()).toBe(compactAnswer);
  await expect(frame.locator("#ex-investigation")).toBeHidden();
  await expect(frame.locator(".ex-stream-answer")).toContainText("No live health check");
  await frame.getByRole("button", { name: "Replay investigation", exact: true }).click();
  await frame.locator(".ex-pattern-switcher > summary").click();
  await frame.getByRole("button", { name: "Investigation", exact: true }).click();
  await expect(workspace).toHaveAttribute("data-stage", "example");
  await expect(frame.locator("#ex-pattern-applied")).toBeFocused();
  await expect(frame.locator(".ex-thread > .is-bragi")).toBeHidden();
  await expect(frame.locator("#ex-pattern-applied .is-bragi")).toBeVisible();
  await page.clock.runFor(20000);
  await expect(workspace).toHaveAttribute("data-stage", "example");
  await frame.getByRole("button", { name: "Show result", exact: true }).click();
  await expect(frame.locator("#ex-pattern-applied")).toBeHidden();
  await expect(frame.locator(".ex-thread > .is-bragi")).toBeVisible();
});

test("fits the same investigation inside constrained and mobile master-shell chat frames", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium");
  const frame = await openAdaptiveChat(page);
  await frame.getByRole("button", { name: "Replay investigation", exact: true }).click();
  await advanceToStage(page, frame, "investigating");
  for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await page.clock.runFor(16);
    await expect.poll(() => frame.locator("#ex-workbench").evaluate((element) =>
      element.getBoundingClientRect().bottom <= innerHeight + 1,
    )).toBe(true);
    const metrics = await frame.locator("#ex-workbench").evaluate((element) => {
      const thread = element.querySelector(".ex-thread")!;
      return {
        rootOverflow: element.scrollWidth - element.clientWidth,
        threadOverflow: thread.scrollWidth - thread.clientWidth,
        documentOverflow: document.documentElement.scrollWidth - innerWidth,
        height: element.getBoundingClientRect().height,
        bottom: element.getBoundingClientRect().bottom,
        viewport: innerHeight,
      };
    });
    expect(metrics.rootOverflow).toBe(0);
    expect(metrics.threadOverflow).toBe(0);
    expect(metrics.documentOverflow).toBe(0);
    expect(metrics.height).toBeGreaterThan(200);
    expect(metrics.bottom).toBeLessThanOrEqual(metrics.viewport + 1);
    await frame.locator("#ex-promotion").scrollIntoViewIfNeeded();
    await expect(frame.locator("#ex-promotion")).toBeInViewport();
    await page.screenshot({ path: testInfo.outputPath(`adaptive-investigation-${viewport.width}x${viewport.height}.png`) });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await frame.getByRole("button", { name: "Show result", exact: true }).click();
  await expect(frame.locator("#ex-final")).toHaveCSS("opacity", "1");
});

test("streams only after verification and respects a collapsed investigation at completion", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium");
  const frame = await openAdaptiveChat(page);
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await frame.getByRole("button", { name: "Replay investigation", exact: true }).click();
  await advanceToStage(page, frame, "investigating");
  await frame.locator("#ex-run .ex-step-toggle").first().click();
  await frame.locator("#ex-promotion").click();
  await expect(frame.locator("#ex-investigation")).not.toHaveAttribute("open", "");
  await advanceToStage(page, frame, "answering");
  await expect(frame.locator("#ex-run .ex-step.is-complete")).toHaveCount(6);
  await expect(frame.locator(".ex-stream-answer")).toHaveAttribute("aria-busy", "true");
  await expect(frame.locator(".ex-final-reveal")).toBeHidden();
  await advanceToStage(page, frame, "complete");
  await expect(frame.locator(".ex-observed")).not.toHaveAttribute("open", "");
  await expect(frame.locator(".ex-stream-answer")).toHaveAttribute("aria-busy", "false");
  await expect(frame.locator("#ex-run .ex-step-toggle").first()).toHaveAttribute("aria-expanded", "true");
  const search = frame.getByRole("searchbox", { name: "Search this conversation" });
  await search.fill("Database pressure");
  await expect(frame.locator(".ex-window-search-count")).toHaveText("0/0");
  await search.fill("Synthetic replay only");
  await expect(frame.locator(".ex-observed")).toHaveAttribute("open", "");
  await expect(frame.locator(".ex-search-match")).toBeInViewport();
});

test("keeps the adaptive mock shell stateful and production-shaped", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "One browser covers the ordered viewport sequence.");
  await page.emulateMedia({ reducedMotion: "reduce" });

  await page.setViewportSize({ width: 1440, height: 900 });
  let workspace = await openWorkspace(page);
  await expect(workspace).toHaveAttribute("data-conversations", "closed");
  await expect(workspace).toHaveAttribute("data-digest", "closed");
  await expect(workspace.getByRole("complementary", { name: "Conversations" })).toBeHidden();
  await expect(workspace.getByRole("complementary", { name: "What the deck sees" })).toBeHidden();

  await workspace.getByRole("button", { name: /Conversations/ }).click();
  const conversations = workspace.getByRole("complementary", { name: "Conversations" });
  await expect(conversations).toBeVisible();
  await expect(conversations).toHaveCSS("width", "240px");
  await expect(conversations.locator(".ex-conversations-count")).toHaveText("20+");
  await expect(conversations.locator(".ex-conversation-group h3")).toHaveText([
    "Current screen",
    "Other screens",
    "Agent conversations",
  ]);
  const resize = conversations.getByRole("separator", { name: "Conversations" });
  await resize.focus();
  await page.keyboard.press("ArrowRight");
  await expect(resize).toHaveAttribute("aria-valuenow", "260");
  await expect(conversations).toHaveCSS("width", "260px");
  await page.keyboard.press("ArrowLeft");
  await expect(resize).toHaveAttribute("aria-valuenow", "240");
  const favorite = conversations.locator(".ex-conversation-item").filter({ hasText: "Any stopped databases?" })
    .locator(".ex-conversation-favorite");
  await favorite.click();
  await expect(favorite).toHaveAttribute("aria-pressed", "true");
  await expect(favorite).toHaveAccessibleName("Remove favorite: Any stopped databases?");
  await conversations.getByRole("button", { name: "Unread" }).click();
  await expect(conversations.locator(".ex-conversation-item:visible")).toHaveCount(2);
  await conversations.getByRole("button", { name: "Favorites" }).click();
  await expect(conversations.locator(".ex-conversation-item:visible")).toHaveCount(3);
  await conversations.getByRole("button", { name: "Mine" }).click();
  await expect(conversations.locator(".ex-conversation-item:visible")).toHaveCount(6);
  await conversations.getByRole("searchbox", { name: "Filter conversations" }).fill("stopped");
  await expect(conversations.locator(".ex-conversation-item:visible")).toHaveCount(1);
  await conversations.locator(".ex-conversation-select").filter({ hasText: "Any stopped databases?" }).click();
  await expect(conversations).toBeHidden();

  await workspace.getByRole("button", { name: /Conversations/ }).click();
  await conversations.getByRole("searchbox", { name: "Filter conversations" }).fill("");
  await conversations.getByRole("button", { name: "Remove cached conversation: New conversation" }).click();
  await expect(conversations.locator(".ex-conversations-count")).toHaveText("19+");
  await conversations.getByRole("button", { name: "New conversation" }).click();
  await expect(conversations).toBeHidden();
  await expect(workspace.locator(".ex-user-message")).toHaveText("What can I investigate from the current Dashboard context?");

  await workspace.getByRole("button", { name: /What I see/ }).click();
  const digest = workspace.getByRole("complementary", { name: "What the deck sees" });
  await expect(digest).toBeVisible();
  await expect(digest).toHaveCSS("width", "280px");
  await expect(digest.locator(".ex-digest-freshness")).toHaveAttribute("data-state", "stale");
  await digest.getByRole("button", { name: "Refresh" }).click();
  await expect(digest.locator(".ex-digest-freshness")).toHaveAttribute("data-state", "fresh");
  await expect(digest.getByText("Just now")).toBeVisible();
  const sourceState = page.locator("#ex-sources");
  await sourceState.click();
  const sourceReadiness = workspace.locator(".ex-source-readiness");
  await expect(sourceReadiness).toHaveAttribute("role", "status");
  await expect(sourceReadiness).toHaveAttribute("aria-busy", "true");
  await sourceState.click();
  await expect(sourceReadiness).toHaveClass(/is-error/);
  await expect(sourceReadiness).toContainText("Evidence sources unavailable");
  await expect(sourceReadiness.getByRole("link", { name: "Open diagnostics" })).toBeVisible();
  await sourceState.click();
  await expect(workspace.getByRole("navigation", { name: "Evidence sources" })).toBeVisible();
  await expect(sourceReadiness.locator(".ex-source-status")).toHaveCount(3);

  const transcriptSearch = workspace.getByRole("searchbox", { name: "Search this conversation" });
  await expect(workspace).toHaveAttribute("data-stage", "compact");
  await page.keyboard.press("Control+K");
  await expect(transcriptSearch).toBeFocused();
  await transcriptSearch.fill("probe");
  await expect(workspace.locator(".ex-search-match")).toHaveCount(1);
  const searchCount = workspace.locator(".ex-window-search-count");
  await expect(searchCount).toHaveText(/^1\/\d+$/);
  await workspace.getByRole("button", { name: "Next match" }).click();
  await expect(searchCount).toHaveText(/^2\/\d+$/);
  await workspace.getByRole("button", { name: "Previous match" }).click();
  await expect(searchCount).toHaveText(/^1\/\d+$/);
  await transcriptSearch.focus();
  await page.keyboard.press("Escape");
  await expect(transcriptSearch).toHaveValue("");
  const message = workspace.getByRole("textbox", { name: "Message" });
  await expect(message).toBeFocused();
  const send = workspace.getByRole("button", { name: "Send" });
  await send.focus();
  await page.keyboard.press("Tab");
  await expect(transcriptSearch).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(send).toBeFocused();
  await workspace.getByRole("button", { name: "Dock right" }).click();
  await expect(workspace).toHaveAttribute("data-layout", "dock");
  await expect(digest).toBeHidden();
  await workspace.getByRole("button", { name: "Floating panel" }).click();
  await expect(workspace).toHaveAttribute("data-layout", "floating");
  await workspace.getByRole("button", { name: "Full workspace" }).click();
  await expect(workspace).toHaveAttribute("data-layout", "workspace");

  await page.getByRole("button", { name: "Show result" }).click();
  const transcript = workspace.locator(".ex-thread");
  await transcript.evaluate((element) => { element.scrollTop = 0; });
  await workspace.getByRole("button", { name: "Jump to latest" }).click();
  await expect(transcript).toHaveAttribute("data-position", "latest");

  const attach = workspace.locator(".ex-attach");
  await attach.click();
  await expect(attach).toHaveAttribute("aria-pressed", "true");
  await expect(attach).toHaveAccessibleName("Remove staged evidence");
  await message.fill("Show the current bounded evidence.");
  await workspace.getByRole("button", { name: "Send" }).click();
  await expect(workspace.locator(".ex-user-message")).toHaveText("Show the current bounded evidence.");
  await workspace.locator(".ex-new-conversation").click();
  await expect(workspace.locator(".ex-user-message")).toHaveText("What can I investigate from the current Dashboard context?");
  await page.screenshot({ path: testInfo.outputPath("adaptive-shell-1440x900.png") });
  await workspace.getByRole("button", { name: "Close command deck" }).click();
  await expect(workspace).toHaveAttribute("data-shell", "specimen");
  await page.getByRole("button", { name: "Workspace shell" }).click();
  await workspace.locator(".ex-attach").focus();
  await page.keyboard.press("Escape");
  await expect(workspace).toHaveAttribute("data-shell", "specimen");

  await page.setViewportSize({ width: 745, height: 589 });
  workspace = await openWorkspace(page);
  await workspace.getByRole("button", { name: /Conversations/ }).click();
  const constrainedMetrics = await workspace.evaluate((root) => {
    const body = root.querySelector<HTMLElement>(".ex-workspace-body")!;
    const panel = root.querySelector<HTMLElement>(".ex-conversations")!;
    const transcriptColumn = root.querySelector<HTMLElement>(".ex-transcript-column")!;
    const rootRect = root.getBoundingClientRect();
    const overflowers = Array.from(root.querySelectorAll<HTMLElement>("*"))
      .filter((element) => element.getBoundingClientRect().width > 0)
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          selector: `${element.tagName.toLowerCase()}.${element.className}`,
          left: Math.round(rect.left - rootRect.left),
          right: Math.round(rect.right - rootRect.right),
          scrollWidth: element.scrollWidth,
          clientWidth: element.clientWidth,
        };
      })
      .filter(({ left, right, scrollWidth, clientWidth }) =>
        left < -1 || right > 1 || scrollWidth > clientWidth + 1)
      .slice(0, 12);
    return {
      bodyWidth: Math.round(body.getBoundingClientRect().width),
      panelPosition: getComputedStyle(panel).position,
      panelWidth: Math.round(panel.getBoundingClientRect().width),
      transcriptWidth: Math.round(transcriptColumn.getBoundingClientRect().width),
      overflow: root.scrollWidth - root.clientWidth,
      overflowers,
    };
  });
  expect(constrainedMetrics.panelPosition).toBe("absolute");
  expect(constrainedMetrics.panelWidth).toBe(240);
  expect(constrainedMetrics.transcriptWidth).toBe(constrainedMetrics.bodyWidth);
  expect(constrainedMetrics.overflow, JSON.stringify(constrainedMetrics.overflowers, null, 2)).toBe(0);
  const constrainedConversations = workspace.getByRole("complementary", { name: "Conversations" });
  await constrainedConversations.getByRole("button", { name: "Close conversations" }).click();
  await expect(constrainedConversations).toBeHidden();
  await workspace.getByRole("button", { name: /Conversations/ }).click();
  await workspace.locator(".ex-conversations-scrim").click({ position: { x: 500, y: 100 } });
  await expect(constrainedConversations).toBeHidden();
  await page.screenshot({ path: testInfo.outputPath("adaptive-shell-993x641.png") });

  await page.setViewportSize({ width: 390, height: 844 });
  workspace = await openWorkspace(page);
  await workspace.getByRole("button", { name: /Conversations/ }).click();
  const mobileMetrics = await workspace.evaluate((root) => {
    const panel = root.querySelector<HTMLElement>(".ex-conversations")!;
    const close = root.querySelector<HTMLElement>(".ex-conversations-close")!;
    const toolbarButtons = Array.from(root.querySelectorAll<HTMLElement>(".ex-workspace-tools button"))
      .filter((button) => button.getBoundingClientRect().height > 0);
    const shellControls = Array.from(root.querySelectorAll<HTMLElement>([
      ".ex-windowbar button",
      ".ex-window-search input",
      ".ex-workspace-tools button",
      ".ex-conversations button",
      ".ex-conversations input",
      ".ex-composer button",
      ".ex-composer textarea",
    ].join(","))).filter((control) => control.getBoundingClientRect().height > 0);
    return {
      panelWidth: Math.round(panel.getBoundingClientRect().width),
      rootWidth: Math.round(root.getBoundingClientRect().width),
      closeHeight: Math.round(close.getBoundingClientRect().height),
      minimumToolbarHeight: Math.min(...toolbarButtons.map((button) => button.getBoundingClientRect().height)),
      minimumShellControlHeight: Math.min(...shellControls.map((control) => control.getBoundingClientRect().height)),
      searchVisible: root.querySelector<HTMLElement>(".ex-window-search")!.getBoundingClientRect().height > 0,
      layoutVisible: root.querySelector<HTMLElement>(".ex-window-layout")!.getBoundingClientRect().height > 0,
      resizeVisible: root.querySelector<HTMLElement>(".ex-conversation-resize")!.getBoundingClientRect().height > 0,
      overflow: root.scrollWidth - root.clientWidth,
      documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    };
  });
  expect(mobileMetrics.panelWidth).toBeLessThanOrEqual(Math.round(mobileMetrics.rootWidth * 0.82) + 1);
  expect(mobileMetrics.closeHeight).toBeGreaterThanOrEqual(44);
  expect(mobileMetrics.minimumToolbarHeight).toBeGreaterThanOrEqual(44);
  expect(mobileMetrics.minimumShellControlHeight).toBeGreaterThanOrEqual(44);
  expect(mobileMetrics.searchVisible).toBe(true);
  expect(mobileMetrics.layoutVisible).toBe(false);
  expect(mobileMetrics.resizeVisible).toBe(false);
  expect(mobileMetrics.overflow).toBe(0);
  expect(mobileMetrics.documentOverflow).toBe(0);
  await page.screenshot({ path: testInfo.outputPath("adaptive-shell-390x844.png") });
});
