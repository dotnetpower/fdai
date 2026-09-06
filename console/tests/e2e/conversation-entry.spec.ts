import { expect, test, type Page } from "@playwright/test";

test.describe.configure({ mode: "serial" });

interface ChatRequest {
  readonly session_id: string;
  readonly prompt: string;
  readonly view_context: Record<string, unknown>;
  readonly history: readonly { readonly content: string }[];
}

async function openConsole(page: Page, locale = "en") {
  const requests: ChatRequest[] = [];
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/chat/stream")) {
      requests.push(route.request().postDataJSON());
      await route.fulfill({
        contentType: "text/event-stream",
        body: `event: done\ndata: ${JSON.stringify({
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
  await page.getByRole("button", { name: "Explain a concept", exact: true }).click();
  await expect(input).toHaveValue(/SLI/);
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
