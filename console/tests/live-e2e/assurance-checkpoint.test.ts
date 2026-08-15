import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  buildAssuranceCheckpoint,
  parseAssuranceCheckpoint,
  pendingQuestions,
  readAssuranceCheckpoint,
  resumableResults,
  writeAssuranceCheckpoint,
  type AssuranceCheckpointBinding,
} from "./assurance-checkpoint";

const BINDING: AssuranceCheckpointBinding = {
  source_revision: "0".repeat(40),
  configuration_digest: `sha256:${"a".repeat(64)}`,
  workspace_patch_digest: `sha256:${"b".repeat(64)}`,
};
const QUESTION_IDS = ["en-aggregation-1", "ko-aggregation-1", "en-inventory-1"];
const RESULTS = [{ question_id: "en-aggregation-1", passed: true }];

function checkpoint() {
  return buildAssuranceCheckpoint(BINDING, QUESTION_IDS, RESULTS);
}

describe("parseAssuranceCheckpoint", () => {
  it("accepts a checkpoint it produced", () => {
    expect(parseAssuranceCheckpoint(JSON.parse(JSON.stringify(checkpoint())))).not.toBeNull();
  });

  it("rejects a corrupted result set instead of importing partial evidence", () => {
    const tampered = { ...checkpoint(), results: [{ question_id: "en-aggregation-1", passed: false }] };
    expect(parseAssuranceCheckpoint(tampered)).toBeNull();
  });

  it("rejects results outside the recorded cohort and duplicate results", () => {
    expect(parseAssuranceCheckpoint({
      ...checkpoint(),
      results: [{ question_id: "unknown-1" }],
    })).toBeNull();
    expect(parseAssuranceCheckpoint({
      ...checkpoint(),
      results: [RESULTS[0], RESULTS[0]],
    })).toBeNull();
  });

  it("rejects malformed shapes and unknown schema versions", () => {
    expect(parseAssuranceCheckpoint(null)).toBeNull();
    expect(parseAssuranceCheckpoint("{}")).toBeNull();
    expect(parseAssuranceCheckpoint({ ...checkpoint(), schema_version: "9.9.9" })).toBeNull();
    expect(parseAssuranceCheckpoint({ ...checkpoint(), binding: {} })).toBeNull();
    expect(parseAssuranceCheckpoint({ ...checkpoint(), question_ids: [] })).toBeNull();
    expect(parseAssuranceCheckpoint({ ...checkpoint(), results: "all" })).toBeNull();
  });
});

describe("resumableResults", () => {
  it("resumes only when the provenance binding and cohort match exactly", () => {
    const expected = { binding: BINDING, questionIds: QUESTION_IDS };
    expect(resumableResults(checkpoint(), expected)).toHaveLength(1);
  });

  it("discards a checkpoint from a different source revision or workspace", () => {
    const expected = { binding: BINDING, questionIds: QUESTION_IDS };
    for (const field of ["source_revision", "configuration_digest", "workspace_patch_digest"] as const) {
      const drifted = buildAssuranceCheckpoint(
        { ...BINDING, [field]: `${BINDING[field]}-changed` },
        QUESTION_IDS,
        RESULTS,
      );
      expect(resumableResults(drifted, expected)).toEqual([]);
    }
  });

  it("discards a checkpoint whose cohort order or size differs", () => {
    expect(resumableResults(buildAssuranceCheckpoint(BINDING, [...QUESTION_IDS].reverse(), RESULTS), {
      binding: BINDING,
      questionIds: QUESTION_IDS,
    })).toEqual([]);
    expect(resumableResults(buildAssuranceCheckpoint(BINDING, QUESTION_IDS.slice(0, 2), RESULTS), {
      binding: BINDING,
      questionIds: QUESTION_IDS,
    })).toEqual([]);
  });

  it("treats a missing checkpoint as a fresh run", () => {
    expect(resumableResults(null, { binding: BINDING, questionIds: QUESTION_IDS })).toEqual([]);
  });
});

describe("pendingQuestions", () => {
  it("keeps cohort order and skips completed questions", () => {
    const questions = QUESTION_IDS.map((question_id) => ({ question_id }));
    expect(pendingQuestions(questions, RESULTS).map((item) => item.question_id))
      .toEqual(["ko-aggregation-1", "en-inventory-1"]);
    expect(pendingQuestions(questions, [])).toHaveLength(3);
  });
});

describe("checkpoint persistence", () => {
  it("round-trips through an atomic write", async () => {
    const directory = await mkdtemp(join(tmpdir(), "fdai-assurance-"));
    const path = join(directory, "nested", "checkpoint.json");

    await writeAssuranceCheckpoint(path, checkpoint());

    expect(await readAssuranceCheckpoint(path)).not.toBeNull();
    expect((await readFile(path, "utf8")).endsWith("\n")).toBe(true);
  });

  it("treats a missing or torn checkpoint as a fresh run", async () => {
    const directory = await mkdtemp(join(tmpdir(), "fdai-assurance-"));
    const missing = join(directory, "absent.json");
    const torn = join(directory, "torn.json");
    await writeFile(torn, '{"schema_version": "1.0.0", "bind', "utf8");

    expect(await readAssuranceCheckpoint(missing)).toBeNull();
    expect(await readAssuranceCheckpoint(torn)).toBeNull();
  });
});
