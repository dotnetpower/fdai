import { expect, test } from "@playwright/test";
import { openSurface, routeMocks } from "./settings-mock-page";

test.describe("Task-first IAM refinement", () => {
  test.describe.configure({ mode: "serial" });
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium");
    await page.setViewportSize({ width: 993, height: 641 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await routeMocks(page);
  });

  test("desktop puts two people in the first viewport before optional guidance", async ({ page }, testInfo) => {
    const frame = await openSurface(page, "settings-iam.html::users", true);
    await page.screenshot({ path: testInfo.outputPath("users-first-viewport.png") });
    const geometry = await frame.locator("[data-roster] > tr").nth(1).evaluate((row) => ({
      bottom: row.getBoundingClientRect().bottom,
      viewport: innerHeight,
    }));
    await testInfo.attach("first-viewport-geometry.json", { body: JSON.stringify(geometry), contentType: "application/json" });
    expect(geometry.bottom).toBeLessThanOrEqual(geometry.viewport - 16);
    await expect(frame.locator(".iam-workflow-details")).not.toHaveAttribute("open", "");
    await expect(frame.locator(".iam-search-results")).toHaveCount(0);
    await expect(frame.locator("[data-roster] select")).toHaveCount(0);
  });

  test("desktop search, counts and empty recovery use one canonical roster", async ({ page }) => {
    const frame = await openSurface(page, "settings-iam.html::users");
    const search = frame.getByRole("searchbox");
    await search.fill("   ");
    await search.press("Enter");
    await expect(search).toHaveValue("");
    await expect(frame.locator("[data-roster] > tr:visible")).toHaveCount(4);
    await search.fill("a");
    await expect(frame.locator("[data-search-hint]")).toContainText("at least 2 characters");
    await expect(frame.locator("[data-roster] > tr:visible")).toHaveCount(4);
    await search.fill("OPERATOR");
    await expect(frame.locator("[data-roster] > tr:visible")).toHaveCount(1);
    await expect(frame.locator("[data-roster-count]")).toHaveText("1 of 4 shown");
    await expect(frame.locator("[data-roster-total]")).toHaveText("3 people / 1 group");
    await expect(frame.locator("[data-iam-announcement]")).toHaveText("1 of 4 shown");
    await frame.getByRole("button", { name: "Groups", exact: true }).click();
    await expect(frame.locator("[data-roster-empty]")).toBeVisible();
    await frame.locator("[data-roster-empty]").getByRole("button", { name: "Clear filters" }).click();
    await expect(search).toBeFocused();
    await expect(search).toHaveValue("");
    await expect(frame.locator("[data-roster] > tr:visible")).toHaveCount(4);
    await expect(frame.getByRole("button", { name: "All", exact: true })).toHaveAttribute("aria-pressed", "true");
  });

  test("desktop disclosure reduces identity and capability noise without dropping facts", async ({ page }) => {
    const frame = await openSurface(page, "settings-iam.html");
    await expect(frame.locator("[data-current-role]")).toHaveCount(1);
    await expect(frame.locator(".iam-identity-details")).not.toHaveAttribute("open", "");
    await expect(frame.locator(".iam-capabilities")).not.toHaveAttribute("open", "");
    await frame.locator(".iam-identity-details > summary").click();
    await expect(frame.getByText("Subject ID", { exact: true })).toBeVisible();
    await frame.locator(".iam-capabilities > summary").click();
    await expect(frame.locator("[data-current-capabilities] .iam-capability:visible")).toHaveCount(12);
    await frame.getByRole("tab", { name: "Role definitions", exact: true }).click();
    await expect(frame.locator("[data-role-definitions] .iam-capability:visible")).toHaveCount(0);
    await expect(frame.getByText("Includes Reader permissions", { exact: true })).toBeVisible();
    await expect(frame.getByText("Includes Contributor permissions", { exact: true })).toBeVisible();
    await expect(frame.getByText("Includes Approver permissions", { exact: true })).toBeVisible();
    const owner = frame.locator('[data-role="Owner"]');
    await owner.locator("summary").click();
    await expect(owner.locator(".iam-capability:visible")).toHaveCount(12);
    await expect(frame.locator('[data-role="BreakGlass"]')).toContainText("Separate emergency permissions");
    await expect(frame.getByRole("tab", { name: "Role definitions", exact: true })).not.toHaveCSS("background-color", "rgb(37, 99, 235)");
    await frame.locator(".iam-workspace").evaluate(() => scrollTo(0, 200));
    expect(await frame.locator(".iam-nav").evaluate((element) => Math.abs(element.getBoundingClientRect().top))).toBeLessThanOrEqual(1);
  });

  test("desktop editors isolate targets, validate text, trap focus and restore the row", async ({ page }, testInfo) => {
    const mutations: string[] = [];
    page.on("request", (request) => { if (request.method() !== "GET") mutations.push(request.url()); });
    const frame = await openSurface(page, "settings-iam.html::users");
    const opener = frame.getByRole("button", { name: "Request role for Example Analyst", exact: true });
    const rosterTop = await frame.locator("[data-roster]").evaluate((element) => element.getBoundingClientRect().top);
    await opener.click();
    const dialog = frame.getByRole("dialog", { name: "Request a role", exact: true });
    await expect(dialog).toBeVisible();
    await expect(dialog.locator("[data-draft-principal]")).toHaveText("Example Analyst");
    await expect(dialog.locator("[data-draft-current-role]")).toHaveText("Reader");
    await dialog.getByRole("combobox").selectOption("Contributor");
    const reason = dialog.getByRole("textbox");
    await reason.fill("short");
    await reason.press("Tab");
    await expect(reason).toHaveAttribute("aria-invalid", "true");
    await expect(dialog.locator(".iam-validation")).toContainText("15 more characters");
    await reason.fill("   Example operational need supported by current evidence.   ");
    await expect(reason).toHaveAttribute("aria-invalid", "false");
    await expect(dialog.locator(".iam-validation")).toContainText("Minimum met");
    await expect(dialog.getByRole("button", { name: "Submit access request" })).toBeDisabled();
    await expect(dialog.getByRole("button", { name: "Submit access request" })).toHaveAttribute("aria-describedby", "iam-request-preview-note");
    for (let index = 0; index < 6; index++) {
      await page.keyboard.press("Tab");
      expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
    }
    await page.screenshot({ path: testInfo.outputPath("role-request-editor.png") });
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(opener).toBeFocused();
    expect(await frame.locator("[data-roster]").evaluate((element) => element.getBoundingClientRect().top)).toBeCloseTo(rosterTop, 0);
    await frame.getByRole("button", { name: "Request role for Example Operator", exact: true }).click();
    await expect(dialog.locator("[data-draft-principal]")).toHaveText("Example Operator");
    await expect(dialog.getByRole("textbox")).toHaveValue("");
    await expect(dialog.getByRole("combobox")).toHaveValue("");
    await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(frame.getByRole("button", { name: "Request role for Example Operator", exact: true })).toBeFocused();
    expect(mutations).toEqual([]);
  });

  test("desktop request filters and review cancellation preserve list context", async ({ page }) => {
    const frame = await openSurface(page, "settings-iam.html::requests");
    const status = frame.getByRole("combobox", { name: "Status", exact: true });
    await status.selectOption("pending");
    await expect(frame.locator("[data-requests] > tr:visible")).toHaveCount(1);
    await expect(frame.locator("[data-request-result]")).toHaveText("1 of 3 shown");
    const opener = frame.getByRole("button", { name: "Review", exact: true });
    await opener.click();
    const dialog = frame.getByRole("dialog", { name: "Review access request", exact: true });
    await expect(dialog.locator("[data-review-target]")).toHaveText("Example Analyst");
    await expect(dialog.locator("[data-review-requester]")).toHaveText("Example Operator");
    await expect(dialog.getByRole("textbox")).toBeFocused();
    await dialog.getByRole("textbox").fill("Independent review of the bounded example operational need.");
    await expect(dialog.getByRole("button", { name: "Approve", exact: true })).toBeDisabled();
    await expect(dialog.getByRole("button", { name: "Reject", exact: true })).toBeDisabled();
    await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(opener).toBeFocused();
    await status.selectOption("assigned");
    await expect(frame.locator("[data-requests] > tr:visible")).toHaveCount(1);
    await expect(frame.getByText("Verified by directory", { exact: true })).toBeVisible();
    await status.selectOption("rejected");
    await expect(frame.locator("[data-request-empty]")).toBeVisible();
    await frame.getByRole("button", { name: "Show all requests", exact: true }).click();
    await expect(status).toBeFocused();
    await expect(frame.locator("[data-requests] > tr:visible")).toHaveCount(3);
  });

  test("desktop Back, scenario reset and failed-view recovery are explicit", async ({ page }) => {
    const frame = await openSurface(page, "settings-iam.html");
    await frame.getByRole("tab", { name: "Users", exact: true }).click();
    await frame.getByRole("searchbox").fill("Analyst");
    await frame.getByRole("tab", { name: "Role definitions", exact: true }).click();
    await page.goBack();
    await expect(frame.getByRole("tab", { name: "Users", exact: true })).toHaveAttribute("aria-selected", "true");
    await expect(frame.getByRole("searchbox")).toHaveValue("Analyst");
    await expect(page).toHaveURL(/settings-iam\.html::users$/);
    await frame.locator(".iam-preview-controls > summary").click();
    await frame.getByRole("combobox", { name: "Scenario", exact: true }).selectOption("unavailable");
    await expect(frame.getByRole("searchbox")).toHaveValue("");
    await expect(frame.getByRole("button", { name: "Groups", exact: true })).toBeDisabled();
    await expect(frame.locator("[data-roster-count]")).toHaveText("3 of 3 shown / request references");
    await frame.locator(".iam-preview-controls > summary").click();
    await frame.getByRole("combobox", { name: "Scenario", exact: true }).selectOption("reader");
    await expect(frame.getByRole("tab", { name: "Users", exact: true })).toHaveAttribute("aria-describedby", "iam-owner-required-help");
    await frame.getByRole("tabpanel").getByRole("button", { name: "View your access" }).click();
    await expect(frame.getByRole("tab", { name: "My access", exact: true })).toBeFocused();
    const invalid = await openSurface(page, "settings-iam.html::unregistered");
    await expect(invalid.getByRole("alert")).toContainText("not registered");
    await invalid.getByRole("button", { name: "Reset preview to My access" }).click();
    await expect(invalid.getByRole("tab", { name: "My access", exact: true })).toHaveAttribute("aria-selected", "true");
    await expect(invalid.getByRole("alert")).toBeHidden();
  });

  test("mobile editors keep actions visible and compact rows retain their meaning", async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const frame = await openSurface(page, "settings-iam.html::users", true);
    await expect(frame.getByText("Person", { exact: true }).first()).toBeVisible();
    await expect(frame.getByText("Group", { exact: true })).toBeVisible();
    await frame.getByRole("button", { name: "Request role for Example Analyst", exact: true }).click();
    const dialog = frame.getByRole("dialog", { name: "Request a role", exact: true });
    expect(await dialog.evaluate((element) => {
      const bounds = element.getBoundingClientRect();
      const cancel = element.querySelector("[data-editor-cancel]")!.getBoundingClientRect();
      return { fits: bounds.width <= innerWidth && bounds.height <= innerHeight, cancelVisible: cancel.bottom <= innerHeight, height: cancel.height };
    })).toEqual({ fits: true, cancelVisible: true, height: 44 });
    await page.screenshot({ path: testInfo.outputPath("role-request-mobile.png") });
    await page.keyboard.press("Escape");
    await frame.getByRole("tab", { name: "Access requests", exact: true }).click();
    await frame.getByRole("button", { name: "Review", exact: true }).click();
    const review = frame.getByRole("dialog", { name: "Review access request", exact: true });
    await expect(review.getByText("Requested by", { exact: true })).toBeVisible();
    await expect(review.getByRole("button", { name: "Approve", exact: true })).toHaveCSS("min-height", "44px");
    await page.screenshot({ path: testInfo.outputPath("review-mobile.png") });
    await review.getByRole("button", { name: "Cancel", exact: true }).click();
    expect(await frame.locator(".iam-workspace").evaluate((element) => element.scrollWidth <= element.clientWidth && document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
});
