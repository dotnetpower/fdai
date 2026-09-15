/** Numeric local-browser observations, not screen-reader or live operational evidence. */
import { expect, type Locator, type Page, type TestInfo } from "@playwright/test";
import { writeFile } from "node:fs/promises";

/** Retain numeric evidence even when the list reporter does not persist in-memory attachments. */
export async function recordUiEvidence(info: TestInfo, name: string, value: unknown) {
  const path = info.outputPath(`${name}.json`);
  await writeFile(path, JSON.stringify(value, null, 2));
  await info.attach(name, { path, contentType: "application/json" });
}

/** Measure visible region descendants against their composited backgrounds and retained bounds. */
export async function measureHandoverPanel(panel: Locator, info: TestInfo, label: string) {
  const result = await panel.evaluate((root) => {
    const rgba = (value: string) => {
      const channels = value.match(/[\d.]+/g)!.map(Number);
      return value.startsWith("color(srgb") ? channels.map((value, index) => index < 3 ? value * 255 : value) : channels;
    };
    const composite = (color: number[], base: number[]) => base.map((value, index) =>
      color[index]! * (color[3] ?? 1) + value * (1 - (color[3] ?? 1)));
    const background = (element: Element | null) => {
      const ancestors: Element[] = [];
      for (let current = element; current; current = current.parentElement) ancestors.unshift(current);
      return ancestors.reduce((base, current) => composite(rgba(getComputedStyle(current).backgroundColor), base), [255, 255, 255]);
    };
    const luminance = (rgb: number[]) => {
      const values = rgb.map((channel) => channel / 255 <= .04045 ? channel / 255 / 12.92 : ((channel / 255 + .055) / 1.055) ** 2.4);
      return values[0]! * .2126 + values[1]! * .7152 + values[2]! * .0722;
    };
    const contrast = (color: number[], base: number[]) => {
      const first = luminance(composite(color, base)), second = luminance(base);
      return (Math.max(first, second) + .05) / (Math.min(first, second) + .05);
    };
    const bounds = root.getBoundingClientRect();
    const elements = [...root.querySelectorAll<HTMLElement>("h3,h4,h5,p,dt,dd,li,legend,code,pre,span,a,summary,button,input,select,textarea")]
      .filter((element) => element.checkVisibility() && !element.closest('.sr-only,[aria-hidden="true"]'));
    const rows = elements.map((element) => {
      const style = getComputedStyle(element), rect = element.getBoundingClientRect();
      const control = element.matches("button,input,select,textarea,a,summary");
      const input = element.matches("button,input,select,textarea");
      const text = control || [...element.childNodes].some((node) => node.nodeType === Node.TEXT_NODE && node.textContent?.trim());
      const threshold = parseFloat(style.fontSize) >= 24 || (parseFloat(style.fontSize) >= 18.66 && Number(style.fontWeight) >= 700) ? 3 : 4.5;
      return { tag: element.tagName, id: element.id, name: (element.getAttribute("aria-label") ?? element.textContent ?? "").slice(0, 90),
        control, input, disabled: element.matches(":disabled"), text, fontSize: parseFloat(style.fontSize), threshold,
        textContrast: contrast(rgba(style.color), background(element)),
        borderContrast: input ? contrast(rgba(style.borderTopColor), background(element.parentElement)) : null,
        focused: element.matches(":focus-visible"), focusContrast: contrast(rgba(style.outlineColor), background(element.parentElement)),
        outlineStyle: style.outlineStyle, outlineWidth: parseFloat(style.outlineWidth),
        width: rect.width, height: rect.height,
        clippedControl: input && element.tagName !== "TEXTAREA" && element.clientHeight + 1 < parseFloat(style.lineHeight) + parseFloat(style.paddingTop) + parseFloat(style.paddingBottom),
        outside: rect.left < bounds.left - 1 || rect.right > bounds.right + 1,
        overflow: !element.matches("input,select,textarea") && element.clientWidth > 0 && element.scrollWidth > element.clientWidth + 1,
      };
    });
    return { viewport: { width: innerWidth, height: innerHeight }, panelWidth: bounds.width,
      documentOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      mainOverflow: [...document.querySelectorAll("main")].some((element) => element.scrollWidth > element.clientWidth),
      panelOverflow: root.scrollWidth > root.clientWidth, rows };
  });
  await recordUiEvidence(info, label, result);
  return result;
}

/** Check the declared region geometry and contrast, retaining numeric evidence before assertions. */
export async function assertHandoverGeometry(panel: Locator, info: TestInfo, label: string, contrast = true) {
  const result = await measureHandoverPanel(panel, info, label);
  expect.soft(result.documentOverflow || result.mainOverflow || result.panelOverflow).toBe(false);
  expect.soft(result.rows.filter((row) => row.outside || row.overflow || row.clippedControl)).toEqual([]);
  expect.soft(result.rows.filter((row) => row.control && (row.height < 44 || row.width < 44))).toEqual([]);
  if (contrast) {
    expect.soft(result.rows.filter((row) => row.text && !row.disabled && row.textContrast < row.threshold)).toEqual([]);
    expect.soft(result.rows.filter((row) => row.input && !row.disabled && row.borderContrast! < 3)).toEqual([]);
    expect.soft(result.rows.filter((row) => row.focused && (row.outlineWidth < 2 || row.outlineStyle !== "solid" || row.focusContrast < 3))).toEqual([]);
  }
  return result;
}

/** Exercise real Tab/Shift+Tab movement rather than inferring order from source markup. */
export async function assertTabOrder(page: Page, controls: readonly Locator[]) {
  await controls[0]!.focus();
  for (let index = 0; index < controls.length; index += 1) {
    if (index > 0) await page.keyboard.press("Tab");
    await expect(controls[index]!).toBeFocused();
    const focus = await controls[index]!.evaluate((element) => {
      const style = getComputedStyle(element), rect = element.getBoundingClientRect();
      const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
      return { style: style.outlineStyle, width: parseFloat(style.outlineWidth), unobstructed: hit === element || element.contains(hit) };
    });
    expect(focus.style).toBe("solid");
    expect(focus.width).toBeGreaterThanOrEqual(2);
    expect(focus.unobstructed).toBe(true);
  }
  for (let index = controls.length - 2; index >= 0; index -= 1) {
    await page.keyboard.press("Shift+Tab");
    await expect(controls[index]!).toBeFocused();
  }
}

/** Double each original computed font once; inherited percentages alone do not prove 200% text. */
export async function enlargeHandoverText(panel: Locator) {
  const result = await panel.evaluate((root) => {
    const elements = [root as HTMLElement, ...root.querySelectorAll<HTMLElement>("*")]
      .filter((element) => element.checkVisibility() && !element.closest('.sr-only,[aria-hidden="true"]'));
    const original = elements.map((element) => parseFloat(getComputedStyle(element).fontSize));
    elements.forEach((element, index) => {
      element.style.setProperty("font-size", `${original[index]! * 2}px`, "important");
      element.style.setProperty("line-height", "1.5", "important");
      element.style.setProperty("letter-spacing", ".12em", "important");
      element.style.setProperty("word-spacing", ".16em", "important");
      if (element.tagName === "P") element.style.setProperty("margin-block-end", "2em", "important");
    });
    return { elements: elements.length, failures: elements.filter((element, index) =>
      parseFloat(getComputedStyle(element).fontSize) < original[index]! * 1.99).length };
  });
  expect(result.elements).toBeGreaterThan(20);
  expect(result.failures).toBe(0);
  return result;
}
