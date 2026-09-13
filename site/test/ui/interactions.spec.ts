import { expect, test } from "@playwright/test";

for (const locale of ["en", "ko"] as const) {
  const prefix = locale === "ko" ? "ko/" : "";

  test(`${locale} landing keeps theme choice and keyboard action affordances`, async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("starlight-theme", "auto"));
    await page.goto(prefix);
    const actions = page.locator(".hero .sl-link-button");
    await expect(actions).toHaveCount(3);
    for (const theme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme: theme });
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await expect(actions.nth(1)).toHaveCSS("color", "rgb(243, 247, 255)");
      await expect(actions.nth(2)).toHaveCSS("text-decoration-line", "underline");
      await actions.first().focus();
      await page.keyboard.press("Tab");
      await expect(actions.nth(1)).toBeFocused();
      expect(await actions.nth(1).evaluate(el => Number.parseFloat(getComputedStyle(el).outlineWidth))).toBeGreaterThanOrEqual(2);
      await actions.nth(1).hover();
      await expect(actions.nth(1)).toHaveCSS("background-color", "rgb(36, 55, 84)");
      await page.mouse.move(0, 0);
    }
    await actions.first().press("Enter");
    await expect(page).toHaveURL(new RegExp(`/${prefix}get-started/?$`));
  });

  test(`${locale} ontology selection and focused navigation work by keyboard`, async ({ page }) => {
    await page.goto(prefix);
    const explorer = page.locator(".ao-explorer");
    await expect(explorer).toHaveClass(/is-enhanced/);
    const nodes = explorer.locator(".ao-node");
    expect(await nodes.evaluateAll(elements => elements.every(el => getComputedStyle(el).marginBottom === "0px"))).toBe(true);
    if ((page.viewportSize()?.width ?? 0) >= 704) {
      const alignment = await explorer.evaluate(el => {
        const list = el.querySelector(".ao-nodes")!.getBoundingClientRect();
        const detail = el.querySelector(".ao-panel.is-active")!.getBoundingClientRect();
        return Math.abs(list.y - detail.y);
      });
      expect(alignment).toBeLessThanOrEqual(1);
    }
    await nodes.nth(1).press("Enter");
    await expect(nodes.nth(1)).toHaveAttribute("aria-pressed", "true");
    await expect(explorer.locator(".ao-panel.is-active")).toHaveAttribute("data-index", "1");
    const irreversible = explorer.locator(".ao-node").filter({ has: page.locator(".ao-node-irr") }).first();
    await irreversible.press("Enter");
    await expect(explorer.locator(".ao-panel.is-active .ao-badge--irr")).toHaveCSS("color", "rgb(255, 204, 221)");
    const filter = explorer.locator(".ao-filter").last();
    await filter.press("Space");
    await expect(filter).toHaveAttribute("aria-pressed", "true");
    await expect(explorer.locator(".ao-node.is-active")).toBeVisible();
    await page.goto(`${prefix}sre/`);
    const menu = page.locator("starlight-menu-button button");
    if (await menu.isVisible()) await menu.press("Enter");
    await page.locator(".fdai-focused-nav-back").press("Enter");
    await expect(page).toHaveURL(new RegExp(`/${prefix}get-started/?$`));
  });

  test(`${locale} diagram exposes node buttons without nesting them in an image`, async ({ page }) => {
    await page.goto(`${prefix}get-started/`);
    const diagram = page.locator("fdai-architecture-diagram").first();
    const svg = diagram.locator(".stage > svg");
    await expect(svg).toHaveAttribute("role", "group");
    await expect(svg).toHaveAttribute("aria-labelledby", "diagram-title diagram-description");
    const nodes = diagram.locator("[data-node-id]");
    await nodes.first().focus();
    await page.keyboard.press("ArrowRight");
    await expect(nodes.nth(1)).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(nodes.nth(1)).toHaveAttribute("aria-pressed", "true");
    await expect(diagram.locator(".details.open")).toBeVisible();
    expect(await nodes.evaluateAll(elements => elements.every(el => getComputedStyle(el).opacity === "1"))).toBe(true);
    await diagram.locator(".details-close").press("Enter");
    await expect(nodes.nth(1)).toBeFocused();
    await page.keyboard.press("Enter");
    await page.keyboard.press("Escape");
    await expect(diagram.locator(".details.open")).toHaveCount(0);
  });

  test(`${locale} production search opens, reports results and restores focus`, async ({ page }) => {
    await page.goto(`${prefix}get-started/`);
    const opener = page.locator("site-search button[data-open-modal]");
    await opener.focus();
    await page.keyboard.press("Enter");
    const dialog = page.locator("site-search dialog");
    await expect(dialog).toBeVisible();
    const input = dialog.getByRole("textbox");
    await expect(input).toBeVisible();
    await input.fill("FDAI");
    await expect(dialog.locator(".pagefind-ui__result-link").first()).toBeVisible();
    await input.fill("no-such-topic-53102");
    await expect(dialog.locator(".pagefind-ui__message")).toContainText(/no results|없|0/i);
    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();
    await expect(opener).toBeFocused();
    await opener.press("Enter");
    await input.fill("FDAI");
    const result = dialog.locator(".pagefind-ui__result-link").first();
    await expect(result).toBeVisible();
    const href = await result.getAttribute("href");
    const destination = new URL(href!, page.url());
    expect(destination.pathname).toContain(`/fdai/${prefix}`);
    await result.press("Enter");
    await expect(page).toHaveURL(destination.href);
    await expect(page.locator("h1")).toBeVisible();
  });
}
