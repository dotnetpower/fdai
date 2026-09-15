import { expect, test } from "@playwright/test";
import { restoreBrowserEntraSessionStorage } from "./browser-entra-state";

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

  const resourceResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/ontology/instances/states" && response.ok();
  });
  await restoreBrowserEntraSessionStorage(page);
  await page.goto("/live?locale=ko");
  const resourceResponse = await resourceResponsePromise;
  const resourcePayload = await resourceResponse.json() as {
    readonly total_count: number;
  };
  expect(resourcePayload.total_count).toBeGreaterThan(0);
  expect(resourcePayload.total_count).not.toBe(3_205);
  await expect(page.locator(".live-coverage-card")).toHaveCount(5);
  await expect(page.locator(".live-scope-strip")).toContainText("SSE /live/stream");
  await expect(
    page.locator(".live-coverage-card").filter({ hasText: "카탈로그 규칙" }),
  ).toContainText(/8,537.*활성 50개.*수집 8,487개.*리소스 유형 373개/);
  await expect(
    page.locator(".live-coverage-card").filter({ hasText: "ARG 기록 리소스" }),
  ).toContainText(resourcePayload.total_count.toLocaleString(), {
    timeout: 30_000,
  });
  await expect(
    page.locator(".live-coverage-card").filter({ hasText: "최근 analyzer 대상" }),
  ).toContainText(/35.*22.*13.*unverified_state_fact.*소스 완전/);
  await expect(
    page.locator(".live-coverage-card").filter({ hasText: "최근 analyzer 발견" }),
  ).toContainText(/0.*게시 0건.*오류 0건/);
  await expect(
    page.locator(".live-coverage-card").filter({ hasText: "규칙 평가" }),
  ).toContainText("평가되지 않음");

  const cards = page.locator(".live-observation-item");
  await expect(cards.first()).toBeVisible();
  const grid = page.locator(".live-activity-grid");
  const scroll = await grid.evaluate((node) => ({
    clientHeight: node.clientHeight,
    scrollHeight: node.scrollHeight,
    overflowY: getComputedStyle(node).overflowY,
    columns: getComputedStyle(node).gridTemplateColumns.split(" ").length,
  }));
  expect(scroll.overflowY).not.toBe("auto");
  expect(scroll.scrollHeight).toBe(scroll.clientHeight);
  expect(scroll.columns).toBe(4);
  expect(await page.locator(".live-work-card").count()).toBeLessThanOrEqual(15);
  await expect(page.locator(".live-observations")).toHaveCount(0);
  await expect(page.locator(".live-workspace")).toContainText("실시간 활동");
  await expect(page.locator(".live-workspace")).toContainText("소스 읽기");
  await expect(page.locator(".live-health")).not.toContainText("관찰되지 않음");

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
  )).toBe(560);
  await expect(drawer.getByText("관찰 요약", { exact: true })).toBeVisible();
  await expect(drawer.getByText("결과 및 제한 사항", { exact: true })).toBeVisible();
  await expect(drawer.getByText("시각 및 최신성", { exact: true })).toBeVisible();
  await expect(
    drawer.getByText("기술 식별자", { exact: true }),
  ).toBeVisible();
  expect(
    await drawer.locator("details").evaluate(
      (node) => (node as HTMLDetailsElement).open,
    ),
  ).toBe(false);
  await page.getByRole("button", { name: "닫기" }).click();
  await expect(drawer).toBeHidden();

  const firstActivityCard = cards.first();
  await firstActivityCard.focus();
  await page.keyboard.press("Enter");
  await expect(drawer).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(firstActivityCard).toBeFocused();

  const operationsNavigation = page.locator(
    '.activity-bar-button[aria-label="운영"]',
  );
  await operationsNavigation.click();
  await expect(operationsNavigation).toHaveAttribute("aria-expanded", "true");
  expect(await page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  )).toBe(true);
  await operationsNavigation.click();
  await expect(operationsNavigation).toHaveAttribute("aria-expanded", "false");

  await page.emulateMedia({
    forcedColors: "active",
    reducedMotion: "reduce",
  });
  await firstActivityCard.focus();
  const adaptiveStyles = await firstActivityCard.evaluate((node) => {
    const style = getComputedStyle(node);
    return {
      animationName: style.animationName,
      outlineStyle: style.outlineStyle,
      transitionDuration: style.transitionDuration,
    };
  });
  expect(adaptiveStyles.animationName).toBe("none");
  expect(adaptiveStyles.outlineStyle).not.toBe("none");
  expect(adaptiveStyles.transitionDuration).toBe("0s");
  await page.emulateMedia({
    forcedColors: "none",
    reducedMotion: "no-preference",
  });

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

  const refreshedResourceResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/ontology/instances/states" && response.ok();
  });
  await page.goto("/live?locale=ko");
  const refreshedResourcePayload = await (
    await refreshedResourceResponsePromise
  ).json() as { readonly total_count: number };
  await expect(page.locator(".live-coverage-card")).toHaveCount(5);
  await expect(
    page.locator(".live-coverage-card.skeleton-shimmer"),
  ).toHaveCount(0, { timeout: 30_000 });
  await expect(
    page.locator(".live-coverage-card").filter({ hasText: "카탈로그 규칙" }),
  ).toContainText(/8,537.*활성 50개.*수집 8,487개.*리소스 유형 373개/);
  await expect(
    page.locator(".live-coverage-card").filter({ hasText: "ARG 기록 리소스" }),
  ).toContainText(refreshedResourcePayload.total_count.toLocaleString(), {
    timeout: 30_000,
  });
  await expect(
    page.locator(".live-coverage-card").filter({ hasText: "규칙 평가" }),
  ).toContainText("평가되지 않음");
  const firstCardPosition = await page
    .locator(".live-activity-grid .live-work-card")
    .first()
    .evaluate((node) => Math.round(node.getBoundingClientRect().top));
  expect(firstCardPosition).toBeLessThan(760);
  const screenshotPath = process.env.FDAI_LIVE_SCREENSHOT_PATH;
  if (screenshotPath) {
    await page.evaluate(() => {
      if (document.activeElement instanceof HTMLElement) {
        document.activeElement.blur();
      }
    });
    await page.mouse.move(720, 90);
    await page.waitForTimeout(250);
    await page.screenshot({
      path: screenshotPath,
      mask: [page.locator(".account-menu-trigger")],
      maskColor: "#e9edf1",
    });
  }
  const viewport = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(viewport.scrollWidth).toBeLessThanOrEqual(viewport.clientWidth);

  for (const size of [
    { width: 993, height: 641 },
    { width: 720, height: 450 },
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

  const mobileTargets = await page.locator(
    [
      ".live .page-header-domain-trigger",
      ".live .live-control-btn",
      ".live-work-header .live-filter-chip",
      ".live-work-header .segmented-control button",
      ".live-work-footer a",
    ].join(","),
  ).evaluateAll((nodes) =>
    nodes
      .filter((node) => {
        const style = getComputedStyle(node);
        return style.display !== "none" && style.visibility !== "hidden";
      })
      .map((node) => {
        const rect = node.getBoundingClientRect();
        return {
          height: Math.round(rect.height),
          width: Math.round(rect.width),
        };
      })
  );
  expect(mobileTargets.every(
    (target) => target.width >= 44 && target.height >= 44,
  )).toBe(true);

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

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/live?locale=ko&data=sample");
  await expect(page.locator(".live-kpi")).toHaveCount(3);
  await expect(page.locator(".live-coverage-card")).toHaveCount(0);
  await expect(page.locator(".live-work-card")).toHaveCount(15);
  await expect(page.locator(".live-workspace")).toContainText(
    /현재 15건.*제어 루프 12건.*소스 읽기 3건/,
  );
  await expect(page.locator(".live-observation-item")).toHaveCount(3);
  const sampleScreenshotPath = process.env.FDAI_LIVE_SAMPLE_SCREENSHOT_PATH;
  if (sampleScreenshotPath) {
    await page.evaluate(() => {
      if (document.activeElement instanceof HTMLElement) {
        document.activeElement.blur();
      }
    });
    await page.mouse.move(720, 90);
    await page.waitForTimeout(250);
    await page.screenshot({
      path: sampleScreenshotPath,
      mask: [page.locator(".account-menu-trigger")],
      maskColor: "#e9edf1",
    });
  }
});
