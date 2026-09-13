import { expect, test } from "@playwright/test";

for (const locale of ["en", "ko"] as const) {
  test(`${locale} premium home exposes the original sky without boxed hero panels`, async ({ page }, info) => {
    await page.goto(locale === "ko" ? "ko/" : "", { waitUntil: "networkidle" });
    const geometry = await page.evaluate(() => {
      const hero = document.querySelector(".home-hero")!;
      const copy = document.querySelector(".home-hero-copy")!;
      const style = getComputedStyle(copy), rect = copy.getBoundingClientRect();
      const scene = hero.getBoundingClientRect();
      return {
        background: style.backgroundColor, border: style.borderWidth, shadow: style.boxShadow,
        sceneWidth: scene.width, sceneHeight: scene.height,
        copyAreaShare: rect.width * rect.height / (scene.width * scene.height),
        viewport: [innerWidth, innerHeight],
        primaryBottom: document.querySelector(".hero .primary")!.getBoundingClientRect().bottom,
        contentRadius: getComputedStyle(document.querySelector(".sl-markdown-content")!).borderRadius,
        headerHeight: document.querySelector("header.header")!.getBoundingClientRect().height,
        controls: [...document.querySelectorAll("header.header button[data-open-modal], header.header select")].map(el => {
          const bounds = el.getBoundingClientRect();
          return { width: bounds.width, height: bounds.height, left: bounds.left, right: bounds.right };
        }),
        panels: [...document.querySelectorAll(".home-outcome")].map(el => ({ background: getComputedStyle(el).backgroundColor, radius: getComputedStyle(el).borderRadius })),
      };
    });
    expect(geometry.background).toBe("rgba(0, 0, 0, 0)");
    expect(geometry.border).toBe("0px");
    expect(geometry.shadow).toBe("none");
    expect(geometry.contentRadius).toBe("0px");
    expect(geometry.sceneWidth).toBe(geometry.viewport[0]);
    expect(geometry.panels).toEqual(Array(3).fill({ background: "rgba(0, 0, 0, 0)", radius: "0px" }));
    if (geometry.viewport[0] < 800) {
      expect(geometry.headerHeight, "Default mobile controls should share one compact row").toBeLessThanOrEqual(90);
      for (const control of geometry.controls) {
        expect(control.width).toBeGreaterThanOrEqual(44);
        expect(control.height).toBeGreaterThanOrEqual(44);
        expect(control.left).toBeGreaterThanOrEqual(0);
        expect(control.right).toBeLessThanOrEqual(geometry.viewport[0]);
      }
    }
    if (info.project.name === "desktop") {
      expect(geometry.copyAreaShare).toBeLessThan(0.4);
      expect(geometry.primaryBottom).toBeLessThan(geometry.viewport[1] - 110);
      await page.locator(".home-nav a[href='#safety']").press("Enter");
      await expect(page).toHaveURL(/#safety$/);
      await expect(page.locator("#safety")).toBeFocused();
    }
    await test.info().attach("composition-geometry", { body: JSON.stringify(geometry, null, 2), contentType: "application/json" });
  });

  test(`${locale} hero text is inside the protected center of the local scrim`, async ({ page }, info) => {
    await page.goto(locale === "ko" ? "ko/" : "");
    const measure = () => page.evaluate(() => {
      const copy = document.querySelector(".home-hero-copy")!;
      const rect = copy.getBoundingClientRect();
      const pseudo = getComputedStyle(copy, "::before");
      const width = Number.parseFloat(pseudo.width), height = Number.parseFloat(pseudo.height);
      const cx = rect.x + Number.parseFloat(pseudo.left) + width / 2;
      const cy = rect.y + Number.parseFloat(pseudo.top) + height / 2;
      const positions = [];
      for (const el of copy.querySelectorAll("h1, .tagline, .home-eyebrow, .sl-link-button")) {
        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
        for (let text = walker.nextNode(); text; text = walker.nextNode()) {
          if (!text.textContent?.trim()) continue;
          const range = document.createRange(); range.selectNodeContents(text);
          for (const line of range.getClientRects()) {
            const radius = Math.max(...[line.left, line.right].flatMap(x => [line.top, line.bottom].map(y => Math.hypot((x - cx) / (width / 2), (y - cy) / (height / 2)))));
            positions.push({ text: text.textContent, radius, color: getComputedStyle(el).color, button: el.matches(".sl-link-button") });
          }
        }
      }
      return { positions, scrim: getComputedStyle(document.documentElement).getPropertyValue("--home-hero-scrim"), gradient: pseudo.backgroundImage };
    });
    const luminance = (c: number[]) => c.map(v => v / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4).reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
    for (const enlarged of [false, true]) {
      if (enlarged) {
        await page.addStyleTag({ content: "html { font-size: 200% !important; } main * { line-height: 1.5 !important; letter-spacing: .12em !important; word-spacing: .16em !important; } main p { margin-bottom: 2em !important; }" });
      }
      const evidence = await measure();
      await info.attach(enlarged ? "enlarged-scrim-coverage" : "default-scrim-coverage", { body: JSON.stringify(evidence), contentType: "application/json" });
      expect(evidence.positions.length).toBeGreaterThan(2);
      expect(evidence.gradient).toContain("72%");
      expect(Math.max(...evidence.positions.map(p => p.radius)), enlarged ? "200% text and user spacing" : "Default text").toBeLessThanOrEqual(0.72);
      const scrim = evidence.scrim.match(/[\d.]+/g)!.map(Number);
      const brightest = scrim.slice(0, 3).map(c => c * scrim[3] + 255 * (1 - scrim[3]));
      for (const text of evidence.positions.filter(position => !position.button)) {
        const color = text.color.match(/[\d.]+/g)!.slice(0, 3).map(Number);
        expect((luminance(color) + .05) / (luminance(brightest) + .05), text.text).toBeGreaterThanOrEqual(4.5);
      }
    }
  });
}
