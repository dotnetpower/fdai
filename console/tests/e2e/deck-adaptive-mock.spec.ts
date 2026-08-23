import { fileURLToPath, pathToFileURL } from "node:url";

import { expect, test, type Page } from "@playwright/test";

const mockUrl = pathToFileURL(fileURLToPath(
  new URL("../../../mocks/ui/deck-sources-v2.html", import.meta.url),
)).href;

async function openWorkspace(page: Page) {
  await page.goto(mockUrl);
  await page.getByRole("button", { name: "Workspace shell" }).click();
  return page.getByRole("region", { name: "Adaptive Command deck response mock" });
}

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
  await page.keyboard.press("Control+K");
  await expect(transcriptSearch).toBeFocused();
  await transcriptSearch.fill("validator");
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
