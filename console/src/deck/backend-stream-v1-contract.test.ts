import { afterEach, expect, test, vi } from "vitest";

afterEach(() => {
  vi.unstubAllGlobals();
});

test("rejects v1 frames with mismatched request ids or missing sequences", async () => {
  for (const variant of ["mismatch", "missing-sequence"] as const) {
    vi.resetModules();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input, init) => {
        const request = JSON.parse(String(init?.body)) as { request_id: string };
        const payload = {
          v: 1,
          request_id: variant === "mismatch" ? "another-request" : request.request_id,
          ...(variant === "mismatch" ? { seq: 1 } : {}),
          answer: "must not be accepted",
          model: "gpt-test",
        };
        const validToken = {
          v: 1,
          request_id: request.request_id,
          seq: 1,
          revision: 0,
          delta: "must be discarded",
        };
        return new Response(
          `event: token\ndata: ${JSON.stringify(validToken)}\n\n` +
            `event: done\ndata: ${JSON.stringify(payload)}\n\n`,
        );
      }),
    );
    const backend = await import("./backend");
    backend.fallbackTypewriter.intervalMs = 0;
    const tokens: string[] = [];

    const reply = await backend.askBackendStream("q", null, [], {
      onToken: (token) => tokens.push(token),
    });

    expect(reply.source).toBe("partial (sequence gap)");
    expect(reply.text).toBe("");
    expect(tokens).toEqual([]);
    expect(reply.verification).toBeUndefined();
  }
});

test("accepts an evidence-bound ontology query done frame", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(
      `event: done\ndata: ${JSON.stringify({
        seq: 1,
        revision: 0,
        status: "answered",
        answer: "Verified ontology query completed.",
        source: "ontology-query",
        verification: {
          status: "verified",
          authority: "ontology-query",
          checks_completed: 1,
          checks_total: 1,
          evidence_refs: ["inventory:evidence-1"],
          reason_code: "semantic_answer_verified",
          claims: [],
          failed_claim_ids: [],
        },
        intent_graph: {
          schema_version: 2,
          goals: [{
            goal_id: "goal-1",
            intent: "object_set",
            capability: "query.object_set",
            arguments: {},
            depends_on: [],
            evidence_mode: "operational",
            freshness_required: true,
            confidence: 1,
            alternatives: [],
          }],
          clarification: null,
          confidence: 1,
          action_posture: "advise_only",
        },
        intent_graph_evidence: {
          schema_version: 1,
          status: "completed",
          evidence_mode: "operational_grounded",
          goals: [{
            task_id: "query:resources",
            goal_id: "goal-1",
            intent: "object_set",
            capability: "query.object_set",
            evidence_mode: "operational",
            status: "completed",
            duration_ms: 5,
            depends_on: [],
            started_at: "2026-08-11T00:00:00Z",
            completed_at: "2026-08-11T00:00:00Z",
            evidence_refs: ["inventory:evidence-1"],
          }],
        },
      })}\n\n`,
    )),
  );
  const backend = await import("./backend");

  const reply = await backend.askBackendStream("show resources", null, [], {
    onToken: () => undefined,
  });

  expect(reply.text).toBe("Verified ontology query completed.");
  expect(reply.source).toBe("ontology-query");
  expect(reply.verification?.status).toBe("verified");
  expect(reply.verification?.evidence_refs).toEqual(["inventory:evidence-1"]);
  expect(reply.intentGraphEvidence?.evidence_mode).toBe("operational_grounded");
});
