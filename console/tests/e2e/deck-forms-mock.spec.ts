import { expect, test, type FrameLocator, type Page } from "@playwright/test";

import { openDeck, origin, pressPreview } from "./deck-mock-page";

// Response forms of the one Command deck mock. Every form renders inside the same assistant turn
// anatomy, never runs a managed-resource change, and keeps unknowns explicit.

async function expectContained(page: Page, frame: FrameLocator) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const layout = await frame.locator("#ds-workspace").evaluate((workspace) => {
    const fits = (selector: string) => {
      const node = workspace.querySelector(selector)!;
      return node.scrollWidth <= node.clientWidth;
    };
    return {
      document: document.documentElement.scrollWidth <= innerWidth,
      workspace: workspace.scrollWidth <= workspace.clientWidth,
      transcript: fits("#ds-transcript"),
      turn: fits(".cs-deck-agent-turn"),
      composer: fits("#ds-composer"),
      composerBottom: workspace.querySelector("#ds-composer")!.getBoundingClientRect().bottom,
      height: innerHeight,
    };
  });
  expect(layout).toMatchObject({ document: true, workspace: true, transcript: true, turn: true, composer: true });
  expect(layout.composerBottom).toBeLessThanOrEqual(layout.height + 1);
}

test.describe("Command deck response forms", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "The desktop scenario owns the ordered viewport sequence.");
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ reducedMotion: "reduce" });
  });

  test("keeps the incident brief inside one assistant turn with honest, scannable state", async ({ page }, testInfo) => {
    const { frame, errors } = await openDeck(page, { form: "incident", scenario: "open" });
    await expect(frame.getByRole("heading", { level: 1 })).toHaveText("Command deck");
    await expect(frame.locator("#ds-conversation-title")).toHaveText("What happened with INC-260928-08?");
    await expect(frame.locator(".cs-deck-user-turn")).toHaveCount(1);
    const turn = frame.locator(".cs-deck-agent-turn");
    await expect(turn).toHaveCount(1);
    await expect(turn.getByRole("heading", { level: 3 })).toHaveText("Operational alert route unresolved");
    const status = turn.locator(".cs-deck-status-line");
    await expect(status).toContainText("Open at last record");
    await expect(status).toContainText("Current status unknown");
    await expect(turn.locator(".cs-deck-status-note")).toContainText("Not live");
    for (const fact of ["Customer impact", "Not established", "Delivery and recovery", "Not verified", "Response owner", "Not recorded"]) {
      await expect(turn.locator(".cs-deck-answer-facts")).toContainText(fact);
    }
    await expect(turn.locator(".cs-deck-answer-next")).toContainText("read-only check");
    await expect(turn.locator(".cs-deck-verification")).toContainText("Current state unknown");
    const timeline = turn.locator(".cs-deck-disclosure").first();
    await expect(timeline).not.toHaveAttribute("open", "");
    await timeline.locator(":scope > summary").click();
    await expect(timeline).toContainText("Observation window: 3m 45s.");
    await expect(timeline.locator(".cs-deck-timeline > li")).toHaveCount(3);
    await expect(frame.getByRole("button", { name: /execute|approve|apply/i })).toHaveCount(0);

    await turn.locator('.cs-deck-prose a.cs-deck-cite[aria-label*="audit:68882"]').first().click();
    const source = turn.locator(".cs-deck-source.is-target");
    await expect(source).toContainText("audit:68882");
    await source.click();
    await expect(source).toHaveAttribute("aria-expanded", "true");
    await expect(turn.locator(".cs-deck-source-detail:not([hidden])")).toContainText("No current binding readback");
    expect(errors).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath("deck-incident-desktop.png") });
  });

  test("records local questions without requests, markup injection, or a new answer", async ({ page }) => {
    const { frame, requests, errors } = await openDeck(page, { form: "incident", scenario: "open" });
    const before = requests.length;
    const typed = "<img src=x onerror=alert(1)> 근거를 확인해 주세요";
    await frame.locator("#ds-input").fill(typed);
    await frame.locator("#ds-input").press("Enter");
    await expect(frame.locator("#ds-composer-note")).toContainText("Preview only");
    await expect(frame.locator("#ds-input")).toHaveValue(typed);
    await expect(frame.locator("#ds-turns img")).toHaveCount(0);
    await expect(frame.locator(".cs-deck-agent-turn")).toHaveCount(1);
    expect(requests.slice(before)).toEqual([]);
    expect(requests.every((url) => url.startsWith(origin))).toBe(true);
    expect(errors).toEqual([]);
  });

  test("keeps a governed change a draft with seven named safeguards", async ({ page }) => {
    const { frame, errors } = await openDeck(page, { form: "change", scenario: "proposal" });
    const card = frame.locator(".cs-deck-request.is-proposal");
    await expect(card.getByRole("heading", { level: 4 })).toHaveText("Restart example-api revision 0043");
    await expect(card.locator(".cs-deck-safeguard")).toHaveCount(7);
    await expect(card.locator('.cs-deck-safeguard[data-state="missing"]')).toContainText("Two-phase audit");
    const submit = card.getByRole("button", { name: "Submit for human review" });
    await expect(submit).toBeDisabled();
    await expect(submit).toHaveAccessibleDescription("Blocked until all seven safeguards are ready");
    await card.getByRole("button", { name: "Discard draft" }).click();
    await expect(card.locator(".cs-deck-request-state")).toHaveText("Discarded");
    await expect(card.getByRole("button")).toHaveCount(2);
    for (const button of await card.getByRole("button").all()) await expect(button).toBeDisabled();
    await expect(frame.locator(".cs-deck-agent-turn").last()).toContainText("Nothing was submitted or changed.");

    await pressPreview(frame, 'button[data-scenario="verification"]');
    await expect(frame.locator("body")).toHaveAttribute("data-deck-state", "settled");
    const turn = frame.locator(".cs-deck-agent-turn");
    await expect(turn.locator(".cs-deck-turn-head .cs-deck-answer-state")).toHaveText("Partial");
    await expect(turn.locator(".cs-deck-evidence-group")).toHaveCount(3);
    await expect(turn).toContainText("The provider accepting the restart is not proof of recovery.");
    expect(errors).toEqual([]);
  });

  test("asks consent before memory and keeps a document's structure", async ({ page }) => {
    const { frame, errors } = await openDeck(page, { form: "memory", scenario: "retention" });
    const consent = frame.locator(".cs-deck-request.is-consent");
    await expect(consent.locator(".cs-deck-request-state")).toHaveText("Consent required");
    await expect(consent).toContainText("Raw logs, secrets, temporary state, and unverified claims are excluded.");
    await consent.getByRole("button", { name: "Review retention request" }).click();
    await expect(consent.locator(".cs-deck-request-state")).toHaveText("In review");

    await pressPreview(frame, 'button[data-scenario="document"]');
    await expect(frame.locator("body")).toHaveAttribute("data-deck-state", "settled");
    const documentBlock = frame.locator(".cs-deck-document");
    await expect(documentBlock.getByRole("heading", { level: 4 })).toHaveText("Application readiness investigation");
    await expect(documentBlock.getByRole("heading", { level: 5 })).toHaveText(["Objective", "Verified findings", "Limits",
      "Response procedure", "Output contract", "Machine-readable summary"]);
    await expect(documentBlock.getByRole("table", { name: "Markdown response output contract" })).toBeVisible();
    const source = documentBlock.locator(".cs-deck-disclosure");
    await source.locator(":scope > summary").click();
    await expect(source.locator(".cs-deck-code")).toContainText("# Application readiness investigation");
    await expect(documentBlock).toContainText("execution_authority: false");
    expect(errors).toEqual([]);
  });

  test("replays the shared investigation fixtures in the same deck", async ({ page }) => {
    const { frame, errors } = await openDeck(page, { form: "investigation", scenario: "drift" });
    await expect(frame.locator(".cs-deck-investigation")).toHaveCount(1);
    await expect(frame.locator(".cs-deck-wave")).toHaveCount(3);
    await expect(frame.getByRole("button", { name: "Draft remediation" })).toBeVisible();
    await expect(frame.locator('button[data-form="investigation"]')).toHaveAttribute("aria-pressed", "true");
    expect(errors).toEqual([]);
  });

  test("keeps each form contained at constrained and mobile sizes", async ({ page }, testInfo) => {
    for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport);
      const cases: ReadonlyArray<readonly [string, string]> = [["incident", "open"], ["change", "proposal"], ["memory", "document"], ["answer", "connected"]];
      for (const [form, scenario] of cases) {
        const { frame } = await openDeck(page, { form, scenario });
        await expectContained(page, frame);
        await page.screenshot({ path: testInfo.outputPath(`deck-${form}-${viewport.width}x${viewport.height}.png`) });
      }
    }
  });
});
