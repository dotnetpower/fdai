import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

function rgb(value: string): number[] {
  const channels = value.match(/[\d.]+/g)?.map(Number) ?? [];
  expect(channels.length, `Expected computed RGB color: ${value}`).toBeGreaterThanOrEqual(3);
  return channels;
}

function luminance(channels: number[]): number {
  const linear = channels.slice(0, 3).map(value => {
    const channel = value / 255;
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
}

function contrast(foreground: number[], background: number[]): number {
  const a = luminance(foreground), b = luminance(background);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

for (const theme of ["light", "dark"] as const) {
  test(`${theme} landing actions and graphics have measurable contrast in every state`, async ({ page }) => {
    await page.addInitScript(value => localStorage.setItem("starlight-theme", value), theme);
    await page.goto("");
    const backdrop = await page.evaluate(() => {
      const color = getComputedStyle(document.documentElement).backgroundColor;
      const opacity = Number.parseFloat(getComputedStyle(document.querySelector(".nebula-bg")!).opacity);
      return { color, opacity };
    });
    // A white shader pixel at maximum canvas opacity is the worst case for
    // light text. It is stronger evidence than sampling one animation frame.
    const worstBackground = rgb(backdrop.color).slice(0, 3).map(value => 255 * backdrop.opacity + value * (1 - backdrop.opacity));
    const measurements: { label: string; state: string; ratio: number }[] = [];
    const selector = ".hero .sl-link-button, .cta-btn";
    const stationary = await page.evaluate(selector => {
      const results = [];
      for (const el of document.querySelectorAll<HTMLAnchorElement>(selector)) {
        for (const state of ["default", "focus"]) {
          if (state === "focus") el.focus({ preventScroll: true });
          const s = getComputedStyle(el);
          results.push({ label: el.textContent!.trim(), state, text: s.color, background: s.backgroundColor, image: s.backgroundImage });
        }
      }
      return results;
    }, selector);
    const hovered = [];
    for (let index = 0; index < stationary.length / 2; index++) {
      await page.locator(selector).nth(index).hover();
      hovered.push(await page.evaluate(({ selector, index }) => {
        const el = document.querySelectorAll(selector)[index];
        const s = getComputedStyle(el);
        return { label: el.textContent!.trim(), state: "hover", text: s.color, background: s.backgroundColor, image: s.backgroundImage };
      }, { selector, index }));
    }
    for (const colors of [...stationary, ...hovered]) {
        expect(colors.image).toBe("none");
        const background = rgb(colors.background);
        const ratio = contrast(rgb(colors.text), background[3] === 0 ? worstBackground : background);
        measurements.push({ label: colors.label, state: colors.state, ratio });
        expect(ratio, `${colors.label} ${colors.state}`).toBeGreaterThanOrEqual(4.5);
    }
    const sampleColors = await page.evaluate(() => { const s = getComputedStyle(document.querySelector(".hc-approve")!); return { text: s.color, background: s.backgroundColor }; });
    expect(contrast(rgb(sampleColors.text), rgb(sampleColors.background))).toBeGreaterThanOrEqual(4.5);
    await expect(page.locator(".example-note")).toHaveCount(2);
    const bars = await page.locator(".ttf-fill").evaluateAll(elements => elements.map(el => ({ fill: getComputedStyle(el).backgroundColor, track: getComputedStyle(el.parentElement!).backgroundColor })));
    for (const colors of bars) {
      expect(contrast(rgb(colors.fill), rgb(colors.track))).toBeGreaterThanOrEqual(3);
    }
    await test.info().attach("measured-contrast", { body: JSON.stringify(measurements, null, 2), contentType: "application/json" });
  });

  test(`${theme} search results and placeholder stay readable`, async ({ page }) => {
    await page.addInitScript(value => localStorage.setItem("starlight-theme", value), theme);
    await page.goto("get-started/");
    await page.locator("site-search button[data-open-modal]").click();
    const dialog = page.locator("site-search dialog");
    const input = dialog.getByRole("textbox");
    await expect(input).toBeVisible();
    const placeholder = await input.evaluate(el => ({ text: getComputedStyle(el, "::placeholder").color, opacity: getComputedStyle(el, "::placeholder").opacity, background: getComputedStyle(el).backgroundColor }));
    expect(placeholder.opacity).toBe("1");
    expect(contrast(rgb(placeholder.text), rgb(placeholder.background))).toBeGreaterThanOrEqual(4.5);
    await input.fill("FDAI");
    await expect(dialog.locator(".pagefind-ui__result-link").first()).toBeVisible();
    const scan = await new AxeBuilder({ page }).include("site-search dialog")
      .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
    expect(scan.violations.map(({ id, nodes }) => ({ id, targets: nodes.map(node => node.target) }))).toEqual([]);
  });
}

test.describe("progressive reading fallback", () => {
  test.use({ javaScriptEnabled: false });
  for (const locale of ["en", "ko"]) {
    test(`${locale} content and native links remain usable without JavaScript`, async ({ page }) => {
      const prefix = locale === "ko" ? "ko/" : "";
      await page.goto(prefix);
      await expect(page.locator(".ttf-inflow-num")).toHaveText("100");
      await expect(page.locator(".ttf-pct-num")).toHaveText(["78", "17", "5"]);
      await expect(page.locator(".ao-explorer")).not.toHaveClass(/is-enhanced/);
      await expect(page.locator(".ao-panel").first()).toBeVisible();
      await expect(page.locator(".ao-panel").last()).toBeVisible();
      await page.locator(".hero .sl-link-button.primary").click();
      await expect(page).toHaveURL(new RegExp(`/${prefix}get-started/?$`));
      await expect(page.locator("h1")).toBeVisible();
    });
  }
});
