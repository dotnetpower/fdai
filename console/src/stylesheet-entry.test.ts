import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

const index = readFileSync(fileURLToPath(new URL("../index.html", import.meta.url)), "utf8");
const main = readFileSync(fileURLToPath(new URL("./main.tsx", import.meta.url)), "utf8");
const favicon = readFileSync(
  fileURLToPath(new URL("../public/brand/fdai-favicon.svg", import.meta.url)),
  "utf8",
);

describe("console stylesheet entry", () => {
  test("uses the FDAI brand logo as the browser icon", () => {
    expect(index).toContain(
      '<link rel="icon" type="image/svg+xml" href="/brand/fdai-favicon.svg" />',
    );
    expect(favicon).toContain('data-favicon-underlay="true" fill="#FFFFFF"');
  });

  test("keeps the stylesheet owned by the document across SPA hot updates", () => {
    expect(index).toContain('<link rel="stylesheet" href="/src/styles.css" />');
    expect(main).not.toContain('import "./styles.css"');
  });
});
