import { expect, type Locator } from "@playwright/test";

/** Verify that typography, spacing, and a shared left edge distinguish headings from fields. */
export async function expectSettingsHierarchy(region: Locator) {
  const headers = await region.locator(".cs-settings-section-head:visible, .cp-section-head:visible").evaluateAll((elements) =>
    elements.map((header) => {
      const section = header.parentElement!;
      const heading = header.querySelector("h2, h3")!;
      const description = header.querySelector("p") ?? heading;
      const label = section.querySelector(".cs-setting-row > div:first-child > strong");
      const bounds = header.getBoundingClientRect();
      return {
        title: heading.textContent,
        topRule: getComputedStyle(section).borderTopWidth,
        bottomRule: getComputedStyle(header).borderBottomWidth,
        titleSize: getComputedStyle(heading).fontSize,
        titleWeight: getComputedStyle(heading).fontWeight,
        copyGap: description === heading ? null : description.getBoundingClientRect().top - heading.getBoundingClientRect().bottom,
        bodyGap: header.nextElementSibling!.getBoundingClientRect().top - bounds.bottom,
        fullWidth: Math.abs(bounds.width - section.clientWidth) <= 1,
        label: label ? {
          size: getComputedStyle(label).fontSize,
          weight: getComputedStyle(label).fontWeight,
          inset: label.getBoundingClientRect().left - bounds.left,
        } : null,
      };
    }),
  );
  expect(headers.length).toBeGreaterThan(0);
  for (const header of headers) {
    expect(header.topRule, header.title ?? "Section").toBe("0px");
    expect(header.bottomRule).toBe("0px");
    expect(header.titleSize).toBe("20px");
    expect(header.titleWeight).toBe("600");
    if (header.copyGap !== null) expect(header.copyGap).toBeGreaterThanOrEqual(8);
    expect(header.bodyGap).toBeGreaterThanOrEqual(8);
    expect(header.fullWidth).toBe(true);
    if (header.label) {
      expect(header.label.size).toBe("14px");
      expect(header.label.weight).toBe("500");
      expect(header.label.inset).toBeCloseTo(0, 0);
    }
  }
}
