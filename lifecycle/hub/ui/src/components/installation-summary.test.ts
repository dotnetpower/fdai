import { describe, expect, it } from "vitest";
import { safeConsoleUrl } from "./installation-summary";

describe("safeConsoleUrl", () => {
  it("accepts only exact HTTPS origins", () => {
    expect(safeConsoleUrl("https://console.example.com")).toBe("https://console.example.com/");
    expect(safeConsoleUrl("https://console.example.com/")).toBe("https://console.example.com/");
    for (const value of [
      "http://console.example.com",
      "https://user@console.example.com",
      "https://console.example.com/path",
      "https://console.example.com/?next=other",
      "javascript:alert(1)",
      "not-a-url",
      null,
    ]) {
      expect(safeConsoleUrl(value)).toBeNull();
    }
  });
});
