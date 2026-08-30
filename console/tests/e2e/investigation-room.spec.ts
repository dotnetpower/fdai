import { expect, test, type Page, type Route } from "@playwright/test";

const digestA = `sha256:${"a".repeat(64)}`;
const digestB = `sha256:${"b".repeat(64)}`;

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
    if (path === "/views/process") {
      await json(route, {
        source: "postgresql:process_runtime",
        synthetic: false,
        durable: true,
        items: [{
          id: "adaptive-1",
          workflow_ref: "adaptive-investigation",
          workflow_version: "1.0.0",
          status: "succeeded",
          current_step: "",
          target_resource_id: "resource-1",
          updated_at: "2026-08-30T03:00:03Z",
          has_view: false,
        }],
      });
      return;
    }
    if (path === "/views/process/adaptive-1/events") {
      await json(route, {
        process: {
          id: "adaptive-1",
          workflow_ref: "adaptive-investigation",
          workflow_version: "1.0.0",
          status: "succeeded",
          current_step: "",
          target_resource_id: "resource-1",
          updated_at: "2026-08-30T03:00:03Z",
          has_view: false,
          started_at: "2026-08-30T03:00:00Z",
          correlation_id: "correlation-1",
          revision: 2,
        },
        events: [],
        count: 0,
        planning: null,
        investigation: {
          read_only: true,
          mutation_controls: false,
          process_revision: 2,
          process_id: "adaptive-1",
          workflow_version: "1.0.0",
          incident_id: "incident-1",
          initial_frame_digest: digestA,
          initial_active_set_receipt_digest: digestB,
          active_strategy_digest: digestA,
          challenger_strategy_digest: digestB,
          budget: {
            max_rounds: 4,
            max_queries: 4,
            max_cost_units: 100,
            deadline_at: "2026-08-30T03:05:00Z",
            policy_digest: digestB,
          },
          rounds: [{
            round_index: 1,
            iteration_digest: digestA,
            frame_digest: digestB,
            evidence_cutoff: "2026-08-30T03:00:01Z",
            graph_revision: "graph-1",
            active_hypothesis_ids: [
              "hypothesis-database-saturation-with-a-very-long-identifier",
              "hypothesis-network-path-degradation",
              "hypothesis-capacity-limit",
            ],
            active_set_receipt_digest: digestA,
            selection_digest: digestB,
            selected_candidate_id: "observation-candidate-resource-health",
            separated_pair_count: 3,
            total_pair_count: 3,
            hold_reason: null,
            shadow_comparison_digest: digestA,
            execution: null,
            revision: null,
          }],
          round_count: 1,
          terminal: {
            result_digest: digestA,
            disposition: "converged",
            terminal_frame_digest: digestB,
            terminal_active_set_receipt_digest: digestA,
            used_queries: 1,
            used_cost_units: 10,
          },
          closure: null,
        },
      });
      return;
    }
    await json(route, { detail: `unmocked browser-test route: ${path}` }, 404);
  };
  await page.route("**/api/**", handle);
  await page.route("**/views/process**", handle);
}

async function assertRoom(page: Page): Promise<void> {
  await installFixture(page);
  await page.goto("/processes");

  const room = page.getByRole("region", { name: "Investigation Room" });
  await expect(room).toBeVisible();
  await expect(room).toContainText("3 active hypotheses");
  await expect(room).toContainText("Separated hypothesis pairs: 3 of 3");
  await expect(room.getByRole("button")).toHaveCount(0);

  for (const selector of ["html", ".process-view-stage", ".investigation-room"]) {
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

test("renders the desktop Investigation Room without overflow", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await assertRoom(page);
});

test("keeps the constrained desktop Investigation Room bounded", async ({ page }) => {
  await page.setViewportSize({ width: 993, height: 641 });
  await assertRoom(page);
});

test("keeps the mobile Investigation Room bounded", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await assertRoom(page);
});
