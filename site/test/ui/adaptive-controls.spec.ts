import { expect, test } from "@playwright/test";

for (const locale of ["en", "ko"] as const) {
  const prefix = locale === "ko" ? "ko/" : "";

  test(`${locale} home exposes theme and language in every viewport`, async ({ page }) => {
    await page.goto(prefix);
    const theme = page.locator("header starlight-theme-select select");
    const language = page.locator("header starlight-lang-select select");
    await expect(theme).toBeVisible();
    await expect(language).toBeVisible();
    const splitWords = await page.locator("h1").evaluate(heading => {
      const text = heading.firstChild;
      if (!text || text.nodeType !== Node.TEXT_NODE) return [];
      return [...(text.textContent ?? "").matchAll(/\S+/g)].filter(match => {
        const range = document.createRange();
        range.setStart(text, match.index!);
        range.setEnd(text, match.index! + match[0].length);
        return new Set([...range.getClientRects()].map(rect => Math.round(rect.y))).size > 1;
      }).map(match => match[0]);
    });
    expect(splitWords).toEqual([]);
    await theme.selectOption("dark");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await theme.selectOption("light");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    if ((page.viewportSize()?.width ?? 0) >= 800) {
      expect(await theme.evaluate(el => {
        const style = getComputedStyle(el);
        const canvas = document.createElement("canvas");
        const context = canvas.getContext("2d")!;
        context.font = style.font;
        const width = context.measureText((el as HTMLSelectElement).selectedOptions[0].text).width;
        return width <= el.clientWidth - Number.parseFloat(style.paddingLeft) - Number.parseFloat(style.paddingRight);
      })).toBe(true);
    }
    const otherLocale = locale === "ko" ? "en" : "ko";
    const otherOption = language.locator("option").filter({ hasText: otherLocale === "ko" ? "한국어" : "English" });
    await language.selectOption((await otherOption.getAttribute("value"))!);
    await expect(page.locator("html")).toHaveAttribute("lang", otherLocale);
  });

  test(`${locale} mobile menu and diagram controls have honest state and touch targets`, async ({ page, isMobile }) => {
    await page.goto(`${prefix}get-started/`);
    const menu = page.locator("starlight-menu-button button");
    if (await menu.isVisible()) {
      for (const control of [menu, page.locator("site-search button[data-open-modal]")]) {
        const box = await control.boundingBox();
        expect(box!.width).toBeGreaterThanOrEqual(44);
        expect(box!.height).toBeGreaterThanOrEqual(44);
      }
      await menu.press("Enter");
      await expect(menu).toHaveAttribute("aria-expanded", "true");
      const sidebar = page.locator("#starlight__sidebar");
      await expect(sidebar).toBeVisible();
      await sidebar.locator("a").first().focus();
      await page.keyboard.press("Escape");
      await expect(menu).toHaveAttribute("aria-expanded", "false");
      await expect(menu).toBeFocused();
    }
    if (isMobile) {
      const diagram = page.locator("fdai-architecture-diagram").first();
      await expect(diagram.locator(".stage > svg")).toHaveAttribute("role", "group");
      for (const button of await diagram.locator(".toolbar button").all()) {
        const box = await button.boundingBox();
        expect(box!.width).toBeGreaterThanOrEqual(44);
        expect(box!.height).toBeGreaterThanOrEqual(44);
      }
      const table = page.locator("table[data-fdai-scrollable]").first();
      if (await table.count()) {
        await table.focus();
        await expect(table).toBeFocused();
        await page.keyboard.press("ArrowRight");
        await expect.poll(() => table.evaluate(el => el.scrollLeft)).toBeGreaterThan(0);
      }
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  });

  test(`${locale} enlargement and user spacing keep the landing usable`, async ({ page }) => {
    await page.goto(prefix);
    await page.addStyleTag({ content: "html { font-size: 200% !important; } main * { line-height: 1.5 !important; letter-spacing: .12em !important; word-spacing: .16em !important; } main p { margin-bottom: 2em !important; }" });
    const geometry = await page.evaluate(() => ({
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      escaped: [...document.querySelectorAll("main *, header.header *")].filter(el => {
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.right > document.documentElement.clientWidth + 1;
      }).slice(0, 12).map(el => ({ tag: el.tagName, className: String(el.className), text: el.textContent?.trim().slice(0, 60), right: el.getBoundingClientRect().right })),
    }));
    expect(geometry.overflow, JSON.stringify(geometry.escaped)).toBeLessThanOrEqual(1);
    const primary = page.locator(".hero .sl-link-button.primary");
    await primary.press("Enter");
    await expect(page).toHaveURL(new RegExp(`/${prefix}get-started/?$`));
  });

  test(`${locale} forced colors and reduced motion preserve control meaning`, async ({ page }) => {
    await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
    await page.goto(prefix);
    await expect(page.locator(".nebula-bg")).toBeHidden();
    await expect(page.locator(".fda-abbr")).not.toHaveCSS("color", "rgba(0, 0, 0, 0)");
    const secondary = page.locator(".hero .sl-link-button.secondary");
    await secondary.focus();
    expect(await secondary.evaluate(el => Number.parseFloat(getComputedStyle(el).outlineWidth))).toBeGreaterThanOrEqual(2);
    await secondary.press("Enter");
    await expect(page).toHaveURL(new RegExp(`/${prefix}reference/roadmap/?$`));
  });
}
