import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { setLocale } from "../i18n";
import type { AnswerVerification, SemanticProjectionReceipt } from "./backend";
import { assuranceHref, primaryAnswerText, verificationLabel } from "./grounded-reply";

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
});

describe("grounded reply presentation", () => {
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
      reason_code: "semantic_runtime_unavailable",
    };

    expect(primaryAnswerText(
      "Verified evidence is unavailable. (semantic_runtime_unavailable)",
      unavailable,
    )).toBe(
      "Which source or scope should I check instead? Name a resource, time range, or evidence source.",
    );

    setLocale("ko");
    try {
      expect(primaryAnswerText("검증된 근거를 사용할 수 없습니다.", unavailable)).toBe(
        "대신 어떤 근거 원본이나 범위를 확인할까요? 리소스, 기간 또는 근거 원본을 지정해 주세요.",
      );
    } finally {
      setLocale("en");
    }
  });

  it("directs model identity failures to authentication recovery", () => {
    const unavailable = {
      ...verification("server_read_model"),
      status: "unverified" as const,
      reason_code: "semantic_model_identity_unavailable",
    };

    expect(primaryAnswerText(
      "Model authentication is unavailable.",
      unavailable,
    )).toBe(
      "Model authentication is unavailable. Restore the configured Azure identity, then retry this question.",
    );

    setLocale("ko");
    try {
      expect(primaryAnswerText("모델 인증을 사용할 수 없습니다.", unavailable)).toBe(
        "모델 인증을 사용할 수 없습니다. 구성된 Azure ID를 복구한 후 이 질문을 다시 시도해 주세요.",
      );
    } finally {
      setLocale("en");
    }
  });

  it("preserves the server's typed partial-evidence hold", () => {
    const held = {
      ...verification("ontology-query"),
      status: "unverified" as const,
      reason_code: "semantic_evidence_held",
    };
    const receipt: SemanticProjectionReceipt = {
      schema_version: "2.0.0",
      projection_id: "semantic-projection-1",
      request_id: "semantic-request-1",
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
