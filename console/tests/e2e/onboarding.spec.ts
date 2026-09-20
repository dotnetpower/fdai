import { mkdir, writeFile } from "node:fs/promises";

import { expect, test, type Page, type Route, type TestInfo } from "@playwright/test";

const blockedOnboarding = {
  probe_mode: "configured",
  ready: false,
  blocked: true,
  missing_resources: ["state_store", "event_bus", "executor_identity"],
  missing_role_assignments: [
    ["executor", "event_bus_data_owner", "event_bus"],
    ["executor", "secret_reader", "secret_store"],
  ],
  present_resource_count: 5,
  present_role_count: 0,
  error: null,
};

test("observer proposals remain read-only across desktop and mobile", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "Sequential viewport validation.");
  await installOnboardingFixture(page, async (route) => { await json(route, blockedOnboarding); });
  const target = `cluster-${"example-".repeat(32)}bound`;
  const methods = ["gitops", "existing_host", "managed_host", "run_command"];
  const candidates = methods.flatMap((method) => ["private", "public"].map((egress) => ({
    method, egress, state: "unknown", blockers: [], missing: ["kubernetes_read", "persistent_storage"],
  })));
  let empty = false;
  let release: (() => void) | undefined;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  const requests: string[] = [];
  await page.route("**/observer-deployment-proposals*", async (route) => {
    requests.push(route.request().method());
    await gate;
    await json(route, {
      synthetic: false, execution_authority: false,
      items: empty ? [] : [{ target_ref: target, state: "current", execution_authority: false,
        expires_at: new Date(Date.now() + 60000).toISOString(),
        proposal: { target_ref: target, status: "needs_evidence", execution_authority: false,
          approval_required: true, recommended: null, candidates },
      }],
    });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/settings/environment-and-deployment/observers");
  await expect(page.locator(".observer-proposals [role=status]")).toBeVisible();
  release?.();
  await expect(page.getByRole("tab", { name: "Cluster observers" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("heading", { name: "Cluster observer proposals" })).toBeVisible();
  await expect.poll(() => requests.length).toBe(1);
  await expect(page.locator(".observer-proposal")).toHaveCount(1);
  await page.locator(".observer-proposal summary").focus();
  await page.locator(".observer-proposal summary").press("Enter");
  await expect(page.locator(".observer-proposal dt")).toHaveCount(8);
  for (const viewport of [{ width: 1440, height: 900 }, { width: 993, height: 641 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    expect(await page.locator(".observer-proposals").evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    await capture(page, testInfo, `observer-proposals-${viewport.width}`);
  }
  empty = true;
  await page.getByRole("button", { name: "Refresh evidence" }).click();
  await expect(page.getByText("No observer proposal has been received.")).toBeVisible();
  expect(requests).toEqual(["GET", "GET"]);
  await expect(page.getByRole("button", { name: /approve|install|execute/i })).toHaveCount(0);
  empty = false;
  await page.goto("/settings/environment-and-deployment/observers?locale=ko");
  await expect(page.getByRole("heading", { name: "클러스터 관측 구성 제안" })).toBeVisible();
  await page.locator(".observer-proposal summary").click();
  await capture(page, testInfo, "observer-proposals-ko-mobile");
});

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function installOnboardingFixture(
  page: Page,
  respond: (route: Route, requestNumber: number) => Promise<void>,
): Promise<() => number> {
  let requestCount = 0;
  const handler = async (route: Route): Promise<void> => {
    if (!["fetch", "xhr"].includes(route.request().resourceType())) {
      await route.continue();
      return;
    }
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api(?=\/)/, "");
    if (path === "/system/data-sources") {
      await json(route, {
        surface: "read-data-sources",
        sources: [{
          key: "onboarding-probe",
          source: "browser-test-fixture",
          routes: ["/onboarding", "/observer-deployment-proposals"],
          availability: "available",
          configured: true,
          reachable: true,
          authoritative: true,
          durable: true,
          synthetic: true,
          reason: null,
          last_observed_at: "2026-09-16T03:00:00Z",
        }],
      });
      return;
    }
    if (path === "/onboarding") {
      requestCount += 1;
      await respond(route, requestCount);
      return;
    }
    await json(route, { detail: `unmocked browser-test route: ${url.pathname}` }, 404);
  };
  await page.route("**/api/**", handler);
  await page.route("**/system/data-sources*", handler);
  await page.route("**/onboarding*", handler);
  return () => requestCount;
}

async function layout(page: Page) {
  return page.evaluate(() => {
    const summary = document.querySelector<HTMLElement>(".onboarding-summary");
    const details = document.querySelector<HTMLElement>(".onboarding-details");
    return {
      documentFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      mainFits: document.querySelector("main")!.scrollWidth <= document.querySelector("main")!.clientWidth,
      summaryColumns: summary ? getComputedStyle(summary).gridTemplateColumns.split(" ").length : 0,
      detailColumns: details ? getComputedStyle(details).gridTemplateColumns.split(" ").length : 0,
    };
  });
}

async function textContrast(page: Page) {
  return page.locator(".onboarding-content").evaluate((content) => {
    const channels = (color: string) => color.match(/[\d.]+/g)!.map(Number);
    const luminance = (rgb: number[]) => rgb.slice(0, 3).reduce((sum, channel, index) => {
      const value = channel / 255;
      const linear = value <= 0.04045
        ? value / 12.92
        : ((value + 0.055) / 1.055) ** 2.4;
      return sum + linear * [0.2126, 0.7152, 0.0722][index]!;
    }, 0);
    return [...content.querySelectorAll("p, span, h3, th, td, a")]
      .filter((element) =>
        element.checkVisibility()
        && [...element.childNodes].some((node) =>
          node.nodeType === Node.TEXT_NODE && node.textContent?.trim()))
      .map((element) => {
        const ancestors: Element[] = [];
        for (let parent: Element | null = element; parent; parent = parent.parentElement) {
          ancestors.unshift(parent);
        }
        let background = [255, 255, 255];
        for (const parent of ancestors) {
          const color = channels(getComputedStyle(parent).backgroundColor);
          const alpha = color[3] ?? 1;
          background = background.map((value, index) =>
            color[index]! * alpha + value * (1 - alpha));
        }
        const style = getComputedStyle(element);
        const color = channels(style.color);
        const foreground = color.slice(0, 3).map((value, index) =>
          value * (color[3] ?? 1) + background[index]! * (1 - (color[3] ?? 1)));
        const foregroundLuminance = luminance(foreground);
        const backgroundLuminance = luminance(background);
        const large = Number.parseFloat(style.fontSize) >= 24
          || (
            Number.parseFloat(style.fontSize) >= 18.667
            && Number.parseInt(style.fontWeight) >= 700
          );
        return {
          text: element.textContent?.trim().slice(0, 60),
          ratio: (Math.max(foregroundLuminance, backgroundLuminance) + 0.05)
            / (Math.min(foregroundLuminance, backgroundLuminance) + 0.05),
          minimum: large ? 3 : 4.5,
        };
      });
  });
}

async function capture(page: Page, testInfo: TestInfo, name: string): Promise<void> {
  const screenshot = await page.screenshot({ fullPage: true });
  await testInfo.attach(name, { body: screenshot, contentType: "image/png" });
  const captureRoot = process.env.FDAI_ONBOARDING_VISUAL_CAPTURE_ROOT;
  if (!captureRoot) return;
  await mkdir(captureRoot, { recursive: true });
  await writeFile(`${captureRoot}/${name}.png`, screenshot);
}

test("loads the onboarding workspace with mock-aligned hierarchy and responsive layout", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "Sequential viewport gate runs once.");
  await page.emulateMedia({ reducedMotion: "reduce" });
  let releaseResponse: (() => void) | undefined;
  const responseGate = new Promise<void>((resolve) => {
    releaseResponse = resolve;
  });
  await installOnboardingFixture(page, async (route) => {
    await responseGate;
    await json(route, blockedOnboarding);
  });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/onboarding");
  await expect(page.locator(".onboarding-skeleton")).toBeVisible();
  await expect(page.locator(".onboarding-skeleton-summary > span")).toHaveCount(4);
  await expect(page.locator(".onboarding-skeleton-details > span")).toHaveCount(2);
  const skeletonAnimation = await page.locator(".onboarding-skeleton .skeleton-shimmer")
    .first()
    .evaluate((element) => getComputedStyle(element, "::after").animationName);
  expect(skeletonAnimation).toBe("none");
  await capture(page, testInfo, "onboarding-loading-desktop");
  releaseResponse?.();

  await expect(page.getByRole("heading", { name: "Onboarding readiness" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Onboarding readiness summary" })).toBeVisible();
  await expect(page.getByText("3 resource gap(s)", { exact: true })).toBeVisible();
  await expect(page.getByText("Audit state store")).toBeVisible();
  await expect(page.getByRole("table", {
    name: "Role assignments missing from the latest onboarding readiness observation",
  })).toBeVisible();
  await expect(page.getByRole("link", { name: "Review access requests" }))
    .toHaveAttribute("href", "/settings/iam/requests");
  await expect(page.getByText("Values come from the configured Operator API onboarding probe."))
    .toBeVisible();
  const contrast = await textContrast(page);
  expect(contrast.length).toBeGreaterThan(20);
  expect(contrast.filter((item) => item.ratio < item.minimum)).toEqual([]);
  const routeLinks = page.locator(".onboarding-content a[href]");
  await expect(routeLinks).toHaveCount(6);
  await routeLinks.first().focus();
  for (let index = 0; index < 6; index += 1) {
    await expect(routeLinks.nth(index)).toBeFocused();
    if (index < 5) await page.keyboard.press("Tab");
  }
  const focusedOutline = await routeLinks.nth(5).evaluate((element) => {
    const style = getComputedStyle(element);
    return { style: style.outlineStyle, width: Number.parseFloat(style.outlineWidth) };
  });
  expect(focusedOutline.style).not.toBe("none");
  expect(focusedOutline.width).toBeGreaterThanOrEqual(2);
  expect(await layout(page)).toEqual({
    documentFits: true,
    mainFits: true,
    summaryColumns: 4,
    detailColumns: 2,
  });
  await capture(page, testInfo, "onboarding-desktop");

  await page.setViewportSize({ width: 993, height: 641 });
  expect(await layout(page)).toEqual({
    documentFits: true,
    mainFits: true,
    summaryColumns: 2,
    detailColumns: 1,
  });
  await capture(page, testInfo, "onboarding-constrained");

  await page.setViewportSize({ width: 390, height: 844 });
  expect(await layout(page)).toEqual({
    documentFits: true,
    mainFits: true,
    summaryColumns: 1,
    detailColumns: 1,
  });
  const actionHeight = await page.getByRole("link", { name: "Open provisioning" })
    .evaluate((element) => element.getBoundingClientRect().height);
  expect(actionHeight).toBeGreaterThanOrEqual(44);
  await expect(page.getByText("event_bus_data_owner")).toBeVisible();
  await capture(page, testInfo, "onboarding-mobile");
});

test("recovers from an initial onboarding read failure", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "Behavior is viewport-independent.");
  const requestCount = await installOnboardingFixture(page, async (route, requestNumber) => {
    if (requestNumber === 1) {
      await json(route, { error: { message: "Synthetic onboarding read failure" } }, 500);
      return;
    }
    await json(route, {
      ...blockedOnboarding,
      ready: true,
      blocked: false,
      missing_resources: [],
      missing_role_assignments: [],
      present_resource_count: 8,
      present_role_count: 2,
    });
  });

  await page.goto("/onboarding");
  await expect(page.getByRole("alert")).toContainText("Synthetic onboarding read failure");
  await page.getByRole("button", { name: "Retry loading" }).click();
  await expect(page.getByRole("region", { name: "Onboarding readiness summary" })).toBeVisible();
  await expect(page.getByText("Ready", { exact: true })).toBeVisible();
  expect(requestCount()).toBe(2);
});

test("keeps an unconfigured probe distinct from observed gaps", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "Behavior is viewport-independent.");
  await installOnboardingFixture(page, async (route) => {
    await json(route, {
      ...blockedOnboarding,
      probe_mode: "not-configured",
      ready: false,
      blocked: false,
      present_resource_count: 0,
      present_role_count: 0,
    });
  });

  await page.goto("/onboarding");
  await expect(page.getByText("The Azure onboarding probe is not configured.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Required resources" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Required role assignments" })).toBeVisible();
  await expect(page.getByText("Required", { exact: true })).toHaveCount(2);
  await expect(page.getByText("The repository baseline is shown because no authoritative tenant observation is available."))
    .toBeVisible();
  expect((await layout(page)).documentFits).toBe(true);
});
