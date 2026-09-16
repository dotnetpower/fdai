import { expect, test, type Page, type Route } from "@playwright/test";

function baselineProjection(state: "measured" | "unpublished" = "measured") {
  const published = state === "measured";
  return {
    baseline: {
      version: published ? "example-baseline-v3" : "not-published",
      scope: published ? "example-scope" : "none",
      created_at: published ? "2026-09-04T08:00:00Z" : null,
      document_name: published
        ? "example-configuration-baseline"
        : "No published configuration baseline",
      lifecycle: published ? "active-pinned" : "not-published",
      resource_count: published ? 12 : 0,
      topology_count: published ? 18 : 0,
      unknown_count: published ? 2 : 0,
    },
    versions: published
      ? [
        {
          version: "example-baseline-v3",
          status: "active",
          created_at: "2026-09-04T08:00:00Z",
          resource_count: 12,
          topology_count: 18,
          unknown_count: 2,
          comparison: {
            baseline_version: "example-baseline-v3",
            verdict: "passed",
            finding_count: 0,
            counts: { unchanged: 12 },
          },
        },
        {
          version: "example-baseline-v4",
          status: "candidate",
          created_at: "2026-09-06T08:00:00Z",
          resource_count: 12,
          topology_count: 18,
          unknown_count: 2,
          comparison: {
            baseline_version: "example-baseline-v3",
            verdict: "failed",
            finding_count: 1,
            counts: { changed: 1 },
          },
        },
      ]
      : [],
    drift: {
      verdict: published ? "failed" : "not-evaluated",
      observed_at: published ? "2026-09-06T09:15:00Z" : null,
      finding_count: published ? 1 : 0,
      counts: published ? { changed: 1 } : {},
    },
    knowledge: {
      status: published ? "cited" : "not-indexed",
      citation_count: published ? 2 : 0,
      citations: published
        ? ["knowledge:baseline#1", "knowledge:baseline#2"]
        : [],
    },
    safety: {
      mutation_count: 0,
      approval_request_count: 0,
      mitigation_execution_count: 0,
      unsupported_claim_count: 0,
    },
    performance: null,
    review: {
      configured: published,
      state: published ? "paused-failed" : "not-configured",
      completed_runs: published ? 2 : 0,
      required_runs: published ? 3 : 0,
      failed_attempts: published ? 1 : 0,
    },
  };
}

async function json(route: Route, payload: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(payload),
  });
}

async function installBaselineApi(
  page: Page,
  payload: unknown = baselineProjection(),
  waitForBaseline: Promise<void> = Promise.resolve(),
) {
  const requests: string[] = [];
  const handle = async (route: Route) => {
    if (route.request().resourceType() === "document") {
      await route.continue();
      return;
    }
    const path = new URL(route.request().url()).pathname.replace(/^\/api/, "");
    requests.push(`${route.request().method()} ${path}`);
    if (path === "/system/data-sources") {
      await json(route, {
        surface: "read-data-sources",
        sources: [{
          key: "configuration-baseline",
          source: "browser-test-fixture",
          routes: ["/configuration-baselines"],
          availability: "available",
          configured: true,
          reachable: true,
          authoritative: true,
          durable: true,
          synthetic: true,
          reason: null,
          last_observed_at: "2026-09-06T09:15:00Z",
        }],
      });
      return;
    }
    if (path === "/configuration-baselines") {
      await waitForBaseline;
      await json(route, payload);
      return;
    }
    await json(route, { detail: "Not configured in this browser test" }, 404);
  };
  await page.route("**/api/**", handle);
  await page.route("**/system/data-sources", handle);
  await page.route("**/configuration-baselines", handle);
  return requests;
}

async function expectNoPageOverflow(page: Page) {
  expect(await page.locator(".shell-body > main").evaluate((main) => ({
    document: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    main: main.scrollWidth <= main.clientWidth + 1,
  }))).toEqual({ document: true, main: true });
}

async function contrastEvidence(page: Page) {
  return page.locator(".configuration-baselines-route").evaluate((root) => {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 1;
    const context = canvas.getContext("2d", { willReadFrequently: true })!;
    const rgba = (value: string) => {
      context.clearRect(0, 0, 1, 1);
      context.fillStyle = value;
      context.fillRect(0, 0, 1, 1);
      return [...context.getImageData(0, 0, 1, 1).data];
    };
    const luminance = (color: number[]) => color.slice(0, 3)
      .map((value) => {
        const channel = value / 255;
        return channel <= 0.04045
          ? channel / 12.92
          : ((channel + 0.055) / 1.055) ** 2.4;
      })
      .reduce(
        (sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index]!,
        0,
      );
    const backgroundFor = (element: Element) => {
      const ancestors: Element[] = [];
      for (let parent: Element | null = element; parent; parent = parent.parentElement) {
        ancestors.unshift(parent);
      }
      let background = [255, 255, 255];
      for (const ancestor of ancestors) {
        const color = rgba(getComputedStyle(ancestor).backgroundColor);
        const alpha = (color[3] ?? 255) / 255;
        background = background.map((channel, index) =>
          (color[index] ?? 255) * alpha + channel * (1 - alpha)
        );
      }
      return background;
    };
    const ratio = (first: number[], second: number[]) => {
      const firstLuminance = luminance(first);
      const secondLuminance = luminance(second);
      return (Math.max(firstLuminance, secondLuminance) + 0.05)
        / (Math.min(firstLuminance, secondLuminance) + 0.05);
    };
    const text = [...root.querySelectorAll("h2, h3, p, span, dt, dd, th, td, a, button, code")]
      .filter((element) =>
        element.checkVisibility()
        && !element.closest("[aria-hidden=true]")
        && [...element.childNodes].some((node) =>
          node.nodeType === Node.TEXT_NODE && node.textContent?.trim()
        )
      )
      .map((element) => {
        const background = backgroundFor(element);
        const style = getComputedStyle(element);
        const foregroundColor = rgba(style.color);
        const foregroundAlpha = (foregroundColor[3] ?? 255) / 255;
        const foreground = foregroundColor.slice(0, 3).map((channel, index) =>
          channel * foregroundAlpha + background[index]! * (1 - foregroundAlpha)
        );
        const size = Number.parseFloat(style.fontSize);
        const weight = Number.parseInt(style.fontWeight);
        const minimum = size >= 24 || (size >= 18.667 && weight >= 700) ? 3 : 4.5;
        return {
          text: element.textContent?.trim().slice(0, 60),
          ratio: ratio(foreground, background),
          minimum,
        };
      });
    const activeTab = root.querySelector('[role="tab"][aria-selected="true"]')!;
    return {
      text,
      activeTabIndicatorRatio: ratio(
        rgba(getComputedStyle(activeTab).borderBottomColor),
        backgroundFor(activeTab),
      ),
    };
  });
}

test.describe("Configuration baselines", () => {
  test.beforeEach(({}, testInfo) => {
    test.skip(
      testInfo.project.name !== "desktop-chromium",
      "Desktop validation precedes the constrained and mobile checks.",
    );
  });

  for (const knowledgeStatus of ["not-configured", "blocked", "cited"] as const) {
    test(`completed checks preserve ${knowledgeStatus} Knowledge evidence`, async ({ page }) => {
      const projection = {
        ...baselineProjection(),
        versions: [],
        knowledge: { status: knowledgeStatus, citation_count: 0, citations: [] },
        performance: { total_ms: 71.2, observation_ms: 40.1, knowledge_ms: 0.2 },
        review: {
          configured: false,
          state: "not-configured",
          completed_runs: 0,
          required_runs: 0,
          failed_attempts: 0,
        },
      };
      const requests = await installBaselineApi(page, projection);
      for (const locale of ["en", "ko"] as const) {
        await page.setViewportSize({ width: 1440, height: 900 });
        await page.goto(`/configuration-baselines?locale=${locale}`);
        await expect(page.locator(".kpi-card").filter({ hasText: "71.2 ms" })).toBeVisible();
        const citations = page.locator(".kpi-card").filter({
          hasText: locale === "en" ? "Citations" : "인용",
        });
        const label = knowledgeStatus === "cited"
          ? "0"
          : knowledgeStatus === "blocked"
            ? locale === "en" ? "Blocked" : "차단됨"
            : locale === "en" ? "Not configured" : "구성되지 않음";
        await expect(citations).toContainText(label);
        await page.getByRole("tab", {
          name: locale === "en" ? "Drift" : "구성 차이", exact: true,
        }).click();
        const count = page.locator("#knowledge .details-list > div").last();
        await expect(count).toContainText(knowledgeStatus === "cited"
          ? "0" : locale === "en" ? "Not available" : "사용할 수 없음");
        await expectNoPageOverflow(page);
      }
      expect(requests.every((request) => request.startsWith("GET "))).toBe(true);
    });
  }

  test("loads nullable measurements and preserves the reviewed view hierarchy", async ({
    page,
  }, testInfo) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    let releaseBaseline: () => void = () => undefined;
    const baselineGate = new Promise<void>((resolve) => {
      releaseBaseline = resolve;
    });
    const requests = await installBaselineApi(page, baselineProjection(), baselineGate);
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/configuration-baselines");

    await expect(page.locator(".configuration-baselines-panel .loading-skeleton"))
      .toBeVisible();
    releaseBaseline();
    await expect(page.locator(".configuration-baselines-route")).toBeVisible();
    await expect(page.getByRole("tab")).toHaveCount(3);
    await expect(page.getByRole("tab", { name: "Baseline", exact: true }))
      .toHaveAttribute("aria-selected", "true");
    await expect(page.getByRole("heading", { name: "Baseline history", exact: true }))
      .toBeVisible();
    await expect(page.locator(".configuration-baselines-history tbody tr")).toHaveCount(2);
    await expect(page.locator(".kpi-card").filter({ hasText: "Total latency" }))
      .toContainText("Not measured");
    await expectNoPageOverflow(page);
    const lightContrast = await contrastEvidence(page);
    expect(lightContrast.text.length).toBeGreaterThan(30);
    expect(lightContrast.text.filter((item) => item.ratio + 0.01 < item.minimum))
      .toEqual([]);
    expect(lightContrast.activeTabIndicatorRatio).toBeGreaterThanOrEqual(3);
    await page.evaluate(() => document.documentElement.setAttribute("data-theme", "dark"));
    const darkContrast = await contrastEvidence(page);
    expect(darkContrast.text.filter((item) => item.ratio + 0.01 < item.minimum))
      .toEqual([]);
    expect(darkContrast.activeTabIndicatorRatio).toBeGreaterThanOrEqual(3);
    await page.evaluate(() => document.documentElement.setAttribute("data-theme", "light"));
    const contrastSummary = {
      checkedTextNodes: lightContrast.text.length + darkContrast.text.length,
      minimumTextRatio: Math.min(
        ...lightContrast.text.map((item) => item.ratio),
        ...darkContrast.text.map((item) => item.ratio),
      ),
      minimumActiveTabIndicatorRatio: Math.min(
        lightContrast.activeTabIndicatorRatio,
        darkContrast.activeTabIndicatorRatio,
      ),
    };
    console.info("configuration-baselines-contrast", JSON.stringify(contrastSummary));
    await testInfo.attach("configuration-baselines-contrast.json", {
      body: JSON.stringify(contrastSummary),
      contentType: "application/json",
    });
    await testInfo.attach("configuration-baselines-desktop.png", {
      body: await page.screenshot({ fullPage: true }),
      contentType: "image/png",
    });

    await page.getByRole("tab", { name: "Drift", exact: true }).click();
    await expect(page).toHaveURL(/\/configuration-baselines\/drift$/);
    await expect(page.getByRole("heading", { name: "Current drift", exact: true }))
      .toBeVisible();
    await expect(page.getByRole("heading", { name: "Measured performance", exact: true }))
      .toBeVisible();
    await expect(page.getByRole("heading", { name: "Baseline history", exact: true }))
      .toHaveCount(0);
    await page.getByRole("tab", { name: "Drift", exact: true }).press("ArrowRight");
    await expect(page).toHaveURL(/\/configuration-baselines\/review$/);
    const reviewTab = page.getByRole("tab", { name: "Review", exact: true });
    await expect(reviewTab).toBeFocused();
    expect(await reviewTab.evaluate((tab) => {
      const style = getComputedStyle(tab);
      return {
        style: style.outlineStyle,
        width: Number.parseFloat(style.outlineWidth),
      };
    })).toEqual({ style: "solid", width: 2 });
    await expect(page.getByRole("heading", { name: "Safety counters", exact: true }))
      .toBeVisible();

    for (const viewport of [
      { width: 993, height: 641 },
      { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(viewport);
      await expectNoPageOverflow(page);
      await testInfo.attach(`configuration-baselines-${viewport.width}.png`, {
        body: await page.screenshot({ fullPage: true }),
        contentType: "image/png",
      });
    }
    const shortTabs = await page.getByRole("tab").evaluateAll((tabs) =>
      tabs.filter((tab) => tab.getBoundingClientRect().height < 44).map((tab) => tab.textContent),
    );
    expect(shortTabs).toEqual([]);

    await page.goto("/configuration-baselines?locale=ko");
    await expect(page.getByRole("heading", { name: /구성 기준선/ })).toBeVisible();
    await expect(page.getByRole("tab")).toHaveText(["기준선", "구성 차이", "검토"]);
    await expectNoPageOverflow(page);
    await expect(page.locator("html")).toHaveAttribute("lang", "ko");
    await page.getByRole("tab", { name: "구성 차이", exact: true }).click();
    expect(new URL(page.url()).searchParams.get("locale")).toBe("ko");
    await expect(page.getByRole("heading", { name: "현재 구성 차이", exact: true }))
      .toBeVisible();
    await testInfo.attach("configuration-baselines-ko-mobile.png", {
      body: await page.screenshot({ fullPage: true }),
      contentType: "image/png",
    });
    await page.setViewportSize({ width: 993, height: 900 });
    await page.addStyleTag({
      content: `
        .configuration-baselines-route {
          --cs-type-page-title-size: 48px;
          --cs-type-page-subtitle-size: 26px;
          --cs-type-section-title-size: 36px;
          --cs-type-body-size: 28px;
          --cs-type-compact-size: 26px;
          --cs-type-label-size: 24px;
          --cs-type-caption-size: 22px;
        }
        .configuration-baselines-route p {
          letter-spacing: 0.12em;
          line-height: 1.5;
          word-spacing: 0.16em;
        }
      `,
    });
    await expectNoPageOverflow(page);
    await testInfo.attach("configuration-baselines-text-enlargement.png", {
      body: await page.screenshot({ fullPage: true }),
      contentType: "image/png",
    });
    expect(requests).toContain("GET /configuration-baselines");
    expect(requests.every((request) => request.startsWith("GET "))).toBe(true);
    expect(errors).toEqual([]);
  });

  test("renders an unpublished baseline as unavailable evidence instead of measured zero", async ({
    page,
  }) => {
    await installBaselineApi(page, baselineProjection("unpublished"));
    await page.goto("/configuration-baselines");

    await expect(page.locator(".kpi-card").filter({ hasText: "Version" }))
      .toContainText("Not published");
    await expect(page.getByText("No baseline history", { exact: true })).toBeVisible();
    await expect(page.locator("#baseline").getByText("Not available", { exact: true }))
      .toHaveCount(5);
    await expect(page.getByText("0.0 ms", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("alert")).toHaveCount(0);
  });
});
