import { expect, test, type Page, type Route } from "@playwright/test";

const correlation = "campaign-20260917-t002758950004-5bd447f7";

function json(route: Route, payload: unknown): Promise<void> {
  return route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(payload),
  });
}

function auditItem(
  seq: number,
  actor: string,
  recordedAt: string,
  correlationId: string | null,
) {
  return {
    seq,
    event_id: `event-${seq}`,
    correlation_id: correlationId,
    actor,
    action_kind: "observation-campaign.source-transition",
    mode: "shadow",
    entry: {
      summary: "Observed one bounded campaign transition.",
      domain: "metrics",
    },
    entry_hash: `hash-${seq}`,
    previous_hash: `hash-${seq - 1}`,
    recorded_at: recordedAt,
  };
}

async function installWaterfallFixture(page: Page): Promise<void> {
  await page.route("**/system/data-sources*", (route) => json(route, {
    surface: "read-data-sources",
    sources: [{
      key: "agent-activity-waterfall-test",
      source: "deterministic browser fixture",
      routes: ["/audit", "/agents/activity", "/agents/stream"],
      availability: "available",
      configured: true,
      reachable: true,
      authoritative: true,
      durable: true,
      synthetic: true,
      reason: null,
      last_observed_at: "2026-09-17T00:28:30Z",
    }],
  }));
  await page.route("**/audit*", (route) => json(route, {
    items: [
      auditItem(3, "Heimdall", "2026-09-17T00:28:29Z", null),
      auditItem(2, "Huginn", "2026-09-17T00:27:59Z", correlation),
      auditItem(1, "Heimdall", "2026-09-17T00:27:58Z", correlation),
    ],
    next_cursor: null,
  }));
  await page.route("**/agents/activity*", (route) => json(route, {
    items: [],
    snapshot_at: "2026-09-17T00:28:30Z",
    source: "durable-operational-projection",
  }));
  await page.route("**/agents/stream*", (route) => route.fulfill({
    status: 200,
    contentType: "text/event-stream",
    body: "",
  }));
}

for (const locale of ["en", "ko"] as const) {
  test(`separates Waterfall identity, disclosure, and Trace navigation in ${locale}`, async ({
    page,
  }, testInfo) => {
    if (testInfo.project.name === "desktop-chromium") {
      await page.setViewportSize(
        locale === "en" ? { width: 1440, height: 900 } : { width: 993, height: 641 },
      );
    }
    await installWaterfallFixture(page);
    const startPath =
      `/agent-activity?view=waterfall&window=1h&layer=pipeline&locale=${locale}`;
    await page.goto(startPath);

    const group = page.locator(".waterfall-group").filter({ hasText: correlation });
    const identity = group.locator(".waterfall-corr");
    const collapseName = locale === "ko"
      ? `${correlation} 상관관계 그룹 접기`
      : `Collapse correlation group ${correlation}`;
    const expandName = locale === "ko"
      ? `${correlation} 상관관계 그룹 펼치기`
      : `Expand correlation group ${correlation}`;
    const traceName = locale === "ko"
      ? `${correlation} 추적 보기`
      : `View trace for ${correlation}`;
    const toggle = group.getByRole("button", { name: collapseName });
    const traceLink = group.getByRole("link", { name: traceName });

    await expect(identity).toHaveText(correlation);
    await expect(identity).toHaveCSS("user-select", "text");
    expect(await identity.evaluate((element) => element.tagName)).toBe("SPAN");
    await identity.click();
    await expect(page).toHaveURL(new RegExp(`${startPath.replace(/[?]/g, "\\?")}$`));

    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await toggle.click();
    await expect(group.getByRole("button", { name: expandName })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    await expect(page).toHaveURL(new RegExp(`${startPath.replace(/[?]/g, "\\?")}$`));

    await group.getByRole("button", { name: expandName }).focus();
    await page.keyboard.press("Tab");
    await expect(traceLink).toBeFocused();

    const geometry = await group.evaluate((element) => {
      const link = element.querySelector<HTMLElement>(".waterfall-trace-link");
      const bounds = element.getBoundingClientRect();
      const linkBounds = link?.getBoundingClientRect();
      const canvas = document.createElement("canvas");
      canvas.width = 1;
      canvas.height = 1;
      const context = canvas.getContext("2d");
      if (link === null || context === null) {
        throw new Error("Expected Trace action presentation is missing");
      }
      const rgb = (color: string): readonly [number, number, number] => {
        context.clearRect(0, 0, 1, 1);
        context.fillStyle = color;
        context.fillRect(0, 0, 1, 1);
        const [red, green, blue] = context.getImageData(0, 0, 1, 1).data;
        return [red!, green!, blue!];
      };
      const luminance = (color: string): number => {
        const channels = rgb(color).map((value) => {
          const channel = value / 255;
          return channel <= 0.04045
            ? channel / 12.92
            : ((channel + 0.055) / 1.055) ** 2.4;
        });
        return 0.2126 * channels[0]! + 0.7152 * channels[1]! + 0.0722 * channels[2]!;
      };
      const foreground = luminance(getComputedStyle(link).color);
      const background = luminance(getComputedStyle(element).backgroundColor);
      return {
        left: bounds.left,
        right: bounds.right,
        linkHeight: linkBounds?.height ?? 0,
        linkContrast:
          (Math.max(foreground, background) + 0.05) /
          (Math.min(foreground, background) + 0.05),
        viewportWidth: innerWidth,
        documentOverflow:
          document.documentElement.scrollWidth - document.documentElement.clientWidth,
      };
    });
    expect(geometry.left).toBeGreaterThanOrEqual(0);
    expect(geometry.right).toBeLessThanOrEqual(geometry.viewportWidth);
    expect(geometry.documentOverflow).toBeLessThanOrEqual(0);
    expect(geometry.linkContrast).toBeGreaterThanOrEqual(4.5);
    expect(geometry.linkHeight).toBeGreaterThanOrEqual(
      testInfo.project.name === "mobile-chromium" ? 44 : 32,
    );

    const uncorrelatedLabel = locale === "ko"
      ? "상관관계 없는 이벤트 #3"
      : "Uncorrelated event #3";
    const uncorrelated = page.locator(".waterfall-group").filter({
      hasText: uncorrelatedLabel,
    });
    await expect(uncorrelated.locator(".waterfall-trace-link")).toHaveCount(0);

    await traceLink.click();
    await expect(page).toHaveURL(`/trace?correlation=${encodeURIComponent(correlation)}`);
    await page.goBack();
    await expect(page).toHaveURL(new RegExp(`${startPath.replace(/[?]/g, "\\?")}$`));
    await expect(page.locator(".waterfall-group").filter({ hasText: correlation })).toBeVisible();
  });
}
