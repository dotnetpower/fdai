import { fileURLToPath, pathToFileURL } from "node:url";

import { expect, test, type Page } from "@playwright/test";

const shell = pathToFileURL(fileURLToPath(new URL("../../../index.html", import.meta.url))).href;
const mocks = [
  { file: "incident-conversation.html", question: ".ic-question .cs-deck-user-bubble", stream: ".ic-messages", composer: ".ic-composer form", answer: ".ic-answer", input: "#incident-question", primary: ".ic-answer-actions .is-primary" },
  { file: "deck-sources-v2.html", question: ".ex-thread > .is-user .ex-user-bubble", stream: ".ex-thread", composer: ".ex-composer", answer: ".ex-thread > .is-bragi", input: ".ex-composer-input", primary: ".ex-send" },
];

async function openMock(page: Page, file: string) {
  await page.goto("about:blank");
  await page.goto(`${shell}#mocks/ui/${file}`);
  const frame = page.frameLocator("#preview-frame");
  await expect(frame.locator("body")).toHaveAttribute("data-chat-theme", "clear-neutral");
  await expect(frame.locator("body")).toHaveClass(/cs-embedded/);
  return frame;
}

test("uses neutral surfaces and aligned readable chat controls in both mock routes", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const mock of mocks) {
    const frame = await openMock(page, mock.file);
    await expect(frame.locator(mock.question)).toHaveCSS("background-color", "rgb(242, 242, 242)");
    await expect(frame.locator("body")).toHaveCSS("color", "rgb(38, 38, 38)");
    await expect(frame.locator(mock.primary)).toHaveCSS("background-color", "rgb(37, 99, 235)");
    const geometry = await frame.locator("body").evaluate((body, mock) => {
      const stream = body.querySelector(mock.stream)!;
      const composer = body.querySelector(mock.composer)!;
      const rect = stream.getBoundingClientRect();
      const control = composer.getBoundingClientRect();
      return {
        left: rect.left + parseFloat(getComputedStyle(stream).paddingLeft),
        right: rect.right - parseFloat(getComputedStyle(stream).paddingRight),
        controlLeft: control.left + parseFloat(getComputedStyle(composer).paddingLeft),
        controlRight: control.right - parseFloat(getComputedStyle(composer).paddingRight),
        overflow: document.documentElement.scrollWidth > innerWidth || stream.scrollWidth > stream.clientWidth,
      };
    }, mock);
    expect(Math.abs(geometry.left - geometry.controlLeft)).toBeLessThanOrEqual(1);
    expect(Math.abs(geometry.right - geometry.controlRight)).toBeLessThanOrEqual(1);
    expect(geometry.overflow).toBe(false);
    await frame.locator(mock.input).focus();
    await expect(frame.locator(mock.input)).toHaveCSS("outline-style", "solid");
    await expect(frame.locator(mock.input)).toHaveCSS("outline-width", "2px");
    await frame.locator(mock.primary).hover();
    const color = await frame.locator(mock.primary).evaluate((element) => getComputedStyle(element).color);
    expect(color).toBe("rgb(255, 255, 255)");
    await page.screenshot({ path: testInfo.outputPath(`neutral-${mock.file}-desktop.png`) });
  }
});

test("wraps long Korean replies and sample tables without changing state or overflowing", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium");
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    for (const mock of mocks) {
      const frame = await openMock(page, mock.file);
      await frame.locator(mock.input).fill("현재 상태와 근거를 확인해 주세요. " + "long-unbroken-identifier".repeat(8));
      await expect(frame.locator(mock.input)).toBeFocused();
      await expect(frame.locator(mock.question)).toHaveCSS("background-color", "rgb(242, 242, 242)");
      const check = () => frame.locator(mock.stream).evaluate((element) =>
        element.scrollWidth <= element.clientWidth && document.documentElement.scrollWidth <= innerWidth,
      );
      expect(await check()).toBe(true);
      await page.screenshot({ path: testInfo.outputPath(`neutral-${mock.file}-${viewport.width}x${viewport.height}.png`) });
      if (mock.file === "deck-sources-v2.html") {
        await frame.locator("#ex-preview-controls > summary").click();
        await frame.locator(".ex-pattern-switcher > summary").click();
        await frame.getByRole("button", { name: "Markdown document", exact: true }).click();
        await frame.locator("#ex-preview-controls > summary").click();
        await expect(frame.locator(".ex-md-document table")).toBeVisible();
        await frame.locator(".ex-md-document table td").first().evaluate((element) => {
          element.textContent = "확인되지 않은 긴 리소스 식별자 / " + "identifier-without-spaces".repeat(6);
        });
        expect(await check()).toBe(true);
      }
    }
  }
});
