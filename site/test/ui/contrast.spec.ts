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

/** Worst-case opaque backdrop beneath an alpha surface, not a sampled shader frame. */
function composite(surface: number[], backdrop: number): number[] {
  const alpha = surface[3] ?? 1;
  return surface.slice(0, 3).map(channel => channel * alpha + backdrop * (1 - alpha));
}

for (const theme of ["light", "dark"] as const) {
  test(`${theme} landing surfaces and actions have measurable contrast in every state`, async ({ page }) => {
    await page.addInitScript(value => localStorage.setItem("starlight-theme", value), theme);
    await page.goto("");
    const backdrop = await page.locator(".home-content").evaluate(el => getComputedStyle(el).backgroundColor);
    expect(luminance(rgb(backdrop))).toBeGreaterThan(theme === "light" ? 0.85 : 0.02);
    await expect(page.locator(".nebula-bg")).toHaveCount(1);
    await expect(page.locator(".nebula-bg")).toHaveCSS("opacity", "1");
    await expect(page.locator(".nebula-bg")).toHaveCSS("pointer-events", "none");
    const measurements: { label: string; state: string; ratio: number }[] = [];
    const selector = ".hero .sl-link-button, .home-button";
    await expect(page.locator(selector)).toHaveCount(3);
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
        const ratio = contrast(rgb(colors.text), background);
        measurements.push({ label: colors.label, state: colors.state, ratio });
        expect(ratio, `${colors.label} ${colors.state}`).toBeGreaterThanOrEqual(4.5);
    }
    await page.locator(".home-safeguards summary").press("Enter");
    const boundaries = await page.evaluate(selector => {
      const results = [];
      for (const el of document.querySelectorAll<HTMLElement>(`${selector}, .home-safeguards summary`)) {
        el.focus({ preventScroll: true });
        const style = getComputedStyle(el);
        let ancestor = el.parentElement;
        let background = getComputedStyle(document.body).backgroundColor;
        while (ancestor) {
          const candidate = getComputedStyle(ancestor).backgroundColor;
          if (!candidate.endsWith(", 0)") && candidate !== "transparent") { background = candidate; break; }
          ancestor = ancestor.parentElement;
        }
        const boundary = el.matches("summary") ? getComputedStyle(el.parentElement!).borderColor : style.borderColor;
        const scrim = el.closest(".home-hero") ? getComputedStyle(document.documentElement).getPropertyValue("--home-hero-scrim") : null;
        results.push({ label: el.textContent!.trim(), outline: style.outlineColor, outlineWidth: Number.parseFloat(style.outlineWidth), boundary, background, scrim });
      }
      return results;
    }, selector);
    for (const boundary of boundaries) {
      expect(boundary.outlineWidth, boundary.label).toBeGreaterThanOrEqual(2);
      const backgrounds = boundary.scrim ? [0, 255].map(channel => composite(rgb(boundary.scrim!), channel)) : [rgb(boundary.background)];
      for (const background of backgrounds) {
        const focusRatio = contrast(rgb(boundary.outline), background);
        const borderRatio = contrast(rgb(boundary.boundary), background);
        expect(focusRatio, `${boundary.label} focus`).toBeGreaterThanOrEqual(3);
        expect(borderRatio, `${boundary.label} boundary`).toBeGreaterThanOrEqual(3);
        measurements.push({ label: boundary.label, state: "focus outline", ratio: focusRatio }, { label: boundary.label, state: "boundary", ratio: borderRatio });
      }
    }
    const chrome = await page.evaluate(() => {
      const header = document.querySelector("header.header")!;
      const labels = [...header.querySelectorAll(".home-nav a, .home-docs-link, starlight-theme-select label, starlight-lang-select label, button[data-open-modal]")]
        .filter(el => el.getBoundingClientRect().width > 0)
        .map(el => ({ label: el.textContent?.trim() || "Search icon", color: getComputedStyle(el).color, background: getComputedStyle(header).backgroundColor }));
      for (const el of document.querySelectorAll(".home-hero-note, .home-explore")) {
        labels.push({ label: el.textContent!.trim(), color: getComputedStyle(el).color, background: getComputedStyle(el.parentElement!).backgroundColor });
      }
      return labels;
    });
    for (const label of chrome) {
      for (const backdrop of [0, 255]) {
        const ratio = contrast(rgb(label.color), composite(rgb(label.background), backdrop));
        expect(ratio, `${label.label} on composited chrome`).toBeGreaterThanOrEqual(4.5);
        measurements.push({ label: label.label, state: "chrome", ratio });
      }
    }
    const scan = await new AxeBuilder({ page }).include("main").include("header.header")
      .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
    expect(scan.violations.map(({ id, nodes }) => ({ id, targets: nodes.map(node => node.target) }))).toEqual([]);
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
      await expect(page.locator(".home-outcome")).toHaveCount(3);
      await expect(page.locator(".home-flow-list > li")).toHaveCount(4);
      await page.locator(".home-safeguards summary").press("Enter");
      await expect(page.locator(".home-safeguards [data-safeguard]")).toHaveCount(7);
      await expect(page.locator("[data-safeguard=audit]")).toBeVisible();
      await page.locator(".hero .sl-link-button.primary").click();
      await expect(page).toHaveURL(new RegExp(`/${prefix}get-started/?$`));
      await expect(page.locator("h1")).toBeVisible();
    });
  }
});
