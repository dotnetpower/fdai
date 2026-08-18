import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

const consoleStyles = readFileSync(fileURLToPath(new URL("./styles.css", import.meta.url)), "utf8");
const mockStyles = readFileSync(
  fileURLToPath(new URL("../../mocks/ui/assets/calm-slate.css", import.meta.url)),
  "utf8",
);
const sharedTokens = readFileSync(
  fileURLToPath(new URL("../../ui/calm-slate-tokens.css", import.meta.url)),
  "utf8",
);
const sharedPrimitives = readFileSync(
  fileURLToPath(new URL("../../ui/calm-slate-primitives.css", import.meta.url)),
  "utf8",
);
const componentGallery = readFileSync(
  fileURLToPath(new URL("../../mocks/ui/components.html", import.meta.url)),
  "utf8",
);

describe("shared Calm Slate tokens", () => {
  test("keeps foundation tokens in one stylesheet consumed by Console and mocks", () => {
    expect(consoleStyles).toContain('@import url("../../ui/calm-slate-tokens.css")');
    expect(mockStyles).toContain('@import url("../../../ui/calm-slate-tokens.css")');
    expect(consoleStyles).toContain('@import url("../../ui/calm-slate-primitives.css")');
    expect(mockStyles).toContain('@import url("../../../ui/calm-slate-primitives.css")');
    expect(sharedTokens).toContain("--cs-radius: 8px");
    expect(sharedTokens).toContain("--cs-type-page-title-size: 24px");
    expect(sharedTokens).toContain("--cs-type-page-subtitle-size: 13px");
    expect(sharedTokens).toContain("--cs-type-lead-size: 16px");
    expect(sharedTokens).toContain("--cs-type-section-title-size: 18px");
    expect(sharedTokens).toContain("--cs-type-panel-title-size: 15px");
    expect(sharedTokens).toContain("--cs-type-body-size: 14px");
    expect(sharedTokens).toContain("--cs-type-compact-size: 13px");
    expect(sharedTokens).toContain("--cs-type-label-size: 12px");
    expect(sharedTokens).toContain("--cs-type-caption-size: 11px");
    expect(sharedTokens).toContain("--cs-font-size: var(--cs-type-body-size)");
    expect(consoleStyles).toContain("--font-sans: var(--cs-font)");
    expect(mockStyles).toContain("font-size: var(--cs-font-size)");
    expect(mockStyles).not.toContain("--cs-radius: 14px");
    expect(mockStyles).not.toContain("--cs-font:");
    expect(sharedPrimitives).toContain(".is-content-updated::after");
    expect(sharedPrimitives).toContain("animation: calm-slate-content-update 1.35s");
    expect(sharedPrimitives).toContain(".cs-type-page-title");
    expect(sharedPrimitives).toContain(".cs-type-body");
    expect(sharedPrimitives).toContain(".cs-type-caption");
    expect(consoleStyles).toContain("font-size: var(--cs-type-page-title-size)");
    expect(mockStyles).toContain("font-size: var(--cs-type-page-title-size)");
  });

  test("renders every semantic typography role in the component gallery", () => {
    expect(componentGallery).toContain('id="typography"');
    expect(componentGallery).toContain("Typography &amp; content hierarchy");
    for (const role of [
      "page-title",
      "page-subtitle",
      "lead",
      "section-title",
      "panel-title",
      "body",
      "compact",
      "label",
      "caption",
    ]) {
      expect(componentGallery).toContain(`cs-type-${role}`);
    }
  });
});
