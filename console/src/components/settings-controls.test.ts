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
const mockModels = readFileSync(
  fileURLToPath(new URL("../../../mocks/ui/settings-models.html", import.meta.url)),
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
const models = readFileSync(
  fileURLToPath(new URL("../routes/settings-models.tsx", import.meta.url)),
  "utf8",
);
const styles = readFileSync(fileURLToPath(new URL("../styles.css", import.meta.url)), "utf8");

describe("Settings controls", () => {
  test("defines the Settings surface in the Calm Slate mockup first", () => {
    expect(mock).toContain("cs-settings-segmented");
    expect(mock).toContain("cs-settings-toggle-track");
    expect(mock).toContain("cs-settings-input");
    expect(mock).toContain("cs-control-segmented is-five");
    expect(mock).toContain("Capture model request and response trace");
    expect(mock).toContain("Account preferences are up to date");
    expect(mock).toContain('class="cs-control-button" type="button" disabled');
    expect(mockStyles).toContain(".cs-settings-segmented button {");
    expect(mockStyles).toContain("font: 13px var(--cs-font)");
    expect(mockStyles).toContain(".cs-settings-toggle input:checked + .cs-settings-toggle-track");
    expect(mockStyles).toContain(".cs-settings-segmented { grid-auto-columns: minmax(0, 1fr); }");
    expect(mockModels).toContain('class="cs-domain-list cs-control-policy-list"');
    expect(mockModels).toContain('class="cs-control-policy-state"');
    expect(mockModels).not.toContain('<textarea class="cs-settings-input" aria-label="Allowed domains"');
  });

  test("maps the approved controls into the production Settings route", () => {
    expect(controls).toContain('class="settings-segmented"');
    expect(display).toContain('class="settings-toggle-control"');
    expect(styles).toMatch(/\.settings-segmented button \{[^}]*font: inherit;/s);
    expect(styles).toContain(".settings-route button.secondary");
    expect(styles).toContain(".settings-route .form-input");
    expect(styles).toContain(".settings-segmented { grid-auto-columns: minmax(0, 1fr); }");
    expect(styles).toContain(".settings-save-bar");
    expect(styles).toContain(".settings-route > .settings-section:first-of-type");
    expect(styles).toContain(".settings-list { border-bottom: 0; }");
    expect(styles).toContain(".settings-route > .settings-iam-panel");
    expect(styles).toContain(".settings-iam-route .settings-iam-panel");
    expect(styles).toContain(".operator-memory-route .data-table td > span > strong");
    expect(controls).toContain('class="settings-section-head"');
    expect(context).toContain('aria-label={t("settings.timezone")}');
    expect(models).toContain('class="settings-domain-list cs-control-policy-list"');
    expect(models).toContain('class="settings-domain-add"');
    expect(styles.indexOf("/* Console settings")).toBeGreaterThan(styles.length * 0.7);
  });
});
