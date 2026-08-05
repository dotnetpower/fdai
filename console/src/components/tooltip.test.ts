import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";
import { TOOLTIP_DELAY_MS, TOOLTIP_EXIT_MS } from "./tooltip";

const source = readFileSync(fileURLToPath(new URL("./tooltip.tsx", import.meta.url)), "utf8");
const styles = readFileSync(fileURLToPath(new URL("../styles.css", import.meta.url)), "utf8");

describe("shared Tooltip contract", () => {
  test("uses the documented pointer and exit timing", () => {
    expect(TOOLTIP_DELAY_MS).toBe(100);
    expect(TOOLTIP_EXIT_MS).toBe(50);
    expect(source).toContain('event.pointerType !== "touch"');
    expect(source).toContain('event.pointerType === "touch"');
    expect(source).toContain("children.props.onFocus?.(event)");
    expect(source).toContain("show(0)");
    expect(source).toContain("children.props.onBlur?.(event)");
  });

  test("connects keyboard triggers to a dismissible description", () => {
    expect(source).toContain('"aria-describedby": state === null ? undefined : id');
    expect(source).toContain('event.key === "Escape"');
    expect(source).toContain('document.addEventListener("keydown", dismissOnEscape)');
    expect(source).toContain('document.addEventListener("pointerdown", dismissOutside)');
    expect(source).toContain('role="tooltip"');
    expect(source).toContain("tabIndex: children.props.tabIndex");
    expect(source).not.toContain("onClick={hide}");
  });

  test("renders in a portal and avoids viewport collisions", () => {
    expect(source).toContain("createPortal(");
    expect(source).toContain("document.body");
    expect(source).toContain("flip({ padding: 16 })");
    expect(source).toContain("shift({ padding: 16 })");
  });

  test("disables tooltip animation for reduced motion", () => {
    expect(styles).toContain("@media (prefers-reduced-motion: reduce)");
    expect(styles).toContain(".app-tooltip { animation: none !important; }");
  });

  test("preserves authored line breaks while wrapping long tokens", () => {
    expect(styles).toMatch(
      /\.app-tooltip\s*\{[^}]*max-width:\s*min\(320px, calc\(100vw - 32px\)\);[^}]*overflow-wrap:\s*anywhere;[^}]*white-space:\s*pre-line;/,
    );
  });

  test("supports a wider structured backend status variant", () => {
    expect(source).toContain('readonly variant?: "backend" | "image-preview";');
    expect(source).toContain("data-variant={variant}");
    expect(styles).toMatch(
      /\.app-tooltip\[data-variant="backend"\]\s*\{[^}]*width:\s*min\(390px, calc\(100vw - 48px\)\);[^}]*white-space:\s*normal;/,
    );
  });

  test("opens image previews without hover delay or enter animation", () => {
    expect(source).toContain(
      'delay ?? (variant === "image-preview" ? 0 : TOOLTIP_DELAY_MS)',
    );
    expect(source).toContain("show(pointerDelay)");
    expect(styles).toMatch(
      /\.app-tooltip\[data-variant="image-preview"\]\[data-state="instant-open"\]\s*\{\s*animation:\s*none;/,
    );
  });
});
