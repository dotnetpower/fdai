import { expect, test, type Route } from "@playwright/test";

const withheldIdentity = `Owner/Repo#12:${"a".repeat(240)}`;

test.use({ viewport: { width: 390, height: 844 } });

test.beforeEach(async ({ page }) => {
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
              routes: [
                "/assurance-twin/posture",
                "/assurance-twin/reviews",
                "/assurance-twin/review",
              ],
              availability: "available",
              configured: true,
              reachable: true,
              authoritative: true,
              durable: true,
              synthetic: false,
              reason: null,
              last_observed_at: "2026-09-09T08:00:00Z",
            },
          ],
        },
      });
      return;
    }
    if (path === "/assurance-twin/posture") {
      await route.fulfill({
        json: {
          surface: "assurance-twin-posture",
          available: false,
          complete: false,
          source: "postgresql:state_kv:assurance-twin-posture",
          reports: [],
          gaps: [
            {
              identity: withheldIdentity,
              freshness: "stale",
              reason_code: "evidence_not_fresh",
              reason_codes: ["inventory_freshness_ttl_exceeded"],
            },
          ],
        },
      });
      return;
    }
    if (path === "/assurance-twin/reviews") {
      await route.fulfill({
        json: {
          surface: "assurance-twin-review",
          available: false,
          complete: false,
          source: "postgresql:state_kv:assurance-twin-review",
          reviews: [],
          gaps: [
            {
              identity: withheldIdentity,
              freshness: "unavailable",
              reason_code: "evidence_conflict",
              reason_codes: ["conflicting_redelivery"],
            },
          ],
        },
      });
      return;
    }
    await route.fulfill({ status: 503, json: { detail: "unavailable" } });
  };
  await page.route("**/api/**", handleApi);
  await page.route("**/system/data-sources*", handleApi);
  await page.route("**/assurance-twin/**", handleApi);
});

test("contains withheld Assurance Twin identities inside the mobile viewport", async ({ page }) => {
  await page.goto("/assurance-twin");

  await expect(page.getByText("Withheld posture evidence")).toBeVisible();
  await expect(page.getByText(withheldIdentity).first()).toBeVisible();

  const geometry = await page.evaluate(() => {
    const main = document.querySelector("main");
    const gapLists = [...document.querySelectorAll<HTMLElement>(".assurance-twin-gaps")];
    return {
      document: {
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
      },
      main: main === null
        ? null
        : {
            clientWidth: main.clientWidth,
            scrollWidth: main.scrollWidth,
          },
      gaps: gapLists.map((gap) => ({
        clientWidth: gap.clientWidth,
        scrollWidth: gap.scrollWidth,
      })),
    };
  });

  expect(geometry.document.scrollWidth).toBeLessThanOrEqual(geometry.document.clientWidth);
  expect(geometry.main).not.toBeNull();
  expect(geometry.main!.scrollWidth).toBeLessThanOrEqual(geometry.main!.clientWidth);
  expect(geometry.gaps).toHaveLength(2);
  for (const gap of geometry.gaps) {
    expect(gap.scrollWidth).toBeLessThanOrEqual(gap.clientWidth);
  }
});

test("exposes withheld evidence as named status regions without action controls", async ({ page }) => {
  await page.goto("/assurance-twin");

  const gaps = page.locator("main .assurance-twin-gaps");
  await expect(gaps).toHaveCount(2);
  for (const [index, gap] of (await gaps.all()).entries()) {
    await expect(gap).toHaveAttribute("role", "status");
    await expect(gap).toContainText(
      index === 0 ? "Withheld posture evidence" : "Withheld change-review evidence"
    );
    await expect(gap).toContainText(withheldIdentity);
  }
  await expect(gaps.locator("button")).toHaveCount(0);
});
