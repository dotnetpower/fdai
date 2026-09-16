import { expect, type FrameLocator } from "@playwright/test";

export const governanceRoutes = [
  "architecture", "ontology", "handover", "rules", "workflow-builder", "capabilities",
  "skills", "blast-radius", "promotion", "context-selection-comparisons", "scope", "observation-affinity",
];

/** Measure the actual embedded Governance surface, not a surrogate gallery class. */
export async function inspectGovernance(frame: FrameLocator) {
  return frame.locator("main").evaluate((main) => {
    const bodyStyle = getComputedStyle(document.body);
    const visible = (element: Element) => {
      const closed = element.closest("details:not([open])");
      if (closed && !closed.querySelector(":scope > summary")?.contains(element)) return false;
      const box = element.getBoundingClientRect();
      return box.width > 1 && box.height > 1 && getComputedStyle(element).visibility !== "hidden";
    };
    const regions = [...main.querySelectorAll(".fg-workbench, .fg-detail, .fg-section, .fg-toolbar, .ontology-view, .ontology-semantic-workbench, .cp-section, .oa-workbench")]
      .filter(visible);
    const controls = [...main.querySelectorAll("button, select, input:not([type=hidden]), summary")].filter(visible);
    const headerCopy = main.querySelector(":scope > header > div:first-child, :scope > .cs-page-header > div:first-child");
    let headerSlack = 0;
    if (headerCopy) {
      const range = document.createRange();
      range.selectNodeContents(headerCopy);
      headerSlack = headerCopy.getBoundingClientRect().height - range.getBoundingClientRect().height;
    }
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 1;
    const context = canvas.getContext("2d", { willReadFrequently: true })!;
    const rgba = (value: string) => {
      context.clearRect(0, 0, 1, 1);
      context.fillStyle = value;
      context.fillRect(0, 0, 1, 1);
      return [...context.getImageData(0, 0, 1, 1).data];
    };
    const luminance = (color: number[]) => color.slice(0, 3)
      .map((value) => {
        const channel = value / 255;
        return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
      }).reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index]!, 0);
    const background = (element: Element) => {
      let current: Element | null = element;
      while (current) {
        const color = rgba(getComputedStyle(current).backgroundColor);
        if (color[3] === 255) return color;
        current = current.parentElement;
      }
      return [255, 255, 255, 255];
    };
    const text = [...main.querySelectorAll("*")]
      .filter((element) => element instanceof HTMLElement && !element.matches("script, style, option, noscript") && visible(element))
      .filter((element) => [...element.childNodes].some((node) => node.nodeType === Node.TEXT_NODE && node.textContent?.trim()))
      .map((element) => {
        const style = getComputedStyle(element);
        const fg = luminance(rgba(style.color));
        const bg = luminance(background(element));
        const size = Number.parseFloat(style.fontSize);
        const large = size >= 24 || (size >= 18.66 && Number.parseInt(style.fontWeight) >= 700);
        return {
          text: element.textContent?.trim().slice(0, 60), tag: element.tagName,
          className: element.className, size,
          contrast: (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05),
          minimum: large ? 3 : 4.5,
        };
      });
    return {
      viewport: [innerWidth, innerHeight],
      theme: { background: bodyStyle.backgroundColor, text: bodyStyle.color, accent: bodyStyle.getPropertyValue("--cs-steel").trim() },
      documentFits: document.documentElement.scrollWidth <= innerWidth,
      mainFits: main.scrollWidth <= main.clientWidth + 1,
      overflowingRegions: regions.filter((element) => element.scrollWidth > element.clientWidth + 1).map((element) => element.className),
      overflowingChildren: regions.flatMap((region) => [...region.querySelectorAll("*")].filter((element) => visible(element)
        && !element.closest(".gw-table-scroll")
        && element.getBoundingClientRect().right > region.getBoundingClientRect().right + 1)
        .slice(0, 8).map((element) => ({ region: region.className, child: element.className || element.tagName, text: element.textContent?.trim().slice(0, 40), width: element.getBoundingClientRect().width }))),
      clippedControls: controls.filter((element) => element.matches("button, summary") && (element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1))
        .map((element) => ({ text: element.textContent?.trim().slice(0, 60), className: element.className })),
      smallTargets: controls.filter((element) => {
        const box = element.getBoundingClientRect();
        return (box.width < 24 || box.height < 24) && !element.matches("input[type=checkbox],input[type=radio]");
      }).map((element) => element.textContent?.trim().slice(0, 60)),
      contrastFailures: text.filter((item) => item.contrast + 0.01 < item.minimum),
      microText: text.filter((item) => item.size < 12 && item.text),
      heading: getComputedStyle(main.querySelector("h1")!).fontSize,
      headerSlack,
    };
  });
}

export async function expectGovernance(frame: FrameLocator, headingSize = "24px") {
  await expect(frame.locator("main")).toHaveAttribute("data-governance-ready", "true");
  if (await frame.locator("#ontology-picker").count()) {
    await expect(frame.locator("main")).toHaveAttribute("data-affinity-ready", "true");
  }
  await expect(frame.locator("body")).toHaveCSS("background-color", "rgb(255, 255, 255)");
  const result = await inspectGovernance(frame);
  expect(result.theme).toEqual({ background: "rgb(255, 255, 255)", text: "rgb(38, 38, 38)", accent: "#2563eb" });
  expect(result.documentFits, JSON.stringify(result)).toBe(true);
  expect(result.mainFits, JSON.stringify(result)).toBe(true);
  expect(result.overflowingRegions, JSON.stringify(result.overflowingChildren)).toEqual([]);
  expect(result.clippedControls).toEqual([]);
  expect(result.smallTargets).toEqual([]);
  expect(result.contrastFailures).toEqual([]);
  expect(result.microText).toEqual([]);
  expect(result.heading).toBe(headingSize);
  if (headingSize === "24px") expect(result.headerSlack).toBeLessThanOrEqual(48);
  return result;
}

/** Exercise each authored selection without issuing any resource or permission operation. */
export async function exerciseGovernance(frame: FrameLocator) {
  for (const control of await frame.locator("[data-fg-select]").all()) {
    if (!(await control.isVisible())) continue;
    await control.click();
    await expect(control).toHaveAttribute("aria-pressed", "true");
    const panelId = await control.getAttribute("aria-controls");
    expect(panelId).toBeTruthy();
    await expect(frame.locator(`[id="${panelId}"]`)).toBeVisible();
    await expectGovernance(frame);
  }
  for (const control of await frame.locator("[data-oversight-agent]").all()) {
    await control.click();
    await expect(control).toHaveAttribute("aria-pressed", "true");
    await expect(frame.locator("[data-oversight-name]")).toHaveText((await control.getAttribute("data-name"))!);
    await expectGovernance(frame);
  }
  for (const control of await frame.locator("[data-architecture-lens]").all()) {
    await control.click();
    await expect(control).toHaveAttribute("aria-selected", "true");
    await expectGovernance(frame);
  }
  const model = frame.locator('[data-ontology-tab="map"]');
  if (await model.count()) {
    await model.click();
    for (const control of await frame.locator("[data-ontology-node]").all()) {
      await control.click();
      await expect(control).toHaveAttribute("aria-pressed", "true");
      await expectGovernance(frame);
    }
    for (const control of await frame.locator("[data-ontology-lens]").all()) {
      await control.click();
      await expect(control).toHaveAttribute("aria-pressed", "true");
      await expectGovernance(frame);
    }
  }
  for (const tab of await frame.locator("[data-ontology-tab]").all()) {
    await tab.click();
    await expect(tab).toHaveAttribute("aria-current", "page");
    if (await tab.getAttribute("data-ontology-tab") === "instances") {
      await expect(
        frame.frameLocator(".flow-ontology-embed").locator("body"),
      ).toHaveClass(/is-embedded/);
    }
    await expectGovernance(frame);
  }
  for (const disclosure of await frame.locator("details").all()) {
    if (!(await disclosure.isVisible())) continue;
    if (await disclosure.getAttribute("open") === null) await disclosure.locator(":scope > summary").click();
    await expectGovernance(frame);
  }
  for (const search of await frame.locator('[data-fg-filter-key="search"]').all()) {
    const catalog = frame.locator('[data-fg-select="rules"][data-fg-value="catalog"]');
    if (await catalog.count()) await catalog.click();
    await search.fill("no-matching-synthetic-record");
    await expect(frame.locator("[data-fg-filter-empty]:visible")).toHaveCount(1);
    await expectGovernance(frame);
    await search.fill("");
  }
}
