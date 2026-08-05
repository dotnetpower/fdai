import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

const consoleStyles = readFileSync(fileURLToPath(new URL("./styles.css", import.meta.url)), "utf8");
const mockStyles = readFileSync(
  fileURLToPath(new URL("../../mocks/ui/assets/calm-slate.css", import.meta.url)),
  "utf8",
);
const sharedTokens = readFileSync(
  fileURLToPath(new URL("../../ui/calm-slate-tokens.css", import.meta.url)),
  "utf8",
);

describe("shared Calm Slate tokens", () => {
  test("keeps foundation tokens in one stylesheet consumed by Console and mocks", () => {
    expect(consoleStyles).toContain('@import url("../../ui/calm-slate-tokens.css")');
    expect(mockStyles).toContain('@import url("../../../ui/calm-slate-tokens.css")');
    expect(sharedTokens).toContain("--cs-radius: 8px");
    expect(sharedTokens).toContain("--cs-font-size: 14px");
    expect(consoleStyles).toContain("--font-sans: var(--cs-font)");
    expect(mockStyles).toContain("font-size: var(--cs-font-size)");
    expect(mockStyles).not.toContain("--cs-radius: 14px");
    expect(mockStyles).not.toContain("--cs-font:");
  });
});
