import { expect, test, type FrameLocator } from "@playwright/test";
import iamText from "../../src/routes/i18n/settings-iam.en.json" with { type: "json" };
import { openSurface, routeMocks } from "./settings-mock-page";

const tabNames = ["My access", "Users", "Role definitions", "Access requests"];

async function expectLayout(frame: FrameLocator) {
  expect(await frame.locator(".iam-workspace").evaluate((element) => ({
    document: document.documentElement.scrollWidth <= innerWidth,
    workspace: element.scrollWidth <= element.clientWidth,
    regions: [...element.querySelectorAll(".iam-panel, .iam-table-wrap, .iam-authority, .iam-review-editor, .iam-access-strip")]
      .filter((region) => region.getBoundingClientRect().width > 0)
      .every((region) => region.scrollWidth <= region.clientWidth + 1),
  }))).toEqual({ document: true, workspace: true, regions: true });
}

async function scenario(frame: FrameLocator, value: string) {
  const controls = frame.locator(".iam-preview-controls");
  if (!(await controls.evaluate((element) => element.hasAttribute("open")))) {
    await controls.locator("summary").click();
  }
  await controls.getByRole("combobox", { name: "Scenario" }).selectOption(value);
}

test.describe("Implemented IAM mock parity", () => {
  test.describe.configure({ mode: "serial" });
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "Desktop acceptance precedes responsive validation.");
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await routeMocks(page);
  });

  test("desktop mirrors Owner, directory, canonical roles and request-review boundaries", async ({ page }, testInfo) => {
    const mutations: string[] = [];
    const errors: string[] = [];
    page.on("request", (request) => { if (request.method() !== "GET") mutations.push(request.url()); });
    page.on("pageerror", (error) => errors.push(error.message));
    const frame = await openSurface(page, "settings-iam.html");
    await expect(frame.getByRole("tab")).toHaveText(tabNames, { useInnerText: true });
    await expect(frame.getByText(iamText.fdaiOwnerConfirmed)).toBeVisible();
    await frame.locator(".iam-authority details > summary").click();
    await expect(frame.getByText(iamText.tenantAdminDistinction)).toBeVisible();
    await expect(frame.getByText(iamText.promotionRequired, { exact: true })).toBeVisible();
    await expect(frame.locator("[data-capability-count]")).toHaveText(["12", "12"]);
    await expect(frame.locator("[data-current-capabilities] .iam-capability")).toHaveCount(12);
    await expect(frame.locator(".cp-kpis")).toHaveCount(0);
    await expectLayout(frame);
    await page.screenshot({ path: testInfo.outputPath("iam-my-access-desktop.png") });

    await frame.getByRole("tab", { name: "Users", exact: true }).click();
    await expect(page).toHaveURL(/settings-iam\.html::users$/);
    await expect(frame.getByRole("heading", { name: "People and groups" })).toBeVisible();
    await frame.locator(".iam-workflow-details > summary").click();
    await expect(frame.getByRole("link", { name: iamText.openMappingReviews })).toHaveAttribute("href", "handover.html");
    await expect(frame.locator(".iam-workflow li")).toHaveCount(4);
    await frame.locator(".iam-workflow-details > summary").click();
    await expect(frame.locator("[data-roster] > tr:visible")).toHaveCount(4);
    await expect(frame.locator("[data-roster-total]")).toHaveText("3 people / 1 group");
    await expect(frame.locator("[data-roster-count]")).toHaveText("4 of 4 shown");
    const filters = frame.getByRole("group", { name: "Roster type" });
    await filters.getByRole("button", { name: "Groups", exact: true }).click();
    await expect(frame.locator("[data-roster] > tr:visible")).toHaveCount(1);
    await expect(frame.locator("[data-roster-count]")).toHaveText("1 of 4 shown");
    await expect(frame.getByText("Group managed", { exact: true })).toBeVisible();
    await filters.getByRole("button", { name: "People", exact: true }).click();
    await expect(frame.locator("[data-roster] > tr:visible")).toHaveCount(3);
    await expect(frame.locator("[data-roster-count]")).toHaveText("3 of 4 shown");
    const search = frame.getByRole("searchbox", { name: iamText.findUser });
    await expect(search).toHaveAttribute("minlength", "2");
    await search.fill("no-matching-example");
    await expect(frame.getByText("No matching people or groups", { exact: true })).toBeVisible();
    await search.fill("Analyst");
    await expect(frame.locator("[data-roster] > tr:visible")).toHaveCount(1);
    await frame.getByRole("button", { name: "Request role for Example Analyst", exact: true }).click();
    const editor = frame.getByRole("dialog", { name: "Request a role", exact: true });
    const requestedRole = editor.getByRole("combobox");
    await expect(requestedRole.locator("option")).toHaveText(["Choose a role", "Reader", "Contributor", "Approver", "Owner"]);
    await requestedRole.selectOption("Contributor");
    await expect(editor.getByRole("heading", { name: "Request a role" })).toBeVisible();
    const reason = frame.getByRole("textbox", { name: "Explain the operational need (at least 20 characters)" });
    await reason.fill("Review the example workload evidence during the planned maintenance window.");
    await expect(frame.getByRole("button", { name: "Submit access request" })).toBeDisabled();
    await expect(frame.locator('[data-roster] [data-principal-name="Example Analyst"] [data-observed-role]')).toHaveText("Reader");
    await expectLayout(frame);
    await page.screenshot({ path: testInfo.outputPath("iam-user-request-desktop.png") });
    await frame.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(editor).toBeHidden();
    await expect(frame.getByRole("button", { name: "Request role for Example Analyst", exact: true })).toBeFocused();

    await frame.getByRole("tab", { name: "Role definitions", exact: true }).click();
    await expect(frame.locator("[data-role-definitions] > tr")).toHaveCount(5);
    await expect(frame.locator("[data-role-definitions] > tr > td:first-child")).toHaveText(["Reader", "Contributor", "Approver", "Owner", "BreakGlass"]);
    const emergency = frame.locator('[data-role="BreakGlass"]');
    await expect(emergency).toContainText("Emergency activation only");
    await expect(emergency.locator('[title="approve-runtime-hil"]')).toHaveCount(0);
    await expect(emergency.locator(".iam-capability")).toHaveCount(3);
    await expectLayout(frame);
    await page.screenshot({ path: testInfo.outputPath("iam-roles-desktop.png") });

    await frame.getByRole("tab", { name: "Access requests", exact: true }).click();
    await expect(frame.locator('[data-request-state="assignment-pending"] .iam-request-status')).toContainText("Approved");
    await expect(frame.getByText("Assignment pending", { exact: true })).toBeVisible();
    await expect(frame.locator("[data-assigned-status]")).toHaveText("Assigned");
    await frame.getByRole("button", { name: "Review", exact: true }).click();
    const review = frame.getByRole("textbox", { name: "Review justification" });
    await expect(review).toBeFocused();
    await expect(review).toHaveAttribute("minlength", "20");
    await expect(review).toHaveAttribute("maxlength", "2000");
    await review.fill("The bounded operational need is supported by the example evidence.");
    await expect(frame.getByRole("button", { name: "Approve", exact: true })).toBeDisabled();
    await expect(frame.getByRole("button", { name: "Reject", exact: true })).toBeDisabled();
    await expectLayout(frame);
    await page.screenshot({ path: testInfo.outputPath("iam-review-desktop.png") });
    await frame.getByRole("button", { name: "Cancel", exact: true }).click();
    await frame.getByRole("tab", { name: "Access requests", exact: true }).focus();
    await page.keyboard.press("Home");
    await expect(frame.getByRole("tab", { name: "My access", exact: true })).toBeFocused();
    expect(mutations).toEqual([]);
    expect(errors).toEqual([]);
  });

  test("desktop preview makes restricted, unavailable and asynchronous states explicit", async ({ page }, testInfo) => {
    const frame = await openSurface(page, "settings-iam.html::requests");
    await expect(frame.getByRole("tab", { name: "Access requests", exact: true })).toHaveAttribute("aria-selected", "true");
    await scenario(frame, "reader");
    await expect(frame.getByRole("tabpanel").getByText("Owner access required")).toBeVisible();
    await expect(frame.locator(".iam-requests-table")).toBeHidden();
    await expect(frame.getByRole("tab", { name: "Users", exact: true })).toBeDisabled();
    await expect(frame.getByRole("tab", { name: "Access requests", exact: true })).toBeDisabled();
    await frame.getByRole("tab", { name: "My access", exact: true }).click();
    await expect(frame.getByText(iamText.fdaiOwnerNotAssigned)).toBeVisible();
    await expect(frame.locator("[data-capability-count]")).toHaveText(["1", "1"]);
    await frame.getByRole("tab", { name: "My access", exact: true }).focus();
    await page.keyboard.press("End");
    await expect(frame.getByRole("tab", { name: "Role definitions", exact: true })).toBeFocused();

    await scenario(frame, "unavailable");
    await frame.getByRole("tab", { name: "Users", exact: true }).click();
    await expect(frame.locator("[data-roster-unavailable]")).toBeVisible();
    await expect(frame.getByRole("searchbox", { name: iamText.findUser })).toBeDisabled();
    await expect(frame.locator("[data-roster] > tr:visible")).toHaveCount(3);
    await expect(frame.locator("[data-unknown-role]:visible")).toHaveCount(3);
    await frame.getByRole("tab", { name: "Access requests", exact: true }).click();
    await expect(frame.locator("[data-assigned-status]")).toHaveText("Assignment pending");
    await expect(frame.getByText("Directory verification unavailable", { exact: true })).toBeVisible();
    await scenario(frame, "loading");
    await expect(frame.getByRole("status", { name: "Loading identity and access data" })).toHaveAttribute("aria-busy", "true");
    await expect(frame.getByRole("tabpanel")).toHaveCount(0);
    await scenario(frame, "error");
    await expect(frame.getByRole("alert")).toContainText("Failed to load identity and access data");
    await expect(frame.getByRole("tabpanel")).toHaveCount(0);
    await scenario(frame, "owner");
    await expect(frame.getByRole("tabpanel")).toHaveCount(1);
    await expectLayout(frame);
    await page.screenshot({ path: testInfo.outputPath("iam-states-desktop.png") });
  });

  test("accepted IAM panels fit constrained and mobile frames, including expanded review", async ({ page }, testInfo) => {
    for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport);
      const frame = await openSurface(page, "settings-iam.html", true);
      for (const name of tabNames) {
        await frame.getByRole("tab", { name, exact: true }).click();
        if (name === "Users") {
          await frame.locator('[data-roster] .iam-principal strong').first().evaluate((element) => {
            element.textContent = "긴 사용자 이름 / " + "example-long-identity".repeat(6);
          });
        }
        if (name === "Access requests") await frame.getByRole("button", { name: "Review", exact: true }).click();
        await expectLayout(frame);
        await page.screenshot({ path: testInfo.outputPath(`iam-${name.replaceAll(" ", "-")}-${viewport.width}.png`) });
      }
    }
  });

  test("gallery shares the implemented specimen without hijacking its section route", async ({ page }) => {
    const frame = await openSurface(page, "components.html::settings-access");
    const url = page.url();
    await expect(frame.locator("#settings-access")).toHaveAttribute("data-gallery-status", "Documented");
    await expect(frame.getByText(iamText.fdaiOwnerConfirmed)).toBeVisible();
    await frame.getByRole("tab", { name: "Users", exact: true }).click();
    await expect(frame.getByRole("heading", { name: "People and groups" })).toBeVisible();
    await expect(page).toHaveURL(url);
    await expectLayout(frame);
  });

  test("template failures show an explicit error instead of empty or healthy IAM data", async ({ page }) => {
    await page.route("**/assets/settings-iam-content.html*", (route) => route.fulfill({ status: 404, body: "Missing fixture" }));
    await page.goto("http://127.0.0.1:5373/mocks/ui/#settings-iam.html");
    const frame = page.frameLocator("iframe");
    await expect(frame.getByRole("alert")).toContainText("Unable to load the identity and access preview");
    await expect(frame.getByText(iamText.fdaiOwnerConfirmed)).toHaveCount(0);
    await expect(frame.locator("[data-iam-ready]")).toHaveCount(0);
    await page.unroute("**/assets/settings-iam-content.html*");
    await frame.getByRole("button", { name: "Retry preview", exact: true }).click();
    await expect(frame.locator("[data-iam-mock]")).toHaveAttribute("data-iam-ready", "true");
    await expect(frame.getByText(iamText.fdaiOwnerConfirmed)).toBeVisible();
  });
});
