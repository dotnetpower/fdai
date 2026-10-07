import { expect, test, type Page, type Route } from "@playwright/test";

const revision = "0123456789abcdef0123456789abcdef01234567";

function review(alias: string, overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    repository_alias: alias,
    revision,
    review_digest: "4".repeat(64),
    recorded_at: "2026-10-07T08:00:00+00:00",
    issue_count: 12,
    by_priority: { P0: 1, P1: 3, P2: 4, P3: 4, P4: 0 },
    by_severity: { critical: 1, high: 3, medium: 4, low: 2, undetermined: 2 },
    by_confidence: { hypothesis: 2, reported: 6, corroborated: 2, verified: 2, proven: 0 },
    known_exploited_count: 0,
    exposure: "exposed",
    coverage_complete: true,
    top_issue_ids: ["FDAI-SEC-0123456789ab"],
    decision: "urgent",
    ...overrides,
  };
}

async function mockApi(page: Page): Promise<void> {
  const handleApi = async (route: Route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api/, "");
    if (path === "/system/data-sources") {
      await route.fulfill({
        json: {
          surface: "read-data-sources",
          sources: [
            {
              key: "operational-state",
              source: "postgresql",
              routes: ["/code-security/reviews"],
              availability: "available",
              configured: true,
              reachable: true,
              authoritative: true,
              durable: true,
              synthetic: false,
              reason: null,
              last_observed_at: "2026-10-07T08:00:00Z",
            },
          ],
        },
      });
      return;
    }
    if (path === "/code-security/reviews") {
      await route.fulfill({
        json: {
          surface: "code-security-reviews",
          available: true,
          complete: false,
          source: "postgresql:state_kv:code-security-review",
          reviews: [
            review("payments-api-with-a-deliberately-long-repository-alias"),
            review("example-service", {
              decision: "coverage_incomplete",
              coverage_complete: false,
              issue_count: 0,
              by_priority: { P0: 0, P1: 0, P2: 0, P3: 0, P4: 0 },
            }),
          ],
          gaps: [{ reason_code: "code_security_review_malformed" }],
        },
      });
      return;
    }
    await route.fulfill({ status: 503, json: { detail: "unavailable" } });
  };
  await page.route("**/api/**", handleApi);
  await page.route("**/system/data-sources*", handleApi);
  await page.route("**/code-security/**", handleApi);
}

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 993, height: 641 },
  { width: 390, height: 844 },
]) {
  test(`renders code-security reviews without overflow at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await mockApi(page);
    await page.goto("/code-security");

    await expect(page.getByRole("heading", { name: "Code security" }).first()).toBeVisible();
    await expect(page.getByText("payments-api-with-a-deliberately-long-repository-alias")).toBeVisible();
    await expect(page.getByText("Coverage incomplete").first()).toBeVisible();
    await expect(page.getByText("Withheld review records")).toBeVisible();
    await expect(page.getByRole("button", { name: /approve|execute|fix/i })).toHaveCount(0);

    const geometry = await page.evaluate(() => {
      const main = document.querySelector("main");
      return {
        documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        mainOverflow: main === null ? null : main.scrollWidth - main.clientWidth,
      };
    });
    expect(geometry.documentOverflow).toBeLessThanOrEqual(0);
    expect(geometry.mainOverflow).not.toBeNull();
    expect(geometry.mainOverflow!).toBeLessThanOrEqual(0);
  });
}
