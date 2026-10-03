import { expect, test } from "@playwright/test";

import { openDeck } from "./deck-mock-page";

// The one Command deck keeps neutral, readable chat controls: the transcript shares its edges with
// the composer, and long Korean text or identifiers wrap without horizontal overflow.
const forms = [
  { form: "answer", scenario: "grounded" },
  { form: "incident", scenario: "open" },
];

test("uses neutral surfaces and aligned readable chat controls in every deck form", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const query of forms) {
    const { frame } = await openDeck(page, query);
    const surfaces = await frame.locator("#ds-workspace").evaluate((workspace) => {
      const bubble = getComputedStyle(workspace.querySelector(".cs-deck-user-bubble")!);
      const card = getComputedStyle(workspace).backgroundColor;
      const inner = workspace.querySelector(".cs-deck-transcript-inner")!;
      const innerStyle = getComputedStyle(inner);
      const box = inner.getBoundingClientRect();
      const grid = workspace.querySelector(".cs-deck-composer-grid")!.getBoundingClientRect();
      // The Answer form folds readiness into the readable evidence services summary.
      const strip = workspace.querySelector(".cs-deck-readiness, .ds-services > summary")!;
      const stripStyle = getComputedStyle(strip);
      const stripBox = strip.getBoundingClientRect();
      return {
        bubble: bubble.backgroundColor,
        bubbleBorder: bubble.borderTopStyle,
        card,
        left: box.left + parseFloat(innerStyle.paddingLeft),
        right: box.right - parseFloat(innerStyle.paddingRight),
        stripLeft: stripBox.left + parseFloat(stripStyle.paddingLeft),
        composerLeft: grid.left,
        composerRight: grid.right,
        overflow: document.documentElement.scrollWidth > innerWidth || inner.scrollWidth > inner.clientWidth,
      };
    });
    expect(surfaces.bubble).not.toBe(surfaces.card);
    expect(surfaces.bubbleBorder).toBe("none");
    expect(Math.abs(surfaces.left - surfaces.composerLeft)).toBeLessThanOrEqual(1);
    expect(Math.abs(surfaces.stripLeft - surfaces.composerLeft)).toBeLessThanOrEqual(1);
    // A classic scrollbar may take the transcript's right edge; the content never passes the composer.
    expect(surfaces.right).toBeLessThanOrEqual(surfaces.composerRight + 1);
    expect(surfaces.overflow).toBe(false);
    const input = frame.locator("#ds-input");
    await input.focus();
    await expect(input).toHaveCSS("outline-style", "solid");
    await expect(input).toHaveCSS("outline-width", "2px");
    await input.fill("Is anything else flagged?");
    const send = frame.locator("#ds-send");
    await expect(send).toBeEnabled();
    // The enabled state may ease in, so the color assertions retry until the transition settles.
    await expect(send).toHaveCSS("color", "rgb(255, 255, 255)");
    await expect(send).not.toHaveCSS("background-color", surfaces.card);
    await page.screenshot({ path: testInfo.outputPath(`neutral-deck-${query.form}-desktop.png`) });
  }
});

test("wraps long Korean text and identifiers in replies and tables without overflowing", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium");
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    const { frame } = await openDeck(page, { form: "memory", scenario: "document" });
    await frame.locator("#ds-input").fill("현재 상태와 근거를 확인해 주세요. " + "long-unbroken-identifier".repeat(8));
    await expect(frame.locator("#ds-input")).toBeFocused();
    await frame.locator(".cs-deck-user-line").evaluate((element) => {
      element.textContent = "현재 상태와 근거를 확인해 주세요. " + "long-unbroken-identifier".repeat(8);
    });
    await frame.locator(".cs-deck-document table td").first().evaluate((element) => {
      element.textContent = "확인되지 않은 긴 리소스 식별자 / " + "identifier-without-spaces".repeat(6);
    });
    const contained = await frame.locator("#ds-transcript").evaluate((element) =>
      element.scrollWidth <= element.clientWidth && document.documentElement.scrollWidth <= innerWidth);
    expect(contained).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`neutral-deck-${viewport.width}x${viewport.height}.png`) });
  }
});
