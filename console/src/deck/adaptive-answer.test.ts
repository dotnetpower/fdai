import { afterEach, describe, expect, it, vi } from "vitest";
import { setLocale } from "../i18n";
import { parseActionDraftExplanation, parseAdaptiveAnswer, parseAdvisoryResponse, type AdaptiveAnswer } from "./adaptive-answer";
import { AdaptiveAnswerSources } from "./adaptive-answer-sources";
import { parseSemanticProjectionReceipt } from "./backend-normalizers";
import { createBackendRequestPayload } from "./backend-context";
import { restoredTurn, replyAgent } from "./command-deck-session";
import { parseTurns, serializeTurns } from "./transcript-store";
import { backendHistoryForTurns } from "./turn-history";
import { regenerationSubmission } from "./use-command-deck-composer";

function adaptive(): AdaptiveAnswer {
  return {
    answer: "An SLO is a measurable service objective.",
    goals: [
      {
        goal_id: "concept", kind: "knowledge", status: "answered", required: true,
        evidence_refs: [], limitation: null,
      },
      {
        goal_id: "example", kind: "environment_example", status: "unavailable", required: false,
        evidence_refs: [], limitation: "No scoped environment evidence is available.",
      },
    ],
    role_agent: "Mimir",
    quality_status: "limited",
    refinements: 0,
    execution_authority: false,
  };
}

function terminal() {
  return {
    seq: 1,
    revision: 0,
    status: "advisory_response",
    source: "semantic-advisory-response",
    answer: adaptive().answer,
    adaptive_answer: adaptive(),
    execution_authority: false,
  };
}

function draftTerminal(requestId = `00000000-0000-4000-8000-${"0".repeat(11)}1`) {
  return {
    ...terminal(),
    status: "action_draft",
    source: "ontology-query",
    answer: "Review this action draft before requesting execution.",
    request_id: requestId,
    action_draft: {
      action_type: "restart-service",
      arguments: { target: "service-example" },
      session_id: "session-example",
      idempotency_key: "governed-draft-example",
    },
    semantic_receipt: {
      schema_version: "1.0.0",
      projection_id: `00000000-0000-4000-8000-${"0".repeat(11)}2`,
      request_id: requestId,
      disposition: "action_draft",
      reason_code: "semantic_action_draft",
      semantic_route: "semantic_action_draft",
      execution_authority: false,
    },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  setLocale("en");
});

describe("advisory response contract", () => {
  it("does not relabel advisory metadata as a whole-response semantic receipt", () => {
    expect(parseAdvisoryResponse(terminal())).toEqual(adaptive());
    expect(parseSemanticProjectionReceipt({
      ...draftTerminal().semantic_receipt,
      disposition: "advisory_response",
      semantic_route: "semantic_advisory_response",
    })).toBeUndefined();
  });

  it("keeps general knowledge distinct from unavailable environment support", () => {
    expect(parseAdaptiveAnswer(adaptive())).toEqual(adaptive());
    expect(parseAdvisoryResponse(terminal())).toEqual(adaptive());
    expect(replyAgent({ adaptiveAnswer: adaptive() })).toBe("Mimir");
  });

  it.each([
    ["authority", { execution_authority: true }],
    ["unregistered role", { role_agent: "Unregistered" }],
    ["too much text", { answer: "x".repeat(16_001) }],
    ["unbounded refinements", { refinements: 2 }],
    ["empty goals", { goals: [] }],
    ["too many goals", { goals: Array.from({ length: 9 }, () => adaptive().goals[0]) }],
    ["extra execution field", { action: "restart" }],
  ])("rejects %s", (_name, changes) => {
    expect(parseAdaptiveAnswer({ ...adaptive(), ...changes })).toBeUndefined();
  });

  it("rejects unsupported evidence, missing limitations, duplicates, and mismatched text", () => {
    const [knowledge, example] = adaptive().goals;
    for (const goals of [
      [{ ...knowledge, evidence_refs: ["inventory:misattributed"] }],
      [{ ...example, status: "answered" }],
      [{ ...example, limitation: null }],
      [{ ...knowledge, kind: ["knowledge"], evidence_refs: ["inventory:misattributed"] }],
      [{ ...knowledge, status: ["answered"] }],
      [knowledge, knowledge],
    ]) {
      expect(parseAdaptiveAnswer({ ...adaptive(), goals })).toBeUndefined();
    }
    expect(parseAdaptiveAnswer(adaptive(), "A different answer")).toBeUndefined();
  });

  it("retains only goal-level verified environment references", () => {
    const answer = {
      ...adaptive(),
      goals: [
        adaptive().goals[0],
        {
          ...adaptive().goals[1], status: "answered", limitation: null,
          evidence_refs: ["inventory:verified-example"],
        },
      ],
    };
    expect(parseAdaptiveAnswer(answer)?.goals[1]?.evidence_refs).toEqual(["inventory:verified-example"]);
  });

  it.each(["verification", "semantic_receipt", "action_draft", "presentation_artifact", "chart_artifact"])(
    "rejects a blanket or authority-bearing %s",
    (field) => {
      expect(parseAdvisoryResponse({ ...terminal(), [field]: {} })).toBeUndefined();
    },
  );

  it("rejects a different request and a successful claim for an unresolved required goal", () => {
    expect(parseAdvisoryResponse({ ...terminal(), request_id: "other" }, "expected")).toBeUndefined();
    expect(parseAdaptiveAnswer({
      ...adaptive(), quality_status: "passed",
      goals: adaptive().goals.map((goal) => ({ ...goal, required: true })),
    })).toBeUndefined();
  });

  it("requires nested semantic metadata to agree with the displayed answer", () => {
    const semantic = {
      disposition: "advisory_response",
      semantic_route: "semantic_advisory_response",
      answer: adaptive().answer,
      adaptive_answer: adaptive(),
      execution_authority: false,
    };
    expect(parseAdvisoryResponse({ ...terminal(), semantic_result: semantic })).toEqual(adaptive());
    expect(parseAdvisoryResponse({
      ...terminal(), semantic_result: { ...semantic, answer: "Different" },
    })).toBeUndefined();
    for (const claims of [
      { execution_receipt_digest: "sha256:forged" },
      { evidence_refs: ["inventory:blanket-claim"] },
      { checks_total: 1 },
      { checks_completed: 1 },
      { checks_passed: 1 },
    ]) {
      expect(parseAdvisoryResponse({
        ...terminal(), semantic_result: { ...semantic, ...claims },
      })).toBeUndefined();
    }
  });
});

describe("advisory source presentation and persistence", () => {
  it("keeps a draft explanation separate from canonical draft text through replay", () => {
    const done = draftTerminal();
    expect(parseActionDraftExplanation(done)).toEqual(adaptive());
    const restored = restoredTurn({
      conversation_id: "conversation-example",
      turn_id: "draft-turn",
      turn_index: 1,
      role: "assistant",
      content: done.answer,
      recorded_at: "2026-09-06T00:00:00Z",
      metadata: { replay_payload: JSON.stringify(done) },
    });
    expect(restored.text).toBe(done.answer);
    expect(restored.adaptiveAnswer).toEqual(adaptive());
    expect(restored.semanticReceipt?.disposition).toBe("action_draft");
    const cached = parseTurns(serializeTurns([restored]));
    expect(cached[0]?.text).toBe(done.answer);
    expect(cached[0]?.adaptiveAnswer).toEqual(adaptive());
    expect(cached[0]?.semanticReceipt?.disposition).toBe("action_draft");
  });

  it.each([
    ["en", "General knowledge", "Environment example", "Unavailable", "Why this part is limited"],
    ["ko", "일반 지식", "현재 환경의 예시", "확인할 수 없음", "이 부분의 답변이 제한된 이유"],
  ] as const)("localizes %s source classifications without a blanket badge", (locale, knowledge, example, unavailable, limitation) => {
    setLocale(locale);
    const rendered = JSON.stringify(AdaptiveAnswerSources({ answer: adaptive() }));
    expect(rendered).toContain(knowledge);
    expect(rendered).toContain(example);
    expect(rendered).toContain(limitation);
    expect(rendered).toContain('"type":"details"');
    expect(rendered).toContain(unavailable);
    expect(rendered).not.toContain("deck-verification");
    expect(rendered).not.toContain("Source unavailable");
  });

  it("round-trips browser-local and durable replay without verification metadata", () => {
    const answer = adaptive();
    const turns = parseTurns(serializeTurns([{
      id: "advisory-turn", role: "deck", text: answer.answer, at: "12:00:00", terminal: true,
      source: terminal().source, adaptiveAnswer: answer,
    }]));
    expect(turns[0]?.adaptiveAnswer).toEqual(answer);
    expect(turns[0]?.verification).toBeUndefined();
    const restored = restoredTurn({
      conversation_id: "conversation-example",
      turn_id: "advisory-turn",
      turn_index: 1,
      role: "assistant",
      content: answer.answer,
      recorded_at: "2026-09-06T00:00:00Z",
      metadata: { source: "ontology-query", replay_payload: JSON.stringify(terminal()) },
    });
    expect(restored.adaptiveAnswer).toEqual(answer);
    expect(restored.agent).toBe("Mimir");
    expect(restored.verification).toBeUndefined();
    expect(restored.source).toBe("semantic-advisory-response");
  });

  it("retains failure status instead of promoting malformed cached or durable advice", () => {
    const cached = parseTurns(JSON.stringify([{
      id: "advisory-turn", role: "deck", text: adaptive().answer, at: "12:00:00",
      source: terminal().source, adaptiveAnswer: adaptive(), verification: { status: "verified" },
    }]));
    const durable = restoredTurn({
      conversation_id: "conversation-example", turn_id: "advisory-turn", turn_index: 1,
      role: "assistant", content: adaptive().answer, recorded_at: "2026-09-06T00:00:00Z",
      metadata: {
        replay_payload: JSON.stringify({ ...terminal(), verification: { status: "verified" } }),
      },
    });
    for (const turn of [cached[0], durable]) {
      expect(turn?.source).toBe("unavailable (invalid advisory response)");
      expect(turn?.text).not.toBe(adaptive().answer);
      expect(turn?.adaptiveAnswer).toBeUndefined();
      expect(turn?.verification).toBeUndefined();
    }
    expect(parseTurns(serializeTurns([durable]))[0]?.source).toBe(durable.source);
    const history = backendHistoryForTurns([durable]);
    expect(history[0]?.source).toBe(durable.source);
    expect(createBackendRequestPayload("Try again.", null, [
      {
        role: "assistant", content: "Earlier verified operational answer.",
        semanticDisposition: "answered",
        semanticRequestId: "00000000-0000-0000-0000-000000000001",
      },
      ...history,
    ], "session-example").source_request_id).toBeUndefined();
  });

  it("retains advisory history through regeneration without reusing operational receipts", () => {
    const cached = parseTurns(serializeTurns([{
      id: "advisory-turn", role: "deck", text: adaptive().answer, at: "12:00:00",
      source: terminal().source, adaptiveAnswer: adaptive(), terminal: true,
    }]));
    const regeneration = regenerationSubmission([
      ...cached,
      { id: "follow-up", role: "operator", text: "Explain that more simply.", at: "12:00:01" },
      {
        id: "next-answer", role: "deck", text: adaptive().answer, at: "12:00:02",
        source: terminal().source, adaptiveAnswer: adaptive(),
      },
    ], 2);
    const history = backendHistoryForTurns(regeneration?.options.historyTurns ?? []);
    expect(history[0]?.adaptiveAnswer).toEqual(adaptive());
    expect(history[0]?.semanticDisposition).toBe("advisory_response");
    expect(regeneration?.options.requestId).toBeUndefined();
    const payload = createBackendRequestPayload("Explain that more simply.", null, [
      {
        role: "assistant", content: "An earlier operational result.",
        semanticDisposition: "answered",
        semanticRequestId: "00000000-0000-0000-0000-000000000001",
      },
      ...history,
    ], "session-example");
    expect(payload.source_request_id).toBeUndefined();
    // Prompt history remains untrusted text, not replayed evidence or execution authority.
    expect(payload.history).toEqual([
      { role: "assistant", content: "An earlier operational result." },
      { role: "assistant", content: adaptive().answer },
    ]);
    const longAnswer = { ...adaptive(), answer: "x".repeat(16_000) };
    expect(createBackendRequestPayload("Explain that more simply.", null, [{
      role: "assistant", content: longAnswer.answer, adaptiveAnswer: longAnswer,
      semanticDisposition: "advisory_response",
    }], "session-example").history).toEqual([
      { role: "assistant", content: "x".repeat(8_000) },
    ]);
  });

  it("does not turn verified example references into a whole-answer badge", () => {
    const supported: AdaptiveAnswer = {
      ...adaptive(),
      goals: [
        adaptive().goals[0]!,
        {
          ...adaptive().goals[1]!, status: "answered", limitation: null,
          evidence_refs: ["inventory:verified-example"],
        },
      ],
    };
    const rendered = JSON.stringify(AdaptiveAnswerSources({ answer: supported }));
    expect(rendered).toContain("inventory:verified-example");
    expect(rendered).toContain("General knowledge");
    expect(rendered).not.toContain("deck-verification");
  });
});

describe("advisory transport parsing", () => {
  const snapshot = {
    routeId: "overview",
    routeLabel: "Overview",
    capturedAt: "2026-09-06T00:00:00Z",
    headline: "Screen context is not advisory evidence",
    facts: [{ key: "resource_count", value: 24 }],
    records: {},
  };

  it.each(["json", "sse"] as const)("retains governed confirmation fields with %s draft explanations", async (format) => {
    vi.stubGlobal("fetch", vi.fn(async (_url: unknown, init?: RequestInit) => {
      const request = JSON.parse(String(init?.body));
      const done = draftTerminal(request.request_id);
      return new Response(format === "json" ? JSON.stringify(done) : `event: done\ndata: ${JSON.stringify(done)}\n\n`, {
        status: 200,
        headers: { "content-type": format === "json" ? "application/json" : "text/event-stream" },
      });
    }));
    const { askBackend, askBackendStream, fallbackTypewriter } = await import("./backend");
    fallbackTypewriter.intervalMs = 0;
    const reply = format === "json"
      ? await askBackend("Explain SLOs and prepare a draft.", snapshot, [])
      : await askBackendStream("Explain SLOs and prepare a draft.", snapshot, [], { onToken: () => {} });
    expect(reply.text).toBe(draftTerminal().answer);
    expect(reply.adaptiveAnswer).toEqual(adaptive());
    expect(reply.actionDraft).toEqual({
      actionType: "restart-service",
      arguments: { target: "service-example" },
      sessionId: "session-example",
      idempotencyKey: "governed-draft-example",
    });
  });

  it("discards malformed optional advice without discarding a governed draft", async () => {
    const done = {
      ...draftTerminal(), adaptive_answer: { ...adaptive(), execution_authority: true },
    };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(done), {
      status: 200, headers: { "content-type": "application/json" },
    })));
    const { askBackend } = await import("./backend");
    const reply = await askBackend("Prepare a draft.", snapshot, []);
    expect(reply.text).toBe(done.answer);
    expect(reply.actionDraft?.idempotencyKey).toBe("governed-draft-example");
    expect(reply.adaptiveAnswer).toBeUndefined();
  });

  it("preserves JSON metadata without citing the current screen", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(terminal()), {
      status: 200, headers: { "content-type": "application/json" },
    })));
    const { askBackend } = await import("./backend");
    const reply = await askBackend("Explain SLOs.", snapshot, []);
    expect(reply.adaptiveAnswer).toEqual(adaptive());
    expect(reply.citations).toEqual([]);
    expect(reply.verification).toBeUndefined();
  });

  it.each(["valid", "answer", "sequence", "verification"] as const)("validates SSE metadata and sequence (%s)", async (scenario) => {
    vi.stubGlobal("fetch", vi.fn(async (_url: unknown, init?: RequestInit) => {
      const request = JSON.parse(String(init?.body));
      const done = {
        ...terminal(), request_id: request.request_id,
        ...(scenario === "answer" ? { answer: "Mismatched answer" } : {}),
        ...(scenario === "sequence" ? { seq: 3 } : {}),
        ...(scenario === "verification" ? { seq: 2, revision: 1 } : {}),
      };
      const prefix = scenario === "verification"
        ? `event: revision\ndata: ${JSON.stringify({
          seq: 1, revision: 1, answer: adaptive().answer, status: "verified",
        })}\n\n`
        : "";
      return new Response(`${prefix}event: done\ndata: ${JSON.stringify(done)}\n\n`, {
        status: 200, headers: { "content-type": "text/event-stream" },
      });
    }));
    const { askBackendStream, fallbackTypewriter } = await import("./backend");
    fallbackTypewriter.intervalMs = 0;
    let visibleText = "";
    const onRevision = vi.fn((text: string) => { visibleText = text; });
    const reply = await askBackendStream("Explain SLOs.", snapshot, [], {
      onToken: (text) => { visibleText += text; }, onRevision,
    });
    expect(reply.citations).toEqual([]);
    expect(reply.verification).toBeUndefined();
    if (scenario !== "valid") {
      expect(visibleText).toBe(reply.text);
      expect(onRevision).toHaveBeenCalledExactlyOnceWith(
        "", scenario === "verification" ? 2 : 1, "unverified",
      );
      expect(reply.adaptiveAnswer).toBeUndefined();
      expect(reply.source).toContain("unavailable");
    } else {
      expect(onRevision).not.toHaveBeenCalled();
      expect(reply.adaptiveAnswer).toEqual(adaptive());
      expect(reply.text).toBe(adaptive().answer);
      expect(reply.semanticReceipt).toBeUndefined();
    }
  });
});
