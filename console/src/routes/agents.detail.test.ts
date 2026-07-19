import { describe, expect, test } from "vitest";
import { isAgentEventExpanded } from "./agents.detail";

describe("agent focus event selection", () => {
  test("expands only the selected event", () => {
    expect(isAgentEventExpanded("corr-selected", "corr-selected")).toBe(true);
    expect(isAgentEventExpanded("corr-other", "corr-selected")).toBe(false);
    expect(isAgentEventExpanded("corr-selected", null)).toBe(false);
  });
});
