import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const app = readFileSync(new URL("./app.tsx", import.meta.url), "utf8");
const deferredDeck = readFileSync(
  new URL("./deck/deferred-command-deck.tsx", import.meta.url),
  "utf8",
);
const documents = readFileSync(
  new URL("./routes/document-ingestion.tsx", import.meta.url),
  "utf8",
);
const settingsRoutes = [
  "settings-models.tsx",
  "settings-runtime.tsx",
  "settings-iam.tsx",
].map((file) => readFileSync(new URL(`./routes/${file}`, import.meta.url), "utf8"));

describe("Console route resilience", () => {
  it("binds every authenticated client before a recoverable startup access failure", () => {
    const accessCheck = app.indexOf("iamSelf = await withStartupTransportRetry");
    expect(accessCheck).toBeGreaterThan(0);
    for (const binding of [
      "setDeckUser(deckUserFromAuth(auth));",
      "setWorkflowAuth(auth);",
      "setPythonTaskAuth(auth);",
      "setUserContextAuth(auth);",
      "setChatAuth(auth);",
    ]) {
      expect(app.indexOf(binding)).toBeGreaterThan(0);
      expect(app.indexOf(binding)).toBeLessThan(accessCheck);
    }
  });

  it("keeps every top-level lazy surface inside a visible error and loading boundary", () => {
    expect(app).not.toContain("fallback={null}");
    expect(app).toContain('class="settings-overlay-scrim"');
    expect(app).toContain(
      "<DeferredCommandDeck client={client} routeLabel={backgroundPanel.label} />",
    );
    expect(readFileSync(new URL("./main.tsx", import.meta.url), "utf8"))
      .toContain("<PanelErrorBoundary>");
    expect(deferredDeck).toContain('import("./command-deck")');
    expect(deferredDeck).toContain("DECK_ACTIVATE_EVENT");
    expect(deferredDeck).toContain("useState(hasPendingDeckOpen)");
    expect(deferredDeck).toContain("offerProactiveHandover(client, storage)");
  });

  it("does not mount a hidden data route behind a direct Settings URL", () => {
    expect(app).toContain("{!settingsOpen || hasTransientRoute() ? (");
  });

  it("keeps blocking initial-load errors retryable", () => {
    for (const source of settingsRoutes) {
      expect(source).toContain("<ErrorState");
      expect(source).toMatch(/onRetry=|failedLoad/);
    }
    expect(documents).toContain("capabilityRevision");
    expect(documents).toContain('knowledgeText("retry")');
  });
});
