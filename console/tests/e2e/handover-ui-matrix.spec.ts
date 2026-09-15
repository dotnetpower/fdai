import { expect, test } from "@playwright/test";
import { goalFixture, HANDOVER_GOAL, installHandoverUiFixture, SCOPED_CASE, SCOPED_SOURCE, SLOTS } from "./handover-ui-fixtures";
import { assertHandoverGeometry, assertTabOrder, enlargeHandoverText, recordUiEvidence } from "./handover-ui-measurements";

for (const locale of ["en", "ko"] as const) {
  test(`checklist ${locale} expanded extremes reflow after the desktop gate`, async ({ page, browser }, info) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const fixture = await installHandoverUiFixture(page);
    fixture.goal = goalFixture("ready_for_review", ["accept", "acknowledge"]);
    fixture.goal.scope_ref = `scope:${"example-".repeat(31)}`;
    fixture.goal.evidence = SLOTS.map((slot, index) => ({ slot, evidence_ref: `doc:${index}:${"a".repeat(246)}:v1`,
      digest: "d".repeat(64), kind: "document" }));
    const start = performance.now();
    await page.goto(`/documents?handover_goal=${HANDOVER_GOAL}&locale=${locale}`);
    const panel = page.locator(".handover-checklist");
    await expect(panel.locator("ol li")).toHaveCount(6);
    const readyMs = performance.now() - start;
    expect(readyMs).toBeLessThan(5000);
    await recordUiEvidence(info, "route-budget", { readyMs, budgetMs: 5000, browser: browser.version(), locale, venue: "synthetic-isolated" });
    for (const summary of await panel.locator("summary").all()) {
      await summary.focus();
      await page.keyboard.press("Enter");
    }
    await expect(panel.locator("details[open]")).toHaveCount(7);
    await expect(panel.locator("ol details summary").first()).toHaveAccessibleName(new RegExp(locale === "en" ? "Operating scope" : "운영 범위"));
    await assertHandoverGeometry(panel, info, `${locale}-desktop-expanded`);
    expect(info.errors).toEqual([]);
    await panel.locator("h3").scrollIntoViewIfNeeded();
    await page.screenshot({ path: info.outputPath(`${locale}-desktop-expanded.png`) });
    for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }, { width: 320, height: 844 }]) {
      await page.setViewportSize(viewport);
      await assertHandoverGeometry(panel, info, `${locale}-expanded-${viewport.width}`);
      await panel.locator("h3").scrollIntoViewIfNeeded();
      await page.screenshot({ path: info.outputPath(`${locale}-expanded-${viewport.width}.png`) });
    }
    const enlargement = await enlargeHandoverText(panel);
    await recordUiEvidence(info, "actual-text-enlargement", enlargement);
    await assertHandoverGeometry(panel, info, `${locale}-320-text-spacing`);
    await page.emulateMedia({ reducedMotion: "reduce", forcedColors: "active" });
    const refresh = panel.getByRole("button", { name: locale === "en" ? "Refresh evidence" : "근거 새로 고침", exact: true });
    await refresh.focus();
    await expect(refresh).toBeFocused();
    expect(await refresh.evaluate((element) => getComputedStyle(element).outlineStyle)).toBe("solid");
    await assertHandoverGeometry(panel, info, `${locale}-320-preferences`, false);
    expect(fixture.posts).toEqual([]);
  });

  test(`scoped ${locale} long draft and expanded retained evidence stay exact`, async ({ page, browser }, info) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const fixture = await installHandoverUiFixture(page);
    const longScope = `scope:${"example-".repeat(31)}`;
    fixture.catalog.scopes = ["scope:example", longScope];
    const start = performance.now();
    await page.goto(`/agent-oversight/mapping-reviews?scoped_case=${SCOPED_CASE}&locale=${locale}`);
    const panel = page.locator(".scoped-duty-workspace");
    await expect(panel.locator(".scoped-duty-facts code").filter({ hasText: "00000000-0000-0000-0000-000000000011" })).toBeVisible();
    const readyMs = performance.now() - start;
    expect(readyMs).toBeLessThan(5000);
    await recordUiEvidence(info, "route-budget", { readyMs, budgetMs: 5000, browser: browser.version(), locale, venue: "synthetic-isolated" });
    await panel.locator("#scoped-binding-0-scope_ref").selectOption(longScope);
    await panel.locator("#scoped-binding-0-kind").selectOption("schedule");
    await panel.locator("#scoped-binding-0-subject_ref").fill(`rotation:${"a".repeat(247)}`);
    await panel.locator("#scoped-binding-0-fallback").fill(`person:${"b".repeat(249)}`);
    await panel.locator("#scoped-binding-0-effective_from").fill("2026-09-15T11:00:00.123456Z");
    await panel.locator("#scoped-binding-0-effective_until").fill("2026-09-16T12:00:00.654321+00:00");
    await panel.locator("#scoped-justification").fill((locale === "en" ? "Reviewed synthetic scope and source. " : "합성 범위와 원본을 독립적으로 검토한 변경 사유입니다. ").repeat(100).slice(0, 2000));
    const retained = panel.locator("details").first();
    await retained.locator("summary").focus();
    await page.keyboard.press("Enter");
    expect(JSON.parse(await retained.locator("pre").innerText())).toEqual({ request: fixture.scopedCase.request, plan: fixture.scopedCase.plan });
    for (const theme of ["light", "dark"]) {
      await page.evaluate((value) => document.documentElement.setAttribute("data-theme", value), theme);
      await assertHandoverGeometry(panel, info, `${locale}-desktop-long-${theme}`);
    }
    expect(info.errors).toEqual([]);
    await page.evaluate(() => document.documentElement.setAttribute("data-theme", "light"));
    for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }, { width: 320, height: 844 }]) {
      await page.setViewportSize(viewport);
      await assertHandoverGeometry(panel, info, `${locale}-long-${viewport.width}`);
      await retained.locator("summary").scrollIntoViewIfNeeded();
      await page.screenshot({ path: info.outputPath(`${locale}-retained-${viewport.width}.png`) });
    }
    await enlargeHandoverText(panel);
    await assertHandoverGeometry(panel, info, `${locale}-long-320-text-spacing`);
    expect(JSON.parse(await retained.locator("pre").innerText())).toEqual({ request: fixture.scopedCase.request, plan: fixture.scopedCase.plan });
    await page.emulateMedia({ reducedMotion: "reduce", forcedColors: "active" });
    await panel.locator("#scoped-catalog").focus();
    await expect(panel.locator("#scoped-catalog")).toBeFocused();
    await assertHandoverGeometry(panel, info, `${locale}-long-320-preferences`, false);
    expect(fixture.posts).toEqual([]);
  });
}

test("scoped desktop keyboard traverses the complete valid form and recovers inserted rows", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = await installHandoverUiFixture(page);
  await page.goto("/agent-oversight/mapping-reviews");
  const panel = page.locator(".scoped-duty-workspace");
  await panel.locator("#scoped-binding-0-scope_ref").selectOption("scope:example");
  await panel.locator("#scoped-binding-0-subject_ref").fill("person:example-primary");
  await panel.locator("#scoped-binding-0-effective_from").fill("2026-09-15T11:00:00Z");
  await panel.locator("#scoped-binding-0-effective_until").fill("2026-09-16T12:00:00Z");
  await panel.locator("#scoped-justification").fill("Synthetic keyboard-only proposal validation, with no provider authority.");
  await panel.locator("#scoped-add-binding").focus();
  await page.keyboard.press("Enter");
  await expect(panel.locator("#scoped-binding-1-agent_name")).toBeFocused();
  await panel.getByRole("button", { name: "Remove declaration 2", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(panel.locator("#scoped-add-binding")).toBeFocused();
  const fields = ["agent_name", "scope_ref", "kind", "subject_ref", "duty", "effective_from", "effective_until"];
  await assertTabOrder(page, [panel.locator("#scoped-catalog"), ...fields.map((field) => panel.locator(`#scoped-binding-0-${field}`)),
    panel.getByRole("button", { name: "Remove declaration 1", exact: true }), panel.locator("#scoped-add-binding"),
    panel.locator("#scoped-supersedes"), panel.locator("#scoped-justification"), panel.getByRole("button", { name: "Request draft", exact: true }),
    panel.locator("#scoped-case-id"), panel.locator("#scoped-observation-agent"), panel.locator("#scoped-observation-scope")]);
  await panel.locator("#scoped-case-id").fill("invalid-synthetic-case");
  await panel.getByRole("button", { name: "Open case", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(panel.locator("#scoped-case-id")).toBeFocused();
  await expect(panel.locator("#scoped-case-id")).toHaveAttribute("aria-describedby", "scoped-case-id-error");
  await expect(panel.locator("#scoped-case-id-error")).toHaveAttribute("role", "alert");
  expect(fixture.posts).toEqual([]);
});

test("checklist desktop state transitions keep incomplete, accepted and failed evidence distinct", async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = await installHandoverUiFixture(page);
  let release!: () => void;
  fixture.readGate = new Promise<void>((resolve) => { release = resolve; });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(`/documents?handover_goal=${HANDOVER_GOAL}`);
  const panel = page.locator(".handover-checklist");
  await expect(panel.locator('.loading-skeleton[role="status"][aria-busy="true"]')).toBeVisible();
  expect(await panel.locator(".skeleton-shimmer").evaluateAll((elements) => elements.every((element) => getComputedStyle(element).animationName === "none"))).toBe(true);
  release();
  const states = ["not_started", "in_progress", "ready_for_review", "accepted", "stale", "blocked", "declined", "superseded"];
  const labels = ["Evidence checklist incomplete", "Evidence checklist incomplete", "Independent review pending", "Evidence accepted",
    "Source evidence is no longer current", "Evidence needs correction before review", "Handover declined", "Replaced by a newer handover"];
  for (const [index, state] of states.entries()) {
    fixture.goal = goalFixture(state, []);
    fixture.goal.revision = 10 + index;
    const reads = fixture.reads.length;
    await panel.getByRole("button", { name: "Refresh evidence", exact: true }).click();
    await expect.poll(() => fixture.reads.length).toBeGreaterThan(reads);
    await expect(panel.locator(".loading-skeleton")).toHaveCount(0);
    await expect(panel.getByRole("status").filter({ hasText: labels[index]! })).toBeVisible();
    await expect(panel.getByRole("button")).toHaveCount(1);
  }
  fixture.readStatus = 503;
  await panel.getByRole("button", { name: "Refresh evidence", exact: true }).click();
  await expect(panel.getByRole("alert")).toContainText("HTTP 503");
  await expect(panel.locator("ol")).toHaveCount(0);
  fixture.readStatus = 200;
  await panel.getByRole("button", { name: "Refresh evidence", exact: true }).click();
  await expect(panel.locator("ol li")).toHaveCount(6);
  await expect(panel.getByRole("alert")).toHaveCount(0);
  await recordUiEvidence(info, "state-matrix", { states, initialSkeleton: true, reducedMotion: true, errorRecovery: true });
  expect(fixture.posts).toEqual([]);
});

test("scoped desktop many declarations and exact held/observed provenance remain bounded", async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = await installHandoverUiFixture(page);
  await page.goto("/agent-oversight/mapping-reviews");
  const panel = page.locator(".scoped-duty-workspace");
  for (let count = 1; count < 30; count += 1) await panel.locator("#scoped-add-binding").click();
  await expect(panel.locator(".scoped-duty-binding")).toHaveCount(30);
  await expect(panel.locator("#scoped-add-binding")).toBeDisabled();
  await assertHandoverGeometry(panel, info, "scoped-30-declarations");
  const window = { source_revision: SCOPED_SOURCE, observed_at: "2026-09-15T11:59:45Z",
    expires_at: "2026-09-15T12:00:45Z", execution_authority: false };
  fixture.observation = { ...window, state: "held", agent_name: "Odin", scope_ref: "scope:example",
    primary_refs: [], backup_refs: [], escalation_refs: [], partial: true, invalid_cases: 1,
    held_reasons: Array.from({ length: 30 }, (_, index) => `synthetic_${index}_${"a".repeat(220)}`) };
  await panel.locator("#scoped-observation-scope").selectOption("scope:example");
  await panel.getByRole("button", { name: "Read current observation", exact: true }).click();
  const observation = panel.locator(".scoped-duty-observation");
  await expect(observation.getByText("Coverage held", { exact: true })).toBeVisible();
  await expect(observation.locator("details[open] li")).toHaveCount(30);
  fixture.observation = { ...window, state: "observed", agent_name: "Odin", scope_ref: "scope:example",
    primary_refs: Array.from({ length: 30 }, (_, index) => `person:primary-${index}-${"a".repeat(220)}`),
    backup_refs: Array.from({ length: 30 }, (_, index) => `person:backup-${index}-${"b".repeat(220)}`),
    escalation_refs: [], held_reasons: [], partial: false, invalid_cases: 0,
    case_id: "00000000-0000-0000-0000-000000000011", case_revision: 4,
    candidate_digest: "d".repeat(64), merge_commit_sha: "e".repeat(40), pr_ref: "https://example.com/review/1" };
  await panel.getByRole("button", { name: "Read current observation", exact: true }).click();
  await expect(observation.getByText("Observed at the recorded time", { exact: true })).toBeVisible();
  await observation.locator("summary").focus();
  await page.keyboard.press("Enter");
  await expect(observation.locator("pre")).toContainText("eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee");
  await expect(observation.getByRole("link")).toHaveAttribute("rel", "noopener noreferrer");
  await assertHandoverGeometry(panel, info, "scoped-observed-many");
  expect(fixture.posts).toEqual([]);
});
