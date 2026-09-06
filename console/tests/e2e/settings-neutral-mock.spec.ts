import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, type FrameLocator, type Locator, type Page } from "@playwright/test";

const root = path.resolve(fileURLToPath(new URL("../../../", import.meta.url)));
const origin = "http://127.0.0.1:5373";
const settings = [
  ["settings.html", "General settings"],
  ["settings-models.html", "Models"],
  ["settings-runtime.html", "Runtime policies"],
  ["settings-memory.html", "Operator memory"],
  ["settings-iam.html", "Identity and access"],
  ["settings-integrations.html", "Integrations"],
  ["settings-diagnostics.html", "Diagnostics"],
] as const;
const specimens = ["settings-preferences", "settings-catalog", "settings-policy", "settings-access", "settings-diagnostics"];

async function openSurface(page: Page, file: string, master = false) {
  await page.goto("about:blank");
  await page.goto(`${origin}/${master ? `#mocks/ui/${file}` : `mocks/ui/#${file}`}`);
  const frame = page.frameLocator(master ? "#preview-frame" : "iframe");
  await expect(frame.locator("body")).toHaveClass(/cs-embedded/);
  if (file.startsWith("components.html")) {
    await expect(frame.locator("body")).toHaveClass(/is-gallery-ready/);
  } else {
    await expect(frame.locator("body")).toHaveAttribute("data-chat-theme", "clear-neutral");
  }
  return frame;
}

async function expectGeometry(region: Locator) {
  expect(await region.evaluate((element) => ({
    document: document.documentElement.scrollWidth <= innerWidth,
    region: element.scrollWidth <= element.clientWidth,
    children: [...element.querySelectorAll(".cs-setting-row, .cs-settings-card, .cs-settings-option-card, .cp-form, .cp-table-wrap")]
      .filter((child) => child.getBoundingClientRect().width > 0)
      .every((child) => child.scrollWidth <= child.clientWidth + 1),
  }))).toEqual({ document: true, region: true, children: true });
}

async function exerciseAccessTabs(frame: FrameLocator) {
  for (const label of ["Users", "Roles", "Requests", "My access"]) {
    const tab = frame.getByRole("tab", { name: label, exact: true });
    await tab.click();
    await expect(tab).toHaveAttribute("aria-selected", "true");
    await expect(frame.getByRole("tabpanel")).toHaveCount(1);
    await expectGeometry(frame.getByRole("tabpanel"));
  }
}

async function exerciseLanguagePicker(picker: Locator) {
  const english = picker.getByRole("button", { name: "English", exact: true });
  const korean = picker.getByRole("button", { name: "Korean", exact: true });
  const width = await picker.evaluate((element) => element.getBoundingClientRect().width);
  expect(width).toBeLessThanOrEqual(240);
  await expect(english).toHaveAttribute("aria-pressed", "true");
  await expect(english.locator("svg")).toBeVisible();
  await expect(korean.locator("svg")).toBeHidden();
  await korean.click();
  await expect(korean).toHaveAttribute("aria-pressed", "true");
  await expect(korean.locator("svg")).toBeVisible();
  await expect(english.locator("svg")).toBeHidden();
  await expect(picker.locator('[aria-pressed="true"]')).toHaveCount(1);
  expect(await picker.evaluate((element) => element.getBoundingClientRect().width)).toBe(width);
  await english.focus();
  await english.press("Space");
  await expect(english).toHaveAttribute("aria-pressed", "true");
  await expect(english).toHaveCSS("outline-color", "rgb(37, 99, 235)");
  await expectGeometry(picker);
}

test.describe("Clear neutral Settings mocks", () => {
  test.describe.configure({ mode: "serial" });
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "Desktop acceptance precedes responsive validation.");
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.route(`${origin}/**`, async (route) => {
      const pathname = decodeURIComponent(new URL(route.request().url()).pathname);
      const entry = pathname.endsWith("/") ? `${pathname}index.html` : pathname;
      const file = path.resolve(root, `.${entry}`);
      if (!file.startsWith(`${root}${path.sep}`) || !/\.(html|css|js|json|svg|png)$/.test(file)) {
        await route.fulfill({ status: 404, body: "Not a UI fixture." });
        return;
      }
      await route.fulfill({ path: file });
    });
  });

  test("desktop routes share the palette without changing evidence or native controls", async ({ page }, testInfo) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    for (const [file, title] of settings) {
      const frame = await openSurface(page, file);
      await expect(frame.getByRole("heading", { level: 1 })).toContainText(title);
      await expect(frame.locator("body")).toHaveCSS("color", "rgb(38, 38, 38)");
      await expect(frame.locator("body")).toHaveCSS("background-color", "rgb(255, 255, 255)");
      expect(await frame.locator("body").evaluate((element) =>
        getComputedStyle(element).getPropertyValue("--cs-steel").trim(),
      )).toBe("#2563eb");
      await expectGeometry(frame.locator("main"));
      if (file === "settings.html") {
        const language = frame.getByRole("group", { name: "Language", exact: true });
        await exerciseLanguagePicker(language);
        await language.screenshot({ path: testInfo.outputPath("language-picker-desktop.png") });
        const toggle = frame.locator('input[type="checkbox"]').nth(1);
        await expect(toggle).toBeChecked();
        await toggle.focus();
        await page.keyboard.press("Space");
        await expect(toggle).not.toBeChecked();
        await page.keyboard.press("Space");
        await expect(toggle.locator("+ span")).toHaveCSS("background-color", "rgb(37, 99, 235)");
        await expect(toggle.locator("+ span")).toHaveCSS("outline-width", "2px");
        expect(await toggle.locator("+ span").evaluate((element) =>
          parseFloat(getComputedStyle(element, "::after").transitionDuration),
        )).toBeLessThan(0.001);
        await expect(frame.getByRole("button", { name: "Save user context" })).toBeDisabled();
      }
      if (file === "settings-models.html") {
        await expect(frame.locator(".cs-settings-option-card")).toHaveCount(3);
        const primary = frame.getByRole("button", { name: "Save narrator preference" });
        await expect(primary).toHaveCSS("background-color", "rgb(37, 99, 235)");
        await primary.hover();
        await expect(primary).toHaveCSS("color", "rgb(255, 255, 255)");
        await expect(frame.getByRole("button", { name: "Unavailable", exact: true })).toBeDisabled();
        await frame.locator("#models-catalog").scrollIntoViewIfNeeded();
        await page.screenshot({ path: testInfo.outputPath("models-catalog-desktop.png") });
      }
      if (file === "settings-runtime.html") {
        await expect(frame.getByText("Unavailable", { exact: true }).last()).toHaveCSS("color", "rgb(102, 102, 102)");
        await expect(frame.getByText("Restart required", { exact: true }).last()).toHaveCSS("color", "rgb(180, 83, 9)");
        const field = frame.getByRole("textbox", { name: "Override value" });
        await field.fill("12 min");
        await expect(field).toHaveCSS("outline-color", "rgb(37, 99, 235)");
        await frame.getByRole("button", { name: "Save revisioned override" }).click();
        await expect(field).toHaveValue("12 min");
        await expect(frame.locator(".cs-readonly-banner")).toContainText("does not save");
      }
      if (file === "settings-iam.html") await exerciseAccessTabs(frame);
      if (file === "settings-diagnostics.html") {
        await expect(frame.getByText("Unknown", { exact: true })).toHaveCSS("color", "rgb(102, 102, 102)");
        await expect(frame.getByText("operator@example.com", { exact: true })).toBeVisible();
      }
      await frame.locator("body").evaluate(() => scrollTo(0, 0));
      await page.screenshot({ path: testInfo.outputPath(`${file}-desktop.png`) });
    }
    expect(errors).toEqual([]);
  });

  test("desktop gallery registers all Settings patterns and preserves palette isolation", async ({ page }, testInfo) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    for (const id of specimens) {
      const frame = await openSurface(page, `components.html::${id}`);
      const specimen = frame.locator(`#${id}`);
      await expect(specimen).toHaveAttribute("data-gallery-status", "Documented");
      await expect(frame.locator('[data-gallery-status="Review required"]')).toHaveCount(0);
      await expect(specimen.locator(".cs-settings-specimen")).toHaveCSS("color", "rgb(38, 38, 38)");
      await expectGeometry(specimen);
      await expect(frame.getByRole("navigation", { name: "Component subviews" }).locator('[aria-current="page"]')).toHaveAttribute("href", `#view=patterns:${id}`);
      if (id === "settings-preferences") {
        await exerciseLanguagePicker(specimen.getByRole("group", { name: "Sample language" }));
        const detail = specimen.getByRole("group", { name: "Sample answer detail" });
        await detail.getByRole("button", { name: "Deep" }).click();
        await expect(detail.getByRole("button", { name: "Deep" })).toHaveAttribute("aria-pressed", "true");
        await expect(detail.locator('[aria-pressed="true"]')).toHaveCount(1);
      }
      if (id === "settings-access") {
        await exerciseAccessTabs(frame);
        await specimen.getByRole("tab", { name: "My access" }).focus();
        await page.keyboard.press("End");
        await expect(specimen.getByRole("tab", { name: "Requests" })).toBeFocused();
        await expect(specimen.getByRole("tab", { name: "Requests" })).toHaveAttribute("aria-selected", "true");
      }
      if (id === "settings-diagnostics") {
        await expect(specimen.getByText("Failed", { exact: true })).toHaveCSS("color", "rgb(198, 40, 40)");
        await expect(specimen.getByRole("status")).toHaveAttribute("aria-busy", "true");
      }
      await frame.getByRole("button", { name: "Dark preview", exact: true }).click();
      await expect(specimen.locator(".cs-settings-specimen")).toHaveCSS("background-color", "rgb(255, 255, 255)");
      await frame.getByRole("button", { name: "Light preview", exact: true }).click();
      await specimen.scrollIntoViewIfNeeded();
      await page.screenshot({ path: testInfo.outputPath(`${id}-desktop.png`) });
    }
    const frame = page.frameLocator("iframe");
    await frame.getByRole("searchbox", { name: "Find a component" }).fill("settings");
    for (const id of specimens) {
      await expect(frame.locator(`[data-gallery-subindex] a[href="#view=patterns:${id}"]`)).toBeVisible();
    }
    expect(errors).toEqual([]);
  });

  test("accepted Settings and gallery layouts remain usable in constrained and mobile shells", async ({ page }, testInfo) => {
    for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport);
      for (const [file] of settings) {
        const frame = await openSurface(page, file, true);
        await expectGeometry(frame.locator("main"));
        if (file === "settings.html") {
          const language = frame.getByRole("group", { name: "Language", exact: true });
          await exerciseLanguagePicker(language);
          await language.screenshot({ path: testInfo.outputPath(`language-picker-${viewport.width}.png`) });
        }
        if (file === "settings-iam.html") await exerciseAccessTabs(frame);
        const description = frame.locator(".cs-setting-row small").first();
        if (await description.count()) {
          await description.evaluate((element) => {
            element.textContent = "확인되지 않은 긴 운영 대상 / " + "long-unbroken-identifier".repeat(8) + " / 2026-09-06T02:00:00Z";
          });
        }
        const identifier = frame.locator("td code").first();
        if (await identifier.count()) {
          await identifier.evaluate((element) => {
            element.textContent = "example-long-identifier".repeat(8);
          });
        }
        await expectGeometry(frame.locator("main"));
        if (viewport.width === 390) {
          const sizes = await frame.locator('button:visible, select:visible, input:not([type="checkbox"]):visible').evaluateAll((controls) =>
            controls.map((control) => control.getBoundingClientRect().height),
          );
          expect(sizes.every((height) => height >= 44)).toBe(true);
        }
        await frame.locator("body").evaluate(() => scrollTo(0, 0));
        await page.screenshot({ path: testInfo.outputPath(`${file}-${viewport.width}.png`) });
      }
      for (const id of specimens) {
        const frame = await openSurface(page, `components.html::${id}`, true);
        const specimen = frame.locator(`#${id}`);
        await expectGeometry(specimen);
        if (id === "settings-preferences") {
          await exerciseLanguagePicker(specimen.getByRole("group", { name: "Sample language" }));
        }
        if (id === "settings-access") await exerciseAccessTabs(frame);
        await specimen.scrollIntoViewIfNeeded();
        await page.screenshot({ path: testInfo.outputPath(`${id}-${viewport.width}.png`) });
      }
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    const frame = await openSurface(page, "settings.html");
    await expectGeometry(frame.locator("main"));
  });
});
