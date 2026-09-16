import { expect, test } from "@playwright/test";

for (const locale of ["en", "ko"] as const) {
  const prefix = locale === "ko" ? "ko/" : "";

  test(`${locale} landing keeps theme choice and keyboard action affordances`, async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("starlight-theme", "auto"));
    await page.goto(prefix);
    const actions = page.locator(".hero .sl-link-button");
    await expect(actions).toHaveCount(2);
    for (const theme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme: theme });
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await expect(actions.nth(1)).toHaveCSS("color", "rgb(238, 244, 255)");
      await expect(actions.nth(1)).toHaveAttribute("href", "#how-it-works");
      await actions.first().focus();
      await page.keyboard.press("Tab");
      await expect(actions.nth(1)).toBeFocused();
      expect(await actions.nth(1).evaluate(el => Number.parseFloat(getComputedStyle(el).outlineWidth))).toBeGreaterThanOrEqual(2);
      await actions.nth(1).hover();
      await expect(actions.nth(1)).toHaveCSS("background-color", "rgb(38, 58, 86)");
      await page.mouse.move(0, 0);
    }
    await actions.first().press("Enter");
    await expect(page).toHaveURL(new RegExp(`/${prefix}get-started/?$`));
  });

  test(`${locale} safeguards and focused navigation work by keyboard`, async ({ page }) => {
    await page.goto(prefix);
    const details = page.locator(".home-safeguards");
    const summary = details.locator("summary");
    await expect(details).not.toHaveAttribute("open", "");
    await summary.press("Enter");
    await expect(details).toHaveAttribute("open", "");
    await expect(details.locator("[data-safeguard]")).toHaveCount(7);
    await expect(details.locator("[data-safeguard=audit]")).toBeVisible();
    await summary.press("Enter");
    await expect(details.locator(".home-safeguards-content")).toBeHidden();
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

  test(`${locale} AKS architecture keeps both runtime views and interactive service details`, async ({ page }, testInfo) => {
    await page.goto(`${prefix}architecture/`);
    await expect(page.getByRole("heading", { name: locale === "ko" ? "AKS 배포" : "AKS deployment", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: locale === "ko" ? "Container Apps 배포" : "Container Apps deployment", exact: true })).toBeVisible();
    const diagram = page.locator('fdai-architecture-diagram[manifest*="fdai-azure-aks-deployment"]');
    await expect(diagram.locator(".stage > svg")).toHaveAttribute("role", "group");
    for (const node of ["operator", "ingestion", "core", "worker", "executor", "jobs"]) {
      await expect(diagram.locator(`[data-node-id="${node}"]`)).toHaveCount(1);
    }
    const executor = diagram.locator('[data-node-id="executor"]');
    await executor.focus();
    await page.keyboard.press("Enter");
    await expect(executor).toHaveAttribute("aria-pressed", "true");
    await expect(diagram.locator(".details.open")).toContainText(locale === "ko" ? "안전장치" : "safeguards");
    await diagram.locator(".details-close").press("Enter");
    const stage = diagram.locator(".stage");
    await stage.focus();
    await page.keyboard.press("+");
    await page.keyboard.press("0");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    await diagram.scrollIntoViewIfNeeded();
    await diagram.screenshot({ path: testInfo.outputPath("aks-architecture.png") });
  });

  test(`${locale} production search opens, reports results and restores focus`, async ({ page }) => {
    await page.goto(prefix);
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
