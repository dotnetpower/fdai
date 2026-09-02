import { expect, test } from "@playwright/test";

const manualStudioUrl = "http://127.0.0.1:5474";
const catalog = {
  schemaVersion: 2,
  generatedAt: "2026-09-01T05:00:00Z",
  minimumSlidesByLevel: {
    L100: 5,
    L200: 10,
    L300: 20,
    L400: 30,
  },
  journey: {
    id: "fdai-value-to-scale",
    title: "FDAI Value-to-Scale Journey",
    stages: [
      { id: "understand-align", number: 1, title: "Discovery & Alignment", question: "현재 상태와 핵심 과제, 목표를 명확히 합니다.", differentiator: false },
      { id: "envision-prioritize", number: 2, title: "Vision & Value", question: "미래 가치와 시작 우선순위를 정합니다.", differentiator: false },
      { id: "architect-validate", number: 3, title: "Architecture & Validation", question: "아키텍처와 구현 가능성을 검증합니다.", differentiator: true },
      { id: "activate-realize", number: 4, title: "Activation & Outcomes", question: "측정 가능한 성과를 입증합니다.", differentiator: false },
      { id: "scale-evolve", number: 5, title: "Scale & Evolution", question: "검증된 성과를 전사로 확장합니다.", differentiator: false },
    ],
  },
  manuals: [
    {
      id: "executive-briefing",
      stageId: "understand-align",
      kind: "core",
      level: "L100",
      status: "complete",
      title: "FDAI 운영 개요",
      eyebrow: "PLATFORM OVERVIEW",
      description: "신호에서 검증까지 이어지는 FDAI 운영 모델을 빠르게 살펴봅니다.",
      createdAt: "2026-09-01",
      duration: "8분",
      slideCount: 5,
      coverImage: "assets/executive-briefing.jpeg",
      coverLabel: "CONTROL PLANE",
      featured: true,
    },
    {
      id: "readiness-maturity",
      stageId: "understand-align",
      kind: "deep-dive",
      level: "L200",
      status: "wip",
      title: "AI/Data Readiness & Maturity",
      eyebrow: "READINESS",
      description: "현재 준비 수준을 확인합니다.",
      createdAt: "2026-09-01",
      duration: "12분",
      slideCount: 3,
      coverImage: "assets/readiness-maturity.jpeg",
      coverLabel: "READINESS",
      featured: false,
    },
    {
      id: "art-of-possible",
      stageId: "envision-prioritize",
      kind: "core",
      level: "L100",
      status: "wip",
      title: "Art of the Possible",
      eyebrow: "POSSIBILITIES",
      description: "미래 운영 경험을 탐색합니다.",
      createdAt: "2026-09-01",
      duration: "10분",
      slideCount: 3,
      coverImage: "assets/art-possible.jpeg",
      coverLabel: "POSSIBILITIES",
      featured: false,
    },
  ],
};

test("opens the independent manual library from the Console header", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.context().route(`${manualStudioUrl}/catalog.json`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "Access-Control-Allow-Origin": "*" },
      body: JSON.stringify(catalog),
    });
  });
  await page.context().route(`${manualStudioUrl}/assets/**`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "image/svg+xml",
      headers: { "Access-Control-Allow-Origin": "*" },
      body: "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"1600\" height=\"1600\"><rect width=\"1600\" height=\"1600\" fill=\"#0f6cbd\"/></svg>",
    });
  });
  await page.context().route(`${manualStudioUrl}/library.html**`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/html",
      body: "<!doctype html><html><body><dialog open aria-label=\"FDAI Executive Briefing\">FDAI Executive Briefing</dialog></body></html>",
    });
  });
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 993, height: 641 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto("/tests/fixtures/help-center.html");
    await expect(page.locator("[data-help-center-fixture-ready]")).toBeVisible();

    const trigger = page.getByRole("button", { name: "Open guides" });
    await expect(trigger).toBeVisible();
    await expect(page.locator(".principal > .help-center + .account-menu")).toHaveCount(1);
    await trigger.click();

    const drawer = page.getByRole("dialog", { name: "Guides" });
    await expect(drawer).toBeVisible();
    await expect(drawer.locator(".manual-journey-stages button")).toHaveCount(5);
    await expect(drawer.getByRole("button", { name: "Open FDAI 운영 개요" })).toBeVisible();
    await expect(drawer.locator(".manual-book-copy small").first()).toContainText("L100");
    await expect(drawer.locator(".manual-book-image img").first()).toHaveJSProperty("naturalWidth", 1600);
    const documentWidth = await page.locator("html").evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(documentWidth.scrollWidth).toBeLessThanOrEqual(documentWidth.clientWidth);
    const drawerWidth = await drawer.evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(drawerWidth.scrollWidth).toBeLessThanOrEqual(drawerWidth.clientWidth);

    if (viewport.width === 390) {
      const closeBounds = await drawer.getByRole("button", { name: "Close guides" }).boundingBox();
      expect(closeBounds?.width).toBeGreaterThanOrEqual(44);
      expect(closeBounds?.height).toBeGreaterThanOrEqual(44);
    }
    if (viewport.width === 1440) {
      const track = drawer.locator(".manual-coverflow-track");
      const bounds = await track.boundingBox();
      expect(bounds).not.toBeNull();
      const activeCover = drawer.locator(".manual-library-card[data-active='true']");
      const initialTransform = await activeCover.evaluate((element) =>
        getComputedStyle(element).transform);
      await page.mouse.move(bounds!.x + bounds!.width / 2, bounds!.y + bounds!.height / 2);
      await page.mouse.down();
      await page.mouse.move(bounds!.x + bounds!.width / 2 - 24, bounds!.y + bounds!.height / 2, {
        steps: 3,
      });
      await expect(track).toHaveClass(/dragging/);
      expect(await activeCover.evaluate((element) => getComputedStyle(element).transform))
        .not.toBe(initialTransform);
      await page.mouse.move(bounds!.x + bounds!.width / 2 - 285, bounds!.y + bounds!.height / 2, {
        steps: 12,
      });
      await expect(track).toHaveClass(/dragging/);
      await page.mouse.up();
      await expect(
        drawer.getByRole("button", { name: "Open Art of the Possible" }),
      ).toHaveAttribute("data-active", "true");
    }

    await page.keyboard.press("Escape");
    await expect(drawer).not.toBeVisible();
    await expect(trigger).toBeFocused();
  }

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/tests/fixtures/help-center.html");
  await page.getByRole("button", { name: "Open guides" }).click();
  const popupPromise = page.waitForEvent("popup");
  await page.getByRole("button", { name: "Open FDAI 운영 개요" }).click();
  const manualPage = await popupPromise;
  await manualPage.waitForLoadState("networkidle");
  await expect(manualPage).toHaveURL(/\/library\.html\?manual=executive-briefing$/);
  await expect(manualPage.getByRole("dialog", { name: "FDAI Executive Briefing" })).toBeVisible();
});
