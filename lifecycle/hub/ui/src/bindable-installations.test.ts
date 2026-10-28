import { describe, expect, it } from "vitest";
import type { BindableInstallation } from "./api";
import { effectiveSelection, isSelectable, optionLabel } from "./bindable-installations";

const items: BindableInstallation[] = [
  { installation_id: "alpha", status: "enrolled" },
  { installation_id: "beta", status: "pending" },
  { installation_id: "gamma", status: "unrequested" },
  { installation_id: "delta", status: "unrequested" },
];

describe("bindable installations", () => {
  it("only unrequested installations accept a new submission", () => {
    expect(items.map(isSelectable)).toEqual([false, false, true, true]);
  });

  it("shows the status next to each installation", () => {
    expect(optionLabel(items[0]!)).toBe("alpha (enrolled)");
    expect(optionLabel(items[1]!)).toBe("beta (request pending)");
    expect(optionLabel(items[2]!)).toBe("gamma (not requested yet)");
  });

  it("defaults to the first unrequested installation", () => {
    expect(effectiveSelection(items, "")).toBe("gamma");
  });

  it("keeps a still-selectable choice and drops one that is no longer selectable", () => {
    expect(effectiveSelection(items, "delta")).toBe("delta");
    expect(effectiveSelection(items, "beta")).toBe("gamma");
    expect(effectiveSelection(items, "gone")).toBe("gamma");
  });

  it("selects nothing when no installation can take a request", () => {
    expect(effectiveSelection(items.slice(0, 2), "")).toBe("");
  });
});
