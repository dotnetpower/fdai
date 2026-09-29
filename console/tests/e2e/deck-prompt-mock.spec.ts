import { readFileSync } from "node:fs";

import { expect, test, type FrameLocator } from "@playwright/test";

import { openDeck, promptPath } from "./deck-mock-page";

// The run record shows the public synthetic prompt fixture inline under each captured model call.
// It never represents a captured runtime prompt and never blocks the conversation.
const prompt = readFileSync(promptPath, "utf8");
const promptTitle = prompt.split("\n")[0] ?? "";
const promptPattern = "**/assets/prompts/system-prompt.example.md";

async function openModelCall(frame: FrameLocator) {
  await frame.locator(".cs-run-record > summary").first().click();
  await frame.locator(".cs-model-trace-lane > details > summary").first().click();
  return frame.locator(".cs-model-trace-lane").first().locator(".cs-deck-prompt-file");
}

test.describe("Command deck synthetic prompt file", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "Desktop then constrained and mobile form one ordered scenario.");
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ reducedMotion: "reduce" });
  });

  test("opens the synthetic Markdown inline as read-only text with copy and download", async ({ page }) => {
    const { frame, errors } = await openDeck(page, { form: "answer", trace: "on" });
    const file = await openModelCall(frame);
    await expect(file.locator(":scope > summary")).toContainText("Synthetic example, not a captured prompt");
    await file.locator(":scope > summary").click();
    const lines = prompt.replace(/\r\n/g, "\n").trimEnd().split("\n").length;
    await expect(file.locator(".cs-deck-prompt-status")).toHaveText(`Markdown, ${lines} lines. Read-only text.`);
    await expect(file.locator(".cs-deck-code")).toContainText(promptTitle);
    await expect(file.locator(".cs-deck-code h1")).toHaveCount(0);
    const [download] = await Promise.all([page.waitForEvent("download"), file.getByRole("link", { name: /Download system-prompt/ }).click()]);
    expect(download.suggestedFilename()).toBe("system-prompt.example.md");
    await expect(frame.locator("dialog[open]")).toHaveCount(0);
    await expect(frame.locator("#ds-input")).toBeEnabled();
    expect(errors).toEqual([]);
  });

  test("keeps capture-off, not-captured, and failed states explicit", async ({ page }) => {
    let { frame } = await openDeck(page, { form: "answer" });
    await frame.locator(".cs-run-record > summary").first().click();
    await expect(frame.locator(".cs-model-trace-note")).toContainText("Provider trace capture is off");
    await expect(frame.locator(".cs-deck-prompt-file")).toHaveCount(0);

    await frame.locator("#ds-preview > summary").click();
    await frame.getByText("Capture model request and response trace", { exact: true }).click();
    await expect(frame.locator("#ds-trace")).toBeChecked();
    await expect(frame.locator(".cs-model-trace-note")).toContainText("Model trace not captured");
    await expect(frame.locator(".cs-deck-prompt-file")).toHaveCount(0);

    ({ frame } = await openDeck(page, { form: "answer", trace: "on" }));
    // Registered after the fixture server, so this handler answers the prompt request first.
    await page.route(promptPattern, (route) => route.fulfill({ status: 500, body: "unavailable" }));
    const file = await openModelCall(frame);
    await file.locator(":scope > summary").click();
    await expect(file.locator(".cs-deck-prompt-status")).toHaveText(
      "The prompt file could not be loaded. The redacted request above is still the record of this call.");
    await expect(file.locator(".cs-deck-code")).toHaveCount(0);
  });

  test("cancels a pending load when the file is closed", async ({ page }) => {
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => { release = resolve; });
    let requested = 0;
    const { frame } = await openDeck(page, { form: "answer", trace: "on" });
    await page.route(promptPattern, async (route) => {
      requested += 1;
      await held;
      await route.fulfill({ status: 200, body: prompt, contentType: "text/markdown" }).catch(() => {});
    });
    const file = await openModelCall(frame);
    await file.locator(":scope > summary").click();
    await expect(file.locator(".cs-deck-prompt-status")).toHaveText("Loading system-prompt.example.md...");
    await expect.poll(() => requested).toBe(1);
    await file.locator(":scope > summary").click();
    release();
    await page.waitForTimeout(200);
    await expect(file.locator(".cs-deck-code")).toHaveCount(0);
    await expect(file.locator(".cs-deck-prompt-status")).toHaveText("");
  });

  test("keeps the prompt file contained in constrained and mobile frames", async ({ page }) => {
    for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport);
      const { frame } = await openDeck(page, { form: "answer", trace: "on" });
      const file = await openModelCall(frame);
      await file.locator(":scope > summary").click();
      await expect(file.locator(".cs-deck-code")).toBeVisible();
      const contained = await file.evaluate((element) => {
        const box = element.getBoundingClientRect();
        const transcript = document.querySelector("#ds-transcript")!;
        return box.right <= transcript.getBoundingClientRect().right + 1
          && transcript.scrollWidth <= transcript.clientWidth
          && document.documentElement.scrollWidth <= innerWidth;
      });
      expect(contained).toBe(true);
    }
  });
});
