import { expect, test, type Page, type Route } from "@playwright/test";

const lifecycleAssessment = {
  idempotency_key: "analyzer:cluster/example/pod/orders:pod_replacement:1",
  resource_ref: "cluster/example/pod/orders-with-a-very-long-immutable-identity-segment",
  resource_kind: "kubernetes_pod",
  signal: "pod_replacement",
  occurred_at: "2026-08-31T06:59:50Z",
  recorded_at: "2026-08-31T07:00:00Z",
  current_state: "running",
  detection_latency_seconds: 10,
  evidence_complete: true,
  evidence_state: "complete",
  publication: {
    current: "duplicate_suppressed",
    attempts: ["published", "duplicate_suppressed"],
    duplicate_observed: true,
  },
  recovery_state: "verified",
  evidence_refs: [
    "kubernetes:pod/old/uid/very-long-retained-evidence-reference",
    "kubernetes:pod/new/uid/very-long-current-evidence-reference",
  ],
  cause_claim_supported: false,
  execution_authority: false,
} as const;

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function installFixture(page: Page): Promise<void> {
  const handle = async (route: Route): Promise<void> => {
    if (route.request().resourceType() === "document") {
      await route.continue();
      return;
    }
    const path = new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/, "");
    if (path === "/system/data-sources") {
      await json(route, {
        surface: "read-data-sources",
        sources: [{
          key: "detection-readiness",
          source: "browser-test-fixture",
          routes: ["/detection-readiness"],
          availability: "available",
          configured: true,
          reachable: true,
          authoritative: true,
          durable: true,
          synthetic: true,
          reason: null,
        }],
      });
      return;
    }
    if (path === "/detection-readiness") {
      await json(route, {
        source: "postgresql:state_kv:detection-readiness",
        observed_at: "2026-08-31T07:00:00Z",
        target_count: 0,
        counts: { ready: 0, partial: 0, blocked: 0, stale: 0, unauthorized: 0, unknown: 0 },
        targets: [],
        lifecycle: {
          source: "postgresql:state_kv:analyzer-finding-receipt",
          observed_at: "2026-08-31T07:00:00Z",
          target_count: 3,
          assessment_count: 5,
          evidence_counts: { complete: 2, incomplete: 1, conflicting: 1, missed: 1 },
          targets: [
            {
              resource_ref: lifecycleAssessment.resource_ref,
              current: lifecycleAssessment,
              history: [
                {
                  ...lifecycleAssessment,
                  idempotency_key: "analyzer:orders:container_restart:0",
                  signal: "container_restart",
                  occurred_at: "2026-08-31T06:50:00Z",
                  recorded_at: "2026-08-31T06:50:07Z",
                  current_state: "failed",
                  publication: {
                    current: "published",
                    attempts: ["published"],
                    duplicate_observed: false,
                  },
                  recovery_state: "open",
                },
                {
                  ...lifecycleAssessment,
                  idempotency_key: "analyzer:orders:insufficient_evidence:0",
                  signal: "insufficient_evidence",
                  occurred_at: "2026-08-31T06:45:00Z",
                  recorded_at: "2026-08-31T06:45:05Z",
                  current_state: "unknown",
                  evidence_complete: false,
                  evidence_state: "missed",
                  publication: {
                    current: "published",
                    attempts: ["published"],
                    duplicate_observed: false,
                  },
                  recovery_state: "unknown",
                },
              ],
            },
            {
              resource_ref: "cluster/example/pod/conflicting",
              current: {
                ...lifecycleAssessment,
                idempotency_key: "analyzer:conflicting",
                resource_ref: "cluster/example/pod/conflicting",
                signal: "conflicting_evidence",
                evidence_complete: false,
                evidence_state: "conflicting",
                recovery_state: "unknown",
              },
              history: [],
            },
            {
              resource_ref: "cluster/example/pod/incomplete",
              current: {
                ...lifecycleAssessment,
                idempotency_key: "analyzer:incomplete",
                resource_ref: "cluster/example/pod/incomplete",
                signal: "insufficient_evidence",
                evidence_complete: false,
                evidence_state: "incomplete",
                recovery_state: "unknown",
              },
              history: [],
            },
          ],
        },
      });
      return;
    }
    await json(route, { detail: `unmocked browser-test route: ${path}` }, 404);
  };
  await page.route("**/api/**", handle);
  await page.route("**/system/data-sources", handle);
  await page.route("**/detection-readiness", handle);
}

async function assertLifecycle(page: Page): Promise<void> {
  await installFixture(page);
  await page.goto("/detection-readiness");

  const region = page.getByRole("region", { name: "Pod lifecycle evidence" });
  await expect(region).toBeVisible();
  await expect(region).toContainText("Current observed state");
  await expect(region).toContainText("Evidence conflicting");
  await expect(region).toContainText("Evidence incomplete");
  await expect(region).toContainText("Duplicate suppressed");
  await expect(region).toContainText("no cause claim or execution authority");
  await expect(region.getByRole("button")).toHaveCount(0);

  const history = region.getByText("Earlier failure and recovery history (2)");
  await history.click();
  await expect(region).toContainText("container_restart");
  await expect(region).toContainText("Evidence missed");
  await expect(region).toContainText("Recovery not verified");

  for (const selector of ["html", "main", ".detection-lifecycle"]) {
    const dimensions = await page.locator(selector).evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(
      dimensions.scrollWidth,
      `${selector} overflowed: ${dimensions.scrollWidth} > ${dimensions.clientWidth}`,
    ).toBeLessThanOrEqual(dimensions.clientWidth);
  }
}

test.describe.configure({ mode: "serial" });

test("renders current and lifecycle history at desktop width", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await assertLifecycle(page);
});

test("preserves lifecycle evidence at constrained desktop width", async ({ page }) => {
  await page.setViewportSize({ width: 993, height: 641 });
  await assertLifecycle(page);
});

test("preserves lifecycle evidence and touch targets at mobile width", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await assertLifecycle(page);
  const summary = page.locator(".detection-lifecycle-history > summary").first();
  await expect(summary).toHaveCSS("min-height", "44px");
});
