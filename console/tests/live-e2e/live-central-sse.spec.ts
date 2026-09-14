import { expect, test } from "@playwright/test";

test("renders authoritative Live activity through one SSE transport", async ({
  page,
}) => {
  const requests = {
    live: 0,
    agents: 0,
    activity: 0,
  };
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname === "/live/stream") requests.live += 1;
    if (url.pathname === "/agents/stream") requests.agents += 1;
    if (url.pathname === "/agents/activity") requests.activity += 1;
  });

  await page.goto("/live?locale=ko");
  await expect(page.locator(".live-coverage-card")).toHaveCount(5);
  await expect(
    page.locator(".live-coverage-card").filter({ hasText: "카탈로그 규칙" }),
  ).toContainText("8,537");
  await expect(
    page.locator(".live-coverage-card").filter({ hasText: "최근 analyzer 대상" }),
  ).toContainText("22");
  await expect(
    page.locator(".live-coverage-card").filter({ hasText: "최근 analyzer 대상" }),
  ).toContainText(/35.*22.*13/);
  await expect(
    page.locator(".live-coverage-card").filter({ hasText: "최근 analyzer 발견" }),
  ).toContainText("0");
  await expect(
    page.locator(".live-coverage-card").filter({ hasText: "규칙 평가" }),
  ).toContainText("평가되지 않음");

  const cards = page.locator(".live-observation-item");
  await expect(cards.first()).toBeVisible();
  const grid = page.locator(".live-observation-grid").last();
  const scroll = await grid.evaluate((node) => ({
    clientHeight: node.clientHeight,
    scrollHeight: node.scrollHeight,
    overflowY: getComputedStyle(node).overflowY,
  }));
  expect(scroll.overflowY).toBe("auto");
  expect(scroll.scrollHeight).toBeGreaterThanOrEqual(scroll.clientHeight);

  await cards.first().click();
  const drawer = page.locator("#live-observation-detail-panel");
  await expect(drawer).toBeVisible();
  await expect(drawer).toHaveAttribute("role", "dialog");
  await expect(drawer).toContainText("관찰 목적");
  await expect(drawer).toContainText("최신성");
  await expect(drawer).toContainText("소요 시간");
  const geometry = await drawer.evaluate((node) => {
    const rect = node.getBoundingClientRect();
    return {
      width: Math.round(rect.width),
      right: Math.round(innerWidth - rect.right),
    };
  });
  expect(geometry.width).toBe(420);
  expect(geometry.right).toBe(0);
  await page.getByRole("button", { name: "닫기" }).click();
  await expect(drawer).toBeHidden();

  await expect.poll(() => requests.live).toBe(1);
  expect(requests.agents).toBe(0);
  expect(requests.activity).toBe(0);

  const activityResponse = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/agents/activity" && url.searchParams.get("limit") === "500";
  });
  await page.goto("/agent-activity?locale=ko");
  const response = await activityResponse;
  expect(response.ok()).toBe(true);
  const activity = await response.json() as {
    readonly items: readonly { readonly schema_version: string }[];
  };
  expect(activity.items).toHaveLength(500);
  expect(activity.items.every((item) => item.schema_version === "1.3.0")).toBe(true);
  await expect(page.locator(".aa-log-row")).toHaveCount(500);
  expect(requests.activity).toBe(1);

  await page.goto("/live?locale=ko");
  await expect(page.locator(".live-coverage-card")).toHaveCount(5);
  const screenshotPath = process.env.FDAI_LIVE_SCREENSHOT_PATH;
  if (screenshotPath) {
    await page.screenshot({ path: screenshotPath, fullPage: true });
  }
  const viewport = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(viewport.scrollWidth).toBeLessThanOrEqual(viewport.clientWidth);
});
