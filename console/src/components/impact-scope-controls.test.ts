import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

const mock = readFileSync(
  fileURLToPath(new URL("../../../mocks/ui/blast-radius.html", import.meta.url)),
  "utf8",
);
const mockStyles = readFileSync(
  fileURLToPath(new URL("../../../mocks/ui/assets/calm-slate.css", import.meta.url)),
  "utf8",
);
const route = readFileSync(
  fileURLToPath(new URL("../routes/blast-radius.tsx", import.meta.url)),
  "utf8",
);
const styles = readFileSync(fileURLToPath(new URL("../styles.css", import.meta.url)), "utf8");

describe("Impact scope controls", () => {
  test("defines the complete control system in the mockup first", () => {
    expect(mock).toContain('class="cs-query-panel cs-mb-24"');
    expect(mock).toContain('class="cs-query-check-box"');
    expect(mock).toContain('class="cs-btn is-primary"');
    expect(mockStyles).toContain(".cs-query-input");
    expect(mockStyles).toContain(".cs-query-check input:checked + .cs-query-check-box");
    expect(mockStyles).toContain(".cs-btn:disabled");
    expect(mockStyles).toContain(".cs-query-action .cs-btn { width: 100%; }");
  });

  test("maps the approved mockup controls into the production route", () => {
    expect(route).toContain('class="impact-query-panel"');
    expect(route).toContain('class="impact-query-input"');
    expect(route).toContain('class="impact-query-check-box"');
    expect(route).toContain('class="btn primary impact-query-submit"');
    expect(route.match(/aria-pressed=\{view === "(impact|map|table)"\}/g)).toHaveLength(3);
    expect(styles).toContain(".impact-query-check input:checked + .impact-query-check-box");
    expect(styles).toContain(".impact-query-submit:disabled");
    expect(styles).toContain(".impact-query-submit { width: 100%; }");
    expect(styles).toContain(".segmented-control button:focus-visible");
  });
});
