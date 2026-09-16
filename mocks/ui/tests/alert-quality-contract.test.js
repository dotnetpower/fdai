const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");

const uiRoot = join(__dirname, "..");
const html = readFileSync(join(uiRoot, "alert-quality.html"), "utf8");
const fixture = JSON.parse(
  readFileSync(
    join(uiRoot, "..", "..", "console", "src", "routes", "alert-quality.backend.fixture.json"),
    "utf8",
  ),
);

test("Alert quality mock uses the typed assessment denominators", () => {
  const assessment = fixture.assessment;
  for (const key of [
    "source_episodes",
    "notification_attempts",
    "confirmed_deliveries",
    "acknowledgements",
  ]) {
    const expected = assessment[key] === null ? "Not recorded" : String(assessment[key]);
    assert.match(
      html,
      new RegExp(`data-assessment-value="${key}"[^>]*>${expected}<`),
    );
  }
  assert.doesNotMatch(html, /Assessed alerts|Duplicate groups|Flapping signals/);
  assert.match(html, />Overlapping notification path</);
  assert.match(html, />1 duplicate path; 3 source episodes; delivery count not recorded</);
});

test("Alert quality findings retain visible mobile labels", () => {
  for (const label of ["Finding", "Evidence", "State", "Next safe step"]) {
    assert.match(html, new RegExp(`<td data-label="${label}">`));
  }
});
