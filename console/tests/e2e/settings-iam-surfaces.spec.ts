import { expect, test, type FrameLocator } from "@playwright/test";
import { openSurface, routeMocks } from "./settings-mock-page";

async function expectQuietSurfaces(frame: FrameLocator) {
  const toolbar = frame.locator(".iam-directory-toolbar");
  await expect(toolbar).toHaveCSS("background-color", "rgb(245, 245, 245)");
  await expect(toolbar).toHaveCSS("border-top-width", "0px");
  await expect(toolbar).toHaveCSS("box-shadow", "none");
  await expect(toolbar.getByRole("searchbox")).toHaveCSS("background-color", "rgb(255, 255, 255)");
  for (const heading of await frame.locator(".iam-roster-table th").all()) {
    await expect(heading).toHaveCSS("background-color", "rgb(245, 245, 245)");
    await expect(heading).toHaveCSS("color", "rgb(82, 82, 82)");
    await expect(heading).toHaveCSS("border-bottom-width", "0px");
  }
  const rowBackgrounds = await frame.locator("[data-roster] > tr").evaluateAll((rows) =>
    rows.map((row) => {
      for (let element: Element | null = row; element; element = element.parentElement) {
        const color = getComputedStyle(element).backgroundColor;
        if (color !== "rgba(0, 0, 0, 0)") return color;
      }
      return "transparent";
    }),
  );
  expect(rowBackgrounds).toEqual(Array(4).fill("rgb(255, 255, 255)"));
  expect(await toolbar.evaluate((element) => {
    const bounds = element.getBoundingClientRect();
    return {
      documentFits: document.documentElement.scrollWidth <= innerWidth,
      toolbarFits: element.scrollWidth <= element.clientWidth,
      controlsFit: [...element.children].every((control) => {
        const box = control.getBoundingClientRect();
        return box.left >= bounds.left && box.right <= bounds.right + 1
          && box.top >= bounds.top && box.bottom <= bounds.bottom + 1;
      }),
    };
  })).toEqual({ documentFits: true, toolbarFits: true, controlsFit: true });
  expect(await frame.locator(".iam-workspace").evaluate((element) =>
    element.scrollWidth <= element.clientWidth,
  )).toBe(true);
}

test.describe("IAM quiet directory surfaces", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium");
    await page.emulateMedia({ reducedMotion: "reduce" });
    await routeMocks(page);
  });

  for (const master of [false, true]) {
    test(`wide ${master ? "master" : "kit"} separates tools from white roster data`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width: 1440, height: 900 });
      const frame = await openSurface(page, "settings-iam.html::users", master);
      await page.screenshot({ path: testInfo.outputPath("users-wide.png") });
      await expectQuietSurfaces(frame);
      await expect(frame.getByRole("searchbox")).toHaveCSS("height", "34px");
      await frame.getByRole("searchbox").focus();
      await expect(frame.getByRole("searchbox")).toHaveCSS("outline-style", "solid");
      await expect(frame.getByRole("searchbox")).toHaveCSS("outline-width", "2px");
      await frame.getByRole("searchbox").fill("Analyst");
      await expect(frame.locator("[data-roster] > tr:visible")).toHaveCount(1);
      await frame.locator(".iam-directory-toolbar").getByRole("button", { name: "Clear filters" }).click();
      await expect(frame.getByRole("searchbox")).toBeFocused();
      await expect(frame.locator("[data-roster-count]")).toHaveText("4 of 4 shown");
      await frame.getByRole("tab", { name: "Role definitions", exact: true }).click();
      await expect(frame.locator(".iam-role-table th").first()).toHaveCSS("background-color", "rgb(248, 248, 248)");
      await frame.getByRole("tab", { name: "Access requests", exact: true }).click();
      await expect(frame.locator(".iam-request-toolbar")).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
    });
  }

  test("wide gallery reuses the same restrained directory surfaces", async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const frame = await openSurface(page, "components.html::settings-access", true);
    await frame.getByRole("tab", { name: "Users", exact: true }).click();
    await expectQuietSurfaces(frame);
    await expect(page).toHaveURL(/components\.html::settings-access$/);
    await page.screenshot({ path: testInfo.outputPath("users-gallery.png") });
  });

  test("wide walkthrough keeps all four tabs readable and their details reachable", async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const frame = await openSurface(page, "settings-iam.html");
    const views = [
      { name: "My access", id: "my-access" },
      { name: "Users", id: "users" },
      { name: "Role definitions", id: "roles" },
      { name: "Access requests", id: "requests" },
    ];
    for (const view of views) {
      await frame.getByRole("tab", { name: view.name, exact: true }).click();
      await expect(frame.getByRole("tab", { name: view.name, exact: true })).toHaveAttribute("aria-selected", "true");
      await expect(frame.getByRole("tabpanel")).toHaveCount(1);
      await expect(page).toHaveURL(new RegExp(`settings-iam\\.html::${view.id}$`));
      expect(await frame.getByRole("tabpanel").evaluate((element) =>
        element.scrollWidth <= element.clientWidth && document.documentElement.scrollWidth <= innerWidth,
      )).toBe(true);
      await page.screenshot({ path: testInfo.outputPath(`tab-${view.id}.png`) });
      if (view.id === "my-access") {
        const disclosures = frame.locator(".iam-authority details, .iam-identity-details, .iam-capabilities");
        for (const disclosure of await disclosures.all()) await disclosure.locator("summary").click();
        await expect(frame.getByText("Subject ID", { exact: true })).toBeVisible();
        await expect(frame.locator("[data-current-capabilities] .iam-capability:visible")).toHaveCount(12);
        await page.screenshot({ path: testInfo.outputPath("identity-expanded.png") });
        for (const disclosure of await disclosures.all()) await disclosure.locator("summary").click();
      }
      if (view.id === "roles") {
        const owner = frame.locator('[data-role="Owner"]');
        await owner.locator("summary").click();
        await expect(owner.locator(".iam-capability:visible")).toHaveCount(12);
        await page.screenshot({ path: testInfo.outputPath("role-expanded.png") });
        await owner.locator("summary").click();
      }
      if (view.id === "requests") {
        await frame.locator("[data-request-filter]").selectOption("assignment-pending");
        await expect(frame.locator("[data-requests] > tr:visible")).toHaveCount(1);
        await expect(frame.getByText("Assignment pending", { exact: true })).toBeVisible();
        await frame.locator("[data-request-filter]").selectOption("all");
        await frame.getByRole("button", { name: "Review", exact: true }).click();
        const dialog = frame.getByRole("dialog");
        await expect(dialog.getByRole("button", { name: "Approve", exact: true })).toBeDisabled();
        await expect(dialog.getByRole("button", { name: "Reject", exact: true })).toBeDisabled();
        await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
      }
    }
  });

  for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }]) {
    test(`responsive ${viewport.width} preserves density and readable controls`, async ({ page }, testInfo) => {
      await page.setViewportSize(viewport);
      const frame = await openSurface(page, "settings-iam.html::users", true);
      await expectQuietSurfaces(frame);
      if (viewport.width === 993) {
        const geometry = await frame.locator("[data-roster] > tr").nth(1).evaluate((row) => ({
          bottom: row.getBoundingClientRect().bottom,
          viewport: innerHeight,
        }));
        expect(geometry.bottom).toBeLessThanOrEqual(geometry.viewport - 16);
      } else {
        for (const control of await frame.locator(".iam-directory-toolbar :is(input, button)").all()) {
          expect(await control.evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44);
        }
        await expect(frame.getByText("Person", { exact: true }).first()).toBeVisible();
      }
      await page.screenshot({ path: testInfo.outputPath(`users-${viewport.width}.png`) });
    });
  }
});
