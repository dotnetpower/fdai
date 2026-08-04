import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

const index = readFileSync(fileURLToPath(new URL("../index.html", import.meta.url)), "utf8");
const main = readFileSync(fileURLToPath(new URL("./main.tsx", import.meta.url)), "utf8");

describe("console stylesheet entry", () => {
  test("keeps the stylesheet owned by the document across SPA hot updates", () => {
    expect(index).toContain('<link rel="stylesheet" href="/src/styles.css" />');
    expect(main).not.toContain('import "./styles.css"');
  });
});
