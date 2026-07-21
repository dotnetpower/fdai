import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

const mock = readFileSync(
  fileURLToPath(new URL("../../../mocks/ui/settings.html", import.meta.url)),
  "utf8",
);
const mockStyles = readFileSync(
  fileURLToPath(new URL("../../../mocks/ui/assets/calm-slate.css", import.meta.url)),
  "utf8",
);
const controls = readFileSync(
  fileURLToPath(new URL("../routes/settings.controls.tsx", import.meta.url)),
  "utf8",
);
const display = readFileSync(
  fileURLToPath(new URL("../routes/settings.display.tsx", import.meta.url)),
  "utf8",
);
const context = readFileSync(
  fileURLToPath(new URL("../routes/settings.context.tsx", import.meta.url)),
  "utf8",
);
const styles = readFileSync(fileURLToPath(new URL("../styles.css", import.meta.url)), "utf8");

describe("Settings controls", () => {
  test("defines the Settings surface in the Calm Slate mockup first", () => {
    expect(mock).toContain('class="cs-settings-segmented"');
    expect(mock).toContain('class="cs-settings-toggle-track"');
    expect(mock).toContain('class="cs-settings-input"');
    expect(mock).toContain('class="cs-settings-segmented is-four"');
    expect(mock).toContain('class="cs-btn" type="button" disabled');
    expect(mockStyles).toContain(".cs-settings-segmented button {");
    expect(mockStyles).toContain("font: 13px var(--cs-font)");
    expect(mockStyles).toContain(".cs-settings-toggle input:checked + .cs-settings-toggle-track");
    expect(mockStyles).toContain(".cs-settings-segmented { grid-auto-columns: minmax(0, 1fr); }");
  });

  test("maps the approved controls into the production Settings route", () => {
    expect(controls).toContain('class="settings-segmented"');
    expect(display).toContain('class="settings-toggle-control"');
    expect(styles).toMatch(/\.settings-segmented button \{[^}]*font: inherit;/s);
    expect(styles).toContain(".settings-route button.secondary");
    expect(styles).toContain(".settings-route .form-input");
    expect(styles).toContain(".settings-segmented { grid-auto-columns: minmax(0, 1fr); }");
    expect(context).toContain('aria-label={t("settings.timezone")}');
    expect(styles.indexOf("/* Console settings")).toBeGreaterThan(styles.length * 0.7);
  });
});
