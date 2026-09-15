import { describe, expect, it, vi } from "vitest";
import { copyTraceValue } from "./rule-trace-copy";

describe("Trace copy feedback", () => {
  it("reports success only after the clipboard write completes", async () => {
    const writeText = vi.fn(async () => undefined);

    await expect(copyTraceValue({ writeText }, "trace-value")).resolves.toBe("copied");
    expect(writeText).toHaveBeenCalledWith("trace-value");
  });

  it("reports clipboard absence or rejection", async () => {
    await expect(copyTraceValue(undefined, "trace-value")).resolves.toBe("failed");
    await expect(copyTraceValue({
      writeText: vi.fn(async () => {
        throw new Error("denied");
      }),
    }, "trace-value")).resolves.toBe("failed");
  });
});
