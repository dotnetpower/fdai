import { expect, test } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";

type NebulaEvidence = { frames: number; pixel: number[] };

for (const theme of ["light", "dark"] as const) {
  test(`${theme} home retains the original rendered nebula and motion preference`, async ({ page, context }, info) => {
    await context.addInitScript(() => {
      const state = window as Window & { nebulaEvidence?: NebulaEvidence };
      state.nebulaEvidence = { frames: 0, pixel: [] };
      const draw = WebGLRenderingContext.prototype.drawArrays;
      WebGLRenderingContext.prototype.drawArrays = function (...args) {
        draw.apply(this, args);
        if (!(this.canvas instanceof HTMLCanvasElement) || !this.canvas.matches(".nebula-bg")) return;
        const pixel = new Uint8Array(4);
        this.readPixels(Math.floor(this.drawingBufferWidth / 2), Math.floor(this.drawingBufferHeight / 2), 1, 1, this.RGBA, this.UNSIGNED_BYTE, pixel);
        state.nebulaEvidence!.frames += 1;
        state.nebulaEvidence!.pixel = [...pixel];
      };
    });
    for (const reducedMotion of ["reduce", "no-preference"] as const) {
      await page.emulateMedia({ colorScheme: theme, reducedMotion });
      await page.goto("ko/", { waitUntil: "networkidle" });
      const canvas = page.locator("body > canvas.nebula-bg");
      await expect(canvas).toHaveCount(1);
      await expect(canvas).toHaveAttribute("data-intensity", "1");
      await expect(canvas).toHaveAttribute("data-speed", "1");
      await expect(canvas).toHaveAttribute("aria-hidden", "true");
      await expect(canvas).toHaveCSS("opacity", "1");
      const initial = await page.evaluate(() => (window as Window & { nebulaEvidence?: NebulaEvidence }).nebulaEvidence!);
      expect(initial.frames).toBeGreaterThan(0);
      expect(initial.pixel[3]).toBe(255);
      expect(initial.pixel.slice(0, 3).some(channel => channel > 20)).toBe(true);
      const later = await page.evaluate(() => new Promise<number>(resolve => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve((window as Window & { nebulaEvidence?: NebulaEvidence }).nebulaEvidence!.frames)));
      }));
      if (reducedMotion === "reduce") expect(later).toBe(initial.frames);
      else expect(later).toBeGreaterThan(initial.frames);
      const geometry = await canvas.evaluate(el => ({ width: el.getBoundingClientRect().width, height: el.getBoundingClientRect().height, viewport: [innerWidth, innerHeight] }));
      expect(geometry.width).toBe(geometry.viewport[0]);
      expect(geometry.height).toBe(geometry.viewport[1]);
      await info.attach(`${reducedMotion}-nebula-frame`, { body: JSON.stringify({ initial, later, geometry }), contentType: "application/json" });
      if (reducedMotion === "no-preference") {
        const directory = path.resolve(import.meta.dirname, "../../../.fdai/homepage-premium");
        await mkdir(directory, { recursive: true });
        // A fixed viewport does not resize and clear the original WebGL canvas.
        await page.screenshot({ path: path.join(directory, `${info.project.name}-ko-${theme}-nebula.png`) });
      }
    }
  });
}
