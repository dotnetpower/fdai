import { describe, expect, it } from "vitest";
import { displayValue, processHref, processIdFromHash, processTone } from "./processes.model";

describe("process view route model", () => {
  it("round-trips a process id through the hash query", () => {
    const href = processHref("process:review/1");
    expect(processIdFromHash(href)).toBe("process:review/1");
  });

  it("returns null when no process query exists", () => {
    expect(processIdFromHash("#/processes")).toBeNull();
  });

  it("maps terminal and waiting states to stable tones", () => {
    expect(processTone("succeeded")).toBe("success");
    expect(processTone("waiting")).toBe("warning");
    expect(processTone("failed")).toBe("danger");
    expect(processTone("running")).toBe("info");
  });

  it("formats empty and structured values without throwing", () => {
    expect(displayValue(null)).toBe("-");
    expect(displayValue({ status: "ready" })).toBe('{"status":"ready"}');
  });
});