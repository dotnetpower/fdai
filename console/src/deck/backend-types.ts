import type { Answer } from "./answerer";

export interface BackendTurn {
  readonly role: "user" | "assistant";
  readonly content: string;
  readonly resourceContext?: ResourceContext;
}

export interface ResourceContext {
  readonly name: string;
  readonly resource_type: string;
  readonly evidence_ref: string;
}

export interface RouterCandidate {
  readonly deployment: string;
  readonly p50_ms: number | null;
  readonly p95_ms: number | null;
  readonly samples: number;
  readonly history_ms: readonly number[];
}

export interface RouterSnapshot {
  readonly chose: string;
  readonly reason: string;
  readonly candidates: readonly RouterCandidate[];
}

export interface BackendReply {
  readonly text: string;
  readonly source: string;
  readonly router?: RouterSnapshot;
}

export interface ActionDraft {
  readonly actionType: string;
  readonly arguments: Readonly<Record<string, unknown>>;
  readonly sessionId: string | null;
  readonly idempotencyKey: string;
}

export type AnswerVerificationStatus = "verified" | "consistent" | "corrected" | "unverified";
export type AtomicClaimStatus = "supported" | "unsupported" | "ambiguous";

export interface AtomicAnswerClaim {
  readonly claim_id: string;
  readonly kind: "id" | "number" | "percentage" | "timestamp" | "causal" | "scope";
  readonly text: string;
  readonly span: { readonly start: number; readonly end: number };
  readonly raw_value: string;
  readonly normalized_value: string;
  readonly unit: string | null;
  readonly anchors: readonly string[];
  readonly status: AtomicClaimStatus;
  readonly evidence_refs: readonly string[];
  readonly reason_code: string | null;
}

export interface EvidenceManifestEntry {
  readonly ref: string;
  readonly path: string;
  readonly field: string;
  readonly kind: string;
  readonly raw_value: string;
  readonly normalized_value: string;
  readonly anchors: readonly string[];
  readonly aliases?: readonly string[];
}

export interface AnswerEvidenceManifest {
  readonly schema_version: number;
  readonly manifest_id: string;
  readonly authority: string;
  readonly route_id: string | null;
  readonly captured_at: string | null;
  readonly complete: boolean;
  readonly source_entry_count: number;
  readonly entries: readonly EvidenceManifestEntry[];
}

export interface AnswerVerification {
  readonly status: AnswerVerificationStatus;
  readonly authority: string;
  readonly checks_completed: number;
  readonly checks_total: number;
  readonly evidence_refs: readonly string[];
  readonly reason_code: string | null;
  readonly claims?: readonly AtomicAnswerClaim[];
  readonly evidence_manifest?: AnswerEvidenceManifest;
  readonly failed_claim_ids?: readonly string[];
}

export interface DelegationMetadata {
  readonly primary_agent: string;
  readonly contributors: readonly string[];
  readonly trace_ref?: string;
  readonly handoff_from?: string;
  readonly handoff_reason?: string;
}

export interface AnswerPlanMetadata {
  readonly intent: "definition" | "why" | "procedure" | "comparison" | "diagnosis" | "status" | "list" | "summary" | "proposal" | "open_question" | "greeting";
  readonly detail_level: "brief" | "standard" | "deep";
  readonly format: "prose" | "bullets" | "numbered_steps" | "table" | "chart" | "checklist" | "mixed";
  readonly sections: readonly string[];
  readonly evidence_requirement: "none" | "screen" | "catalog" | "server_read_model" | "agent_owned";
  readonly max_words: number;
  readonly discuss: "skip" | "shadow" | "selective";
  readonly explicit_overrides: readonly string[];
  readonly preference_applied: boolean;
}

export interface AnswerPlanningContributionMetadata {
  readonly agent: string;
  readonly evidence_refs: readonly string[];
  readonly confidence: number;
  readonly suggested_sections: readonly string[];
}

export interface AnswerPlanningMetadata {
  readonly mode: "shadow";
  readonly status: "skipped" | "completed" | "degraded" | "timed_out";
  readonly primary_agent: string | null;
  readonly consulted_agents: readonly string[];
  readonly contributions: readonly AnswerPlanningContributionMetadata[];
  readonly failures: readonly { readonly agent: string; readonly kind: string }[];
  readonly elapsed_ms: number;
  readonly unique_evidence_count: number;
  readonly duplicate_evidence_count: number;
  readonly conflicting_evidence_refs: readonly string[];
  readonly covered_sections: readonly string[];
  readonly estimated_added_tokens: number;
  readonly budget: {
    readonly max_contributors: number;
    readonly max_rounds: number;
    readonly max_wall_ms: number;
    readonly max_added_tokens: number;
    readonly nested_rounds: false;
  };
  readonly reason: string | null;
}

export interface VerificationProgress {
  readonly phase: string;
  readonly label: string;
  readonly completed: number | null;
  readonly total: number | null;
  readonly sources?: readonly RetrievalSourcePreview[];
}

export interface RetrievalSourcePreview {
  readonly kind: string;
  readonly label: string;
  readonly detail: string;
  readonly side_effect_class: "read" | "route" | "simulate" | "ground";
}

export type InvestigationActivityStatus =
  | "pending"
  | "running"
  | "completed"
  | "unavailable"
  | "failed";

export interface InvestigationExecutionEvidence {
  readonly tool: string;
  readonly command: string;
  readonly inputKind?: "command" | "query";
  readonly redacted: true;
  readonly output?: string;
  readonly outputTruncated?: boolean;
  readonly exitCode?: number;
  readonly startedAt?: string;
  readonly completedAt?: string;
  readonly durationMs?: number;
}

export interface InvestigationActivity {
  readonly activityId: string;
  readonly kind: string;
  readonly status: InvestigationActivityStatus;
  readonly label: string;
  readonly agent?: string;
  readonly detail?: string;
  readonly completed: number | null;
  readonly total: number | null;
  readonly authority?: string;
  readonly observedAt?: string;
  readonly execution?: InvestigationExecutionEvidence;
  readonly branchId?: string;
}

export interface InvestigationMilestone {
  readonly messageId: string;
  readonly text: string;
  readonly agent?: string;
}

export type EvidenceBranchKind = "tool" | "operational" | "agent" | "public_web";

export type EvidenceBranchStatus =
  | "pending"
  | "running"
  | "completed"
  | "unavailable"
  | "failed"
  | "timed_out"
  | "cancelled";

export interface EvidenceBranch {
  readonly branchId: string;
  readonly kind: EvidenceBranchKind;
  readonly parentBranchId: string | null;
  readonly status: EvidenceBranchStatus;
  readonly summary: string;
  readonly startedAt: string;
  readonly completedAt?: string;
  readonly durationMs?: number;
  readonly evidenceRefs: readonly string[];
}

export interface ConfirmedAnswerSegment {
  readonly segmentIndex: number;
  readonly revision: number;
  readonly text: string;
  readonly status: Exclude<AnswerVerificationStatus, "unverified">;
  readonly evidenceRefs: readonly string[];
  readonly replaceStart?: number;
  readonly replaceEnd?: number;
}

export type CodeValidationStatus = "valid" | "invalid" | "not_checked";

export interface GroundedCodeArtifact {
  readonly artifact_ref: string;
  readonly language: string;
  readonly content: string;
  readonly sha256: string;
  readonly validation_status: CodeValidationStatus;
  readonly validation_detail: string | null;
}

export interface ModelTraceMessage {
  readonly role: "system" | "user" | "assistant" | "tool";
  readonly content: string;
}

export interface ModelTraceCall {
  readonly call_id: string;
  readonly kind: string;
  readonly model: string;
  readonly status: "completed" | "incomplete";
  readonly started_at: string;
  readonly completed_at: string | null;
  readonly duration_ms: number | null;
  readonly request: {
    readonly messages: readonly ModelTraceMessage[];
    readonly sha256: string;
  };
  readonly response: {
    readonly role: "assistant";
    readonly content: string;
    readonly sha256: string;
  } | null;
  readonly usage: Readonly<Record<string, number>> | null;
  readonly redactions: readonly {
    readonly rule: string;
    readonly replacements: number;
  }[];
}

export interface ModelTrace {
  readonly schema_version: 1;
  readonly redacted: true;
  readonly calls: readonly ModelTraceCall[];
  readonly omitted_calls: number;
}

export type ProgressiveAnswer = Answer & {
  readonly source: string;
  readonly router?: RouterSnapshot;
  readonly verification?: AnswerVerification;
  readonly delegation?: DelegationMetadata;
  readonly answerPlan?: AnswerPlanMetadata;
  readonly answerPlanning?: AnswerPlanningMetadata;
  readonly codeArtifacts?: readonly GroundedCodeArtifact[];
  readonly confirmed?: ConfirmedAnswerSegment;
  readonly actionDraft?: ActionDraft;
  readonly resourceContext?: ResourceContext;
  readonly modelTrace?: ModelTrace;
};

export interface BackendHealth {
  readonly available: boolean;
  readonly mode: string;
  readonly model: string | null;
  readonly endpoint: string | null;
  readonly router?: RouterSnapshot;
}

export interface StreamCallbacks {
  readonly onToken: (delta: string) => void;
  readonly onProgress?: (progress: VerificationProgress) => void;
  readonly onActivity?: (activity: InvestigationActivity) => void;
  readonly onMilestone?: (milestone: InvestigationMilestone) => void;
  readonly onBranch?: (branch: EvidenceBranch) => void;
  readonly onConfirmed?: (segment: ConfirmedAnswerSegment) => void;
  readonly onRevision?: (
    answer: string,
    revision: number,
    status: AnswerVerificationStatus,
  ) => void;
  readonly signal?: AbortSignal;
  readonly sessionId?: string;
  readonly targetAgent?: string;
  readonly conversationBinding?: import("./open-deck").IncidentConversationBinding;
  /** Inline image attachments to escalate this turn to a vision narrator. */
  readonly attachments?: readonly import("./composer-attachment-store").ChatAttachment[];
}
