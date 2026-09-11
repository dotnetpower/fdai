import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";
import { documentActionProps } from "./document-library-row";

const styles = readFileSync(
  fileURLToPath(new URL("../styles.css", import.meta.url)),
  "utf8",
);

describe("documentActionProps", () => {
  it("keeps unavailable actions focusable and prevents activation", () => {
    const onClick = vi.fn();

    const props = documentActionProps(false, false, onClick);

    expect(props["aria-disabled"]).toBe(true);
    expect(props.disabled).toBe(false);
    expect(props.onClick).toBeUndefined();
    expect(onClick).not.toHaveBeenCalled();
  });

  it("stacks document identity metadata within its bounded column", () => {
    expect(styles).toMatch(
      /\.document-library-name\s*\{[^}]*display: grid;[^}]*gap: 2px;/,
    );
  });

  it("uses native disabled behavior only while an available action is pending", () => {
    const onClick = vi.fn();

    const pending = documentActionProps(true, true, onClick);
    expect(pending["aria-disabled"]).toBeUndefined();
    expect(pending.disabled).toBe(true);
    expect(pending.onClick).toBeUndefined();

    const ready = documentActionProps(true, false, onClick);
    expect(ready.disabled).toBe(false);
    ready.onClick?.();
    expect(onClick).toHaveBeenCalledOnce();
  });
});
