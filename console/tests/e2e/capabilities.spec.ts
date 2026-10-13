import { expect, test } from "@playwright/test";

test.describe("Capability catalog workbench", () => {
  test.beforeEach(({}, testInfo) => {
    test.skip(
      testInfo.project.name !== "desktop-chromium",
      "Desktop acceptance precedes responsive validation.",
    );
  });

  test("supports full-row selection, discovery controls, and truthful detail states", async ({
    page,
  }) => {
    const capabilities: Array<Record<string, unknown>> = Array.from(
      { length: 42 },
      (_, index) => ({
      capability_id: `example.capability.${String(index + 1).padStart(2, "0")}`,
      name: `Example capability ${String(index + 1).padStart(2, "0")}`,
      category: index % 2 === 0 ? "detection" : "investigation",
      summary: "Inspect bounded example evidence.",
      side_effect_class: index % 3 === 0 ? "simulate" : "read",
      default_mode: "shadow",
      required_role: index % 2 === 0 ? "reader" : "contributor",
      slide_ref: null,
      tags: ["example"],
      parity: "native",
      official_source: null,
      evidence_refs: [],
      }),
    );
    capabilities[21] = {
      ...capabilities[21]!,
      capability_id: "devops.github",
      name: "Read and write GitHub operations",
      category: "knowledge",
      summary: "Use governed GitHub operations.",
      official_source: "https://learn.microsoft.com/azure/sre-agent/tools",
      evidence_refs: ["services/core-control-plane/src/fdai/delivery/gitops_pr/"],
    };
    await page.route("**/*capabilities*", async (route) => {
      if (
        route.request().resourceType() === "document"
        || !new URL(route.request().url()).pathname.endsWith("/capabilities")
      ) {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          source: "test-capability-catalog",
          execution_eligibility: false,
          count: capabilities.length,
          capabilities,
        }),
      });
    });
    await page.route("**/iam", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          principal: {
            oid: "example-operator",
            roles: ["Contributor"],
            capabilities: ["view-console"],
          },
          roles: [],
          assignment_boundary: "identity-provider-group",
        }),
      });
    });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/capabilities");

    await expect(page.getByRole("heading", { name: /Capability catalog/ })).toBeVisible();
    const rows = page.locator(".data-table tbody tr");
    await expect(rows).toHaveCount(20);

    await rows.first().locator("td").nth(1).click();
    await expect(page.locator("#capability-detail")).toBeVisible();
    await expect(rows.first()).toHaveClass(/row-active/);
    await expect(page).toHaveURL(/capability=/);
    expect(await page.locator(".capabilities-workspace").evaluate((workspace) => {
      const table = workspace.querySelector("#capabilities-table")?.getBoundingClientRect();
      const detail = workspace.querySelector("#capability-detail")?.getBoundingClientRect();
      return table !== undefined && detail !== undefined && detail.x >= table.right;
    })).toBe(true);
    await expect(page.getByText("Declared", { exact: true })).toBeVisible();
    await expect(page.getByText("Not measured", { exact: true })).toHaveCount(2);
    await expect(page.getByText("Not granted by catalog", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Close", exact: true }).click();
    const firstRowAction = rows.first().locator(".data-table-row-action");
    await firstRowAction.focus();
    await firstRowAction.press("Enter");
    await expect(page.locator("#capability-detail")).toBeVisible();

    await page.getByRole("searchbox", { name: "Filter capabilities" }).fill("devops.github");
    await expect(rows).toHaveCount(1);
    await rows.first().locator("td").nth(1).click();
    await expect(page.getByRole("link", { name: "Open GitHub" })).toHaveAttribute("href", "/github");
    await page.locator(".capability-provenance > summary").click();
    await expect(page.getByText("Implementation references", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Reset filters" }).click();
    await expect(rows).toHaveCount(20);
    await page.getByRole("combobox", { name: "Sort by" }).selectOption("role");
    await expect(page).toHaveURL(/sort=role/);
    await page.getByRole("button", { name: "Next", exact: true }).click();
    await expect(page).toHaveURL(/page=2/);
    await expect(page.getByText("Page 2 of 3", { exact: true })).toBeVisible();

    await rows.first().locator("td").nth(1).click();
    await page.setViewportSize({ width: 993, height: 641 });
    expect(await page.locator(".capabilities-workspace").evaluate((workspace) => {
      const table = workspace.querySelector("#capabilities-table")?.getBoundingClientRect();
      const detail = workspace.querySelector("#capability-detail")?.getBoundingClientRect();
      return table !== undefined && detail !== undefined && detail.y >= table.bottom;
    })).toBe(true);

    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    )).toBe(true);
    await expect(page.getByRole("button", { name: "Previous", exact: true }))
      .toHaveCSS("min-height", "44px");
  });
});
