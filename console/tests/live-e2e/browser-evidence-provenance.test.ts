import { describe, expect, it } from "vitest";

import { buildBrowserEvidenceProvenance } from "./browser-evidence-provenance";

describe("browser evidence provenance", () => {
  it("binds source and workspace state to canonical run configuration", () => {
    expect(buildBrowserEvidenceProvenance(
      "a".repeat(40),
      `sha256:${"b".repeat(64)}`,
      { schema_version: "1.0.0", routes: ["/overview"] },
    )).toEqual({
      source_revision: "a".repeat(40),
      configuration_digest: "sha256:71285b16907b8930f027a74fbcf0fa5b4e8d81087e03d243362018cd57838a7e",
      workspace_patch_digest: `sha256:${"b".repeat(64)}`,
    });
  });

  it("produces one digest for equivalent configurations with different key order", () => {
    const revision = "a".repeat(40);
    const patch = `sha256:${"b".repeat(64)}`;
    const first = buildBrowserEvidenceProvenance(
      revision,
      patch,
      { schema_version: "1.0.0", nested: { b: 2, a: 1 } },
    );
    const second = buildBrowserEvidenceProvenance(
      revision,
      patch,
      { nested: { a: 1, b: 2 }, schema_version: "1.0.0" },
    );
    expect(first.configuration_digest).toBe(second.configuration_digest);
  });

  it.each([
    [undefined, `sha256:${"b".repeat(64)}`, "FDAI_E2E_SOURCE_REVISION"],
    ["not-a-revision", `sha256:${"b".repeat(64)}`, "FDAI_E2E_SOURCE_REVISION"],
    ["a".repeat(40), undefined, "FDAI_E2E_WORKSPACE_PATCH_SHA256"],
    ["a".repeat(40), "not-a-digest", "FDAI_E2E_WORKSPACE_PATCH_SHA256"],
  ])("rejects incomplete provenance: %o", (revision, digest, message) => {
    expect(() => buildBrowserEvidenceProvenance(revision, digest, {})).toThrow(message);
  });

  it.each([
    [{ value: undefined }, "JSON values only"],
    [{ value: Number.POSITIVE_INFINITY }, "numbers must be finite"],
    [{ value: new Date("2026-08-14T00:00:00Z") }, "plain JSON objects"],
  ])("rejects a non-canonical run configuration: %o", (configuration, message) => {
    expect(() => buildBrowserEvidenceProvenance(
      "a".repeat(40),
      `sha256:${"b".repeat(64)}`,
      configuration,
    )).toThrow(message);
  });
});
