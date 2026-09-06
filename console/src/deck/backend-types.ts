import type { Answer } from "./answerer";

export interface BackendTurn {
  readonly role: "user" | "assistant";
  readonly content: string;
  readonly source?: string;
  readonly semanticRequestId?: string;
  readonly semanticDisposition?: SemanticProjectionReceipt["disposition"] | "advisory_response";
  /** Retained locally for replay and source selection, never forwarded as trusted evidence. */
  readonly adaptiveAnswer?: import("./adaptive-answer").AdaptiveAnswer;
  readonly resourceContext?: ResourceContext;
  readonly evidenceFreshnessContext?: EvidenceFreshnessContext;
  readonly conversationBinding?: import("./open-deck").IncidentConversationBinding;
}

export interface ResourceContext {
  readonly name: string;
  readonly resource_type: string;
  readonly evidence_ref: string;
  readonly resource_group?: string;
  readonly event_at?: string;
  readonly event_status?: string;
}

export interface EvidenceFreshnessContext {
  readonly source: string;
  readonly observed_at: string;
  readonly window_start: string;
  readonly status: "matched" | "partial" | "none" | "unavailable";
  readonly truncated: boolean;
}

export interface RouterCandidate {
  readonly deployment: string;
  readonly p50_ms: number | null;
  readonly p95_ms: number | null;
  readonly samples: number;
  readonly history_ms: readonly number[];
  readonly status?: "measured" | "unmeasured" | "failed" | "stale";
  readonly measured_at?: string;
}

export interface RouterSnapshot {
  readonly chose: string;
  readonly reason: string;
  readonly candidates: readonly RouterCandidate[];
  readonly updated_at?: string;
  readonly expires_at?: string;
  readonly interval_seconds?: number;
  readonly vision?: {
    readonly available: boolean;
    readonly chose: string | null;
    readonly candidates: readonly RouterCandidate[];
  };
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

export interface SemanticProjectionReceipt {
  readonly schema_version: "1.0.0" | "2.0.0";
  readonly projection_id: string;
  readonly request_id: string;
  readonly disposition: "answered" | "direct_response" | "held" | "clarification" | "unsupported" | "action_draft" | "cancelled";
  readonly reason_code: string;
  readonly semantic_route?: "verified_query_plan" | "semantic_direct_response" | "semantic_clarification" | "semantic_unsupported" | "semantic_action_draft" | "semantic_cancellation";
  readonly direct_response_intent?: "greeting" | "self_introduction";
  readonly unavailable_reason?: "authoritative_evidence_unavailable" | "historical_evidence_unavailable" | "semantic_planner_unavailable";
  readonly ontology_release_digest?: string;
  readonly principal_manifest_digest?: string;
  readonly plan_digest?: string;
  readonly execution_receipt_digest?: string;
  readonly assurance_observation?: SemanticAssuranceObservation;
  readonly execution_authority: false;
}

export interface SemanticAssuranceFrame {
  readonly operation: "select" | "aggregate" | "compare" | "explain_change" | "validate" | "action_draft";
  readonly subject_types: readonly string[];
  readonly measure_concepts: readonly string[];
  readonly temporal_scope: "none" | "current" | "windowed" | "historical";
  readonly output_shape: string;
  readonly frame_digest: string;
}

export interface SemanticAssurancePathStep {
  readonly from_type: string;
  readonly link_type: string;
  readonly direction: "outgoing" | "incoming";
  readonly to_type: string;
}

export interface SemanticAssurancePath {
  readonly path_id: string;
  readonly steps: readonly SemanticAssurancePathStep[];
}

export interface SemanticAssuranceObservation {
  readonly schema_version: "1.0.0";
  readonly frame: SemanticAssuranceFrame | null;
  readonly capabilities: readonly string[];
  readonly object_types: readonly string[];
  readonly link_types: readonly string[];
  readonly function_types: readonly string[];
  readonly ontology_paths: readonly SemanticAssurancePath[];
  readonly fact_kinds: readonly string[];
  readonly limitation_kinds: readonly string[];
  readonly claim_kinds: readonly string[];
  readonly evidence_posture: "fresh" | "stale" | "incomplete" | "conflicting" | "unavailable";
  readonly authority_posture: "read_only" | "draft_only";
  readonly read_performed: boolean;
  readonly observation_digest: string;
  readonly execution_authority: false;
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
  readonly target?: InvestigationExecutionTarget;
  readonly redacted: true;
  readonly output?: string;
  readonly outputTruncated?: boolean;
  readonly exitCode?: number;
  readonly startedAt?: string;
  readonly completedAt?: string;
  readonly durationMs?: number;
}

export interface InvestigationExecutionTarget {
  readonly interfaceKind: "internal_query" | "http" | "cli" | "sdk";
  readonly service: string;
  readonly component: string;
  readonly operation: string;
  readonly sourceKind?: string;
  readonly transport?: "event_bus" | "in_process";
  readonly endpoint?: {
    readonly method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
    readonly path: string;
  };
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
  readonly recordedAt?: string;
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

export interface ModelUsage {
  readonly prompt_tokens?: number;
  readonly completion_tokens?: number;
  readonly total_tokens: number;
}

export type TurnTimingPhaseName =
  | "semantic_plan"
  | "evidence"
  | "generation"
  | "quality_review"
  | "verification";

export type TurnTimingPhaseStatus =
  | "completed"
  | "corrected"
  | "degraded"
  | "failed"
  | "unverified";

export interface TurnTimingPhase {
  readonly phase: TurnTimingPhaseName;
  readonly status: TurnTimingPhaseStatus;
  readonly started_at: string;
  readonly completed_at: string;
  readonly duration_ms: number;
}

export interface TurnTiming {
  readonly schema_version: 1;
  readonly started_at: string;
  readonly completed_at: string;
  readonly duration_ms: number;
  readonly phases: readonly TurnTimingPhase[];
}

export interface TrajectoryDetail {
  readonly schema_version: 1;
  readonly activities: readonly InvestigationActivity[];
  readonly branches: readonly EvidenceBranch[];
  readonly milestones: readonly InvestigationMilestone[];
  readonly omitted: {
    readonly activities: number;
    readonly branches: number;
    readonly milestones: number;
  };
  readonly truncated_outputs: number;
}

export type IntentEvidenceMode =
  | "screen_grounded"
  | "document_grounded"
  | "operational_grounded"
  | "web_grounded"
  | "mixed_grounded"
  | "model_knowledge"
  | "partial"
  | "held_for_review";

export type IntentEvidenceAuthority =
  | "server_inventory_graph"
  | "server_metering"
  | "server_ontology_manifest"
  | "server_ontology_instance_path"
  | "server_ontology_query"
  | "server_operational_metrics"
  | "server_operational_state_history"
  | "server_resource_health"
  | "server_governed_document"
  | "server_subscription_scope"
  | "server_subscription_health";

export interface IntentGraphMetadata {
  readonly schema_version: 2;
  readonly goals: readonly {
    readonly goal_id: string;
    readonly intent: string;
    readonly capability: string | null;
    readonly arguments: Readonly<Record<string, unknown>>;
    readonly depends_on: readonly string[];
    readonly evidence_mode: string;
    readonly freshness_required: boolean;
    readonly confidence: number;
    readonly alternatives: readonly string[];
  }[];
  readonly clarification: string | null;
  readonly confidence: number;
  readonly action_posture: "advise_only" | "draft_only";
}

export interface IntentGraphEvidence {
  readonly schema_version: 2;
  readonly status: "completed" | "partial" | "unavailable" | "failed" | "cancelled";
  readonly evidence_mode: IntentEvidenceMode;
  readonly goals: readonly {
    readonly task_id: string;
    readonly goal_id: string;
    readonly intent: string;
    readonly capability: string | null;
    readonly evidence_mode: string;
    readonly status: "completed" | "unavailable" | "failed" | "timed_out" | "skipped" | "cancelled";
    readonly duration_ms: number;
    readonly depends_on: readonly string[];
    readonly reason?: string;
    readonly blocked_by?: readonly string[];
    readonly evidence_refs?: readonly string[];
    readonly authority?: IntentEvidenceAuthority;
    readonly started_at: string;
    readonly completed_at: string;
  }[];
}

export interface IncidentCandidate {
  readonly incidentId: string;
  readonly correlationId: string;
  readonly title: string;
  readonly severity: string;
  readonly status: "open" | "in_progress" | "resolved";
  readonly lastUpdatedAt: string;
  readonly locale: "en" | "ko";
}

export type PresentationTone = "neutral" | "positive" | "attention" | "warning";
export type PresentationEmphasis = "primary" | "secondary" | "supporting";
export type PresentationLayout = "stack" | "operational_brief" | "markdown_document";
export type PresentationAssemblyInputKind =
  | "incident_projection"
  | "operator_locale"
  | "presentation_context"
  | "verified_semantic_result";

export interface PresentationAssembly {
  readonly mode: "dynamic";
  readonly label: string;
  readonly sectionCount: number;
  readonly inputKinds: readonly PresentationAssemblyInputKind[];
  readonly digest: string;
}

export interface PresentationSummaryItem {
  readonly label: string;
  readonly value: string;
  readonly tone: PresentationTone;
}

export interface PresentationChartItem {
  readonly label: string;
  readonly value: number;
  readonly tone: PresentationTone;
}

export interface PresentationColumn {
  readonly key: string;
  readonly label: string;
}

interface PresentationBlockBase {
  readonly slotId: string;
  readonly title: string;
  readonly emphasis: PresentationEmphasis;
  readonly collapsed: boolean;
  readonly evidenceRefs: readonly string[];
}

export interface PresentationTableData {
  readonly columns: readonly PresentationColumn[];
  readonly rows: readonly Readonly<Record<string, string>>[];
  readonly statusKey: string | null;
}

export interface PresentationAccessibleChartData {
  readonly description: string;
  readonly unit: string;
  readonly items: readonly PresentationChartItem[];
  readonly exactTable: PresentationTableData;
  readonly visualization?: "bar" | "bar_list" | "donut";
}

export interface PresentationCoverageItem extends PresentationChartItem {
  readonly total: number;
}

export type PresentationBlock =
  | PresentationBlockBase & {
      readonly kind: "summary";
      readonly data: { readonly items: readonly PresentationSummaryItem[] };
    }
  | PresentationBlockBase & {
      readonly kind: "callout";
      readonly data: { readonly tone: PresentationTone; readonly lines: readonly string[] };
    }
  | PresentationBlockBase & { readonly kind: "table"; readonly data: PresentationTableData }
  | PresentationBlockBase & {
      readonly kind: "threshold_table";
      readonly data: PresentationTableData;
    }
  | PresentationBlockBase & { readonly kind: "list"; readonly data: PresentationTableData }
  | PresentationBlockBase & {
      readonly kind: "bar";
      readonly data: { readonly items: readonly PresentationChartItem[] };
    }
  | PresentationBlockBase & {
      readonly kind: "bar";
      readonly data: PresentationAccessibleChartData;
    }
  | PresentationBlockBase & {
      readonly kind: "coverage";
      readonly data: { readonly items: readonly PresentationChartItem[] };
    }
  | PresentationBlockBase & {
      readonly kind: "coverage";
      readonly data: Omit<PresentationAccessibleChartData, "items" | "visualization"> & {
        readonly visualization?: "category_bar";
        readonly items: readonly PresentationCoverageItem[];
      };
    }
  | PresentationBlockBase & {
      readonly kind: "time_series";
      readonly data: {
        readonly description: string;
        readonly metric: string;
        readonly unit: string;
        readonly visualization?: "area" | "line";
        readonly points: readonly { readonly timestamp: string; readonly value: number }[];
        readonly exactTable: PresentationTableData;
      };
    }
  | PresentationBlockBase & {
      readonly kind: "comparison";
      readonly data: {
        readonly description: string;
        readonly metric: string;
        readonly unit: string;
        readonly visualization?: "comparison_bar";
        readonly items: readonly {
          readonly role: "baseline" | "current" | "target" | "before" | "after";
          readonly label: string;
          readonly value: number;
        }[];
        readonly exactTable: PresentationTableData;
      };
    }
  | PresentationBlockBase & {
      readonly kind: "timeline";
      readonly data: {
        readonly description: string;
        readonly visualization?: "tracker";
        readonly items: readonly { readonly timestamp: string; readonly label: string }[];
        readonly exactTable: PresentationTableData;
      };
    }
  | PresentationBlockBase & {
      readonly kind: "scatter";
      readonly data: {
        readonly description: string;
        readonly xLabel: string;
        readonly yLabel: string;
        readonly points: readonly { readonly label: string; readonly x: number; readonly y: number }[];
        readonly exactTable: PresentationTableData;
      };
    }
  | PresentationBlockBase & {
      readonly kind: "heatmap";
      readonly data: {
        readonly description: string;
        readonly rowLabel: string;
        readonly columnLabel: string;
        readonly cells: readonly { readonly row: string; readonly column: string; readonly value: number }[];
        readonly exactTable: PresentationTableData;
      };
    }
  | PresentationBlockBase & {
      readonly kind: "evidence";
      readonly data: {
        readonly items: readonly { readonly label: string; readonly value: string }[];
      };
    };

export interface PresentationArtifact {
  readonly schemaVersion: 1 | 2 | 3;
  readonly layout: PresentationLayout;
  readonly blocks: readonly PresentationBlock[];
  readonly evidenceRefs: readonly string[];
  readonly assembly?: PresentationAssembly;
}

export interface ConversationDocumentArtifact {
  readonly sourceRequestId: string;
  readonly expectedRows: number;
  readonly includedRows: number;
  readonly complete: true;
  readonly sha256: string;
  readonly previewMarkdown: string;
  readonly markdownUrl: string;
  readonly pdfUrl?: string;
}

export type ProgressiveAnswer = Answer & {
  readonly adaptiveAnswer?: import("./adaptive-answer").AdaptiveAnswer;
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
  readonly evidenceFreshnessContext?: EvidenceFreshnessContext;
  readonly modelTrace?: ModelTrace;
  readonly modelLatencyMs?: number;
  readonly modelUsage?: ModelUsage;
  readonly turnTiming?: TurnTiming;
  readonly trajectoryDetail?: TrajectoryDetail;
  readonly intentGraph?: IntentGraphMetadata;
  readonly intentGraphEvidence?: IntentGraphEvidence;
  readonly evidenceMode?: IntentEvidenceMode;
  readonly semanticReceipt?: SemanticProjectionReceipt;
  readonly incidentCandidates?: readonly IncidentCandidate[];
  readonly presentationArtifact?: PresentationArtifact;
  readonly documentArtifact?: ConversationDocumentArtifact;
  readonly conversationBinding?: import("./open-deck").IncidentConversationBinding;
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
  readonly semanticPlanningProfile?: "interactive" | "golden_campaign_no_t2";
  readonly targetAgent?: string;
  readonly handoverGoalId?: string;
  readonly conversationBinding?: import("./open-deck").IncidentConversationBinding;
  /** Inline image attachments to escalate this turn to a vision narrator. */
  readonly attachments?: readonly import("./composer-attachment-store").ChatAttachment[];
}
