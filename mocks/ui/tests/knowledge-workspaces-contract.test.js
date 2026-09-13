const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");

const uiRoot = join(__dirname, "..");
const sourcePages = ["knowledge.html", "github.html", "gitlab.html", "azure-devops.html"];
const sourceRenderer = readFileSync(join(uiRoot, "assets", "knowledge-sources.js"), "utf8");
const documentRenderer = readFileSync(join(uiRoot, "assets", "knowledge-documents.js"), "utf8");
const styles = readFileSync(join(uiRoot, "assets", "knowledge-workspaces.css"), "utf8");
const parityRenderer = readFileSync(join(uiRoot, "assets", "console-parity.js"), "utf8");
const documents = readFileSync(join(uiRoot, "documents.html"), "utf8");

test("Knowledge source mocks use the focused renderer and preserve route identity", () => {
  sourcePages.forEach((file) => {
    const html = readFileSync(join(uiRoot, file), "utf8");
    assert.match(html, /class="cs-knowledge-surface"/);
    assert.match(html, /data-preserve-page-title/);
    assert.match(html, /assets\/knowledge-workspaces\.css/);
    assert.match(html, /assets\/knowledge-sources\.js/);
    assert.match(html, /data-console-parity-page/);
    assert.match(html, /href="#knowledge-main">Skip to Knowledge content/);
  });
  assert.match(parityRenderer, /page\.renderer === "knowledge"/);
  assert.match(parityRenderer, /FDAI_KNOWLEDGE_RENDERER\.mount/);
  assert.doesNotMatch(parityRenderer, /\["Repositories", "18", "authorized scope"\]/);
});

test("Knowledge overview exposes all governed source destinations without authority claims", () => {
  for (const label of ["Documents", "GitHub", "GitLab", "Azure DevOps"]) {
    assert.match(sourceRenderer, new RegExp(`title: "${label}"`));
  }
  assert.match(sourceRenderer, /Repository knowledge requires integration setup/);
  assert.match(sourceRenderer, /Browser credentials/);
  assert.match(sourceRenderer, /Execution authority/);
  assert.match(sourceRenderer, /None/);
  assert.match(sourceRenderer, /settings-integrations\.html/);
});

test("Connector workspaces distinguish default, loading, connected, and error specimens", () => {
  for (const value of ["setup", "checking", "connected", "error"]) {
    assert.match(sourceRenderer, new RegExp(`<option value="${value}"`));
  }
  assert.match(sourceRenderer, /Illustrative connected state/);
  assert.match(sourceRenderer, /No live provider request was made/);
  assert.match(sourceRenderer, /No successful observation/);
  assert.match(sourceRenderer, /Cached success/);
  assert.match(sourceRenderer, /Not substituted/);
  assert.match(sourceRenderer, /aria-pressed/);
  assert.match(sourceRenderer, /data-kw-repository-search/);
  assert.match(sourceRenderer, /data-kw-retry/);
});

test("Documents keeps consent, custody, and failure states explicit", () => {
  assert.match(documents, /data-kw-document-form/);
  assert.match(documents, /id="document-consent" type="checkbox" required/);
  assert.match(documents, /data-kw-document-submit[\s\S]*disabled/);
  assert.match(documents, /No bytes leave this preview/);
  assert.match(documents, /payload not retained/);
  assert.match(documents, /data-kw-library-panel="loading"/);
  assert.match(documents, /data-kw-library-panel="empty"/);
  assert.match(documents, /data-kw-library-panel="unavailable"/);
  assert.match(documents, /execution authority/i);
  assert.match(documentRenderer, /Preview validated\. No upload or retention request was sent\./);
  assert.match(documentRenderer, /showLibraryState/);
});

test("Knowledge styling preserves focus, reflow, readable type, and user preferences", () => {
  assert.match(styles, /:focus-visible/);
  assert.match(styles, /@media \(max-width: 980px\)/);
  assert.match(styles, /@media \(max-width: 720px\)/);
  assert.match(styles, /@media \(max-width: 520px\)/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(styles, /@media \(forced-colors: active\)/);
  assert.match(styles, /--cs-type-caption-size: 12px/);
  assert.doesNotMatch(styles, /border-left:\s*[2-9]\d*px/);
  assert.doesNotMatch(styles, /border-top:\s*[2-9]\d*px/);
});
