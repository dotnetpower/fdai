import { expect, test, type Page, type Route } from "@playwright/test";

const groundedCorrelation = "inc-01J2-API-LATENCY";

const groundedHypothesis = {
  seq: 1,
  tier: "t1",
  outcome: "grounded",
  grounded: true,
  cause_domain: "infrastructure",
  cause: "A configuration revision exhausted the API connection pool and propagated into request latency.",
  confidence: 0.92,
  reason: "The rollout changed the per-instance connection limit while replica count remained constant. Telemetry and the change record agree on the same propagation path.",
  citations: [
    { kind: "change", ref: "chg-01J2-884" },
    { kind: "telemetry", ref: "metric:db.pool.available" },
    { kind: "incident", ref: "inc-01J1-POOL-EXHAUST" },
    { kind: "rule", ref: "reliability.connection-pool-guard" },
  ],
  remediation_ref: "rbk-01J2-773",
  causal_chain: {
    root_event_id: "evt-change",
    failure_event_id: "evt-latency",
    confidence: 0.92,
    ambiguity: 1,
    hops: [
      {
        cause_event_id: "evt-change",
        effect_event_id: "evt-pool",
        cause_resource_ref: "resource:api-config",
        effect_resource_ref: "resource:api-pool",
        lead_seconds: 11,
        relationship: "configures",
        confidence: 0.97,
      },
      {
        cause_event_id: "evt-pool",
        effect_event_id: "evt-queue",
        cause_resource_ref: "resource:api-pool",
        effect_resource_ref: "resource:api-queue",
        lead_seconds: 42,
        relationship: "causes",
        confidence: 0.94,
      },
      {
        cause_event_id: "evt-queue",
        effect_event_id: "evt-latency",
        cause_resource_ref: "resource:api-queue",
        effect_resource_ref: "resource:api-latency",
        lead_seconds: 43,
        relationship: "propagates",
        confidence: 0.92,
      },
    ],
  },
  mode: "enforce",
  recorded_at: "2026-07-16T09:50:21Z",
};

const groundedView = {
  correlation_id: groundedCorrelation,
  incident_id: "incident-01J2",
  hypotheses: [groundedHypothesis],
  response: {
    verdict: "auto",
    decision: "rollback approved",
    action_kind: "config.rollback",
    mode: "enforce",
    rollback_reference: "rbk-01J2-773",
    recorded_at: "2026-07-16T09:51:03Z",
  },
};

const abstainedView = {
  correlation_id: "inc-abstained",
  incident_id: "incident-abstained",
  hypotheses: [{
    ...groundedHypothesis,
    seq: 2,
    tier: "t2",
    outcome: "abstained",
    grounded: false,
    cause_domain: "unknown",
    cause: null,
    confidence: null,
    reason: "The initiating change has no resolvable citation.",
    citations: [],
    remediation_ref: null,
    causal_chain: null,
    mode: "shadow",
  }],
  response: null,
};

function json(route: Route, payload: unknown, status = 200): Promise<void> {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(payload),
  });
}

async function installRcaFixture(page: Page): Promise<{ readonly releaseLoading: () => void }> {
  let releaseLoading = (): void => undefined;
  const loadingGate = new Promise<void>((resolve) => {
    releaseLoading = resolve;
  });
  await page.route("**/rca?*", async (route) => {
    const correlation = new URL(route.request().url()).searchParams.get("correlation");
    if (correlation === "inc-loading") {
      await loadingGate;
      await json(route, groundedView);
      return;
    }
    if (correlation === "inc-error") {
      await json(route, { error: { message: "synthetic RCA failure" } }, 500);
      return;
    }
    if (correlation === "inc-abstained") {
      await json(route, abstainedView);
      return;
    }
    if (correlation === "inc-empty") {
      await json(route, {
        correlation_id: correlation,
        incident_id: "incident-empty",
        hypotheses: [],
        response: null,
      });
      return;
    }
    await json(route, groundedView);
  });
  return { releaseLoading };
}

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    main: (() => {
      const element = document.querySelector("main");
      return element ? element.scrollWidth - element.clientWidth : -1;
    })(),
  }));
  expect(overflow).toEqual({ document: 0, main: 0 });
}

test("matches the RCA design hierarchy and keeps correlation lookup recoverable", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "desktop-chromium",
    "Desktop presentation gate runs once.",
  );
  await installRcaFixture(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/root-cause-analysis?correlation=${groundedCorrelation}`);

  await expect(page.getByRole("heading", { name: "Root-cause hypotheses" })).toBeVisible();
  await expect(page.locator(".rca-hypothesis-hero")).toContainText(
    "A configuration revision exhausted the API connection pool",
  );
  await expect(page.getByRole("img", {
    name: "Grounded hypothesis confidence 0.92. Confidence does not grant action authority.",
  })).toBeVisible();
  await expect(page.getByRole("region", { name: "Evidence citations" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Response plan" })).toBeVisible();
  await expect(page.locator(".rca-causal-node")).toHaveCount(4);
  await expectNoHorizontalOverflow(page);

  const desktopColumns = await page.locator(".rca-hypothesis-hero").evaluate(
    (element) => getComputedStyle(element).gridTemplateColumns.split(" ").length,
  );
  expect(desktopColumns).toBe(2);

  await page.getByRole("button", { name: "Change correlation" }).click();
  const input = page.getByRole("textbox", { name: "Correlation id" });
  await expect(input).toBeFocused();
  await input.fill("inc-unsubmitted");
  await expect(page.locator(".rca-hypothesis-hero")).toBeVisible();
  await page.getByRole("button", { name: "Cancel change" }).click();
  await expect(input).toBeHidden();
  await expect(page.locator(".rca-lookup-summary")).toContainText(groundedCorrelation);

  await page.screenshot({
    path: testInfo.outputPath("rca-desktop-1440x900.png"),
    fullPage: true,
  });

  await page.evaluate(() => localStorage.setItem("fdai:console:theme", "dark"));
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.locator(".rca-hypothesis-hero")).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

test("reflows the RCA workspace at constrained desktop and mobile widths", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "desktop-chromium",
    "Sequential responsive gate runs once.",
  );
  await installRcaFixture(page);
  await page.setViewportSize({ width: 993, height: 641 });
  await page.goto(`/root-cause-analysis?correlation=${groundedCorrelation}`);
  await expect(page.locator(".rca-hypothesis-hero")).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await page.setViewportSize({ width: 390, height: 844 });
  await expectNoHorizontalOverflow(page);
  const mobileColumns = await page.locator(".rca-hypothesis-hero").evaluate(
    (element) => getComputedStyle(element).gridTemplateColumns.split(" ").length,
  );
  expect(mobileColumns).toBe(1);
  const touchTargets = await page.locator(".rca-related-links a").evaluateAll((elements) =>
    elements.map((element) => element.getBoundingClientRect().height));
  expect(touchTargets.every((height) => height >= 44)).toBe(true);
  const chainOverflow = await page.locator(".rca-causal-panel").evaluate(
    (element) => element.scrollWidth - element.clientWidth,
  );
  expect(chainOverflow).toBe(0);

  await page.evaluate(() => localStorage.setItem("fdai:console:locale", "ko"));
  await page.reload();
  await expect(page.getByRole("heading", { name: "근본 원인 가설" })).toBeVisible();
  await expect(page.getByRole("button", { name: "상관관계 변경" })).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await page.screenshot({
    path: testInfo.outputPath("rca-mobile-390x844-ko.png"),
    fullPage: true,
  });
});

test("keeps abstained, empty, and failed RCA states distinct", async ({ page }, testInfo) => {
  test.skip(
    testInfo.project.name !== "desktop-chromium",
    "State presentation gate runs once.",
  );
  const fixture = await installRcaFixture(page);

  await page.goto("/root-cause-analysis");
  await expect(page.getByText(
    "Enter a correlation id and fetch to see its root-cause analysis.",
  )).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Correlation id" })).toBeVisible();

  await page.goto("/root-cause-analysis?correlation=inc-loading");
  await expect(page.locator(".rca-skeleton")).toBeVisible();
  await expect(page.locator(".rca-skeleton")).toHaveAttribute("aria-busy", "true");
  fixture.releaseLoading();
  await expect(page.getByRole("heading", { name: "Root-cause hypotheses" })).toBeVisible();

  await page.goto("/root-cause-analysis?correlation=inc-abstained");
  await expect(page.getByRole("heading", {
    name: "Insufficient grounding - no root cause presented",
  })).toBeVisible();
  await expect(page.getByText("Hypothesis confidence is unavailable.")).toHaveCount(0);
  await expect(page.locator(".rca-confidence.is-unavailable")).toBeVisible();
  await expect(page.getByText("No citations - insufficient evidence.")).toBeVisible();
  await expect(page.getByText("No linked response action has been recorded")).toBeVisible();

  await page.goto("/root-cause-analysis?correlation=inc-empty");
  await expect(page.getByRole("heading", {
    name: "Root-cause analysis has not started",
  })).toBeVisible();

  await page.goto("/root-cause-analysis?correlation=inc-error");
  await expect(page.getByRole("alert")).toContainText("Failed to load RCA");
});
