import { expect, test, type FrameLocator } from "@playwright/test";
import guideText from "../../src/routes/i18n/settings-integrations.en.json" with { type: "json" };
import { openSurface, routeMocks } from "./settings-mock-page";

async function expectFits(frame: FrameLocator) {
  expect(await frame.locator(".tw-workspace").evaluate((element) => ({
    document: document.documentElement.scrollWidth <= innerWidth,
    workspace: element.scrollWidth <= element.clientWidth,
    images: [...element.querySelectorAll("img")].every((image) =>
      image.getBoundingClientRect().width <= image.parentElement!.clientWidth,
    ),
  }))).toEqual({ document: true, workspace: true, images: true });
}

test.describe("Teams Workflows static preview", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium");
    await page.setViewportSize({ width: 1070, height: 918 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await routeMocks(page);
  });

  test("desktop guide follows Console setup without accepting or sending secrets", async ({ page }, testInfo) => {
    const unexpected: string[] = [];
    page.on("request", (request) => {
      if (request.method() !== "GET" || new URL(request.url()).origin !== "http://127.0.0.1:5373") {
        unexpected.push(`${request.method()} ${new URL(request.url()).origin}`);
      }
    });
    const frame = await openSurface(page, "settings-integrations.html::teams-workflows");
    await expect(frame.locator("[data-teams-workflow-preview]")).toHaveAttribute("data-teams-workflow-ready", "true");
    const workspace = frame.locator(".tw-workspace");
    await expect(workspace.locator(".tw-summary > div")).toHaveCount(3);
    await expect(workspace.locator(":scope > details")).toHaveCount(4);
    await expect(workspace.locator("details[open]")).toHaveCount(0);
    await expect(workspace.getByLabel("Teams Workflows HTTP URL")).toBeDisabled();
    await expect(workspace.getByLabel("Teams Workflows HTTP URL")).toHaveValue("");
    await expect(workspace.getByRole("button", { name: "Save and send test" })).toBeDisabled();
    await expect(workspace).toContainText("cannot carry A1 human approvals");
    await expect(workspace).toContainText("never returns the saved URL");
    await frame.locator("#integrations-teams").evaluate((element) => element.scrollIntoView());
    await page.screenshot({ path: testInfo.outputPath("teams-setup-desktop.png") });
    const guide = workspace.locator(".tw-guide");
    await expect(guide).not.toHaveAttribute("open", "");
    await guide.locator("summary").focus();
    await guide.locator("summary").press("Enter");
    await expect(guide).toHaveAttribute("open", "");
    await expect(guide.locator(".tw-guide-steps > li")).toHaveCount(10);
    for (const copy of [
      guideText.guideCreateBody, guideText.guideNameFlowBody, guideText.guideAddTriggerBody,
      guideText.guideSelectTriggerBody, guideText.guideConfigureTriggerBody,
      guideText.guideAddActionBody, guideText.guideConfigureActionBody,
      guideText.guideFinishBody, guideText.guideCopyUrlBody, guideText.guideSecretNote,
    ]) {
      await expect(guide.getByText(copy, { exact: true })).toBeVisible();
    }
    await expect(guide.locator("img")).toHaveCount(9);
    for (const image of await guide.locator("img").all()) {
      await image.scrollIntoViewIfNeeded();
      await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
      await expect(image).toHaveAttribute("alt", /.+/);
      await expect(image).toHaveAttribute("src", /^\/console\/public\/guides\/power-automate\//);
    }
    await expectFits(frame);
    await guide.locator("summary").click();
    await workspace.getByText("Storage and role boundaries", { exact: true }).click();
    await expect(workspace.getByText(guideText.saveBoundary, { exact: true })).toBeVisible();
    await expect(workspace).toContainText("metadata only");
    await workspace.locator(".tw-receipt > summary").click();
    await expect(workspace.getByText("Example: saved and test accepted", { exact: true })).toBeVisible();
    await expect(workspace).toContainText("Acceptance is not proof of a message appearing in Teams");
    await expect(workspace).toContainText("explicit deployment activation");
    await page.screenshot({ path: testInfo.outputPath("teams-receipt-desktop.png") });
    await expect(workspace.getByLabel("Teams Workflows HTTP URL")).toHaveValue("");
    expect(await frame.locator("body").evaluate(() =>
      [...Object.values(localStorage), ...Object.values(sessionStorage)].some((value) =>
        value.includes("workflow-owner@example.com") || value.includes("example-version-2"),
      ),
    )).toBe(false);
    expect(unexpected).toEqual([]);
  });

  test("desktop gallery documents and reuses the same Teams specimen", async ({ page }, testInfo) => {
    const frame = await openSurface(page, "components.html::settings-teams-workflow", true);
    const specimen = frame.locator("#settings-teams-workflow");
    await expect(specimen).toHaveAttribute("data-gallery-status", "Documented");
    await expect(specimen.locator("[data-teams-workflow-preview]")).toHaveAttribute("data-teams-workflow-ready", "true");
    await expect(specimen.locator(".tw-summary > div")).toHaveCount(3);
    await specimen.locator(".tw-receipt > summary").click();
    await expect(specimen.getByText("Example: saved and test accepted", { exact: true })).toBeVisible();
    await expect(page).toHaveURL(/components\.html::settings-teams-workflow$/);
    await expectFits(frame);
    await page.screenshot({ path: testInfo.outputPath("teams-gallery-desktop.png") });
  });

  test("loading and template failure stay explicit and allow a bounded manual retry", async ({ page }) => {
    let release: () => void = () => {};
    const pending = new Promise<void>((resolve) => { release = resolve; });
    let unavailable = true;
    await page.route("**/assets/settings-teams-workflow-content.html*", async (route) => {
      if (!unavailable) return route.fallback();
      await pending;
      await route.fulfill({ status: 503, body: "Preview unavailable" });
    });
    const frame = await openSurface(page, "settings-integrations.html::teams-workflows");
    await expect(frame.getByRole("status", { name: "Loading Teams Workflows preview" })).toHaveAttribute("aria-busy", "true");
    release();
    await expect(frame.getByRole("alert")).toHaveText("Unable to load the Teams Workflows preview.");
    await expect(frame.locator(".tw-workspace")).toHaveCount(0);
    unavailable = false;
    await frame.getByRole("button", { name: "Retry Teams preview" }).click();
    await expect(frame.locator("[data-teams-workflow-preview]")).toHaveAttribute("data-teams-workflow-ready", "true");
  });

  for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }]) {
    test(`responsive ${viewport.width} keeps the guide, evidence and disabled controls readable`, async ({ page }, testInfo) => {
      await page.setViewportSize(viewport);
      const frame = await openSurface(page, "settings-integrations.html::teams-workflows", true);
      await expect(frame.locator("[data-teams-workflow-preview]")).toHaveAttribute("data-teams-workflow-ready", "true");
      const workspace = frame.locator(".tw-workspace");
      await frame.locator("#integrations-teams").evaluate((element) => element.scrollIntoView());
      await page.screenshot({ path: testInfo.outputPath("teams-overview.png") });
      await workspace.locator(".tw-guide > summary").click();
      await workspace.getByAltText(guideText.guideConfigureActionImageAlt).scrollIntoViewIfNeeded();
      await expectFits(frame);
      await page.screenshot({ path: testInfo.outputPath("teams-illustrated-guide.png") });
      await workspace.locator(".tw-guide > summary").click();
      await workspace.locator(".tw-receipt > summary").click();
      await workspace.locator(".tw-receipt").scrollIntoViewIfNeeded();
      await expectFits(frame);
      if (viewport.width === 390) {
        for (const control of await workspace.locator("input:visible, button:visible, summary:visible, a:visible").all()) {
          expect(await control.evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44);
        }
      }
      await page.screenshot({ path: testInfo.outputPath("teams-example-receipt.png") });
    });
  }
});
