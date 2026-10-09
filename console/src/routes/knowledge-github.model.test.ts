import { describe, expect, it } from "vitest";
import { decodeGithubSources, githubConnectionInputValid } from "./knowledge-github.model";

function payload() {
  return {
    indexed: false, complete: true, gaps: [],
    sources: [{
      repository_alias: "example-app", location: "example/app", revision: 1, enabled: false,
      knowledge_source: {
        credential_reference: "public", knowledge_read_enabled: true,
        observed_commit: "a".repeat(40), readme_digest: "b".repeat(64),
        observed_at: "2026-10-09T00:00:00+00:00",
      },
    }],
  };
}

describe("GitHub knowledge sources", () => {
  it("does not infer scan consent or indexing from verified read access", () => {
    const result = decodeGithubSources(payload());
    expect(result.sources[0]?.knowledge_source?.knowledge_read_enabled).toBe(true);
    expect(result.sources[0]?.enabled).toBe(false);
  });
  it("preserves absent knowledge state for a legacy scan registration", () => {
    const value = { ...payload(), sources: [{ ...payload().sources[0], knowledge_source: null }] };
    expect(decodeGithubSources(value).sources[0]?.knowledge_source).toBeNull();
  });
  it.each([
    { indexed: true },
    { sources: [{ ...payload().sources[0], revision: 0 }] },
    { sources: [{ ...payload().sources[0], enabled: "true" }] },
    { sources: [{ ...payload().sources[0], knowledge_source: {
      ...payload().sources[0]!.knowledge_source, credential_reference: "token",
    } }] },
    { sources: [{ ...payload().sources[0], knowledge_source: {
      ...payload().sources[0]!.knowledge_source, observed_commit: "not-a-commit",
    } }] },
  ])("rejects malformed evidence %#", (overrides) => {
    expect(() => decodeGithubSources({ ...payload(), ...overrides })).toThrow();
  });
  it.each(["example/..", "example/.", "https://example.com/app", "example/app/extra"])(
    "rejects malformed repository %s", (location) => {
      expect(githubConnectionInputValid("example-app", location)).toBe(false);
    },
  );
  it("accepts a bounded alias and repository", () => {
    expect(githubConnectionInputValid("example-app", "example/app")).toBe(true);
  });
});
