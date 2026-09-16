import { expect, test, type Page, type Route, type TestInfo } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";

const stageIds = [
  "database",
  "semantic-defaults",
  "model-deployments",
  "console",
  "initial-inventory",
  ...Array.from({ length: 31 }, (_, index) => `pending-stage-${index + 1}`),
  "system-readiness",
];

const snapshot = {
  schema_version: "fdai.provision-status.v1",
  type: "provision.snapshot",
  run_id: "run.genesis-example",
  sequence: 31,
  attempt: 1,
  state: "applying",
  current_stage: "initial-inventory",
  stages_completed: 4,
  stages_total: stageIds.length,
  checkpoints_completed: 18,
  checkpoints_total: 24,
  last_progress_at: "2026-08-31T02:20:00+00:00",
  reason_code: null,
  ready: false,
  readiness: {
    database: true,
    semantic: true,
    models: true,
    runtime: true,
    inventory: false,
    system: false,
  },
  stages: stageIds.map((id, index) => ({
    id,
    status: index < 4 ? "completed" : id === "initial-inventory" ? "active" : "pending",
  })),
  inventory: {
    resources_observed: 184,
    resources_expected: 260,
    pages_completed: 12,
    pages_expected: 18,
  },
};

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function installProvisioningFixture(
  page: Page,
  options: { readonly sourceAvailable?: boolean } = {},
): Promise<void> {
  const sourceAvailable = options.sourceAvailable ?? true;
  const handle = async (route: Route): Promise<void> => {
    if (route.request().resourceType() === "document") {
      await route.continue();
      return;
    }
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api(?=\/)/, "");
    if (path === "/system/data-sources") {
      await json(route, {
        surface: "read-data-sources",
        sources: [{
          key: "provisioning-stream",
          source: sourceAvailable ? "browser-test-fixture" : "not-configured",
          routes: ["/provision/stream"],
          availability: sourceAvailable ? "available" : "unavailable",
          configured: sourceAvailable,
          reachable: sourceAvailable,
          authoritative: sourceAvailable,
          durable: sourceAvailable ? true : null,
          synthetic: sourceAvailable,
          reason: sourceAvailable ? null : "Provisioning relay is not configured.",
          last_observed_at: sourceAvailable ? snapshot.last_progress_at : null,
        }],
      });
      return;
    }
    if (path === "/provision/stream") {
      if (!sourceAvailable) {
        await json(route, { detail: "unexpected provisioning stream request" }, 503);
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: `data: ${JSON.stringify(snapshot)}\n\n`,
      });
      return;
    }
    await json(route, { detail: `unmocked browser-test route: ${url.pathname}` }, 404);
  };
  await page.route("**/api/**", handle);
  await page.route("**/system/data-sources*", handle);
  await page.route("**/provision/stream*", handle);
}

async function installDelayedSourceFixture(page: Page): Promise<() => void> {
  let releaseSource!: () => void;
  const sourceGate = new Promise<void>((resolve) => {
    releaseSource = resolve;
  });
  const handle = async (route: Route): Promise<void> => {
    if (route.request().resourceType() === "document") {
      await route.continue();
      return;
    }
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api(?=\/)/, "");
    if (path === "/system/data-sources") {
      await sourceGate;
      await json(route, { surface: "read-data-sources", sources: [] });
      return;
    }
    await json(route, { detail: `unmocked browser-test route: ${url.pathname}` }, 404);
  };
  await page.route("**/api/**", handle);
  await page.route("**/system/data-sources*", handle);
  return releaseSource;
}

async function assertNoHorizontalOverflow(page: Page): Promise<void> {
  for (const selector of ["html", "main", ".provision"]) {
    const dimensions = await page.locator(selector).evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
      overflowers: Array.from(element.querySelectorAll("*"))
        .map((candidate) => {
          const bounds = candidate.getBoundingClientRect();
          return {
            className: candidate.className,
            right: Math.round(bounds.right),
            width: Math.round(bounds.width),
          };
        })
        .filter((candidate) => candidate.right > element.getBoundingClientRect().right + 1)
        .slice(0, 5),
    }));
    expect(
      dimensions.scrollWidth,
      `${selector}: ${JSON.stringify(dimensions.overflowers)}`,
    ).toBeLessThanOrEqual(dimensions.clientWidth);
  }
}

async function capture(page: Page, testInfo: TestInfo, name: string): Promise<void> {
  const screenshot = await page.screenshot({ fullPage: true });
  await testInfo.attach(name, {
    body: screenshot,
    contentType: "image/png",
  });
  const captureRoot = process.env.FDAI_PROVISION_VISUAL_CAPTURE_ROOT;
  if (!captureRoot) return;
  await mkdir(captureRoot, { recursive: true });
  await writeFile(`${captureRoot}/${name}.png`, screenshot);
}

test("shows verified setup stages and estimated resource discovery", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "Sequential viewport gate runs once.");
  await installProvisioningFixture(page);

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/provisioning");

  await expect(page.getByRole("heading", { name: "Setup stages" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Subscription setup" })).toBeVisible();
  await expect(page.getByText(`4 of ${stageIds.length} stages completed`)).toBeVisible();
  await expect(page.locator(".provision-stage")).toHaveCount(stageIds.length);
  await expect(page.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "10.8");
  await expect(page.getByText("Subscription setup is verified and ready.")).toHaveCount(0);
  await expect(page.getByText("Provisioning stream interrupted")).toHaveCount(0);
  await assertNoHorizontalOverflow(page);
  await capture(page, testInfo, "provisioning-desktop");

  const stagesTab = page.getByRole("tab", { name: "Stages" });
  await stagesTab.focus();
  await stagesTab.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Readiness" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect.poll(async () =>
    page.getByRole("tab", { name: "Readiness" }).evaluate(
      (element) => getComputedStyle(element).outlineStyle,
    )).not.toBe("none");
  await expect(page.getByRole("heading", { name: "Readiness evidence" })).toBeVisible();
  await capture(page, testInfo, "provisioning-desktop-readiness");

  await page.getByRole("tab", { name: "Resources" }).click();
  await expect(page.getByText("184 observed / 260 estimated")).toBeVisible();
  await expect(page.getByText("Awaiting independent verification")).toBeVisible();
  await capture(page, testInfo, "provisioning-desktop-resources");

  await page.getByRole("tab", { name: "Stages" }).click();
  await page.setViewportSize({ width: 993, height: 641 });
  await assertNoHorizontalOverflow(page);
  await capture(page, testInfo, "provisioning-constrained");

  await page.setViewportSize({ width: 390, height: 844 });
  await assertNoHorizontalOverflow(page);
  await expect(
    page.getByRole("tabpanel", { name: "Stages" }).getByText("initial-inventory"),
  ).toBeVisible();
  const headerBox = await page.locator(".provision > .page-header").boundingBox();
  expect(headerBox).not.toBeNull();
  expect((headerBox?.x ?? 0) + (headerBox?.width ?? 0)).toBeLessThanOrEqual(390);
  const tabHeights = await page.getByRole("tab").evaluateAll((tabs) =>
    tabs.map((tab) => tab.getBoundingClientRect().height));
  expect(tabHeights.every((height) => height >= 44)).toBe(true);
  await capture(page, testInfo, "provisioning-mobile");

  await page.setViewportSize({ width: 320, height: 844 });
  await assertNoHorizontalOverflow(page);

  await page.setViewportSize({ width: 640, height: 844 });
  await page.addStyleTag({
    content: `
      .provision {
        --cs-type-page-title-size: 48px;
        --cs-type-page-subtitle-size: 26px;
        --cs-type-section-title-size: 36px;
        --cs-type-panel-title-size: 30px;
        --cs-type-body-size: 28px;
        --cs-type-compact-size: 26px;
        --cs-type-label-size: 24px;
        --cs-type-caption-size: 22px;
        line-height: 1.5 !important;
      }
      .provision * {
        letter-spacing: .12em !important;
        word-spacing: .16em !important;
      }
      .provision p {
        line-height: 1.5 !important;
        margin-block-end: 2em !important;
      }
    `,
  });
  await assertNoHorizontalOverflow(page);
});

test("keeps unavailable and Sample-to-Live states distinct", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "Sequential viewport gate runs once.");
  await installProvisioningFixture(page, { sourceAvailable: false });

  await page.goto("/provisioning");

  await expect(page.getByRole("heading", { name: "Provisioning evidence is unavailable" }))
    .toBeVisible();
  await expect(page.getByText("No provisioning is in progress", { exact: false })).toHaveCount(0);
  await page.getByText("Technical details").click();
  await expect(page.getByText("Provisioning relay is not configured.")).toBeVisible();
  await capture(page, testInfo, "provisioning-unavailable");

  await page.getByRole("button", { name: "Sample", exact: true }).click();
  await expect(page.getByText("sample-provision-run")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Setup stages" })).toBeVisible();
  await capture(page, testInfo, "provisioning-sample");

  await page.getByRole("button", { name: "Live", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Provisioning evidence is unavailable" }))
    .toBeVisible();
  await expect(page.getByText("sample-provision-run")).toHaveCount(0);
});

test("shows source verification before an unavailable result", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "Sequential viewport gate runs once.");
  const releaseSource = await installDelayedSourceFixture(page);

  await page.goto("/provisioning", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Checking the evidence source" })).toBeVisible();

  releaseSource();
  await expect(page.getByRole("heading", { name: "Provisioning evidence is unavailable" }))
    .toBeVisible();
});

test("keeps Korean provisioning copy within the mobile route", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "Sequential viewport gate runs once.");
  await page.addInitScript(() => {
    localStorage.setItem("fdai:console:locale", "ko");
  });
  await installProvisioningFixture(page, { sourceAvailable: false });
  await page.setViewportSize({ width: 390, height: 844 });

  await page.goto("/provisioning");
  await expect(page.getByRole("heading", { name: "프로비저닝 근거를 사용할 수 없음" }))
    .toBeVisible();

  await page.getByRole("button", { name: "Sample", exact: true }).click();
  await expect(page.getByRole("heading", { name: "구독 구성" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "구성 단계" })).toBeVisible();
  await assertNoHorizontalOverflow(page);
  await capture(page, testInfo, "provisioning-korean-mobile");
});
