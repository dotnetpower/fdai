import { expect, test, type Page, type Route } from "@playwright/test";
import { DASHBOARD_SAMPLE_DATA } from "../../src/routes/dashboard.sample";
import type { AutonomyPayload } from "../../src/types";

function unattributedMeasurement(): AutonomyPayload {
  const sample = DASHBOARD_SAMPLE_DATA.autonomy!;
  return {
    ...sample,
    synthetic: false,
    sample_size: 12,
    confidence: null,
    source: {
      name: "example-measurements",
      kind: "measurement",
      as_of: "2026-09-13T02:00:00Z",
    },
    success: {
      auto_resolution_rate: { value: 8 / 12, baseline: null, direction: "higher" },
      human_touchpoints_per_100: { value: null, baseline: null, direction: "lower" },
      mttr_seconds: { value: null, baseline: null, direction: "lower" },
      change_lead_time_seconds: { value: null, baseline: null, direction: "lower" },
      cost_per_resolved_event_usd: { value: null, baseline: null, direction: "lower" },
    },
    finalization: {
      finalized_events: 8,
      pending_events: 4,
      adverse_events: 0,
    },
    attribution: {
      attributed_events: 0,
      unattributed_events: 12,
      coverage: 0,
    },
    verticals: [
      {
        key: "unattributed",
        events: 12,
        auto_resolved: 8,
        open_risks: 4,
        monthly_savings: 0,
      },
    ],
  };
}

function zeroCostMeasurement(): AutonomyPayload {
  const measurement = unattributedMeasurement();
  return {
    ...measurement,
    attribution: {
      attributed_events: 12,
      unattributed_events: 0,
      coverage: 1,
    },
    verticals: [
      {
        key: "resilience",
        events: 12,
        auto_resolved: 8,
        open_risks: 4,
        monthly_savings: 0,
      },
      {
        key: "change_safety",
        events: 0,
        auto_resolved: 0,
        open_risks: 0,
        monthly_savings: 0,
      },
      {
        key: "cost",
        events: 0,
        auto_resolved: 0,
        open_risks: 0,
        monthly_savings: 0,
      },
    ],
  };
}

async function mockApi(
  page: Page,
  autonomy: AutonomyPayload | null = unattributedMeasurement(),
  waitForAutonomy: Promise<void> = Promise.resolve(),
): Promise<void> {
  const auditSample = DASHBOARD_SAMPLE_DATA.kpi.audit_sample;
  if (auditSample === null) {
    throw new Error("Vertical outcomes fixture requires a bounded KPI audit sample.");
  }
  const handle = async (route: Route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api/, "");
    if (path === "/kpi") {
      await route.fulfill({
        json: {
          ...DASHBOARD_SAMPLE_DATA.kpi,
          event_count: auditSample.row_count,
        },
      });
      return;
    }
    if (path === "/kpi/autonomy") {
      await waitForAutonomy;
      await route.fulfill(autonomy === null
        ? { status: 404, json: { detail: "Measurement source unavailable" } }
        : { json: { schema_version: "1.0.0", ...autonomy } });
      return;
    }
    await route.fulfill({
      status: 404,
      json: { detail: `Not configured in vertical outcomes fixture: ${path}` },
    });
  };
  for (const pattern of ["**/api/**", "**/kpi", "**/kpi/**", "**/system/data-sources"]) {
    await page.route(pattern, handle);
  }
}

async function routeGeometry(page: Page) {
  return page.evaluate(() => {
    const main = document.querySelector("main")!;
    const route = document.querySelector(".vertical-outcomes")!;
    return {
      document: {
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
      },
      main: { clientWidth: main.clientWidth, scrollWidth: main.scrollWidth },
      route: { clientWidth: route.clientWidth, scrollWidth: route.scrollWidth },
    };
  });
}

function expectNoOverflow(geometry: Awaited<ReturnType<typeof routeGeometry>>): void {
  for (const { clientWidth, scrollWidth } of Object.values(geometry)) {
    expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1);
  }
}

async function textContrast(page: Page, selectors: readonly string[]) {
  return page.evaluate((targets) => {
    function rgba(value: string): number[] {
      return value.match(/[\d.]+/g)!.map(Number);
    }
    function luminance(rgb: number[]): number {
      const values = rgb.slice(0, 3).map((channel) => {
        const value = channel / 255;
        return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
      });
      return values[0]! * 0.2126 + values[1]! * 0.7152 + values[2]! * 0.0722;
    }
    return targets.flatMap((selector) =>
      [...document.querySelectorAll(selector)]
        .filter((element) => element.checkVisibility())
        .map((element) => {
          const ancestors: Element[] = [];
          for (let current: Element | null = element; current; current = current.parentElement) {
            ancestors.unshift(current);
          }
          let background = [255, 255, 255];
          for (const ancestor of ancestors) {
            const channels = rgba(getComputedStyle(ancestor).backgroundColor);
            const alpha = channels[3] ?? 1;
            background = background.map(
              (channel, index) => channels[index]! * alpha + channel * (1 - alpha),
            );
          }
          const foreground = luminance(rgba(getComputedStyle(element).color));
          const backdrop = luminance(background);
          return (Math.max(foreground, backdrop) + 0.05)
            / (Math.min(foreground, backdrop) + 0.05);
        }),
    );
  }, selectors);
}

test("clears stale Sample outcomes while a Live measurement is loading", async ({ page }) => {
  let releaseAutonomy!: () => void;
  const waitForAutonomy = new Promise<void>((resolve) => {
    releaseAutonomy = resolve;
  });
  await mockApi(page, unattributedMeasurement(), waitForAutonomy);
  await page.goto("/verticals?data=sample&locale=ko");
  await expect(page.locator(".vertical-summary .status-pill")).toHaveText([
    "시뮬레이션",
    "시뮬레이션",
    "시뮬레이션",
  ]);

  await page.getByRole("button", { name: "Live", exact: true }).click();
  await expect(page.locator(".loading-skeleton")).toBeVisible();
  await expect(page.locator(".vertical-summary")).toHaveCount(0);

  releaseAutonomy();
  await expect(page.locator(".loading-skeleton")).toHaveCount(0);
  await expect(page.locator(".vertical-summary .status-pill")).toHaveText([
    "근거 없음",
    "근거 없음",
    "근거 없음",
  ]);
});

test("keeps the vertical structure visible when the measurement projection is unavailable", async ({
  page,
}, testInfo) => {
  await mockApi(page, null);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/verticals?locale=ko");

  await expect(page.locator(".state-evidence-not-connected")).toContainText(
    "자율성 측정이 연결되지 않았습니다",
  );
  await expect(page.locator(".vertical-summary")).toHaveCount(3);
  await expect(page.locator(".vertical-primary-signal > b")).toHaveText([
    "근거 없음",
    "근거 없음",
    "근거 없음",
  ]);
  await expect(page.locator(".vertical-comparison-table tbody tr")).toHaveCount(3);
  await expect(page.locator(".vertical-comparison-table thead th")).toHaveCount(6);
  await page.locator(".vertical-comparison-table tbody a").first().focus();
  await expect(page.locator(".vertical-comparison-table tbody a").first()).toBeFocused();
  await expect(page.locator(".vertical-contract-list a")).toHaveCount(3);
  await page.locator(".vertical-summary-link").first().focus();
  await expect(page.locator(".vertical-summary-link").first()).toBeFocused();
  expect(
    await page.locator(".vertical-summary-link").first()
      .evaluate((element) => getComputedStyle(element).outlineStyle),
  ).not.toBe("none");
  expectNoOverflow(await routeGeometry(page));
  const contrast = await textContrast(page, [
    ".state-evidence-not-connected > span:last-child",
    ".vertical-summary-head > strong",
    ".vertical-primary-signal > b",
    ".vertical-summary-purpose",
    ".vertical-summary dt",
    ".vertical-summary dd",
    ".vertical-summary-link",
  ]);
  expect(contrast.every((ratio) => ratio >= 4.5), JSON.stringify(contrast)).toBe(true);
  await testInfo.attach("unavailable-contrast-ko.json", {
    body: JSON.stringify(contrast),
    contentType: "application/json",
  });
  await page.screenshot({ path: testInfo.outputPath("unavailable-desktop-ko.png") });

  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await expect(page.locator(".vertical-summary")).toHaveCount(3);
    expectNoOverflow(await routeGeometry(page));
    await page.screenshot({ path: testInfo.outputPath(`unavailable-${width}-ko.png`) });
  }
});

test("keeps zero-event savings unavailable in every presentation", async ({ page }) => {
  await mockApi(page, zeroCostMeasurement());
  await page.goto("/verticals?locale=en");

  const costCard = page.locator(".vertical-summary").filter({ hasText: "Cost Governance" });
  await expect(costCard.locator(".vertical-primary-signal > b")).toHaveText("Unavailable");

  const costRow = page.locator(".vertical-comparison-table tbody tr")
    .filter({ hasText: "Cost Governance" });
  await expect(costRow.locator("td").last()).toHaveText("Unavailable");
});

test("keeps all vertical content visible when live measurements are unattributed", async ({
  page,
}, testInfo) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/verticals?locale=ko");

  await expect(page.getByRole("heading", { name: "영역별 성과" })).toBeVisible();
  await expect(page.locator(".state-evidence-not-connected")).toContainText("12");
  await expect(page.locator(".vertical-summary")).toHaveCount(3);
  await expect(page.locator(".vertical-summary .status-pill")).toHaveText([
    "근거 없음",
    "근거 없음",
    "근거 없음",
  ]);
  await expect(page.locator(".vertical-primary-signal > b")).toHaveText([
    "근거 없음",
    "근거 없음",
    "근거 없음",
  ]);

  const comparisonRows = page.locator(".vertical-comparison-table tbody tr");
  await expect(comparisonRows).toHaveCount(3);
  for (let rowIndex = 0; rowIndex < 3; rowIndex += 1) {
    const cells = comparisonRows.nth(rowIndex).locator("th, td");
    await expect(cells).toHaveCount(6);
    await expect(cells.nth(1)).toHaveText("근거 없음");
    await expect(cells.nth(2)).toHaveText("근거 없음");
    await expect(cells.nth(3)).toHaveText("근거 없음");
    await expect(cells.nth(4)).toHaveText("근거 없음");
    await expect(cells.nth(5)).toHaveText("근거 없음");
  }
  await expect(page.locator(".vertical-contract-list a")).toHaveCount(3);
  await expect(page.locator("a[href^='/incidents?'][href*='vertical=resilience']")).toHaveCount(3);
  await expect(page.locator("a[href^='/promotion-gates?']")).toHaveCount(3);
  await expect(page.locator("a[href^='/promotion-gates?'][href*='vertical=']")).toHaveCount(0);
  await expect(page.locator("a[href^='/audit?'][href*='vertical=cost_governance']")).toHaveCount(3);

  const geometry = await routeGeometry(page);
  expectNoOverflow(geometry);
  expect(pageErrors).toEqual([]);
  await testInfo.attach("unattributed-desktop-ko.json", {
    body: JSON.stringify(geometry),
    contentType: "application/json",
  });
  await page.screenshot({ path: testInfo.outputPath("unattributed-desktop-ko.png") });

  await page.goto("/verticals?data=sample&locale=ko");
  await expect(page.locator(".vertical-summary")).toHaveCount(3);
  await expect(page.locator(".vertical-summary .status-pill")).toHaveText([
    "시뮬레이션",
    "시뮬레이션",
    "시뮬레이션",
  ]);
  await expect(page.locator(".state-evidence-not-connected")).toHaveCount(0);
  await expect(page.locator(".vertical-outcomes a[href*='vertical=']")).toHaveCount(0);
});
