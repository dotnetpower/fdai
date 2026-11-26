import { describe, expect, test } from "vitest";
import { reportSeverity, reportSeverityClass, reportSeverityIcon } from "./report-status";

describe("reportSeverity", () => {
  test("rejected and rolled-back are failures", () => {
    expect(reportSeverity("rejected")).toBe("fail");
    expect(reportSeverity("rolled-back")).toBe("fail");
  });

  test("apply-started is pending, not a success", () => {
    expect(reportSeverity("apply-started")).toBe("pending");
  });

  test("dry-run-admitted and applied are successes", () => {
    expect(reportSeverity("dry-run-admitted")).toBe("ok");
    expect(reportSeverity("applied")).toBe("ok");
  });
});

describe("reportSeverityClass", () => {
  test("maps pending to the warn modifier", () => {
    expect(reportSeverityClass("pending")).toBe("warn");
    expect(reportSeverityClass("ok")).toBe("ok");
    expect(reportSeverityClass("fail")).toBe("fail");
  });
});

describe("reportSeverityIcon", () => {
  test("renders a distinct icon per severity", () => {
    expect(reportSeverityIcon("applied")).toBe("✓");
    expect(reportSeverityIcon("apply-started")).toBe("◷");
    expect(reportSeverityIcon("rolled-back")).toBe("✕");
  });
});
