import { describe, expect, it, vi } from "vitest";
import { EvidenceRefresh } from "./evidence-refresh";

describe("read-only evidence refresh", () => {
  it("keeps the loading button focusable without an activation handler", () => {
    const onRefresh = vi.fn();
    const button = EvidenceRefresh({ loading: true, onRefresh });
    expect(button.type).toBe("button");
    expect(button.props.type).toBe("button");
    expect(button.props["aria-disabled"]).toBe(true);
    expect(button.props.disabled).toBeUndefined();
    expect(button.props.onClick).toBeUndefined();
    expect(onRefresh).not.toHaveBeenCalled();
  });

  it("exposes only the caller's read-refresh action when ready", () => {
    const onRefresh = vi.fn();
    const button = EvidenceRefresh({ loading: false, onRefresh });
    expect(button.props["aria-disabled"]).toBe(false);
    expect(button.props.onClick).toBe(onRefresh);
    expect(button.props.children).toBe("Refresh evidence");
  });
});
