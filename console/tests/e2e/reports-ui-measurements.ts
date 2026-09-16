import type { Page } from "@playwright/test";

export interface TextContrastMeasurement {
  readonly selector: string;
  readonly ratio: number;
  readonly foreground: string;
  readonly backgrounds: readonly string[];
}

export async function measureTextContrast(
  page: Page,
  selectors: readonly string[],
): Promise<readonly TextContrastMeasurement[]> {
  return page.evaluate((requestedSelectors) => {
    function rgba(value: string): number[] {
      const channels = value.match(/[\d.]+/g)?.map(Number) ?? [0, 0, 0, 0];
      if (value.startsWith("color(srgb")) {
        return [
          (channels[0] ?? 0) * 255,
          (channels[1] ?? 0) * 255,
          (channels[2] ?? 0) * 255,
          channels[3] ?? 1,
        ];
      }
      return channels;
    }

    function luminance(rgb: readonly number[]): number {
      const values = rgb.slice(0, 3).map((channel) => {
        const value = channel / 255;
        return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
      });
      return values[0]! * 0.2126 + values[1]! * 0.7152 + values[2]! * 0.0722;
    }

    return requestedSelectors.flatMap((selector) =>
      [...document.querySelectorAll(selector)]
        .filter((element) => element.checkVisibility())
        .map((element) => {
          const ancestors: Element[] = [];
          for (let current: Element | null = element; current; current = current.parentElement) {
            ancestors.unshift(current);
          }
          let background = [255, 255, 255];
          const backgrounds: string[] = [];
          for (const ancestor of ancestors) {
            const backgroundColor = getComputedStyle(ancestor).backgroundColor;
            const channels = rgba(backgroundColor);
            const alpha = channels[3] ?? 1;
            if (alpha > 0) backgrounds.push(backgroundColor);
            background = background.map((channel, index) =>
              channels[index]! * alpha + channel * (1 - alpha)
            );
          }
          const foregroundColor = getComputedStyle(element).color;
          const foreground = luminance(rgba(foregroundColor));
          const backdrop = luminance(background);
          return {
            selector,
            ratio: (Math.max(foreground, backdrop) + 0.05)
              / (Math.min(foreground, backdrop) + 0.05),
            foreground: foregroundColor,
            backgrounds,
          };
        })
    );
  }, selectors);
}
