import { describe, expect, it } from "vitest";
import { parseGroundedCodeArtifacts } from "./backend";

const SHA = "a".repeat(64);

describe("parseGroundedCodeArtifacts", () => {
  it("accepts a bounded artifact whose ref matches its digest", () => {
    const artifacts = parseGroundedCodeArtifacts([
      {
        artifact_ref: `code:sha256:${SHA}`,
        language: "python",
        content: "print('ok')\n",
        sha256: SHA,
        validation_status: "valid",
        validation_detail: null,
      },
    ]);

    expect(artifacts).toHaveLength(1);
    expect(artifacts[0]?.validation_status).toBe("valid");
  });

  it("rejects mismatched refs, unknown states, and oversized content", () => {
    const base = {
      artifact_ref: `code:sha256:${SHA}`,
      language: "python",
      content: "pass\n",
      sha256: SHA,
      validation_status: "valid",
      validation_detail: null,
    };

    expect(parseGroundedCodeArtifacts([{ ...base, artifact_ref: "code:sha256:bad" }])).toEqual([]);
    expect(parseGroundedCodeArtifacts([{ ...base, validation_status: "executed" }])).toEqual([]);
    expect(parseGroundedCodeArtifacts([{ ...base, content: "x".repeat(64 * 1024 + 1) }])).toEqual([]);
    expect(parseGroundedCodeArtifacts([{
      ...base,
      validation_detail: "x".repeat(4 * 1024 + 1),
    }])).toEqual([]);
  });

  it("caps the response to eight artifacts", () => {
    const artifacts = Array.from({ length: 10 }, () => ({
      artifact_ref: `code:sha256:${SHA}`,
      language: "python",
      content: "pass\n",
      sha256: SHA,
      validation_status: "valid",
      validation_detail: null,
    }));

    expect(parseGroundedCodeArtifacts(artifacts)).toHaveLength(8);
  });
});
