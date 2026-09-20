import { describe, expect, it } from "vitest";

import { parseModelTrace, parsePantheonPromptProfiles } from "./backend";

const SHA = "a".repeat(64);

function trace() {
  return {
    schema_version: 1,
    redacted: true,
    omitted_calls: 0,
    calls: [{
      call_id: "model-call-1",
      kind: "answer-stream",
      model: "test-model",
      status: "completed",
      started_at: "2026-07-31T01:00:00Z",
      completed_at: "2026-07-31T01:00:01Z",
      duration_ms: 1000,
      request: {
        messages: [
          { role: "system", content: "system" },
          { role: "user", content: "question" },
        ],
        sha256: SHA,
      },
      response: { role: "assistant", content: "answer", sha256: SHA },
      usage: { prompt_tokens: 10, completion_tokens: 2, total_tokens: 12 },
      redactions: [{ rule: "url", replacements: 1 }],
    }],
  };
}

describe("parseModelTrace", () => {
  it("accepts one bounded redacted provider trace", () => {
    expect(parseModelTrace(trace())).toEqual(trace());
  });

  it("accepts a content-free dynamic prompt manifest", () => {
    const promptManifest = {
      system_text_sha256: SHA,
      layers: [{ id: "adaptive-common", version: 1, layer: "base", token_estimate: 12 }],
      token_estimate: 12,
      profile_id: "adaptive-answer",
      profile_version: 1,
      profile_digest: `sha256:${SHA}`,
      system_token_budget: 100,
      request_token_budget: 200,
      reserved_output_tokens: 50,
    };

    expect(parseModelTrace({
      ...trace(),
      calls: [{ ...trace().calls[0], prompt_manifest: promptManifest }],
    })?.calls[0]?.prompt_manifest).toEqual(promptManifest);
  });

  it("rejects a malformed prompt manifest instead of dropping it", () => {
    expect(parseModelTrace({
      ...trace(),
      calls: [{
        ...trace().calls[0],
        prompt_manifest: { system_text_sha256: "bad", layers: [] },
      }],
    })).toBeUndefined();
  });

  it("rejects a prompt manifest with a noncanonical profile id", () => {
    const promptManifest = {
      system_text_sha256: SHA,
      layers: [],
      token_estimate: 0,
      profile_id: "Invalid Profile",
      profile_version: 1,
      profile_digest: `sha256:${SHA}`,
      system_token_budget: 100,
      request_token_budget: 200,
      reserved_output_tokens: 50,
    };

    expect(parseModelTrace({
      ...trace(),
      calls: [{ ...trace().calls[0], prompt_manifest: promptManifest }],
    })).toBeUndefined();
  });

  it.each([
    { schema_version: 2 },
    { redacted: false },
    { calls: Array(9).fill(trace().calls[0]) },
    { calls: [{ ...trace().calls[0], completed_at: "2026-07-31T00:59:59Z" }] },
    { calls: [{ ...trace().calls[0], status: "incomplete" }] },
    { calls: [{ ...trace().calls[0], request: { ...trace().calls[0]!.request, sha256: "bad" } }] },
    { calls: [{ ...trace().calls[0], response: { ...trace().calls[0]!.response, role: "tool" } }] },
  ])("rejects malformed or internally inconsistent traces", (override) => {
    expect(parseModelTrace({ ...trace(), ...override })).toBeUndefined();
  });

  it("accepts an unfinished call only without completion fields or response", () => {
    const unfinished = {
      ...trace().calls[0],
      status: "incomplete",
      completed_at: null,
      duration_ms: null,
      response: null,
      usage: null,
    };

    expect(parseModelTrace({ ...trace(), calls: [unfinished] })?.calls[0]?.status)
      .toBe("incomplete");
  });
});

describe("parsePantheonPromptProfiles", () => {
  const profiles = {
    answer_participants: [{
      agent: "Heimdall",
      prompt_version: "1",
      system_text_sha256: SHA,
      situation: "operator:direct:T0:en",
    }],
    evaluator_profiles: [{
      profile_id: "conversation-assurance-review",
      profile_version: 1,
      profile_digest: `sha256:${SHA}`,
      system_text_sha256: SHA,
      system_token_budget: 2048,
      request_token_budget: 4096,
      reserved_output_tokens: 1024,
    }],
  };

  it("accepts bounded content-free participant and evaluator evidence", () => {
    expect(parsePantheonPromptProfiles(profiles)).toEqual(profiles);
  });

  it("rejects malformed hashes instead of hiding profile drift", () => {
    expect(parsePantheonPromptProfiles({
      ...profiles,
      answer_participants: [{ ...profiles.answer_participants[0], system_text_sha256: "bad" }],
    })).toBeUndefined();
  });
});
