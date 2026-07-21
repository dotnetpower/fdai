import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

const styles = readFileSync(fileURLToPath(new URL("../styles.css", import.meta.url)), "utf8");
const contentSurfaceStyles = styles
  .replace(/\.ontology-graph-key i\s*\{[^}]*\}/g, "")
  .replace(/\.architecture-edge-legend \.is-(?:dependency|attachment)\s*\{[^}]*\}/g, "");
const approvalRoute = readFileSync(
  fileURLToPath(new URL("../routes/hil-queue.tsx", import.meta.url)),
  "utf8",
);

describe("console visual boundary", () => {
  test("content surfaces do not use thick colored top or left edges", () => {
    expect(contentSurfaceStyles).not.toMatch(/border-left:\s*[2-9](?:px|rem|em)/);
    expect(contentSurfaceStyles).not.toMatch(/border-top:\s*[2-9](?:px|rem|em)/);
    expect(contentSurfaceStyles).not.toMatch(/box-shadow:\s*inset\s+[2-9](?:px)?\s+0/);
  });

  test("retired card rail and top-stamp patterns stay removed", () => {
    expect(styles).not.toContain(".kpi-card::before");
    expect(styles).not.toContain(".live-tile::before");
    expect(styles).not.toContain(".approval-card-rail");
    expect(approvalRoute).not.toContain("approval-card-rail");
  });
});
