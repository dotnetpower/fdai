import { expect, test } from "@playwright/test";

test("repeating the same scheduler lookup reads fresh first-page evidence", async ({ page }) => {
  let reads = 0;
  await page.route(/\/(?:api\/)?scheduler-runs(?:\?|$)/, async (route) => {
    if (route.request().resourceType() === "document") {
      await route.continue();
      return;
    }
    expect(route.request().method()).toBe("GET");
    const params = new URL(route.request().url()).searchParams;
    expect(params.get("task_id")).toBe("example-task");
    expect(params.get("status")).toBe("published");
    expect(params.has("cursor")).toBe(false);
    reads += 1;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        task_id: "example-task",
        source: "isolated-test-fixture",
        durable: false,
        items: [{
          run_id: `example-run-${reads}`,
          task_id: "example-task",
          scheduled_for: "2026-09-17T00:00:00Z",
          claimed_at: "2026-09-17T00:00:01Z",
          status: "published",
          attempt: 1,
          completed_at: "2026-09-17T00:00:02Z",
          error_kind: null,
        }],
        next_cursor: null,
      }),
    });
  });
  await page.goto("/scheduler-runs?task_id=example-task&status=published");
  await expect(page.locator(".scheduler-runs-route tbody")).toContainText("example-run-1");
  const url = page.url();
  await page.getByRole("button", { name: "Load history", exact: true }).click();
  await expect(page.locator(".scheduler-runs-route tbody")).toContainText("example-run-2");
  await expect(page.locator(".scheduler-runs-route tbody")).not.toContainText("example-run-1");
  expect(page.url()).toBe(url);
  expect(reads).toBe(2);
});
