import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, type FrameLocator, type Page } from "@playwright/test";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const origin = "http://127.0.0.1:5373";
const promptPath = path.join(root, "mocks/ui/assets/prompts/system-prompt.example.md");
const prompt = readFileSync(promptPath, "utf8");
const promptPattern = "**/assets/prompts/system-prompt.example.md";

async function openMock(page: Page) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.clock.install();
  // Serve only repository UI fixtures in-process; no design server or external endpoint is needed.
  await page.route(`${origin}/**`, async (route) => {
    const pathname = decodeURIComponent(new URL(route.request().url()).pathname);
    const relative = pathname === "/" ? "/index.html" : pathname;
    const file = path.resolve(root, "." + relative);
    const allowed = file.startsWith(path.resolve(root) + path.sep)
      && (/\.(html|css|js|svg|png|woff2?)$/.test(file) || file === promptPath);
    if (!allowed) {
      await route.fulfill({ status: 404, body: "Not a public UI fixture." });
      return;
    }
    await route.fulfill({ path: file });
  });
  await page.goto(`${origin}/#mocks/ui/deck-sources-v2.html`);
  const frame = page.frameLocator("#preview-frame");
  await expect(frame.locator("#ex-workbench")).toHaveAttribute("data-stage", "complete");
  await expect(frame.locator("#ex-model-call")).toBeVisible();
  return frame;
}

async function viewPrompt(frame: FrameLocator) {
  if (!await frame.locator("#ex-model-call").evaluate((element: HTMLDetailsElement) => element.open)) {
    await frame.locator("#ex-model-call > summary").click();
  }
  await frame.getByRole("button", { name: /system-prompt\.example\.md/ }).click();
  return frame.getByRole("region", { name: "system-prompt.example.md", exact: true });
}

async function previewAction(frame: FrameLocator, name: string) {
  const controls = frame.locator("#ex-preview-controls");
  if (!await controls.evaluate((element: HTMLDetailsElement) => element.open)) {
    await controls.locator(":scope > summary").click();
  }
  if (name === "Compact answer" && !await frame.locator("#ex-demo-options").evaluate((element: HTMLDetailsElement) => element.open)) {
    await frame.locator("#ex-demo-options > summary").click();
  }
  await frame.getByRole("button", { name, exact: true }).click();
  await controls.locator(":scope > summary").click();
}

test.describe("Adaptive Markdown prompt preview", () => {
  test.describe.configure({ mode: "serial" });
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "Desktop then constrained/mobile form one ordered scenario.");
  });

  test("expands the synthetic Markdown inline without blocking chat or moving focus", async ({ page, context }, testInfo) => {
    const frame = await openMock(page);
    await expect(frame.locator("#ex-preview-controls")).not.toHaveAttribute("open", "");
    await expect(frame.locator(".ex-conversation-title")).toHaveText("API health-check investigation");
    const geometry = await frame.locator(".ex-thread").evaluate((element) => ({
      top: element.getBoundingClientRect().top,
      overflow: element.scrollWidth > element.clientWidth,
      answerTop: element.querySelector(".ex-stream-answer")!.getBoundingClientRect().top,
      modelTop: element.querySelector("#ex-model-call")!.getBoundingClientRect().top,
    }));
    expect(geometry.top).toBeLessThan(150);
    expect(geometry.overflow).toBe(false);
    expect(geometry.answerTop).toBeLessThan(geometry.modelTop);
    await expect(frame.locator("#ex-model-call")).not.toHaveAttribute("open", "");
    await page.screenshot({ path: testInfo.outputPath("focused-chat-desktop.png") });
    const panel = await viewPrompt(frame);
    await expect(panel).toBeVisible();
    await expect(frame.locator("dialog, [role='dialog'], [aria-modal='true']")).toHaveCount(0);
    await expect(frame.locator("#ex-model-call #ex-prompt-panel")).toHaveCount(1);
    await expect(panel).toHaveCSS("position", "static");
    await expect(frame.locator("#ex-open-prompt")).toHaveAttribute("aria-expanded", "true");
    await expect(panel.locator("#ex-prompt-source code")).toHaveText(prompt);
    await expect(panel).toContainText("not a captured runtime prompt");
    await expect(panel.locator("#ex-prompt-file-meta")).toContainText(`${prompt.trimEnd().split("\n").length} lines`);
    await expect(frame.locator("#ex-open-prompt")).toBeFocused();
    const input = frame.getByRole("textbox", { name: "Message", exact: true });
    await input.fill("A draft can be edited while the prompt is expanded.");
    await expect(input).toBeFocused();
    await expect(panel).toBeVisible();
    await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin });
    await panel.getByRole("button", { name: "Copy Markdown" }).click();
    await expect(panel.locator("#ex-prompt-feedback")).toHaveText("Markdown copied.");
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(prompt);
    const downloadEvent = page.waitForEvent("download");
    await panel.getByRole("link", { name: "Download .md" }).click();
    const download = await downloadEvent;
    expect(download.suggestedFilename()).toBe("system-prompt.example.md");
    const file = await download.path();
    expect(file).not.toBeNull();
    expect(readFileSync(file!, "utf8")).toBe(prompt);
    await page.screenshot({ path: testInfo.outputPath("prompt-markdown-desktop.png") });
    await page.keyboard.press("Escape");
    await expect(panel).not.toBeVisible();
    await expect(frame.locator("#ex-open-prompt")).toHaveAttribute("aria-expanded", "false");
    await expect(frame.locator("#ex-workbench")).toHaveAttribute("data-shell", "workspace");
    await expect(frame.locator("#ex-open-prompt")).toBeFocused();
    await expect(input).toHaveValue("A draft can be edited while the prompt is expanded.");
  });

  test("keeps model-free, not-captured, loading, and failed states distinct", async ({ page }) => {
    let promptRequests = 0;
    page.on("request", (request) => { if (request.url().endsWith("system-prompt.example.md")) promptRequests += 1; });
    const frame = await openMock(page);
    expect(promptRequests).toBe(0);
    await frame.locator("#ex-preview-controls > summary").click();
    await frame.locator("#ex-demo-options > summary").click();
    await frame.getByLabel("Prompt sample").selectOption("not-captured");
    await frame.locator("#ex-preview-controls > summary").click();
    await frame.locator("#ex-model-call > summary").click();
    await expect(frame.locator("#ex-open-prompt")).toBeDisabled();
    await expect(frame.locator("#ex-prompt-missing")).toContainText("No prompt was captured");
    expect(promptRequests).toBe(0);
    await frame.locator("#ex-preview-controls > summary").click();
    await frame.getByLabel("Prompt sample").selectOption("available");
    await frame.locator("#ex-preview-controls > summary").click();
    await page.route(promptPattern, (route) => route.fulfill({ status: 503, body: "Fixture unavailable" }));
    const panel = await viewPrompt(frame);
    await expect(panel.getByRole("alert")).toContainText("HTTP 503");
    await expect(panel.locator("#ex-prompt-source")).toBeHidden();
    await expect(panel.getByRole("button", { name: "Copy Markdown" })).toBeDisabled();
    await expect(panel.getByRole("link", { name: "Download .md" })).toBeHidden();
    await page.clock.runFor(6000);
    expect(promptRequests).toBe(1);
    await page.keyboard.press("Escape");
    await page.unroute(promptPattern);
    await previewAction(frame, "Compact answer");
    for (let i = 0; i < 30; i += 1) {
      if (await frame.locator("#ex-workbench").getAttribute("data-stage") === "compact") break;
      await page.clock.runFor(200);
    }
    await expect(frame.locator("#ex-workbench")).toHaveAttribute("data-stage", "compact");
    await expect(frame.locator("#ex-model-call")).toBeHidden();
    expect(promptRequests).toBe(1);
    await previewAction(frame, "Replay investigation");
    await expect(frame.locator("#ex-model-call")).toBeHidden();
    for (let i = 0; i < 60; i += 1) {
      if (await frame.locator("#ex-workbench").getAttribute("data-stage") === "complete") break;
      await page.clock.runFor(200);
    }
    await expect(frame.locator("#ex-model-call")).toBeVisible();
    await expect(frame.locator("#ex-open-prompt")).toBeEnabled();
  });

  test("bounds loading, ignores closed-view responses, and renders Markdown as inert text", async ({ page }) => {
    const frame = await openMock(page);
    let release: (() => void) | undefined;
    const held = new Promise<void>((resolve) => { release = resolve; });
    await page.route(promptPattern, async (route) => {
      await held;
      await route.fulfill({ contentType: "text/markdown", body: prompt });
    });
    const panel = await viewPrompt(frame);
    await expect(panel.locator("#ex-prompt-loading")).toBeVisible();
    await expect(panel.locator("#ex-prompt-loading")).toHaveAttribute("aria-busy", "true");
    await page.clock.runFor(5001);
    await expect(panel.getByRole("alert")).toContainText("timed out");
    await page.keyboard.press("Escape");
    release!();
    await page.unroute(promptPattern);
    const literal = "# Example\n\n<script>throw new Error('must remain text')</script>\n<img src=\"https://example.com/not-requested\">";
    await page.route(promptPattern, (route) => route.fulfill({ contentType: "text/markdown", body: literal }));
    await viewPrompt(frame);
    await expect(panel.locator("#ex-prompt-source code")).toHaveText(literal);
    await expect(panel.locator("#ex-prompt-source script, #ex-prompt-source img")).toHaveCount(0);
    await panel.getByRole("button", { name: "Collapse source" }).click();
    await expect(frame.locator("#ex-prompt-source code")).toHaveText("");
  });

  test("cancels loading when the containing LLM record is collapsed", async ({ page }) => {
    const frame = await openMock(page);
    let release: (() => void) | undefined;
    const held = new Promise<void>((resolve) => { release = resolve; });
    await page.route(promptPattern, async (route) => {
      await held;
      await route.fulfill({ contentType: "text/markdown", body: prompt });
    });
    const panel = await viewPrompt(frame);
    await expect(panel.locator("#ex-prompt-loading")).toBeVisible();
    await frame.locator("#ex-model-call > summary").click();
    await expect(frame.locator("#ex-open-prompt")).toHaveAttribute("aria-expanded", "false");
    await expect(panel).toBeHidden();
    release!();
    await page.unroute(promptPattern);
    await viewPrompt(frame);
    await expect(panel.locator("#ex-prompt-source code")).toHaveText(prompt);
    await frame.locator("#ex-open-prompt").click();
    await expect(panel).toBeHidden();
    await expect(frame.locator("#ex-prompt-source code")).toHaveText("");
    await expect(frame.getByRole("textbox", { name: "Message", exact: true })).toBeInViewport();
  });

  test("keeps the prompt file readable and contained in constrained and mobile chat frames", async ({ page }, testInfo) => {
    const frame = await openMock(page);
    const panel = await viewPrompt(frame);
    await expect(panel.locator("#ex-prompt-source code")).toHaveText(prompt);
    for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport);
      await page.clock.runFor(16);
      await expect.poll(() => panel.evaluate((element) => {
        const rect = element.getBoundingClientRect();
        const file = document.querySelector("#ex-open-prompt")!.getBoundingClientRect();
        return rect.left >= 0 && rect.right <= innerWidth && Math.abs(rect.top - file.bottom) <= 1;
      })).toBe(true);
      const widths = await panel.evaluate((element) => ({
        panel: element.scrollWidth <= element.clientWidth,
        source: element.querySelector("pre")!.scrollWidth <= element.querySelector("pre")!.clientWidth,
        fullSourceHeight: element.querySelector("pre")!.scrollHeight <= element.querySelector("pre")!.clientHeight + 1,
        document: document.documentElement.scrollWidth <= innerWidth,
      }));
      expect(widths.panel).toBe(true);
      expect(widths.source).toBe(true);
      expect(widths.fullSourceHeight).toBe(true);
      expect(widths.document).toBe(true);
      await expect(frame.getByRole("textbox", { name: "Message", exact: true })).toBeInViewport();
      await frame.locator("#ex-open-prompt").scrollIntoViewIfNeeded();
      await page.screenshot({ path: testInfo.outputPath(`prompt-markdown-${viewport.width}x${viewport.height}.png`) });
    }
    await panel.locator("#ex-prompt-source").focus();
    await page.keyboard.press("Escape");
    await expect(frame.locator("#ex-open-prompt")).toBeFocused();
    await page.setViewportSize({ width: 1440, height: 900 });
    await viewPrompt(frame);
    await expect(panel.locator("#ex-prompt-source code")).toHaveText(prompt);
  });
});
