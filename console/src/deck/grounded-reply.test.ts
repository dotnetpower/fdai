import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { setLocale } from "../i18n";
import type { AnswerVerification, SemanticProjectionReceipt } from "./backend";
import {
  assuranceHref,
  hasEvidenceReferenceCitations,
  primaryAnswerText,
  sourceButtonAccessibleLabel,
  verificationLabel,
} from "./grounded-reply";
import { secondaryEvidencePostureIssueKind } from "./verification-presentation";

function verification(authority: string): AnswerVerification {
  return {
    status: "consistent",
    authority,
    checks_completed: 1,
    checks_total: 1,
    evidence_refs: ["evidence-1"],
    reason_code: "screen_claims_supported",
    claims: [
      {
        claim_id: "c001",
        kind: "number",
        text: "24 events",
        span: { start: 0, end: 2 },
        raw_value: "24",
        normalized_value: "24",
        unit: null,
        anchors: ["events"],
        status: "supported",
        evidence_refs: ["evidence-1"],
        reason_code: null,
      },
    ],
  };
}

function semanticReceipt(
  evidence_posture: "fresh" | "stale" | "incomplete" | "conflicting" | "unavailable",
): SemanticProjectionReceipt {
  return {
    schema_version: "2.0.0",
    projection_id: "projection-1",
    request_id: "request-1",
    disposition: "answered",
    reason_code: "query_completed",
    execution_authority: false,
    assurance_observation: {
      schema_version: "1.0.0",
      frame: null,
      capabilities: [],
      object_types: [],
      link_types: [],
      function_types: [],
      ontology_paths: [],
      fact_kinds: [],
      limitation_kinds: [],
      claim_kinds: [],
      evidence_posture,
      authority_posture: "read_only",
      read_performed: true,
      observation_digest: "sha256:obs",
      execution_authority: false,
    },
  };
}

describe("verificationLabel", () => {
  it("names server evidence instead of the current screen", () => {
    expect(verificationLabel(verification("server_read_model"))).toBe(
      "Consistent with server evidence (1/1 claims supported)",
    );
  });

  it("keeps current-screen wording for browser snapshot evidence", () => {
    expect(verificationLabel(verification("client_snapshot"))).toBe(
      "Consistent with the current screen (1/1 claims supported)",
    );
  });

  it("does not present verified ambiguity as a verified cause", () => {
    expect(verificationLabel({
      ...verification("server_read_model"),
      status: "verified",
      reason_code: "ambiguous_incident",
    })).toBe(
      "Server evidence confirms that multiple incidents match; select one to continue.",
    );
  });

  it("labels a recorded failure separately from a complete RCA", () => {
    expect(verificationLabel({
      ...verification("server_read_model"),
      status: "verified",
      reason_code: "recorded_failure_reason",
    })).toBe(
      "Audit evidence confirms the displayed failure reason; no complete RCA is recorded.",
    );
  });

  it("localizes verification labels for Korean assistive text", () => {
    setLocale("ko");
    try {
      expect(verificationLabel(verification("server_read_model"))).toBe(
        "서버 근거와 일치 (claim 1개 중 1개 근거 있음)",
      );
    } finally {
      setLocale("en");
    }
  });

  it("surfaces stale evidence posture in the verification tooltip", () => {
    expect(
      verificationLabel(verification("server_read_model"), semanticReceipt("stale")),
    ).toBe("Grounding evidence is stale; refresh the read before trusting this answer (1/1 claims supported)");
  });
});

describe("grounded reply presentation", () => {
  it("routes citations to source disclosure and retains only display-authorized Markdown", () => {
    const component = readFileSync(fileURLToPath(new URL("./grounded-reply.tsx", import.meta.url)), "utf8");
    expect(component).toContain("onCitationSelect={selectCitation}");
    expect(component).toContain("sourceReturn.current");
    expect(component).toContain("origin.trigger.focus({ preventScroll: true })");
    expect(component).toContain("<pre><code>{renderedText}</code></pre>");
    expect(component).not.toContain("<pre><code>{text}</code></pre>");
  });

  it("shows the signed-in account and server authority boundary on action drafts", () => {
    const component = readFileSync(
      fileURLToPath(new URL("./grounded-reply.tsx", import.meta.url)),
      "utf8",
    );

    const account = component.indexOf('t("deck.actionDraft.account")');
    const authority = component.indexOf('t("deck.actionDraft.authorityNote")');
    const confirm = component.indexOf('t("deck.actionDraft.confirm")');

    expect(component).toContain("getDeckUser()");
    expect(account).toBeGreaterThan(-1);
    expect(authority).toBeGreaterThan(account);
    expect(confirm).toBeGreaterThan(authority);
  });

  it("uses an attention mark when verified claims have an evidence-posture issue", () => {
    const component = readFileSync(
      fileURLToPath(new URL("./grounded-reply.tsx", import.meta.url)),
      "utf8",
    );

    expect(component).toContain("verificationIssue || verifiedAmbiguity || recordedFailure");
  });

  it("preserves the server's concrete semantic clarification question", () => {
    const clarification = {
      ...verification("ontology-query"),
      status: "unverified" as const,
      reason_code: "semantic_clarification_required",
    };

    expect(primaryAnswerText(
      "확인할 리소스의 정확한 이름 또는 리소스 ID를 알려주세요?",
      clarification,
    )).toBe("확인할 리소스의 정확한 이름 또는 리소스 ID를 알려주세요?");
  });

  it("asks a bounded clarification instead of repeating an unavailable answer", () => {
    const unavailable = {
      ...verification("server_read_model"),
      status: "unverified" as const,
      reason_code: "provider_unavailable",
    };

    expect(primaryAnswerText(
      "Verified evidence is unavailable. (provider_unavailable)",
      unavailable,
    )).toBe(
      "Which source or scope should I check instead? Name a resource, time range, or evidence source.",
    );

    setLocale("ko");
    try {
      expect(primaryAnswerText("검증된 근거를 사용할 수 없습니다.", unavailable)).toBe(
        "대신 어떤 근거 원본이나 범위를 확인할까요? 리소스, 기간 또는 근거 원본을 지정해 주세요.",
      );
      expect(primaryAnswerText("Verified evidence is unavailable.", unavailable)).toBe(
        "Which source or scope should I check instead? Name a resource, time range, or evidence source.",
      );
    } finally {
      setLocale("en");
    }
  });

  it("asks the bounded clarification in the language of the server reply", () => {
    const unavailable = {
      ...verification("server_read_model"),
      status: "unverified" as const,
      reason_code: "provider_unavailable",
    };

    expect(
      primaryAnswerText("검증된 근거를 사용할 수 없어 요청을 보류했습니다. (provider_unavailable)", unavailable),
    ).toBe(
      "대신 어떤 근거 원본이나 범위를 확인할까요? 리소스, 기간 또는 근거 원본을 지정해 주세요.",
    );
  });

  it("renders an actionable planner-unavailable recovery step", () => {
    const unavailable = {
      ...verification("server_read_model"),
      status: "unverified" as const,
      reason_code: "semantic_runtime_unavailable",
    };
    const receipt: SemanticProjectionReceipt = {
      schema_version: "2.0.0",
      projection_id: "semantic-projection-runtime",
      request_id: "semantic-request-runtime",
      disposition: "held",
      reason_code: "semantic_runtime_unavailable",
      unavailable_reason: "semantic_planner_unavailable",
      execution_authority: false,
    };
    const answer = [
      "Confirmed status: the semantic runtime is unavailable.",
      "Safe next step: restore the required FDAI component, then retry.",
      "This authorizes no change. (semantic_runtime_unavailable)",
    ].join("\n");

    expect(primaryAnswerText(answer, unavailable, receipt)).toBe(
      "Semantic planning is unavailable. Restore model connectivity or the semantic runtime, then retry this question.",
    );
  });

  it("maps malformed preflight replies to the planner recovery prompt", () => {
    const unavailable = {
      ...verification("server_read_model"),
      status: "unverified" as const,
      reason_code: "conversation_preflight_malformed",
    };

    expect(primaryAnswerText("Unsupported request shape.", unavailable)).toBe(
      "Semantic planning is unavailable. Restore model connectivity or the semantic runtime, then retry this question.",
    );
  });

  it("directs model identity failures to authentication recovery", () => {
    const unavailable = {
      ...verification("server_read_model"),
      status: "unverified" as const,
      reason_code: "semantic_model_identity_unavailable",
    };
    const receipt: SemanticProjectionReceipt = {
      schema_version: "2.0.0",
      projection_id: "semantic-projection-identity",
      request_id: "semantic-request-identity",
      disposition: "held",
      reason_code: "semantic_model_identity_unavailable",
      unavailable_reason: "semantic_planner_unavailable",
      execution_authority: false,
    };

    expect(primaryAnswerText(
      "Model authentication is unavailable.",
      unavailable,
      receipt,
    )).toBe(
      "Model authentication is unavailable. Restore the configured Azure identity, then retry this question.",
    );

    setLocale("ko");
    try {
      expect(primaryAnswerText("모델 인증을 사용할 수 없습니다.", unavailable, receipt)).toBe(
        "모델 인증을 사용할 수 없습니다. 구성된 Azure ID를 복구한 후 이 질문을 다시 시도해 주세요.",
      );
    } finally {
      setLocale("en");
    }
  });

  it("preserves the server's typed partial-evidence hold", () => {
    const held = {
      ...verification("server_inventory_graph"),
      status: "unverified" as const,
      reason_code: "semantic_evidence_held",
    };
    const receipt: SemanticProjectionReceipt = {
      ...semanticReceipt("incomplete"),
      disposition: "held",
      reason_code: "semantic_evidence_held",
      unavailable_reason: "authoritative_evidence_unavailable",
      plan_digest: `sha256:${"a".repeat(64)}`,
      execution_receipt_digest: `sha256:${"b".repeat(64)}`,
      execution_authority: false,
    };
    const answer = [
      "## Verified observations",
      "- Measured change: 15 ms",
      "## Competing hypotheses",
      "- `dependency-latency` - `unresolved`",
      "- `traffic-load` - `unresolved`",
      "`execution_authority=false`",
    ].join("\n");

    expect(primaryAnswerText(answer, held, receipt)).toBe(answer);
    expect(
      primaryAnswerText(
        answer,
        { ...held, reason_code: "semantic_evidence_incomplete" },
        { ...receipt, reason_code: "semantic_evidence_incomplete" },
      ),
    ).toBe(answer);
    expect(primaryAnswerText("unverified streamed draft", held)).toBe(
      "Which source or scope should I check instead? Name a resource, time range, or evidence source.",
    );
    expect(
      primaryAnswerText(
        "unverified streamed draft",
        { ...held, evidence_refs: [""] },
        receipt,
      ),
    ).toBe(
      "Which source or scope should I check instead? Name a resource, time range, or evidence source.",
    );
  });

  it("keeps long source badges readable without clipping", () => {
    const styles = readFileSync(
      fileURLToPath(new URL("../styles.css", import.meta.url)),
      "utf8",
    );

    expect(styles).toMatch(
      /\.deck-src-badge \{[^}]*width: 60px;[^}]*overflow: hidden;[^}]*text-overflow: ellipsis;/s,
    );
  });

  it("links answer review to the exact turn assessment", () => {
    expect(assuranceHref("turn 1")).toBe("/conversation-assurance?turn=turn+1");
  });

  it("keeps conflict visible when incomplete evidence is the primary posture", () => {
    const incomplete = semanticReceipt("incomplete");
    const receipt: SemanticProjectionReceipt = {
      ...incomplete,
      assurance_observation: {
        ...incomplete.assurance_observation!,
        fact_kinds: ["evidence.completeness", "evidence.conflicts"],
      },
    };

    expect(secondaryEvidencePostureIssueKind(receipt)).toBe("conflictingEvidence");
    expect(
      secondaryEvidencePostureIssueKind({
        ...receipt,
        assurance_observation: {
          ...receipt.assurance_observation!,
          fact_kinds: ["evidence.completeness"],
        },
      }),
    ).toBeNull();
  });

  it("includes evidence posture in the source button accessible name", () => {
    expect(
      sourceButtonAccessibleLabel("3 evidence references", [
        "Partial evidence",
        "Conflicting evidence",
      ]),
    ).toBe("3 evidence references. Partial evidence. Conflicting evidence");
  });

  it("does not treat empty citations as evidence references", () => {
    expect(hasEvidenceReferenceCitations([])).toBe(false);
    expect(hasEvidenceReferenceCitations([{ label: "evidence.incident" }])).toBe(true);
  });

  it("leaves agent ownership to the turn header and hides redundant complete chrome", () => {
    const component = readFileSync(
      fileURLToPath(new URL("./grounded-reply.tsx", import.meta.url)),
      "utf8",
    );

    expect(component).not.toContain(
      'replyAgentLabel(delegation?.primary_agent ?? "Bragi", delegation)',
    );
    expect(component).toContain('const showAnswerState = answerState !== "complete";');
    expect(component).toContain("{showAnswerState ? (");
    expect(component).not.toContain("deck.answerPlan.intent");
    expect(component).not.toContain("deck.answerPlan.detail");
  });

  it("renders verified answer text before a superseding structured component", () => {
    const component = readFileSync(
      fileURLToPath(new URL("./grounded-reply.tsx", import.meta.url)),
      "utf8",
    );
    const summary = component.indexOf('class="deck-presentation-lead"');
    const structured = component.indexOf(
      "<StructuredReply artifact={structuredPresentation} />",
    );

    expect(component).toContain(
      "const structuredPresentation = !streaming && !verificationIssue && presentationArtifact",
    );
    expect(summary).toBeGreaterThan(-1);
    expect(structured).toBeGreaterThan(summary);
    expect(component.slice(summary, structured)).toContain("<RichContent");
    expect(component.slice(summary, structured)).toContain("text={renderedText}");
  });

  it("keeps trajectory status out of the compact reply footer", () => {
    const component = readFileSync(
      fileURLToPath(new URL("./grounded-reply.tsx", import.meta.url)),
      "utf8",
    );

    expect(component).toContain(
      'class="deck-gr-tool deck-gr-review cs-deck-tool"',
    );
    expect(component).not.toContain('class="deck-gr-review-status"');
    expect(component).not.toContain("TrajectoryStatusTrigger");
    expect(component).not.toContain("ConversationTrajectoryResults");
    expect(component).not.toContain('class="deck-trajectory-flyout"');
    expect(component).toContain("verificationIssueKind(verification.reason_code)");
    expect(component).toContain('is-${verificationIssue}');
    expect(component).toContain('verification?.status === "unverified"');
    expect(component).toContain("!verificationIssue && presentationArtifact");
    expect(component).toContain('groundingAttention ? "!" : "\\u2713"');
  });

  it("copies the same primary answer text the operator can see", () => {
    const component = readFileSync(
      fileURLToPath(new URL("./grounded-reply.tsx", import.meta.url)),
      "utf8",
    );

    expect(component).toContain("navigator.clipboard?.writeText(renderedText)");
    expect(component).not.toContain("navigator.clipboard?.writeText(text)");
  });
});
