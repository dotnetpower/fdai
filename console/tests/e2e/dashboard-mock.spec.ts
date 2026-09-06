import { fileURLToPath, pathToFileURL } from "node:url";

import { expect, test } from "@playwright/test";

const shell = pathToFileURL(fileURLToPath(new URL("../../../index.html", import.meta.url))).href;

test("keeps executive Dashboard evidence and chart values separate from the resource snapshot", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "One scenario checks desktop before constrained and mobile.");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(`${shell}#mocks/ui/dashboard.html`);
  const frame = page.frameLocator("#preview-frame");
  const heading = frame.getByRole("heading", { level: 1 });
  await expect(heading).toBeVisible();
  await expect(heading.locator(".cs-page-title-current")).toHaveText("Dashboard");
  await expect(frame.locator("body")).toHaveAttribute("data-chat-theme", "clear-neutral");
  await expect(frame.locator(".cs-readonly-banner")).toContainText("Synthetic preview.");
  await expect(frame.locator(".cs-readonly-banner")).toContainText("No runtime reads, approvals, promotion, or resource actions.");
  await expect(frame.getByRole("link", { name: "Resource dashboard", exact: true })).toHaveAttribute("href", "dashboard-v2.html");
  await expect(frame.locator("#resource-count, #resource-summary, #historical-performance")).toHaveCount(0);
  const posture = frame.locator("a.ow-metric").filter({ hasText: "Executive operating posture" });
  const outcomes = frame.locator(".ow-dashboard-outcomes");
  const values = ["73%", "13.3", "15m", "48m", "Unavailable"];
  await expect(posture).toContainText("73% auto-resolution");
  await expect(posture).toContainText("Policy escapes unavailable / Operational health unknown");
  await expect(posture).toHaveAttribute("href", "operating-outcomes.html#auto-resolution");
  await expect(outcomes.locator(".ow-metric > strong")).toHaveText(values);
  await expect(outcomes.locator("small")).toHaveText([
    "Baseline 65% / Higher is better", "Baseline 26.7 / Lower is better",
    "Baseline 26m / Lower is better", "Baseline 98m / Lower is better", "Attribution not connected",
  ]);
  expect(await outcomes.locator("a").evaluateAll((links) => links.map((link) => link.getAttribute("href")))).toEqual([
    "operating-outcomes.html#auto-resolution", "operating-outcomes.html#human-touchpoints",
    "operating-outcomes.html#mttr", "operating-outcomes.html#change-lead-time",
    "operating-outcomes.html#cost-per-resolved-event",
  ]);
  await expect(frame.locator(".ow-provenance")).toContainText("30-day window / 30 events");
  await expect(frame.locator(".ow-provenance")).toContainText("Confidence unavailable");
  await expect(frame.locator(".ow-provenance")).toContainText("Source: example-autonomy / 2026-07-22T15:18:00Z");
  await expect(frame.locator(".ow-provenance")).toContainText("Paired baseline available");
  await expect(frame.locator(".ow-provenance a")).toHaveCount(1);
  await expect(frame.locator(".ow-provenance a")).toHaveAttribute("href", "operating-outcomes.html");
  await expect(frame.locator("body")).toHaveCSS("background-color", "rgb(255, 255, 255)");
  await expect(posture).toHaveCSS("background-color", "rgb(255, 255, 255)");
  await expect(posture).toHaveCSS("box-shadow", "none");
  const unavailable = outcomes.locator("a").last();
  await expect(unavailable).toHaveCSS("box-shadow", "none");
  await expect(unavailable.locator("strong")).toHaveCSS("color", "rgb(38, 38, 38)");
  await expect(unavailable).not.toHaveAttribute("aria-disabled", "true");
  const chartData = await frame.locator(".js-chartable").evaluateAll((elements) =>
    elements.map((element) => JSON.parse(element.getAttribute("data-chart-rows")!)),
  );
  expect(chartData).toEqual([
    [["T0", "22"], ["T1", "6"], ["T2", "2"]],
  ]);
  await expect(frame.locator(".js-chartable")).toHaveAttribute("data-chart-source", "Synthetic example-autonomy, 30 days.");
  await expect(frame.getByRole("navigation", { name: "Tier evidence" }).locator("a")).toHaveText(["T0 22 / 73%", "T1 6 / 20%", "T2 2 / 7%"]);
  const controlLinks = frame.getByRole("navigation", { name: "Control evidence" }).locator("a");
  await expect(controlLinks).toHaveText(["Auto 22", "Approval 2", "Held 5", "Denied 1"]);
  expect(await controlLinks.evaluateAll((links) => links.map((link) => link.getAttribute("href")))).toEqual([
    "audit.html?window=30d&outcome=auto", "audit.html?window=30d&outcome=hil",
    "audit.html?window=30d&outcome=abstain", "audit.html?window=30d&outcome=deny",
  ]);
  const segmentShares = await frame.locator(".cs-stackbar").evaluateAll((bars) => bars.map((bar) =>
    [...bar.children].map((segment) => (segment as HTMLElement).style.width),
  ));
  expect(segmentShares).toEqual([["73.33%", "20%", "6.67%"], ["73.33%", "6.67%", "16.67%", "3.33%"], ["80%", "20%"]]);
  const evidence = frame.locator(".ow-disclosure");
  await expect(evidence).not.toHaveAttribute("open", "");
  await page.screenshot({ path: testInfo.outputPath("dashboard-neutral-desktop.png") });
  await evidence.locator(":scope > summary").focus();
  await page.keyboard.press("Enter");
  await expect(evidence).toHaveAttribute("open", "");
  await expect(evidence.locator(".ow-metric").first()).toHaveAttribute("href", "audit.html?from_seq=1&through_seq=30");
  await expect(evidence.locator(".ow-metric > strong")).toHaveText(["30", "61 active"]);
  await expect(evidence.getByRole("link", { name: /Living rules/ })).toHaveAttribute("href", "rules.html");
  await expect(evidence.locator("table").first().locator("tbody td")).toHaveText(["Observe", "24", "Remediation PR", "6"]);
  await expect(evidence.locator("table").last().locator("tbody td")).toHaveText(["Auto", "22", "Held", "5", "Approval", "2", "Denied", "1"]);
  await expect(evidence).toContainText("Broker acceptance and an API success do not prove an operational outcome.");
  const approvals = frame.locator(".ow-metric[href='hil.html?status=pending']");
  await expect(approvals).toContainText("Approval queue");
  await expect(approvals.locator("strong")).toHaveText("2");
  await approvals.focus();
  await expect(approvals).toHaveCSS("outline-width", "2px");
  await expect(frame.locator(".ow-metric[href='control-assurance.html#promotion-guards'] strong")).toHaveText("Unavailable");
  await expect(frame.locator(".ow-metric[href='promotion.html'] strong")).toHaveText("Unavailable");
  await expect(frame.locator(".ow-metric[href^='verticals.html#'] small")).toHaveText([
    "10 auto-resolved / 1 open risk / $0 monthly savings",
    "8 auto-resolved / 2 open risks / $0 monthly savings",
    "4 auto-resolved / 3 open risks / $0 monthly savings",
  ]);

  for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await frame.locator("body").evaluate(() => scrollTo(0, 0));
    const geometry = await frame.locator("main").evaluate((element) => ({
      document: document.documentElement.scrollWidth <= innerWidth,
      main: element.scrollWidth <= element.clientWidth,
      cards: [...element.querySelectorAll(".ow-metric,.ov-panel")]
        .every((card) => card.scrollWidth <= card.clientWidth),
    }));
    expect(geometry).toEqual({ document: true, main: true, cards: true });
    await page.screenshot({ path: testInfo.outputPath(`dashboard-neutral-${viewport.width}x${viewport.height}.png`) });
    if (viewport.width === 390) {
      const heights = await evidence.locator(".ow-metric").evaluateAll((links) =>
        links.map((link) => link.getBoundingClientRect().height),
      );
      expect(heights).toHaveLength(2);
      expect(heights.every((height) => height >= 44)).toBe(true);
      await frame.locator(".ow-provenance > span").last().evaluate((element) => {
        element.textContent = "긴 운영 대상 식별자 / " + "long-identifier".repeat(10);
      });
      expect(await frame.locator("main").evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    }
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(outcomes.locator(".ow-metric > strong")).toHaveText(values);
  expect(errors).toEqual([]);
});
