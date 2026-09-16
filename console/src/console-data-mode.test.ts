import { describe, expect, test } from "vitest";
import {
  consoleDataMode,
  consoleDataModeHref,
  supportsSampleData,
} from "./console-data-mode";

describe("Dashboard data mode", () => {
  test("defaults to Live and admits Sample only on supported routes", () => {
    expect(consoleDataMode("dashboard", new URLSearchParams())).toBe("live");
    expect(consoleDataMode("dashboard", new URLSearchParams("data=sample"))).toBe("sample");
    expect(consoleDataMode("live", new URLSearchParams("data=sample"), "sample")).toBe("sample");
    expect(consoleDataMode("audit", new URLSearchParams("data=sample"), "sample")).toBe("sample");
    expect(consoleDataMode("operating-outcomes", new URLSearchParams(), "sample")).toBe("sample");
    expect(supportsSampleData("cost-governance")).toBe(true);
    expect(supportsSampleData("incidents")).toBe(true);
    expect(supportsSampleData("audit")).toBe(true);
    expect(supportsSampleData("trace")).toBe(true);
    expect(supportsSampleData("rca")).toBe(true);
  });

  test("preserves unrelated Dashboard query state", () => {
    expect(consoleDataModeHref("sample", "/overview", "?window=30d"))
      .toBe("/overview?window=30d&data=sample");
    expect(consoleDataModeHref("live", "/overview", "?window=30d&data=sample"))
      .toBe("/overview?window=30d");
  });
});
