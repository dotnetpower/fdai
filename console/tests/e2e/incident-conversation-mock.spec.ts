import { fileURLToPath, pathToFileURL } from "node:url";

import { expect, test, type FrameLocator, type Page } from "@playwright/test";

const shellUrl = pathToFileURL(fileURLToPath(new URL("../../../index.html", import.meta.url))).href;
const mockRoute = "#mocks/ui/incident-conversation.html";

async function openIncident(page: Page, section = "") {
  await page.goto("about:blank");
  await page.goto(`${shellUrl}${mockRoute}${section ? `::${section}` : ""}`);
  const frame = page.frameLocator("#preview-frame");
  await expect(frame.getByRole("heading", { level: 1 })).toHaveText("Command deck");
  await expect(frame.locator("body")).toHaveClass(/cs-embedded/);
  return frame;
}

async function expectNoOverflow(page: Page, frame: FrameLocator) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const dimensions = await frame.locator(".ic-page").evaluate((element) => {
    const transcript = element.querySelector(".ic-scroll")!;
    const answer = element.querySelector(".ic-answer")!;
    return {
      document: document.documentElement.scrollWidth <= innerWidth,
      transcript: transcript.scrollWidth <= transcript.clientWidth,
      answer: answer.scrollWidth <= answer.clientWidth,
      header: element.querySelector(".ic-header")!.getBoundingClientRect().top,
      composer: element.querySelector(".ic-composer")!.getBoundingClientRect().bottom,
      height: innerHeight,
    };
  });
  expect(dimensions.document).toBe(true);
  expect(dimensions.transcript).toBe(true);
  expect(dimensions.answer).toBe(true);
  expect(dimensions.header).toBe(0);
  expect(dimensions.composer).toBeLessThanOrEqual(dimensions.height + 1);
}

test.describe("incident reply inside Command Deck", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "The desktop scenario owns the ordered viewport sequence.");
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ reducedMotion: "reduce" });
  });

  test("keeps all incident content inside the assistant turn with honest, scannable state", async ({ page }, testInfo) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const frame = await openIncident(page);
    const answer = frame.getByRole("article", { name: "Bragi incident response" });
    await expect(frame.getByRole("tablist")).toHaveCount(0);
    await expect(frame.locator(".ic-header #incident-title")).toHaveCount(0);
    await expect(frame.locator(".ic-messages > article")).toHaveCount(2);
    await expect(frame.locator(".ic-messages > article").first()).toHaveAccessibleName("Operator question");
    await expect(answer.locator("#incident-title")).toHaveText("Operational alert route unresolved");
    for (const selector of [".ic-state-line", ".ic-facts", ".ic-next-step", "#incident-timeline", "#incident-evidence", "#analysis-details"]) {
      await expect(answer.locator(selector)).toHaveCount(1);
    }
    await expect(answer.getByText("Open at last record", { exact: true })).toBeInViewport();
    await expect(answer.getByText("Current status unknown", { exact: true })).toBeInViewport();
    await expect(answer.locator(".ic-freshness")).toContainText("Historical evidence");
    await expect(answer.locator(".ic-freshness")).toContainText("Not live");
    await expect(answer.locator(".ic-facts")).toContainText("Response ownerNot recorded");
    await expect(answer.locator(".ic-facts")).toContainText("Delivery / recoveryNot verified");
    await expect(answer.getByText("Notification routing; service / environment unknown")).toBeInViewport();
    await expect(answer.locator(".ic-facts a")).toHaveCount(0);
    await expect(answer.locator(".ic-lead")).toHaveCSS("font-size", "16px");
    await expect(answer.locator(".ic-facts dd").first()).toHaveCSS("font-size", "14px");
    await expect(answer.getByRole("link", { name: "Review routing evidence" })).toBeInViewport();
    for (const id of ["incident-timeline", "incident-evidence", "analysis-details"]) {
      await expect(answer.locator(`#${id}`)).not.toHaveAttribute("open", "");
    }
    for (const id of ["routing-evidence", "impact-gaps", "ownership-gap", "receipt-gap", "verification-checklist", "audit-68882"]) {
      await expect(answer.locator(`#incident-evidence #${id}`)).toHaveCount(1);
      await expect(answer.locator(`#${id}`)).toBeHidden();
    }
    await expectNoOverflow(page, frame);
    const presentation = await answer.evaluate((element) => {
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = 1;
      const context = canvas.getContext("2d", { willReadFrequently: true })!;
      const luminance = (color: string) => {
        context.fillStyle = "#fff";
        context.fillRect(0, 0, 1, 1);
        context.fillStyle = color;
        context.fillRect(0, 0, 1, 1);
        const channels = Array.from(context.getImageData(0, 0, 1, 1).data).slice(0, 3)
          .map((value) => value / 255)
          .map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
        return channels.reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index]!, 0);
      };
      const colors = [".ic-state", ".ic-severity", ".ic-current-state", ".ic-facts dd", ".ic-answer-actions .is-primary"]
        .map((selector) => {
          const style = getComputedStyle(element.querySelector(selector)!);
          const foreground = luminance(style.color);
          const background = luminance(style.backgroundColor);
          return { selector, ratio: (Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05) };
        });
      return {
        colors,
        rows: [...element.querySelectorAll(".ic-facts > div")].map((row) => ({
          left: row.getBoundingClientRect().left,
          top: row.getBoundingClientRect().top,
          valueLeft: row.querySelector("dd")!.getBoundingClientRect().left,
        })),
      };
    });
    for (const color of presentation.colors) {
      expect(color.ratio, `${color.selector} text contrast`).toBeGreaterThanOrEqual(4.5);
    }
    expect(new Set(presentation.rows.map((row) => row.left)).size).toBe(1);
    expect(new Set(presentation.rows.map((row) => row.valueLeft)).size).toBe(1);
    expect(new Set(presentation.rows.map((row) => row.top)).size).toBe(4);
    await page.screenshot({ path: testInfo.outputPath("incident-chat-1440x900.png") });

    await answer.getByRole("link", { name: "View evidence gaps" }).click();
    await expect(answer.locator("#impact-gaps")).toBeFocused();
    await expect(answer.locator("#ownership-gap")).toBeVisible();
    await answer.getByRole("link", { name: "Review routing evidence" }).click();
    await expect(answer.locator("#incident-evidence")).toHaveAttribute("open", "");
    await expect(answer.locator("#routing-evidence")).toBeFocused();
    await expect(answer.getByRole("heading", { name: "Routing evidence", exact: true })).toBeInViewport();
    await answer.locator("#routing-evidence").getByRole("link", { name: "audit:68882" }).click();
    await expect(answer.locator("#audit-68882")).toHaveAttribute("open", "");
    await expect(answer.locator("#audit-68882 summary")).toBeFocused();
    await expect(answer.locator("#audit-68882")).toContainText("No current binding readback, delivery receipt, or recovery observation");
    await expect(answer.locator("#incident-title")).not.toBeInViewport();
    await expect(frame.getByRole("heading", { name: "Command deck", exact: true })).toBeInViewport();
    await expectNoOverflow(page, frame);

    await answer.locator(".ic-severity").click();
    await expect(answer.locator("#severity-evidence")).toBeFocused();
    await expect(answer.locator("#severity-evidence")).toContainText("The basis for that severity");
    const timeline = answer.locator("#incident-timeline");
    await timeline.locator(":scope > summary").focus();
    await page.keyboard.press("Enter");
    await expect(timeline).toHaveAttribute("open", "");
    await expect(timeline.locator(".ic-timeline > li")).toHaveCount(3);
    await expect(timeline.locator(".ic-window-note")).toContainText("3m 45s");
    const timestamps = await timeline.locator("time").evaluateAll((elements) =>
      elements.map((element) => Date.parse(element.getAttribute("datetime")!)),
    );
    expect((Math.max(...timestamps) - Math.min(...timestamps)) / 1000).toBe(225);
    await expect(timeline.getByRole("heading", { name: "No later observation in this snapshot" })).toBeVisible();
    await page.keyboard.press("Space");
    await expect(timeline).not.toHaveAttribute("open", "");
    await expect(timeline.locator(":scope > summary")).toBeFocused();
    const analysis = answer.locator("#analysis-details");
    await analysis.locator("summary").click();
    await expect(analysis).toHaveAttribute("open", "");
    await expect(analysis).toContainText("not incident resolution");
    expect(errors).toEqual([]);
  });

  test("appends local preview questions without requests, markup injection, or changes to the answer", async ({ page }) => {
    const frame = await openIncident(page);
    const answer = frame.locator(".ic-answer");
    const originalAnswer = await answer.innerText();
    const requests: string[] = [];
    page.on("request", (request) => requests.push(request.url()));
    const input = frame.getByRole("textbox", { name: /Ask about this incident/ });
    await input.fill("   ");
    await frame.getByRole("button", { name: "Preview question" }).click();
    await expect(frame.locator(".ic-preview-question")).toHaveCount(0);
    expect(await input.evaluate((element: HTMLTextAreaElement) => element.validationMessage)).toBe("Enter a question to preview.");
    await input.fill('<img src="https://example.com/not-requested" onerror="alert(1)">');
    await page.keyboard.press("Shift+Enter");
    await expect(frame.locator(".ic-preview-question")).toHaveCount(0);
    await frame.getByRole("button", { name: "Preview question" }).click();
    await expect(frame.locator(".ic-preview-question")).toHaveCount(1);
    await expect(frame.locator(".ic-preview-question img")).toHaveCount(0);
    await expect(frame.locator(".ic-preview-question")).toContainText('<img src="https://example.com/not-requested"');
    await expect(frame.getByRole("status")).toContainText("No request was sent");
    await expect(input).toBeFocused();
    await expect(input).toHaveValue("");
    await input.fill("Which recovery evidence is still missing?");
    await page.keyboard.press("Enter");
    await expect(frame.locator(".ic-messages > article")).toHaveCount(4);
    await expect(frame.locator(".ic-messages > article").last()).toHaveClass("ic-preview-question");
    expect(await answer.innerText()).toBe(originalAnswer);
    await expectNoOverflow(page, frame);
    expect(requests).toEqual([]);
  });

  test("preserves the chat flow at constrained and mobile sizes and opens nested source links", async ({ page }, testInfo) => {
    const frame = await openIncident(page);
    await expectNoOverflow(page, frame);
    for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport);
      await frame.locator(".ic-scroll").evaluate((element) => { element.scrollTop = 0; });
      await expect(frame.locator("#incident-title")).toBeInViewport();
      await expectNoOverflow(page, frame);
      await page.screenshot({ path: testInfo.outputPath(`incident-chat-${viewport.width}x${viewport.height}.png`) });
      await frame.getByRole("link", { name: "What would confirm recovery?" }).click();
      await expect(frame.locator("#verification-checklist")).toBeFocused();
      await expect(frame.getByRole("heading", { name: "What would confirm recovery?" })).toBeInViewport();
      await expect(frame.locator("#verification-checklist")).toContainText("Dispatch alone is not success");
      await expectNoOverflow(page, frame);
      await frame.locator("#incident-evidence > summary").click();
      await expect(frame.locator("#incident-evidence")).not.toHaveAttribute("open", "");
      if (viewport.width === 390) {
        const targetHeights = await frame.locator('.ic-answer > details > summary, .ic-answer-actions a, .ic-facts-source, .ic-severity, .ic-composer button')
          .evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().height));
        expect(targetHeights.every((height) => height >= 44)).toBe(true);
        await frame.locator("#incident-title").evaluate((element) => {
          element.textContent = "운영 알림 경로 해석 실패 / Operational notification routing investigation";
        });
        await frame.locator(".ic-facts dd").first().evaluate((element) => {
          element.textContent = "영향 서비스와 환경 미확인 / " + "long-unbroken-identifier".repeat(8);
        });
        await frame.locator(".ic-scroll").evaluate((element) => { element.scrollTop = 0; });
        await expectNoOverflow(page, frame);
        await frame.locator("#incident-question").fill("현재 인시던트의 영향 범위와 복구 증거를 확인해 주세요. " + "long-unbroken-identifier".repeat(12));
        await frame.getByRole("button", { name: "Preview question" }).click();
        await expect(frame.locator(".ic-preview-question")).toHaveCount(1);
        await expectNoOverflow(page, frame);
        await page.screenshot({ path: testInfo.outputPath("incident-chat-mobile-long-content.png") });
      }
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    await openIncident(page);
    await expectNoOverflow(page, frame);
    await expect(frame.getByRole("link", { name: "Review routing evidence" })).toBeInViewport();
    await openIncident(page, "audit-68882");
    await expect(frame.locator("#incident-evidence")).toHaveAttribute("open", "");
    await expect(frame.locator("#audit-68882")).toHaveAttribute("open", "");
    await expect(frame.locator("#audit-68882 summary")).toBeFocused();
    await expectNoOverflow(page, frame);
  });
});
