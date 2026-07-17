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
    expect(source).toContain("children.props.onFocus?.(event)");
    expect(source).toContain("show(0)");
    expect(source).toContain("children.props.onBlur?.(event)");
  });

  test("connects keyboard triggers to a dismissible description", () => {
    expect(source).toContain('"aria-describedby": state === null ? undefined : id');
    expect(source).toContain('event.key === "Escape"');
    expect(source).toContain('document.addEventListener("keydown", dismissOnEscape)');
    expect(source).toContain('role="tooltip"');
    expect(source).toContain("onClick={hide}");
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
});
