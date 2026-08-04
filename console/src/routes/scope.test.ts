import { describe, expect, it, vi } from "vitest";
import { copyScopeArtifact, includedScopeEntryCount, scopeHierarchy } from "./scope";

describe("scope eligibility", () => {
  it("excludes policy exclusions from operational counts", () => {
    expect(includedScopeEntryCount([
      { state: "included" },
      { state: "excluded" },
    ] as never)).toBe(1);
  });

  it("groups only explicit axis entries without deriving inheritance", () => {
    const hierarchy = scopeHierarchy({
      monitoring: {
        axis: "monitoring",
        entries: [{
          address: "scope://example/sub-a",
          level: "subscription",
          subscription: "sub-a",
          resource_group: null,
          state: "included",
        }],
      },
      action: {
        axis: "action",
        entries: [{
          address: "scope://example/sub-a/rg-one",
          level: "resource_group",
          subscription: "sub-a",
          resource_group: "rg-one",
          state: "excluded",
        }],
      },
      executor_boundary: { resource_groups: [], note: null },
    });

    expect(hierarchy).toEqual([{
      subscription: "sub-a",
      entries: [
        { axis: "action", state: "excluded", resourceGroup: "rg-one", address: "scope://example/sub-a/rg-one" },
        { axis: "monitoring", state: "included", resourceGroup: null, address: "scope://example/sub-a" },
      ],
    }]);
  });
});

describe("scope artifact clipboard", () => {
  it("reports copied only after the clipboard write succeeds", async () => {
    const writeText = vi.fn(async () => undefined);

    await expect(copyScopeArtifact({ writeText }, "action:\n")).resolves.toBe("copied");
    expect(writeText).toHaveBeenCalledWith("action:\n");
  });

  it("reports failed when clipboard access is missing or rejects", async () => {
    await expect(copyScopeArtifact(undefined, "artifact")).resolves.toBe("failed");
    await expect(copyScopeArtifact({
      writeText: vi.fn(async () => { throw new Error("denied"); }),
    }, "artifact")).resolves.toBe("failed");
  });
});
