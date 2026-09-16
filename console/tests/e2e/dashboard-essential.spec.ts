import { expect, test, type Page, type Route } from "@playwright/test";
import { DASHBOARD_SAMPLE_DATA } from "../../src/routes/dashboard.sample";
import type { AutonomyPayload, DashboardKpi } from "../../src/types";

test.describe.configure({ mode: "serial" });

function kpiFixture(overrides: Partial<DashboardKpi> = {}): DashboardKpi {
  return {
    ...DASHBOARD_SAMPLE_DATA.kpi,
    event_count: 280,
    hil_pending: 0,
    by_tier: {},
    by_outcome: {},
    audit_sample: {
      from_seq: 1001,
      through_seq: 1280,
      row_count: 280,
      limit: 500,
    },
    ...overrides,
  };
}

function zeroMeasurement(): AutonomyPayload {
  const autonomy = DASHBOARD_SAMPLE_DATA.autonomy!;
  return {
    ...autonomy,
    synthetic: false,
    sample_size: 1,
    source: { name: "example-measurements", kind: "measurement", as_of: "2026-09-01T09:00:00Z" },
    success: { ...autonomy.success, auto_resolution_rate: { value: 0, baseline: 0, direction: "higher" } },
    finalization: { finalized_events: 1, pending_events: 0, adverse_events: 1 },
    attribution: { attributed_events: 1, unattributed_events: 0, coverage: 1 },
    verticals: [{ key: "resilience", events: 1, auto_resolved: 0, open_risks: 1, monthly_savings: 0 }],
  };
}

async function mockApi(page: Page, kpiStatus = 200, zero = false, options: {
  readonly kpi?: Partial<DashboardKpi>;
  readonly autonomy?: AutonomyPayload;
} = {}) {
  const writes: string[] = [];
  const handle = async (route: Route) => {
    const request = route.request();
    if (request.method() !== "GET") writes.push(request.method());
    const path = new URL(request.url()).pathname.replace(/^\/api/, "");
    if (path === "/kpi") {
      return route.fulfill({
        status: kpiStatus,
        json: kpiStatus === 200 ? kpiFixture(options.kpi) : { detail: "Dashboard fixture unavailable" },
      });
    }
    if (path === "/kpi/autonomy" && (zero || options.autonomy)) {
      return route.fulfill({
        json: { schema_version: "1.0.0", ...(options.autonomy ?? zeroMeasurement()) },
      });
    }
    return route.fulfill({ status: 404, json: { detail: "Not configured in dashboard fixture" } });
  };
  for (const pattern of ["**/api/**", "**/kpi", "**/kpi/**", "**/system/data-sources", "**/cost-governance/**"]) {
    await page.route(pattern, handle);
  }
  return writes;
}

async function geometry(page: Page) {
  await expect(page.locator(".deck-invoke")).toBeVisible();
  return page.evaluate(() => {
    const main = document.querySelector("main")!;
    const overview = document.querySelector(".overview-essential")!;
    const sections = [...document.querySelectorAll(".overview-report > .overview-section")].map((section) => {
      const box = section.getBoundingClientRect();
      return { className: section.className, x: box.x, y: box.y, width: box.width, bottom: box.bottom };
    });
    return {
      document: [document.documentElement.clientWidth, document.documentElement.scrollWidth],
      main: [main.clientWidth, main.scrollWidth],
      overview: [overview.clientWidth, overview.scrollWidth],
      sections,
      disclosure: document.querySelector(".overview-details > summary")!.getBoundingClientRect().bottom,
      launcher: document.querySelector(".deck-invoke")!.getBoundingClientRect().top,
    };
  });
}

function expectNoOverflow(result: Awaited<ReturnType<typeof geometry>>) {
  for (const [client, scroll] of [result.document, result.main, result.overview]) {
    expect(scroll).toBeLessThanOrEqual(client! + 1);
  }
}

for (const locale of ["en", "ko"]) {
  test(`desktop ${locale}: essential hierarchy, charts and keyboard disclosure`, async ({ page }, testInfo) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const writes = await mockApi(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto(`/overview?data=sample&locale=${locale}`);
    await expect(page.locator(".overview-progress-ring strong")).toHaveText("72%");
    const ring = (await page.locator(".overview-ring-value").getAttribute("stroke-dasharray"))!
      .split(" ")
      .map(Number);
    expect(ring[0]).toBeCloseTo((922 / 1280) * 100);
    expect(ring[1]).toBeCloseTo((1 - 922 / 1280) * 100);
    const rotation = await page.locator(".overview-ring-baseline").getAttribute("transform");
    expect(Number(rotation!.match(/rotate\(([\d.]+)/)![1])).toBeCloseTo(0.48 * 360);
    await expect(page.locator(".overview-report > .overview-section")).toHaveCount(4);
    await expect(page.locator(".overview-metric")).toHaveCount(4);
    await expect(page.locator(".overview-section-attention .overview-attention-card")).toHaveCount(3);
    await expect(page.locator(".overview-details")).not.toHaveAttribute("open");
    await expect(page.locator(".overview-posture-facts a").last()).toHaveAttribute("href", "/audit?from_seq=1001&through_seq=2280");
    await expect(page.locator(".overview-posture-facts a").last()).toContainText(/1,?280/);
    await expect(page.locator(".overview-section-routing a[href*='outcome=']")).toHaveCount(8);
    const desktop = await geometry(page);
    expectNoOverflow(desktop);
    expect(desktop.sections[1]!.y).toBe(desktop.sections[2]!.y);
    // Reading space takes priority over forcing secondary evidence into one viewport.
    expect(desktop.sections[0]!.bottom).toBeLessThan(desktop.launcher);
    expect(desktop.sections[1]!.bottom).toBeLessThan(desktop.launcher);
    await expect(page.locator(".overview-section-attention small")).toHaveCount(0);
    await expect(page.locator(".overview-section-attention .overview-attention-value").first())
      .toHaveText(locale === "ko" ? "대기 3건" : "Pending: 3");
    const rhythm = await page.locator(".overview-section-attention .overview-attention-card").first()
      .evaluate((element) => {
        const style = getComputedStyle(element);
        return { padding: style.paddingTop, gap: style.gap };
      });
    expect(rhythm).toEqual({ padding: "16px", gap: "8px" });
    await testInfo.attach(`desktop-${locale}.json`, { body: JSON.stringify(desktop), contentType: "application/json" });
    await page.screenshot({ path: testInfo.outputPath(`desktop-${locale}.png`) });

    const summary = page.locator(".overview-details > summary");
    await summary.focus();
    const focusedSummary = await summary.boundingBox();
    const launcher = await page.locator(".deck-invoke").boundingBox();
    expect(focusedSummary!.y + focusedSummary!.height).toBeLessThanOrEqual(launcher!.y);
    await page.keyboard.press("Enter");
    await expect(page.locator(".overview-details")).toHaveAttribute("open", "");
    await expect(page.locator(".overview-status-meta")).toBeVisible();
    await expect(page.locator(".overview-verticals")).toBeVisible();
    await expect(page.locator(".overview-details .overview-attention-card")).toHaveCount(3);
    expectNoOverflow(await geometry(page));
    await page.keyboard.press("Enter");
    await expect(page.locator(".overview-details")).not.toHaveAttribute("open");
    await expect(summary).toBeFocused();
    expect(await summary.evaluate((element) => getComputedStyle(element).outlineStyle)).toBe("solid");
    await page.locator(".overview-metric").first().focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/operating-outcomes\/human-touchpoints/);
    expect(writes).toEqual([]);
    expect(errors).toEqual([]);
  });
}

test("live fixture: unavailable, measured zero, loading and error stay distinct", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockApi(page);
  await page.goto("/overview?locale=en");
  await expect(page.locator(".overview-posture.is-summary .overview-evidence-state")).toHaveText("Evidence unavailable");
  await expect(page.locator(".overview-metrics.is-summary .overview-evidence-row")).toHaveCount(4);
  await expect(page.locator(".overview-progress-ring")).toHaveCount(0);
  await expect(page.locator(".overview-section-routing .overview-evidence-row")).toHaveCount(2);
  await expect(page.locator(".overview-section-attention")).toContainText("Pending: 0");
  expect(await page.locator(".overview-metrics.is-summary .overview-evidence-state").first()
    .evaluate((element) => getComputedStyle(element).fontWeight)).toBe("400");
  expect((await page.locator(".overview-routing-grid").boundingBox())!.height).toBeLessThanOrEqual(144);
  expect((await page.locator(".overview-posture").boundingBox())!.height).toBeLessThanOrEqual(220);
  await expect(page.locator(".overview-primary-metric")).toHaveCount(0);

  await page.unrouteAll();
  await mockApi(page, 200, true);
  await page.reload();
  await expect(page.locator(".overview-progress-ring strong")).toHaveText("0%");
  await expect(page.locator(".overview-ring-value")).toHaveAttribute("stroke-dasharray", "0 100");
  await expect(page.locator(".overview-ring-baseline")).toHaveAttribute("transform", "rotate(0 50 50)");

  await page.unrouteAll();
  await mockApi(page);
  let release!: () => void;
  let fail = true;
  const paused = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/kpi", async (route) => {
    await paused;
    await route.fulfill({
      status: fail ? 500 : 200,
      json: fail ? { detail: "Dashboard fixture unavailable" } : kpiFixture(),
    });
  });
  await page.reload();
  await expect(page.locator(".overview-skeleton[aria-busy=true]")).toBeVisible();
  await expect(page.locator(".overview-skeleton .is-metrics > span")).toHaveCount(4);
  release();
  await expect(page.locator(".overview-skeleton")).toHaveCount(0);
  await expect(page.locator(".overview-essential")).toContainText("Failed to load overview: HTTP 500");
  await expect(page.locator(".overview-report")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "View diagnostics" })).toHaveAttribute("href", "/settings/diagnostics");
  fail = false;
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.locator(".overview-posture.is-summary")).toBeVisible();
  await expect(page.locator(".overview-essential [role=alert]")).toHaveCount(0);
});

test("sample operating outcomes distinguish fixture values from Live evidence", async ({ page }) => {
  await mockApi(page);
  await page.goto("/operating-outcomes/auto-resolution?data=sample&locale=ko");

  await expect(page.locator(".analytics-evidence")).toContainText("시뮬레이션 근거");
  const boundary = page.getByRole("note", { name: "샘플 성과" });
  await expect(boundary).toContainText("샘플 성과");
  await expect(boundary)
    .toContainText("아래 링크는 Live 근거를 열며 샘플 값을 입증하지 않습니다.");
  await expect(page.getByRole("link", { name: "감사 근거 보기" }))
    .toHaveAttribute("href", "/audit?window=30d");
  const geometry = await page.evaluate(() => ({
    document: [
      document.documentElement.clientWidth,
      document.documentElement.scrollWidth,
    ] as const,
    main: [
      document.querySelector("main")!.clientWidth,
      document.querySelector("main")!.scrollWidth,
    ] as const,
  }));
  for (const [client, scroll] of [geometry.document, geometry.main]) {
    expect(scroll).toBeLessThanOrEqual(client + 1);
  }
});

test("sample operating outcomes render a trend for every metric", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  for (const metric of [
    "auto-resolution",
    "human-touchpoints",
    "mttr",
    "change-lead-time",
    "cost-per-resolved-event",
  ]) {
    await page.goto(`/operating-outcomes/${metric}?data=sample&locale=en`);
    await expect(page.locator(".outcome-analysis-grid .analytics-trend")).toBeVisible();
  }
});

test("partial measurements and explicit empty distributions remain distinct", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockApi(page, 200, false, { kpi: { by_tier: { t0: 8, t1: 2 } } });
  await page.goto("/overview?locale=en");
  await expect(page.locator(".overview-routing-grid .overview-distribution-bar")).toHaveCount(1);
  await expect(page.locator(".overview-routing-grid .overview-evidence-row")).toHaveCount(1);
  await expect(page.locator(".overview-routing-grid.is-summary")).toHaveCount(0);

  await page.unrouteAll();
  const measurement = zeroMeasurement();
  await mockApi(page, 200, false, {
    kpi: { by_tier: { t0: 0 }, by_outcome: { auto_resolved: 0 } },
    autonomy: {
      ...measurement,
      success: {
        auto_resolution_rate: { value: null, baseline: 0.5, direction: "higher" },
        human_touchpoints_per_100: { value: 0, baseline: null, direction: "lower" },
        mttr_seconds: { value: null, baseline: null, direction: "lower" },
        change_lead_time_seconds: { value: null, baseline: null, direction: "lower" },
        cost_per_resolved_event_usd: { value: null, baseline: null, direction: "lower" },
      },
    },
  });
  await page.reload();
  await expect(page.locator(".overview-routing-grid [data-evidence-state=empty]")).toHaveCount(2);
  await expect(page.locator(".overview-routing-grid")).toContainText("0 recorded entries");
  await expect(page.locator(".overview-routing-grid .overview-distribution-bar")).toHaveCount(0);
  await expect(page.locator(".overview-metric")).toHaveCount(4);
  await expect(page.locator(".overview-metric:not(.is-unavailable) .overview-metric-value")).toHaveText("0.0");
  await expect(page.locator(".overview-metric.is-unavailable")).toHaveCount(3);
  await expect(page.locator(".overview-posture .overview-evidence-row")).toContainText("50%");
  expectNoOverflow(await geometry(page));
});

test("optional reads show skeletons before collapsing to unavailable summaries", async ({ page }) => {
  await mockApi(page);
  let release!: () => void;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/kpi/autonomy", async (route) => {
    await pending;
    await route.fulfill({ status: 404, json: { detail: "Measurement source unavailable" } });
  });
  await page.goto("/overview?locale=en");
  await expect(page.locator(".overview-metrics.is-loading [aria-busy=true]")).toHaveCount(4);
  await expect(page.locator(".overview-primary-metric [aria-busy=true]")).toBeVisible();
  await expect(page.locator(".overview-section-attention [aria-busy=true]")).toHaveCount(2);
  await expect(page.locator(".overview-posture-facts")).toContainText("280 events");
  await expect(page.locator(".overview-metrics.is-summary")).toHaveCount(0);
  release();
  await expect(page.locator(".overview-metrics.is-summary")).toBeVisible();
  await expect(page.locator(".overview-posture.is-summary")).toBeVisible();
  await expect(page.locator(".overview-report [aria-busy=true]")).toHaveCount(0);
});

for (const locale of ["en", "ko"]) {
  test(`unavailable summaries reflow and keep links (${locale})`, async ({ page }, testInfo) => {
    await mockApi(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/overview?locale=${locale}`);
    await expect(page.locator(".overview-metrics.is-summary")).toBeVisible();
    expectNoOverflow(await geometry(page));
    await page.screenshot({ path: testInfo.outputPath(`unavailable-desktop-${locale}.png`) });
    for (const width of [993, 390, 320]) {
      await page.setViewportSize({ width, height: 844 });
      expectNoOverflow(await geometry(page));
      const row = page.locator(".overview-metrics .overview-evidence-row").first();
      expect((await row.boundingBox())!.height).toBeGreaterThanOrEqual(44);
      const disclosure = page.locator(".overview-details > summary");
      await disclosure.click();
      expectNoOverflow(await geometry(page));
      await disclosure.click();
    }
    await page.setViewportSize({ width: 993, height: 844 });
    await page.addStyleTag({ content: `
      .overview-essential { --cs-type-compact-size: 26px; --cs-type-body-size: 28px; }
      .overview-essential * { line-height: 1.5 !important; letter-spacing: .12em !important; word-spacing: .16em !important; }
    ` });
    expectNoOverflow(await geometry(page));
    const metric = page.locator(".overview-metrics .overview-evidence-row").first();
    await expect(metric).toHaveAttribute("href", "/operating-outcomes/human-touchpoints");
    await metric.focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/operating-outcomes\/human-touchpoints/);
  });
}

test("responsive: container reflow, expanded evidence and enlarged text", async ({ page }, testInfo) => {
  await mockApi(page);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 993, height: 641 });
  await page.goto("/overview?data=sample&locale=ko");
  await expect(page.locator(".overview-progress-ring")).toBeVisible();
  expectNoOverflow(await geometry(page));
  await page.screenshot({ path: testInfo.outputPath("constrained.png") });
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await page.locator(".page-header").scrollIntoViewIfNeeded();
    expectNoOverflow(await geometry(page));
    await page.screenshot({ path: testInfo.outputPath(`mobile-${width}-top.png`) });
    const summary = page.locator(".overview-details > summary");
    await summary.click();
    await expect(page.locator(".overview-details")).toHaveAttribute("open", "");
    expectNoOverflow(await geometry(page));
    await summary.click();
    const target = await page.locator(".overview-distribution-legend a").first().boundingBox();
    expect(target!.height).toBeGreaterThanOrEqual(44);
    await page.screenshot({ path: testInfo.outputPath(`mobile-${width}.png`) });
  }
  await page.setViewportSize({ width: 993, height: 641 });
  await page.addStyleTag({ content: `
    .overview-essential * { line-height: 1.5 !important; letter-spacing: .12em !important; word-spacing: .16em !important; }
    .overview-essential p { margin-bottom: 2em !important; }
    .overview-essential { --cs-type-body-size: 28px; --cs-type-compact-size: 26px; --cs-type-page-title-size: 48px; --cs-type-section-title-size: 36px; --cs-type-panel-title-size: 30px; --cs-type-label-size: 24px; }
  ` });
  expectNoOverflow(await geometry(page));
  await page.locator(".overview-details > summary").click();
  expectNoOverflow(await geometry(page));
});

test("appearance: text contrast, focus, navigation-open and user preferences", async ({ page }, testInfo) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/overview?data=sample&locale=en");
  await expect(page.locator(".overview-progress-ring")).toBeVisible();
  for (const theme of ["light", "dark"]) {
    await page.evaluate((value) => document.documentElement.setAttribute("data-theme", value), theme);
    const contrast = await page.evaluate(() => {
      function rgba(value: string) { return value.match(/[\d.]+/g)!.map(Number); }
      function luminance(rgb: number[]) {
        const values = rgb.slice(0, 3).map((channel) => {
          const value = channel / 255;
          return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
        });
        return values[0]! * 0.2126 + values[1]! * 0.7152 + values[2]! * 0.0722;
      }
      return [".overview-metric-label", ".overview-section-head p", ".overview-panel-kicker",
        ".overview-attention-state", ".overview-primary-metric small", ".overview-metric-value",
        ".overview-posture-fact strong"].flatMap((selector) =>
        [...document.querySelectorAll(selector)].filter((element) => element.checkVisibility()).map((element) => {
          const ancestors: Element[] = [];
          for (let current: Element | null = element; current; current = current.parentElement) ancestors.unshift(current);
          let background = [255, 255, 255];
          for (const ancestor of ancestors) {
            const channels = rgba(getComputedStyle(ancestor).backgroundColor);
            const alpha = channels[3] ?? 1;
            background = background.map((channel, index) => channels[index]! * alpha + channel * (1 - alpha));
          }
          const a = luminance(rgba(getComputedStyle(element).color));
          const b = luminance(background);
          return { selector, ratio: (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05) };
        }));
    });
    expect(contrast.every((item) => item.ratio >= 4.5), JSON.stringify(contrast)).toBe(true);
    await testInfo.attach(`contrast-${theme}.json`, { body: JSON.stringify(contrast), contentType: "application/json" });
    await page.locator(".overview-primary-metric").focus();
    expect(await page.locator(".overview-primary-metric").evaluate((element) => getComputedStyle(element).outlineStyle)).toBe("solid");
  }
  await page.evaluate(() => document.documentElement.setAttribute("data-theme", "light"));
  await page.locator(".page-header-domain-trigger").click();
  await expect(page.locator(".page-header-domain-trigger")).toHaveAttribute("aria-expanded", "true");
  expectNoOverflow(await geometry(page));
  await page.setViewportSize({ width: 993, height: 641 });
  expectNoOverflow(await geometry(page));
  await page.locator(".activity-bar").getByRole("button", { name: "Overview", exact: true }).click();
  await page.keyboard.press("Tab");
  await page.emulateMedia({ reducedMotion: "reduce", forcedColors: "active" });
  await page.locator(".overview-primary-metric").focus();
  await expect(page.locator(".overview-progress-ring strong")).toHaveText("72%");
  expectNoOverflow(await geometry(page));
  expect(await page.locator(".overview-primary-metric").evaluate((element) => getComputedStyle(element).outlineStyle)).toBe("solid");
});
