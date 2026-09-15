import { expect, test } from "@playwright/test";

test("renders authoritative Live activity through one SSE transport", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1440, height: 900 });
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
    page.locator(".live-coverage-card").filter({ hasText: "ARG 기록 리소스" }),
  ).toContainText("840", { timeout: 30_000 });
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
  await expect(page.locator("body")).toHaveClass(/scroll-locked/);
  await expect(drawer).toHaveAttribute("role", "dialog");
  await expect(drawer).toContainText("관찰 목적");
  await expect(drawer).toContainText("최신성");
  await expect(drawer).toContainText("소요 시간");
  await expect.poll(async () => drawer.evaluate((node) => {
    const rect = node.getBoundingClientRect();
    return Math.round(innerWidth - rect.right);
  })).toBe(0);
  expect(await drawer.evaluate(
    (node) => Math.round(node.getBoundingClientRect().width),
  )).toBe(420);
  await page.getByRole("button", { name: "닫기" }).click();
  await expect(drawer).toBeHidden();

  expect(requests.live).toBe(1);
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
    readonly items: readonly {
      readonly activity_id: string;
      readonly schema_version: string;
    }[];
  };
  expect(activity.items).toHaveLength(500);
  expect(activity.items.every((item) => item.schema_version === "1.3.0")).toBe(true);
  const renderedActivityIds = new Set(
    await page
      .locator(".aa-log-row[data-operational-kind]")
      .evaluateAll((nodes) =>
        nodes.flatMap((node) => {
          const activityId = node.getAttribute("data-activity-id");
          return activityId === null ? [] : [activityId];
        })
      ),
  );
  expect(
    activity.items.every((item) => renderedActivityIds.has(item.activity_id)),
  ).toBe(true);
  expect(renderedActivityIds.size).toBeGreaterThanOrEqual(500);
  expect(renderedActivityIds.size).toBeLessThanOrEqual(600);
  expect(requests.activity).toBe(1);

  await page.goto("/live?locale=ko");
  await expect(page.locator(".live-coverage-card")).toHaveCount(5);
  await expect(
    page.locator(".live-coverage-card.skeleton-shimmer"),
  ).toHaveCount(0, { timeout: 30_000 });
  await expect(
    page.locator(".live-coverage-card").filter({ hasText: "카탈로그 규칙" }),
  ).toContainText("8,537");
  await expect(
    page.locator(".live-coverage-card").filter({ hasText: "ARG 기록 리소스" }),
  ).toContainText("840", { timeout: 30_000 });
  await expect(
    page.locator(".live-coverage-card").filter({ hasText: "규칙 평가" }),
  ).toContainText("평가되지 않음");
  const screenshotPath = process.env.FDAI_LIVE_SCREENSHOT_PATH;
  if (screenshotPath) {
    await page.screenshot({ path: screenshotPath, fullPage: true });
  }
  const viewport = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(viewport.scrollWidth).toBeLessThanOrEqual(viewport.clientWidth);

  for (const size of [
    { width: 993, height: 641 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(size);
    const constrained = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }));
    expect(constrained.scrollWidth).toBeLessThanOrEqual(
      constrained.clientWidth,
    );
  }

  await cards.first().click();
  await expect(drawer).toBeVisible();
  await expect.poll(async () => drawer.evaluate((node) => {
    const rect = node.getBoundingClientRect();
    return Math.round(innerWidth - rect.right);
  })).toBe(0);
  expect(await drawer.evaluate(
    (node) => Math.round(node.getBoundingClientRect().width),
  )).toBe(390);
  await page.getByRole("button", { name: "닫기" }).click();
});
