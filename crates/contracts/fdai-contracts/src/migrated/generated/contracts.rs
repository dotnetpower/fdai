use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Alertnoisecommandv000 {
    pub schema_version: String,
    pub capability: String,
}

impl Alertnoisecommandv000 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "0.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.capability.as_str(), "unavailable") { return Err("invalid capability literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Alertnoisecommandv100evaluation {
    pub metric_ref: String,
    pub operator: String,
    pub threshold: f64,
    pub window_seconds: i64,
    pub frequency_seconds: i64,
    pub aggregation: String,
}

impl Alertnoisecommandv100evaluation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.operator.as_str(), "above" | "below") { return Err("invalid operator literal"); }
        if !matches!(self.aggregation.as_str(), "average" | "maximum" | "minimum") { return Err("invalid aggregation literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Alertnoisecommandv100alerttreatment {
    pub kind: String,
    pub target_ref: String,
    pub replacement_group_ref: String,
    pub remove_group_ref: String,
    pub processing_rule_ref: String,
    pub starts_at: String,
    pub ends_at: String,
    pub evaluation: String,
}

impl Alertnoisecommandv100alerttreatment {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "routing" | "suppression" | "evaluation") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Alertnoisecommandv100alertnoisecommand {
    pub schema_version: String,
    pub operation: String,
    pub request_ref: String,
    pub requester_ref: String,
    pub scope_ref: String,
    pub requested_at: String,
    pub expires_at: String,
    pub evidence_digest: String,
    pub treatment: String,
    pub execution_authority: String,
    pub period_seconds: String,
}

impl Alertnoisecommandv100alertnoisecommand {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.operation.as_str(), "alert_noise.assess" | "alert_noise.propose") { return Err("invalid operation literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Alertnoisecommandv100 {
    pub command: Box<Alertnoisecommandv100alertnoisecommand>,
    pub signature: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Alertnoisereadinessv000 {
    pub schema_version: String,
    pub capability: String,
}

impl Alertnoisereadinessv000 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "0.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.capability.as_str(), "unavailable") { return Err("invalid capability literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Alertnoisereadinessv100alertnoisereadiness {
    pub kind: String,
    pub scope_refs: Vec<String>,
    pub generated_at: String,
    pub valid_until: String,
    pub execution_authority: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Alertnoisereadinessv100 {
    pub readiness: Box<Alertnoisereadinessv100alertnoisereadiness>,
    pub signature: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Alertnoiseresultv000 {
    pub schema_version: String,
    pub capability: String,
}

impl Alertnoiseresultv000 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "0.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.capability.as_str(), "unavailable") { return Err("invalid capability literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Alertnoiseresultv110evaluation {
    pub metric_ref: String,
    pub operator: String,
    pub threshold: f64,
    pub window_seconds: i64,
    pub frequency_seconds: i64,
    pub aggregation: String,
}

impl Alertnoiseresultv110evaluation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.operator.as_str(), "above" | "below") { return Err("invalid operator literal"); }
        if !matches!(self.aggregation.as_str(), "average" | "maximum" | "minimum") { return Err("invalid aggregation literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Alertnoiseresultv110alerttreatment {
    pub kind: String,
    pub target_ref: String,
    pub replacement_group_ref: String,
    pub remove_group_ref: String,
    pub processing_rule_ref: String,
    pub starts_at: String,
    pub ends_at: String,
    pub evaluation: String,
}

impl Alertnoiseresultv110alerttreatment {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "routing" | "suppression" | "evaluation") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Alertnoiseresultv110alertnoisecommand {
    pub schema_version: String,
    pub operation: String,
    pub request_ref: String,
    pub requester_ref: String,
    pub scope_ref: String,
    pub requested_at: String,
    pub expires_at: String,
    pub evidence_digest: String,
    pub treatment: String,
    pub execution_authority: String,
    pub period_seconds: String,
}

impl Alertnoiseresultv110alertnoisecommand {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.operation.as_str(), "alert_noise.assess" | "alert_noise.propose") { return Err("invalid operation literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Alertnoiseresultv110noisefinding {
    pub rule_ref: String,
    pub service_ref: String,
    pub reason: String,
    pub guidance: String,
    pub source_episodes: Option<i64>,
    pub observed_deliveries: Option<i64>,
    pub potential_recipients_lower: String,
    pub potential_recipients_upper: String,
    pub duplicate_paths: String,
    pub protected: bool,
    pub team_refs: String,
    pub audience_kinds: String,
}

impl Alertnoiseresultv110noisefinding {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.reason.as_str(), "storm" | "flapping" | "overlap" | "broad_role" | "unowned" | "protected" | "incomplete") { return Err("invalid reason literal"); }
        if !matches!(self.guidance.as_str(), "review-routing" | "review-evaluation" | "review-ownership" | "retain-protected" | "collect-evidence") { return Err("invalid guidance literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Alertnoiseresultv110noiseassessment {
    pub schema_version: String,
    pub source: String,
    pub evidence_digest: String,
    pub policy_digest: String,
    pub tenant_ref: String,
    pub scope_ref: String,
    pub observed_at: String,
    pub valid_until: String,
    pub window_start: String,
    pub window_end: String,
    pub coverage: String,
    pub reasons: Vec<String>,
    pub source_episodes: Option<i64>,
    pub notification_attempts: Option<i64>,
    pub confirmed_deliveries: Option<i64>,
    pub acknowledgements: Option<i64>,
    pub findings: Vec<Alertnoiseresultv110noisefinding>,
    pub execution_authority: String,
}

impl Alertnoiseresultv110noiseassessment {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.coverage.as_str(), "complete" | "partial" | "unavailable") { return Err("invalid coverage literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Alertnoiseresultv110alertchangeplan {
    pub schema_version: String,
    pub action_type: String,
    pub tenant_ref: String,
    pub scope_ref: String,
    pub requester_ref: String,
    pub evidence_digest: String,
    pub policy_digest: String,
    pub target_revision: String,
    pub treatment: Box<Alertnoiseresultv110alerttreatment>,
    pub service_refs: Vec<String>,
    pub lock_refs: Vec<String>,
    pub created_at: String,
    pub expires_at: String,
    pub max_execution_seconds: i64,
    pub max_observation_seconds: i64,
    pub max_recovery_seconds: i64,
    pub rollback_ref: String,
    pub evaluation_receipt_digest: String,
    pub execution_path: String,
    pub default_mode: String,
    pub quorum_required: String,
    pub execution_authority: String,
}

impl Alertnoiseresultv110alertchangeplan {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.action_type.as_str(), "ops.update-alert-routing" | "ops.set-alert-notification-window" | "ops.tune-alert-evaluation" | "ops.restore-alert-configuration") { return Err("invalid action_type literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Alertnoiseresultv110alertrule {
    pub r#ref: String,
    pub resource_ref: String,
    pub service_ref: String,
    pub revision: String,
    pub kind: String,
    pub severity: String,
    pub classification: String,
    pub group_refs: String,
    pub enabled: String,
    pub stateful: String,
    pub evaluation: String,
    pub active_incident: String,
    pub iac_owned: String,
    pub ownership_verified: String,
}

impl Alertnoiseresultv110alertrule {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "metric" | "log" | "activity" | "processing" | "unknown") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Alertnoiseresultv110processingrule {
    pub r#ref: String,
    pub revision: String,
    pub rule_refs: Vec<String>,
    pub action: String,
    pub group_refs: String,
    pub enabled: bool,
    pub effective_from: String,
    pub effective_to: String,
    pub semantics_complete: String,
}

impl Alertnoiseresultv110processingrule {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.action.as_str(), "suppress" | "add") { return Err("invalid action literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Alertnoiseresultv110alertrollbackbaseline {
    pub rule: Box<Alertnoiseresultv110alertrule>,
    pub processing_rule: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Alertnoiseresultv110evaluationcaseresult {
    pub r#ref: String,
    pub actionable: bool,
    pub baseline_detected: bool,
    pub treatment_detected: bool,
    pub baseline_latency_seconds: Option<i64>,
    pub treatment_latency_seconds: Option<i64>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Alertnoiseresultv110evaluationreceipt {
    pub rule_ref: String,
    pub rule_revision: String,
    pub scenario_digest: String,
    pub baseline: Box<Alertnoiseresultv110evaluation>,
    pub treatment: Box<Alertnoiseresultv110evaluation>,
    pub evaluated_at: String,
    pub expires_at: String,
    pub baseline_true_positive: i64,
    pub treatment_true_positive: i64,
    pub baseline_false_positive: i64,
    pub treatment_false_positive: i64,
    pub baseline_false_negative: i64,
    pub treatment_false_negative: i64,
    pub accepted: bool,
    pub reason: String,
    pub replay_method: String,
    pub baseline_max_latency_seconds: String,
    pub treatment_max_latency_seconds: String,
    pub case_results: String,
    pub execution_authority: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Alertnoiseresultv110alertprocesslink {
    pub process_id: String,
    pub workflow_ref: String,
    pub status: String,
    pub mode: String,
}

impl Alertnoiseresultv110alertprocesslink {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.status.as_str(), "pending" | "running" | "waiting" | "compensating" | "compensated" | "succeeded" | "failed" | "cancelled" | "timed_out") { return Err("invalid status literal"); }
        if !matches!(self.mode.as_str(), "shadow" | "enforce") { return Err("invalid mode literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Alertnoiseresultv110alertproposaldetail {
    pub plan_digest: String,
    pub baseline: Box<Alertnoiseresultv110alertrollbackbaseline>,
    pub evaluation: String,
    pub process: String,
    pub recorded_at: String,
    pub execution_authority: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Alertnoiseresultv110alertnoiseresult {
    pub schema_version: String,
    pub producer: String,
    pub command: Box<Alertnoiseresultv110alertnoisecommand>,
    pub command_digest: String,
    pub recorded_at: String,
    pub status: String,
    pub reason: String,
    pub assessment: String,
    pub plan: String,
    pub detail: String,
    pub execution_authority: String,
}

impl Alertnoiseresultv110alertnoiseresult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.status.as_str(), "assessment_ready" | "proposal_ready" | "held") { return Err("invalid status literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Alertnoiseresultv110 {
    pub result: Box<Alertnoiseresultv110alertnoiseresult>,
    pub signature: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Channelattachmentadmissionv000 {
    pub schema_version: String,
    pub capability: String,
}

impl Channelattachmentadmissionv000 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "0.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.capability.as_str(), "unavailable") { return Err("invalid capability literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Channelattachmentadmissionv100 {
    pub schema_version: String,
    pub handoff_id: String,
    pub idempotency_key: String,
    pub origin_digest: String,
    pub ordinal: i64,
    pub attributed_principal_id: String,
    pub principal_manifest_digest: String,
    pub conversation_ref: String,
    pub requested_purpose: String,
    pub source_name: String,
    pub media_type_hint: String,
    pub declared_size: i64,
    pub requested_at: String,
    pub request_digest: String,
    pub execution_authority: bool,
}

impl Channelattachmentadmissionv100 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.requested_purpose.as_str(), "handover_bootstrap" | "knowledge_base") { return Err("invalid requested_purpose literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Channelattachmentreceiptv000 {
    pub schema_version: String,
    pub capability: String,
}

impl Channelattachmentreceiptv000 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "0.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.capability.as_str(), "unavailable") { return Err("invalid capability literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Channelattachmentreceiptv100admission {
    pub schema_version: String,
    pub receipt_kind: String,
    pub handoff_id: String,
    pub request_digest: String,
    pub policy_digest: String,
    pub max_content_bytes: i64,
    pub accepted_at: String,
    pub expires_at: String,
    pub execution_authority: bool,
    pub receipt_digest: String,
}

impl Channelattachmentreceiptv100admission {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.receipt_kind.as_str(), "admission") { return Err("invalid receipt_kind literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Channelattachmentreceiptv100commit {
    pub schema_version: String,
    pub receipt_kind: String,
    pub handoff_id: String,
    pub request_digest: String,
    pub upload_id: String,
    pub document_id: String,
    pub version_id: String,
    pub observed_size: i64,
    pub observed_sha256: String,
    pub state: String,
    pub committed_at: String,
    pub execution_authority: bool,
    pub receipt_digest: String,
}

impl Channelattachmentreceiptv100commit {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.receipt_kind.as_str(), "commit") { return Err("invalid receipt_kind literal"); }
        if !matches!(self.state.as_str(), "received") { return Err("invalid state literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Channelattachmentreceiptv100terminal {
    pub schema_version: String,
    pub receipt_kind: String,
    pub handoff_id: String,
    pub request_digest: String,
    pub upload_id: String,
    pub document_id: String,
    pub version_id: String,
    pub commit_receipt_digest: String,
    pub observed_size: i64,
    pub observed_sha256: String,
    pub requested_purpose: String,
    pub outcome: String,
    pub document_state: String,
    pub index_state: String,
    pub retention_state: String,
    pub active: bool,
    pub available: bool,
    pub handover_draft_ready: bool,
    pub citation: Option<String>,
    pub reason_code: Option<String>,
    pub observed_at: String,
    pub execution_authority: bool,
    pub receipt_digest: String,
}

impl Channelattachmentreceiptv100terminal {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.receipt_kind.as_str(), "terminal") { return Err("invalid receipt_kind literal"); }
        if !matches!(self.requested_purpose.as_str(), "handover_bootstrap" | "knowledge_base") { return Err("invalid requested_purpose literal"); }
        if !matches!(self.outcome.as_str(), "pending" | "ready" | "rejected") { return Err("invalid outcome literal"); }
        if !matches!(self.document_state.as_str(), "created" | "uploading" | "received" | "quarantined" | "scanning" | "protection_check" | "extracting" | "indexing" | "ready" | "ready_with_warnings" | "held" | "failed" | "deleting" | "deleted") { return Err("invalid document_state literal"); }
        if !matches!(self.index_state.as_str(), "not_requested" | "queued" | "building" | "active" | "tombstoned" | "purged" | "failed") { return Err("invalid index_state literal"); }
        if !matches!(self.retention_state.as_str(), "live" | "expiring" | "held" | "tombstoned" | "purge_pending" | "purged") { return Err("invalid retention_state literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv100 {
    pub schema_version: String,
    pub projection_id: String,
    pub request_id: String,
    pub correlation_id: String,
    pub idempotency_key: String,
    pub status: String,
    pub recorded_at: String,
    pub payload: BTreeMap<String, String>,
}

impl Coreoperatorprojectionv100 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.status.as_str(), "accepted" | "available" | "unavailable") { return Err("invalid status literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv110 {
    pub schema_version: String,
    pub projection_id: String,
    pub request_id: String,
    pub correlation_id: String,
    pub idempotency_key: String,
    pub status: String,
    pub recorded_at: String,
    pub payload: BTreeMap<String, String>,
    pub evidence_digest: String,
}

impl Coreoperatorprojectionv110 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.status.as_str(), "accepted" | "available" | "unavailable") { return Err("invalid status literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv120semanticresult {
    pub disposition: String,
    pub reason_code: String,
    pub semantic_route: String,
    pub unavailable_reason: String,
    pub session_id: String,
    pub turn_id: String,
    pub turn_sequence: i64,
    pub ontology_release_digest: String,
    pub principal_manifest_digest: String,
    pub plan_digest: String,
    pub execution_receipt_digest: String,
    pub intent_graph: String,
    pub intent_graph_evidence: String,
    pub evidence_refs: Vec<String>,
    pub checks_completed: i64,
    pub checks_total: i64,
    pub answer: String,
    pub execution_authority: bool,
}

impl Coreoperatorprojectionv120semanticresult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.disposition.as_str(), "answered" | "held" | "clarification" | "unsupported" | "action_draft" | "cancelled") { return Err("invalid disposition literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv120 {
    pub schema_version: String,
    pub projection_id: String,
    pub request_id: String,
    pub correlation_id: String,
    pub idempotency_key: String,
    pub status: String,
    pub recorded_at: String,
    pub payload: BTreeMap<String, String>,
    pub evidence_digest: String,
    pub semantic_result: String,
}

impl Coreoperatorprojectionv120 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.status.as_str(), "accepted" | "available" | "unavailable" | "answered" | "held" | "clarification" | "unsupported" | "action_draft" | "cancelled") { return Err("invalid status literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv130semanticresultassuranceobservationframeoption1 {
    pub operation: String,
    pub subject_types: Vec<String>,
    pub measure_concepts: Vec<String>,
    pub temporal_scope: String,
    pub output_shape: String,
    pub frame_digest: String,
}

impl Coreoperatorprojectionv130semanticresultassuranceobservationframeoption1 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.operation.as_str(), "select" | "aggregate" | "compare" | "explain_change" | "validate" | "action_draft") { return Err("invalid operation literal"); }
        if !matches!(self.temporal_scope.as_str(), "none" | "current" | "windowed" | "historical") { return Err("invalid temporal_scope literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv130semanticresultassuranceobservationontologypathsitemstepsitem {
    pub from_type: String,
    pub link_type: String,
    pub direction: String,
    pub to_type: String,
}

impl Coreoperatorprojectionv130semanticresultassuranceobservationontologypathsitemstepsitem {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.direction.as_str(), "outgoing" | "incoming") { return Err("invalid direction literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv130semanticresultassuranceobservationontologypathsitem {
    pub path_id: String,
    pub steps: Vec<Coreoperatorprojectionv130semanticresultassuranceobservationontologypathsitemstepsitem>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv130semanticresultassuranceobservation {
    pub schema_version: String,
    pub frame: String,
    pub capabilities: Vec<String>,
    pub object_types: Vec<String>,
    pub link_types: Vec<String>,
    pub function_types: Vec<String>,
    pub ontology_paths: Vec<Coreoperatorprojectionv130semanticresultassuranceobservationontologypathsitem>,
    pub fact_kinds: Vec<String>,
    pub limitation_kinds: Vec<String>,
    pub claim_kinds: Vec<String>,
    pub evidence_posture: String,
    pub authority_posture: String,
    pub read_performed: bool,
    pub observation_digest: String,
    pub execution_authority: bool,
}

impl Coreoperatorprojectionv130semanticresultassuranceobservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.evidence_posture.as_str(), "fresh" | "stale" | "incomplete" | "conflicting" | "unavailable") { return Err("invalid evidence_posture literal"); }
        if !matches!(self.authority_posture.as_str(), "read_only" | "draft_only") { return Err("invalid authority_posture literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv130semanticresult {
    pub disposition: String,
    pub reason_code: String,
    pub semantic_route: String,
    pub unavailable_reason: String,
    pub session_id: String,
    pub turn_id: String,
    pub turn_sequence: i64,
    pub ontology_release_digest: String,
    pub principal_manifest_digest: String,
    pub plan_digest: String,
    pub execution_receipt_digest: String,
    pub intent_graph: String,
    pub intent_graph_evidence: String,
    pub evidence_refs: Vec<String>,
    pub checks_completed: i64,
    pub checks_total: i64,
    pub answer: String,
    pub assurance_observation: String,
    pub execution_authority: bool,
}

impl Coreoperatorprojectionv130semanticresult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.disposition.as_str(), "answered" | "held" | "clarification" | "unsupported" | "action_draft" | "cancelled") { return Err("invalid disposition literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv130 {
    pub schema_version: String,
    pub projection_id: String,
    pub request_id: String,
    pub correlation_id: String,
    pub idempotency_key: String,
    pub status: String,
    pub recorded_at: String,
    pub payload: BTreeMap<String, String>,
    pub evidence_digest: String,
    pub semantic_result: String,
}

impl Coreoperatorprojectionv130 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.3.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.status.as_str(), "accepted" | "available" | "unavailable" | "answered" | "held" | "clarification" | "unsupported" | "action_draft" | "cancelled") { return Err("invalid status literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv140semanticresultassuranceobservationframeoption1 {
    pub operation: String,
    pub subject_types: Vec<String>,
    pub measure_concepts: Vec<String>,
    pub temporal_scope: String,
    pub output_shape: String,
    pub frame_digest: String,
}

impl Coreoperatorprojectionv140semanticresultassuranceobservationframeoption1 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.operation.as_str(), "select" | "aggregate" | "compare" | "explain_change" | "validate" | "action_draft") { return Err("invalid operation literal"); }
        if !matches!(self.temporal_scope.as_str(), "none" | "current" | "windowed" | "historical") { return Err("invalid temporal_scope literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv140semanticresultassuranceobservationontologypathsitemstepsitem {
    pub from_type: String,
    pub link_type: String,
    pub direction: String,
    pub to_type: String,
}

impl Coreoperatorprojectionv140semanticresultassuranceobservationontologypathsitemstepsitem {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.direction.as_str(), "outgoing" | "incoming") { return Err("invalid direction literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv140semanticresultassuranceobservationontologypathsitem {
    pub path_id: String,
    pub steps: Vec<Coreoperatorprojectionv140semanticresultassuranceobservationontologypathsitemstepsitem>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv140semanticresultassuranceobservation {
    pub schema_version: String,
    pub frame: String,
    pub capabilities: Vec<String>,
    pub object_types: Vec<String>,
    pub link_types: Vec<String>,
    pub function_types: Vec<String>,
    pub ontology_paths: Vec<Coreoperatorprojectionv140semanticresultassuranceobservationontologypathsitem>,
    pub fact_kinds: Vec<String>,
    pub limitation_kinds: Vec<String>,
    pub claim_kinds: Vec<String>,
    pub evidence_posture: String,
    pub authority_posture: String,
    pub read_performed: bool,
    pub observation_digest: String,
    pub execution_authority: bool,
}

impl Coreoperatorprojectionv140semanticresultassuranceobservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.evidence_posture.as_str(), "fresh" | "stale" | "incomplete" | "conflicting" | "unavailable") { return Err("invalid evidence_posture literal"); }
        if !matches!(self.authority_posture.as_str(), "read_only" | "draft_only") { return Err("invalid authority_posture literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv140semanticresult {
    pub disposition: String,
    pub reason_code: String,
    pub semantic_route: String,
    pub unavailable_reason: String,
    pub session_id: String,
    pub turn_id: String,
    pub turn_sequence: i64,
    pub ontology_release_digest: String,
    pub principal_manifest_digest: String,
    pub plan_digest: String,
    pub execution_receipt_digest: String,
    pub intent_graph: String,
    pub intent_graph_evidence: String,
    pub evidence_refs: Vec<String>,
    pub checks_completed: i64,
    pub checks_total: i64,
    pub answer: String,
    pub direct_response_intent: String,
    pub assurance_observation: String,
    pub execution_authority: bool,
}

impl Coreoperatorprojectionv140semanticresult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.disposition.as_str(), "answered" | "direct_response" | "held" | "clarification" | "unsupported" | "action_draft" | "cancelled") { return Err("invalid disposition literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv140 {
    pub schema_version: String,
    pub projection_id: String,
    pub request_id: String,
    pub correlation_id: String,
    pub idempotency_key: String,
    pub status: String,
    pub recorded_at: String,
    pub payload: BTreeMap<String, String>,
    pub evidence_digest: String,
    pub semantic_result: String,
}

impl Coreoperatorprojectionv140 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.4.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.status.as_str(), "accepted" | "available" | "unavailable" | "answered" | "direct_response" | "held" | "clarification" | "unsupported" | "action_draft" | "cancelled") { return Err("invalid status literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv160semanticresultassuranceobservationframeoption1 {
    pub operation: String,
    pub subject_types: Vec<String>,
    pub measure_concepts: Vec<String>,
    pub temporal_scope: String,
    pub output_shape: String,
    pub frame_digest: String,
}

impl Coreoperatorprojectionv160semanticresultassuranceobservationframeoption1 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.operation.as_str(), "select" | "aggregate" | "compare" | "explain_change" | "validate" | "action_draft") { return Err("invalid operation literal"); }
        if !matches!(self.temporal_scope.as_str(), "none" | "current" | "windowed" | "historical") { return Err("invalid temporal_scope literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv160semanticresultassuranceobservationontologypathsitemstepsitem {
    pub from_type: String,
    pub link_type: String,
    pub direction: String,
    pub to_type: String,
}

impl Coreoperatorprojectionv160semanticresultassuranceobservationontologypathsitemstepsitem {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.direction.as_str(), "outgoing" | "incoming") { return Err("invalid direction literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv160semanticresultassuranceobservationontologypathsitem {
    pub path_id: String,
    pub steps: Vec<Coreoperatorprojectionv160semanticresultassuranceobservationontologypathsitemstepsitem>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv160semanticresultassuranceobservation {
    pub schema_version: String,
    pub frame: String,
    pub capabilities: Vec<String>,
    pub object_types: Vec<String>,
    pub link_types: Vec<String>,
    pub function_types: Vec<String>,
    pub ontology_paths: Vec<Coreoperatorprojectionv160semanticresultassuranceobservationontologypathsitem>,
    pub fact_kinds: Vec<String>,
    pub limitation_kinds: Vec<String>,
    pub claim_kinds: Vec<String>,
    pub evidence_posture: String,
    pub authority_posture: String,
    pub read_performed: bool,
    pub observation_digest: String,
    pub execution_authority: bool,
}

impl Coreoperatorprojectionv160semanticresultassuranceobservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.evidence_posture.as_str(), "fresh" | "stale" | "incomplete" | "conflicting" | "unavailable") { return Err("invalid evidence_posture literal"); }
        if !matches!(self.authority_posture.as_str(), "read_only" | "draft_only") { return Err("invalid authority_posture literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv160adaptivegoalresult {
    pub goal_id: String,
    pub kind: String,
    pub status: String,
    pub required: bool,
    pub evidence_refs: String,
    pub limitation: String,
}

impl Coreoperatorprojectionv160adaptivegoalresult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "knowledge" | "operational" | "environment_example") { return Err("invalid kind literal"); }
        if !matches!(self.status.as_str(), "answered" | "unavailable" | "held") { return Err("invalid status literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv160semanticresultadaptiveanswer {
    pub answer: String,
    pub goals: Vec<Coreoperatorprojectionv160adaptivegoalresult>,
    pub role_agent: String,
    pub quality_status: String,
    pub refinements: String,
    pub execution_authority: String,
}

impl Coreoperatorprojectionv160semanticresultadaptiveanswer {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.role_agent.as_str(), "Odin" | "Heimdall" | "Huginn" | "Forseti" | "Var" | "Thor" | "Vidar" | "Saga" | "Bragi" | "Njord" | "Freyr" | "Loki" | "Mimir" | "Norns" | "Muninn") { return Err("invalid role_agent literal"); }
        if !matches!(self.quality_status.as_str(), "passed" | "limited") { return Err("invalid quality_status literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv160semanticresult {
    pub disposition: String,
    pub reason_code: String,
    pub semantic_route: String,
    pub unavailable_reason: String,
    pub session_id: String,
    pub turn_id: String,
    pub turn_sequence: i64,
    pub ontology_release_digest: String,
    pub principal_manifest_digest: String,
    pub plan_digest: String,
    pub execution_receipt_digest: String,
    pub intent_graph: String,
    pub intent_graph_evidence: String,
    pub evidence_refs: Vec<String>,
    pub checks_completed: i64,
    pub checks_total: i64,
    pub answer: String,
    pub direct_response_intent: String,
    pub assurance_observation: String,
    pub execution_authority: bool,
    pub adaptive_answer: String,
}

impl Coreoperatorprojectionv160semanticresult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.disposition.as_str(), "answered" | "direct_response" | "held" | "clarification" | "unsupported" | "action_draft" | "cancelled" | "advisory_response") { return Err("invalid disposition literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv160 {
    pub schema_version: String,
    pub projection_id: String,
    pub request_id: String,
    pub correlation_id: String,
    pub idempotency_key: String,
    pub status: String,
    pub recorded_at: String,
    pub payload: BTreeMap<String, String>,
    pub evidence_digest: String,
    pub semantic_result: String,
}

impl Coreoperatorprojectionv160 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.6.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.status.as_str(), "accepted" | "available" | "unavailable" | "answered" | "direct_response" | "held" | "clarification" | "unsupported" | "action_draft" | "cancelled" | "advisory_response") { return Err("invalid status literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv170semanticresultassuranceobservationframeoption1 {
    pub operation: String,
    pub subject_types: Vec<String>,
    pub measure_concepts: Vec<String>,
    pub temporal_scope: String,
    pub output_shape: String,
    pub frame_digest: String,
}

impl Coreoperatorprojectionv170semanticresultassuranceobservationframeoption1 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.operation.as_str(), "select" | "aggregate" | "compare" | "explain_change" | "validate" | "action_draft") { return Err("invalid operation literal"); }
        if !matches!(self.temporal_scope.as_str(), "none" | "current" | "windowed" | "historical") { return Err("invalid temporal_scope literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv170semanticresultassuranceobservationontologypathsitemstepsitem {
    pub from_type: String,
    pub link_type: String,
    pub direction: String,
    pub to_type: String,
}

impl Coreoperatorprojectionv170semanticresultassuranceobservationontologypathsitemstepsitem {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.direction.as_str(), "outgoing" | "incoming") { return Err("invalid direction literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv170semanticresultassuranceobservationontologypathsitem {
    pub path_id: String,
    pub steps: Vec<Coreoperatorprojectionv170semanticresultassuranceobservationontologypathsitemstepsitem>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv170semanticresultassuranceobservation {
    pub schema_version: String,
    pub frame: String,
    pub capabilities: Vec<String>,
    pub object_types: Vec<String>,
    pub link_types: Vec<String>,
    pub function_types: Vec<String>,
    pub ontology_paths: Vec<Coreoperatorprojectionv170semanticresultassuranceobservationontologypathsitem>,
    pub fact_kinds: Vec<String>,
    pub limitation_kinds: Vec<String>,
    pub claim_kinds: Vec<String>,
    pub evidence_posture: String,
    pub authority_posture: String,
    pub read_performed: bool,
    pub observation_digest: String,
    pub execution_authority: bool,
}

impl Coreoperatorprojectionv170semanticresultassuranceobservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.evidence_posture.as_str(), "fresh" | "stale" | "incomplete" | "conflicting" | "unavailable") { return Err("invalid evidence_posture literal"); }
        if !matches!(self.authority_posture.as_str(), "read_only" | "draft_only") { return Err("invalid authority_posture literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv170adaptivegoalresult {
    pub goal_id: String,
    pub kind: String,
    pub status: String,
    pub required: bool,
    pub evidence_refs: String,
    pub limitation: String,
}

impl Coreoperatorprojectionv170adaptivegoalresult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "knowledge" | "operational" | "environment_example") { return Err("invalid kind literal"); }
        if !matches!(self.status.as_str(), "answered" | "unavailable" | "held") { return Err("invalid status literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv170semanticresultadaptiveanswer {
    pub answer: String,
    pub goals: Vec<Coreoperatorprojectionv170adaptivegoalresult>,
    pub role_agent: String,
    pub quality_status: String,
    pub refinements: String,
    pub execution_authority: String,
}

impl Coreoperatorprojectionv170semanticresultadaptiveanswer {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.role_agent.as_str(), "Odin" | "Heimdall" | "Huginn" | "Forseti" | "Var" | "Thor" | "Vidar" | "Saga" | "Bragi" | "Njord" | "Freyr" | "Loki" | "Mimir" | "Norns" | "Muninn") { return Err("invalid role_agent literal"); }
        if !matches!(self.quality_status.as_str(), "passed" | "limited") { return Err("invalid quality_status literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv170semanticresult {
    pub disposition: String,
    pub reason_code: String,
    pub semantic_route: String,
    pub unavailable_reason: String,
    pub session_id: String,
    pub turn_id: String,
    pub turn_sequence: i64,
    pub ontology_release_digest: String,
    pub principal_manifest_digest: String,
    pub plan_digest: String,
    pub execution_receipt_digest: String,
    pub intent_graph: String,
    pub intent_graph_evidence: String,
    pub evidence_refs: Vec<String>,
    pub checks_completed: i64,
    pub checks_total: i64,
    pub answer: String,
    pub direct_response_intent: String,
    pub assurance_observation: String,
    pub execution_authority: bool,
    pub adaptive_answer: String,
    pub document_context_digest: String,
}

impl Coreoperatorprojectionv170semanticresult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.disposition.as_str(), "answered" | "direct_response" | "held" | "clarification" | "unsupported" | "action_draft" | "cancelled" | "advisory_response") { return Err("invalid disposition literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv170 {
    pub schema_version: String,
    pub projection_id: String,
    pub request_id: String,
    pub correlation_id: String,
    pub idempotency_key: String,
    pub status: String,
    pub recorded_at: String,
    pub payload: BTreeMap<String, String>,
    pub evidence_digest: String,
    pub semantic_result: String,
}

impl Coreoperatorprojectionv170 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.7.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.status.as_str(), "accepted" | "available" | "unavailable" | "answered" | "direct_response" | "held" | "clarification" | "unsupported" | "action_draft" | "cancelled" | "advisory_response") { return Err("invalid status literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv180semanticresultassuranceobservationframeoption1 {
    pub operation: String,
    pub subject_types: Vec<String>,
    pub measure_concepts: Vec<String>,
    pub temporal_scope: String,
    pub output_shape: String,
    pub frame_digest: String,
}

impl Coreoperatorprojectionv180semanticresultassuranceobservationframeoption1 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.operation.as_str(), "select" | "aggregate" | "compare" | "explain_change" | "validate" | "action_draft") { return Err("invalid operation literal"); }
        if !matches!(self.temporal_scope.as_str(), "none" | "current" | "windowed" | "historical") { return Err("invalid temporal_scope literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv180semanticresultassuranceobservationontologypathsitemstepsitem {
    pub from_type: String,
    pub link_type: String,
    pub direction: String,
    pub to_type: String,
}

impl Coreoperatorprojectionv180semanticresultassuranceobservationontologypathsitemstepsitem {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.direction.as_str(), "outgoing" | "incoming") { return Err("invalid direction literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv180semanticresultassuranceobservationontologypathsitem {
    pub path_id: String,
    pub steps: Vec<Coreoperatorprojectionv180semanticresultassuranceobservationontologypathsitemstepsitem>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv180semanticresultassuranceobservation {
    pub schema_version: String,
    pub frame: String,
    pub capabilities: Vec<String>,
    pub object_types: Vec<String>,
    pub link_types: Vec<String>,
    pub function_types: Vec<String>,
    pub ontology_paths: Vec<Coreoperatorprojectionv180semanticresultassuranceobservationontologypathsitem>,
    pub fact_kinds: Vec<String>,
    pub limitation_kinds: Vec<String>,
    pub claim_kinds: Vec<String>,
    pub evidence_posture: String,
    pub authority_posture: String,
    pub read_performed: bool,
    pub observation_digest: String,
    pub execution_authority: bool,
}

impl Coreoperatorprojectionv180semanticresultassuranceobservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.evidence_posture.as_str(), "fresh" | "stale" | "incomplete" | "conflicting" | "unavailable") { return Err("invalid evidence_posture literal"); }
        if !matches!(self.authority_posture.as_str(), "read_only" | "draft_only") { return Err("invalid authority_posture literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv180adaptivegoalresult {
    pub goal_id: String,
    pub kind: String,
    pub status: String,
    pub required: bool,
    pub evidence_refs: String,
    pub limitation: String,
}

impl Coreoperatorprojectionv180adaptivegoalresult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "knowledge" | "operational" | "environment_example") { return Err("invalid kind literal"); }
        if !matches!(self.status.as_str(), "answered" | "unavailable" | "held") { return Err("invalid status literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv180semanticresultadaptiveanswer {
    pub answer: String,
    pub goals: Vec<Coreoperatorprojectionv180adaptivegoalresult>,
    pub role_agent: String,
    pub quality_status: String,
    pub refinements: String,
    pub execution_authority: String,
}

impl Coreoperatorprojectionv180semanticresultadaptiveanswer {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.role_agent.as_str(), "Odin" | "Heimdall" | "Huginn" | "Forseti" | "Var" | "Thor" | "Vidar" | "Saga" | "Bragi" | "Njord" | "Freyr" | "Loki" | "Mimir" | "Norns" | "Muninn") { return Err("invalid role_agent literal"); }
        if !matches!(self.quality_status.as_str(), "passed" | "limited") { return Err("invalid quality_status literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv180semanticresultresulthandleref {
    pub schema_version: String,
    pub handle_ref: String,
    pub key_version: String,
    pub issued_at: String,
    pub expires_at: String,
}

impl Coreoperatorprojectionv180semanticresultresulthandleref {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.1" | "1.2") { return Err("invalid schema_version literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv180semanticresult {
    pub disposition: String,
    pub reason_code: String,
    pub semantic_route: String,
    pub unavailable_reason: String,
    pub session_id: String,
    pub turn_id: String,
    pub turn_sequence: i64,
    pub ontology_release_digest: String,
    pub principal_manifest_digest: String,
    pub plan_digest: String,
    pub execution_receipt_digest: String,
    pub intent_graph: String,
    pub intent_graph_evidence: String,
    pub evidence_refs: Vec<String>,
    pub checks_completed: i64,
    pub checks_total: i64,
    pub answer: String,
    pub direct_response_intent: String,
    pub assurance_observation: String,
    pub execution_authority: bool,
    pub adaptive_answer: String,
    pub document_context_digest: String,
    pub result_handle_ref: String,
}

impl Coreoperatorprojectionv180semanticresult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.disposition.as_str(), "answered" | "direct_response" | "held" | "clarification" | "unsupported" | "action_draft" | "cancelled" | "advisory_response") { return Err("invalid disposition literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Coreoperatorprojectionv180 {
    pub schema_version: String,
    pub projection_id: String,
    pub request_id: String,
    pub correlation_id: String,
    pub idempotency_key: String,
    pub status: String,
    pub recorded_at: String,
    pub payload: BTreeMap<String, String>,
    pub evidence_digest: String,
    pub semantic_result: String,
}

impl Coreoperatorprojectionv180 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.8.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.status.as_str(), "accepted" | "available" | "unavailable" | "answered" | "direct_response" | "held" | "clarification" | "unsupported" | "action_draft" | "cancelled" | "advisory_response") { return Err("invalid status literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Documentingestionactivityv100 {
    pub schema_version: String,
    pub activity_id: String,
    pub upload_id: String,
    pub document_id: String,
    pub idempotency_key: String,
    pub sequence: i64,
    pub action: String,
    pub occurred_at: String,
    pub record: BTreeMap<String, String>,
}

impl Documentingestionactivityv100 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.action.as_str(), "document.cancelled" | "document.received") { return Err("invalid action literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Documentingestionactivityv110 {
    pub schema_version: String,
    pub activity_id: String,
    pub upload_id: String,
    pub document_id: String,
    pub idempotency_key: String,
    pub sequence: i64,
    pub action: String,
    pub occurred_at: String,
    pub record: BTreeMap<String, String>,
    pub record_digest: String,
}

impl Documentingestionactivityv110 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.action.as_str(), "document.cancelled" | "document.received") { return Err("invalid action literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Documentworkerauditv100 {
    pub schema_version: String,
    pub producer_principal: String,
    pub kind: String,
    pub audited_topic: String,
    pub correlation_id: String,
    pub idempotency_key: String,
    pub stage: String,
    pub decision: String,
    pub reason: String,
    pub document_id: String,
    pub upload_id: String,
    pub initiator_principal: String,
    pub approvers: String,
}

impl Documentworkerauditv100 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.producer_principal.as_str(), "Saga") { return Err("invalid producer_principal literal"); }
        if !matches!(self.kind.as_str(), "document_ingestion") { return Err("invalid kind literal"); }
        if !matches!(self.audited_topic.as_str(), "object.verdict" | "object.approval") { return Err("invalid audited_topic literal"); }
        if !matches!(self.stage.as_str(), "received" | "protection_check") { return Err("invalid stage literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Documentworkerindexv100 {
    pub schema_version: String,
    pub producer_principal: String,
    pub kind: String,
    pub stage: String,
    pub command: String,
    pub correlation_id: String,
    pub idempotency_key: String,
    pub resource_id: String,
    pub document_id: String,
    pub upload_id: String,
}

impl Documentworkerindexv100 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.producer_principal.as_str(), "Muninn") { return Err("invalid producer_principal literal"); }
        if !matches!(self.kind.as_str(), "document_ingestion") { return Err("invalid kind literal"); }
        if !matches!(self.stage.as_str(), "indexing") { return Err("invalid stage literal"); }
        if !matches!(self.command.as_str(), "index") { return Err("invalid command literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Executorcommandv100 {
    pub schema_version: String,
    pub command_id: String,
    pub action_schema_version: String,
    pub action_id: String,
    pub event_id: String,
    pub idempotency_key: String,
    pub target_resource_ref: String,
    pub partition_key: String,
    pub execution_path: String,
    pub requested_mode: String,
    pub attempt: i64,
    pub issued_at: String,
    pub deadline_at: String,
    pub action_payload_digest: String,
    pub action_payload: BTreeMap<String, String>,
}

impl Executorcommandv100 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.execution_path.as_str(), "pr_native" | "direct_api" | "pr_manual" | "tool_call") { return Err("invalid execution_path literal"); }
        if !matches!(self.requested_mode.as_str(), "shadow" | "enforce") { return Err("invalid requested_mode literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Executorreceiptv100 {
    pub schema_version: String,
    pub receipt_id: String,
    pub command_id: String,
    pub action_id: String,
    pub idempotency_key: String,
    pub attempt: i64,
    pub action_payload_digest: String,
    pub requested_mode: String,
    pub status: String,
    pub reason: String,
    pub executor_instance_id: String,
    pub received_at: String,
    pub completed_at: String,
    pub effect_applied: bool,
    pub audit_ref: String,
}

impl Executorreceiptv100 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.requested_mode.as_str(), "shadow" | "enforce") { return Err("invalid requested_mode literal"); }
        if !matches!(self.status.as_str(), "shadowed" | "duplicate" | "rejected" | "expired") { return Err("invalid status literal"); }
        if self.effect_applied { return Err("effect_applied violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Executorreceiptv110 {
    pub schema_version: String,
    pub receipt_id: String,
    pub command_id: String,
    pub action_id: String,
    pub idempotency_key: String,
    pub attempt: i64,
    pub action_payload_digest: String,
    pub requested_mode: String,
    pub status: String,
    pub reason: String,
    pub executor_instance_id: String,
    pub received_at: String,
    pub completed_at: String,
    pub effect_applied: bool,
    pub effect_verified: bool,
    pub rollback_succeeded: String,
    pub provider_receipt_ref: String,
    pub safeguard_proof_bundle_digest: String,
    pub audit_ref: String,
}

impl Executorreceiptv110 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.1.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.requested_mode.as_str(), "shadow" | "enforce") { return Err("invalid requested_mode literal"); }
        if !matches!(self.status.as_str(), "dispatched" | "already_applied" | "abstained_blast_radius" | "abstained_precondition" | "stopped" | "failed" | "authentication_failed" | "permission_denied" | "policy_denied" | "network_denied" | "rejected_mode" | "rejected_invariant" | "rejected_idempotency_conflict" | "expired") { return Err("invalid status literal"); }
        if self.effect_verified { return Err("effect_verified violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv100 {
    pub schema_version: String,
    pub request_id: String,
    pub correlation_id: String,
    pub idempotency_key: String,
    pub resource_ref: String,
    pub request_kind: String,
    pub requested_at: String,
}

impl Operatorcorerequestv100 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.request_kind.as_str(), "query" | "proposal") { return Err("invalid request_kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv110 {
    pub schema_version: String,
    pub request_id: String,
    pub correlation_id: String,
    pub idempotency_key: String,
    pub resource_ref: String,
    pub request_kind: String,
    pub requested_at: String,
    pub context_digest: String,
}

impl Operatorcorerequestv110 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.request_kind.as_str(), "query" | "proposal") { return Err("invalid request_kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv1100semanticturnprincipal {
    pub subject_id: String,
    pub principal_kind: String,
    pub roles: Vec<String>,
    pub groups: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv1100semanticturnboundcontext {
    pub kind: String,
    pub incident_id: String,
    pub correlation_id: String,
    pub screen_id: String,
    pub resource_group_id: String,
    pub selection_token: String,
    pub resource_ids: String,
    pub principal_id: String,
    pub principal_scope_digest: String,
    pub ontology_release_digest: String,
    pub source_generation: String,
    pub selection_digest: String,
    pub complete: String,
}

impl Operatorcorerequestv1100semanticturnboundcontext {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "incident" | "screen" | "resource_group") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv1100semanticturninvestigationcontinuation {
    pub schema_version: String,
    pub source_session_id: String,
    pub source_turn_id: String,
    pub source_turn_sequence: i64,
    pub target_type: String,
    pub target_value: String,
    pub recovery_measure_concepts: Vec<String>,
    pub baseline_start: String,
    pub baseline_end: String,
    pub initial_observation_cutoff: String,
    pub ontology_release_digest: String,
    pub principal_manifest_digest: String,
    pub source_frame_digest: String,
    pub source_plan_digest: String,
    pub source_execution_receipt_digest: String,
    pub execution_authority: bool,
}

impl Operatorcorerequestv1100semanticturninvestigationcontinuation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv1100semanticturnpriorturnsitem {
    pub role: String,
    pub content: String,
}

impl Operatorcorerequestv1100semanticturnpriorturnsitem {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.role.as_str(), "user" | "assistant") { return Err("invalid role literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv1100adaptiverelationshipproof {
    pub target_agent: String,
    pub principal_id: String,
    pub kind: String,
    pub source_revision: String,
    pub verified_at: String,
    pub expires_at: String,
    pub execution_authority: String,
}

impl Operatorcorerequestv1100adaptiverelationshipproof {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.target_agent.as_str(), "Odin" | "Heimdall" | "Huginn" | "Forseti" | "Var" | "Thor" | "Vidar" | "Saga" | "Bragi" | "Njord" | "Freyr" | "Loki" | "Mimir" | "Norns" | "Muninn") { return Err("invalid target_agent literal"); }
        if !matches!(self.kind.as_str(), "steward" | "collaborator") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv1100semanticdocumentcontext {
    pub schema_version: String,
    pub source: String,
    pub principal_ref: String,
    pub conversation_ref: String,
    pub citations: Vec<String>,
    pub authorization_digest: String,
    pub receipt_digests: String,
    pub context_digest: String,
    pub execution_authority: String,
}

impl Operatorcorerequestv1100semanticdocumentcontext {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.source.as_str(), "channel_attachment" | "web_reference") { return Err("invalid source literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv1100semanticturnrecentresulthandlesitem {
    pub schema_version: String,
    pub handle_ref: String,
    pub key_version: String,
    pub issued_at: String,
    pub expires_at: String,
}

impl Operatorcorerequestv1100semanticturnrecentresulthandlesitem {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.1" | "1.2") { return Err("invalid schema_version literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv1100semanticturn {
    pub utterance: String,
    pub principal: Box<Operatorcorerequestv1100semanticturnprincipal>,
    pub session_id: String,
    pub turn_id: String,
    pub turn_sequence: i64,
    pub locale: String,
    pub purpose: String,
    pub deadline_at: String,
    pub view_context_digest: String,
    pub bound_context: String,
    pub investigation_continuation: String,
    pub prior_turns: Vec<Operatorcorerequestv1100semanticturnpriorturnsitem>,
    pub planning_profile: String,
    pub include_model_trace: String,
    pub cancelled: String,
    pub execution_authority: bool,
    pub target_agent: String,
    pub relationship_proof: String,
    pub relationship_unknown_reason: String,
    pub conversation_model_tier: String,
    pub document_context: String,
    pub authentication_receipt_ref: String,
    pub recent_result_handles: String,
}

impl Operatorcorerequestv1100semanticturn {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv1100 {
    pub schema_version: String,
    pub request_id: String,
    pub correlation_id: String,
    pub idempotency_key: String,
    pub resource_ref: String,
    pub request_kind: String,
    pub requested_at: String,
    pub context_digest: String,
    pub semantic_turn: String,
}

impl Operatorcorerequestv1100 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.10.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.request_kind.as_str(), "query" | "proposal" | "semantic_query") { return Err("invalid request_kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv120semanticturnprincipal {
    pub subject_id: String,
    pub principal_kind: String,
    pub roles: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv120semanticturnpriorturnsitem {
    pub role: String,
    pub content: String,
}

impl Operatorcorerequestv120semanticturnpriorturnsitem {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.role.as_str(), "user" | "assistant") { return Err("invalid role literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv120semanticturn {
    pub utterance: String,
    pub principal: Box<Operatorcorerequestv120semanticturnprincipal>,
    pub session_id: String,
    pub turn_id: String,
    pub turn_sequence: i64,
    pub locale: String,
    pub purpose: String,
    pub deadline_at: String,
    pub view_context_digest: String,
    pub prior_turns: Vec<Operatorcorerequestv120semanticturnpriorturnsitem>,
    pub cancelled: String,
    pub execution_authority: bool,
}

impl Operatorcorerequestv120semanticturn {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv120 {
    pub schema_version: String,
    pub request_id: String,
    pub correlation_id: String,
    pub idempotency_key: String,
    pub resource_ref: String,
    pub request_kind: String,
    pub requested_at: String,
    pub context_digest: String,
    pub semantic_turn: String,
}

impl Operatorcorerequestv120 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.request_kind.as_str(), "query" | "proposal" | "semantic_query") { return Err("invalid request_kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv130semanticturnprincipal {
    pub subject_id: String,
    pub principal_kind: String,
    pub roles: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv130semanticturnboundcontext {
    pub kind: String,
    pub incident_id: String,
    pub correlation_id: String,
}

impl Operatorcorerequestv130semanticturnboundcontext {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "incident") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv130semanticturnpriorturnsitem {
    pub role: String,
    pub content: String,
}

impl Operatorcorerequestv130semanticturnpriorturnsitem {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.role.as_str(), "user" | "assistant") { return Err("invalid role literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv130semanticturn {
    pub utterance: String,
    pub principal: Box<Operatorcorerequestv130semanticturnprincipal>,
    pub session_id: String,
    pub turn_id: String,
    pub turn_sequence: i64,
    pub locale: String,
    pub purpose: String,
    pub deadline_at: String,
    pub view_context_digest: String,
    pub bound_context: String,
    pub prior_turns: Vec<Operatorcorerequestv130semanticturnpriorturnsitem>,
    pub planning_profile: String,
    pub cancelled: String,
    pub execution_authority: bool,
}

impl Operatorcorerequestv130semanticturn {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv130 {
    pub schema_version: String,
    pub request_id: String,
    pub correlation_id: String,
    pub idempotency_key: String,
    pub resource_ref: String,
    pub request_kind: String,
    pub requested_at: String,
    pub context_digest: String,
    pub semantic_turn: String,
}

impl Operatorcorerequestv130 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.request_kind.as_str(), "query" | "proposal" | "semantic_query") { return Err("invalid request_kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv140semanticturnprincipal {
    pub subject_id: String,
    pub principal_kind: String,
    pub roles: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv140semanticturnboundcontext {
    pub kind: String,
    pub incident_id: String,
    pub correlation_id: String,
}

impl Operatorcorerequestv140semanticturnboundcontext {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "incident") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv140semanticturnpriorturnsitem {
    pub role: String,
    pub content: String,
}

impl Operatorcorerequestv140semanticturnpriorturnsitem {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.role.as_str(), "user" | "assistant") { return Err("invalid role literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv140semanticturn {
    pub utterance: String,
    pub principal: Box<Operatorcorerequestv140semanticturnprincipal>,
    pub session_id: String,
    pub turn_id: String,
    pub turn_sequence: i64,
    pub locale: String,
    pub purpose: String,
    pub deadline_at: String,
    pub view_context_digest: String,
    pub bound_context: String,
    pub prior_turns: Vec<Operatorcorerequestv140semanticturnpriorturnsitem>,
    pub planning_profile: String,
    pub include_model_trace: String,
    pub cancelled: String,
    pub execution_authority: bool,
}

impl Operatorcorerequestv140semanticturn {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv140 {
    pub schema_version: String,
    pub request_id: String,
    pub correlation_id: String,
    pub idempotency_key: String,
    pub resource_ref: String,
    pub request_kind: String,
    pub requested_at: String,
    pub context_digest: String,
    pub semantic_turn: String,
}

impl Operatorcorerequestv140 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.request_kind.as_str(), "query" | "proposal" | "semantic_query") { return Err("invalid request_kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv150semanticturnprincipal {
    pub subject_id: String,
    pub principal_kind: String,
    pub roles: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv150semanticturnboundcontext {
    pub kind: String,
    pub incident_id: String,
    pub correlation_id: String,
    pub screen_id: String,
    pub resource_group_id: String,
    pub selection_token: String,
    pub resource_ids: String,
    pub principal_id: String,
    pub principal_scope_digest: String,
    pub ontology_release_digest: String,
    pub source_generation: String,
    pub selection_digest: String,
    pub complete: String,
}

impl Operatorcorerequestv150semanticturnboundcontext {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "incident" | "screen" | "resource_group") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv150semanticturninvestigationcontinuation {
    pub schema_version: String,
    pub source_session_id: String,
    pub source_turn_id: String,
    pub source_turn_sequence: i64,
    pub target_type: String,
    pub target_value: String,
    pub recovery_measure_concepts: Vec<String>,
    pub baseline_start: String,
    pub baseline_end: String,
    pub initial_observation_cutoff: String,
    pub ontology_release_digest: String,
    pub principal_manifest_digest: String,
    pub source_frame_digest: String,
    pub source_plan_digest: String,
    pub source_execution_receipt_digest: String,
    pub execution_authority: bool,
}

impl Operatorcorerequestv150semanticturninvestigationcontinuation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv150semanticturnpriorturnsitem {
    pub role: String,
    pub content: String,
}

impl Operatorcorerequestv150semanticturnpriorturnsitem {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.role.as_str(), "user" | "assistant") { return Err("invalid role literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv150semanticturn {
    pub utterance: String,
    pub principal: Box<Operatorcorerequestv150semanticturnprincipal>,
    pub session_id: String,
    pub turn_id: String,
    pub turn_sequence: i64,
    pub locale: String,
    pub purpose: String,
    pub deadline_at: String,
    pub view_context_digest: String,
    pub bound_context: String,
    pub investigation_continuation: String,
    pub prior_turns: Vec<Operatorcorerequestv150semanticturnpriorturnsitem>,
    pub planning_profile: String,
    pub include_model_trace: String,
    pub cancelled: String,
    pub execution_authority: bool,
}

impl Operatorcorerequestv150semanticturn {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv150 {
    pub schema_version: String,
    pub request_id: String,
    pub correlation_id: String,
    pub idempotency_key: String,
    pub resource_ref: String,
    pub request_kind: String,
    pub requested_at: String,
    pub context_digest: String,
    pub semantic_turn: String,
}

impl Operatorcorerequestv150 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.5.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.request_kind.as_str(), "query" | "proposal" | "semantic_query") { return Err("invalid request_kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv160semanticturnprincipal {
    pub subject_id: String,
    pub principal_kind: String,
    pub roles: Vec<String>,
    pub groups: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv160semanticturnboundcontext {
    pub kind: String,
    pub incident_id: String,
    pub correlation_id: String,
    pub screen_id: String,
    pub resource_group_id: String,
    pub selection_token: String,
    pub resource_ids: String,
    pub principal_id: String,
    pub principal_scope_digest: String,
    pub ontology_release_digest: String,
    pub source_generation: String,
    pub selection_digest: String,
    pub complete: String,
}

impl Operatorcorerequestv160semanticturnboundcontext {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "incident" | "screen" | "resource_group") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv160semanticturninvestigationcontinuation {
    pub schema_version: String,
    pub source_session_id: String,
    pub source_turn_id: String,
    pub source_turn_sequence: i64,
    pub target_type: String,
    pub target_value: String,
    pub recovery_measure_concepts: Vec<String>,
    pub baseline_start: String,
    pub baseline_end: String,
    pub initial_observation_cutoff: String,
    pub ontology_release_digest: String,
    pub principal_manifest_digest: String,
    pub source_frame_digest: String,
    pub source_plan_digest: String,
    pub source_execution_receipt_digest: String,
    pub execution_authority: bool,
}

impl Operatorcorerequestv160semanticturninvestigationcontinuation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv160semanticturnpriorturnsitem {
    pub role: String,
    pub content: String,
}

impl Operatorcorerequestv160semanticturnpriorturnsitem {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.role.as_str(), "user" | "assistant") { return Err("invalid role literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv160adaptiverelationshipproof {
    pub target_agent: String,
    pub principal_id: String,
    pub kind: String,
    pub source_revision: String,
    pub verified_at: String,
    pub expires_at: String,
    pub execution_authority: String,
}

impl Operatorcorerequestv160adaptiverelationshipproof {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.target_agent.as_str(), "Odin" | "Heimdall" | "Huginn" | "Forseti" | "Var" | "Thor" | "Vidar" | "Saga" | "Bragi" | "Njord" | "Freyr" | "Loki" | "Mimir" | "Norns" | "Muninn") { return Err("invalid target_agent literal"); }
        if !matches!(self.kind.as_str(), "steward" | "collaborator") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv160semanticturn {
    pub utterance: String,
    pub principal: Box<Operatorcorerequestv160semanticturnprincipal>,
    pub session_id: String,
    pub turn_id: String,
    pub turn_sequence: i64,
    pub locale: String,
    pub purpose: String,
    pub deadline_at: String,
    pub view_context_digest: String,
    pub bound_context: String,
    pub investigation_continuation: String,
    pub prior_turns: Vec<Operatorcorerequestv160semanticturnpriorturnsitem>,
    pub planning_profile: String,
    pub include_model_trace: String,
    pub cancelled: String,
    pub execution_authority: bool,
    pub target_agent: String,
    pub relationship_proof: String,
    pub relationship_unknown_reason: String,
}

impl Operatorcorerequestv160semanticturn {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv160 {
    pub schema_version: String,
    pub request_id: String,
    pub correlation_id: String,
    pub idempotency_key: String,
    pub resource_ref: String,
    pub request_kind: String,
    pub requested_at: String,
    pub context_digest: String,
    pub semantic_turn: String,
}

impl Operatorcorerequestv160 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.6.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.request_kind.as_str(), "query" | "proposal" | "semantic_query") { return Err("invalid request_kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv170semanticturnprincipal {
    pub subject_id: String,
    pub principal_kind: String,
    pub roles: Vec<String>,
    pub groups: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv170semanticturnboundcontext {
    pub kind: String,
    pub incident_id: String,
    pub correlation_id: String,
    pub screen_id: String,
    pub resource_group_id: String,
    pub selection_token: String,
    pub resource_ids: String,
    pub principal_id: String,
    pub principal_scope_digest: String,
    pub ontology_release_digest: String,
    pub source_generation: String,
    pub selection_digest: String,
    pub complete: String,
}

impl Operatorcorerequestv170semanticturnboundcontext {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "incident" | "screen" | "resource_group") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv170semanticturninvestigationcontinuation {
    pub schema_version: String,
    pub source_session_id: String,
    pub source_turn_id: String,
    pub source_turn_sequence: i64,
    pub target_type: String,
    pub target_value: String,
    pub recovery_measure_concepts: Vec<String>,
    pub baseline_start: String,
    pub baseline_end: String,
    pub initial_observation_cutoff: String,
    pub ontology_release_digest: String,
    pub principal_manifest_digest: String,
    pub source_frame_digest: String,
    pub source_plan_digest: String,
    pub source_execution_receipt_digest: String,
    pub execution_authority: bool,
}

impl Operatorcorerequestv170semanticturninvestigationcontinuation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv170semanticturnpriorturnsitem {
    pub role: String,
    pub content: String,
}

impl Operatorcorerequestv170semanticturnpriorturnsitem {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.role.as_str(), "user" | "assistant") { return Err("invalid role literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv170adaptiverelationshipproof {
    pub target_agent: String,
    pub principal_id: String,
    pub kind: String,
    pub source_revision: String,
    pub verified_at: String,
    pub expires_at: String,
    pub execution_authority: String,
}

impl Operatorcorerequestv170adaptiverelationshipproof {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.target_agent.as_str(), "Odin" | "Heimdall" | "Huginn" | "Forseti" | "Var" | "Thor" | "Vidar" | "Saga" | "Bragi" | "Njord" | "Freyr" | "Loki" | "Mimir" | "Norns" | "Muninn") { return Err("invalid target_agent literal"); }
        if !matches!(self.kind.as_str(), "steward" | "collaborator") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv170semanticturn {
    pub utterance: String,
    pub principal: Box<Operatorcorerequestv170semanticturnprincipal>,
    pub session_id: String,
    pub turn_id: String,
    pub turn_sequence: i64,
    pub locale: String,
    pub purpose: String,
    pub deadline_at: String,
    pub view_context_digest: String,
    pub bound_context: String,
    pub investigation_continuation: String,
    pub prior_turns: Vec<Operatorcorerequestv170semanticturnpriorturnsitem>,
    pub planning_profile: String,
    pub include_model_trace: String,
    pub cancelled: String,
    pub execution_authority: bool,
    pub target_agent: String,
    pub relationship_proof: String,
    pub relationship_unknown_reason: String,
    pub conversation_model_tier: String,
}

impl Operatorcorerequestv170semanticturn {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv170 {
    pub schema_version: String,
    pub request_id: String,
    pub correlation_id: String,
    pub idempotency_key: String,
    pub resource_ref: String,
    pub request_kind: String,
    pub requested_at: String,
    pub context_digest: String,
    pub semantic_turn: String,
}

impl Operatorcorerequestv170 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.7.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.request_kind.as_str(), "query" | "proposal" | "semantic_query") { return Err("invalid request_kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv180semanticturnprincipal {
    pub subject_id: String,
    pub principal_kind: String,
    pub roles: Vec<String>,
    pub groups: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv180semanticturnboundcontext {
    pub kind: String,
    pub incident_id: String,
    pub correlation_id: String,
    pub screen_id: String,
    pub resource_group_id: String,
    pub selection_token: String,
    pub resource_ids: String,
    pub principal_id: String,
    pub principal_scope_digest: String,
    pub ontology_release_digest: String,
    pub source_generation: String,
    pub selection_digest: String,
    pub complete: String,
}

impl Operatorcorerequestv180semanticturnboundcontext {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "incident" | "screen" | "resource_group") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv180semanticturninvestigationcontinuation {
    pub schema_version: String,
    pub source_session_id: String,
    pub source_turn_id: String,
    pub source_turn_sequence: i64,
    pub target_type: String,
    pub target_value: String,
    pub recovery_measure_concepts: Vec<String>,
    pub baseline_start: String,
    pub baseline_end: String,
    pub initial_observation_cutoff: String,
    pub ontology_release_digest: String,
    pub principal_manifest_digest: String,
    pub source_frame_digest: String,
    pub source_plan_digest: String,
    pub source_execution_receipt_digest: String,
    pub execution_authority: bool,
}

impl Operatorcorerequestv180semanticturninvestigationcontinuation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv180semanticturnpriorturnsitem {
    pub role: String,
    pub content: String,
}

impl Operatorcorerequestv180semanticturnpriorturnsitem {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.role.as_str(), "user" | "assistant") { return Err("invalid role literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv180adaptiverelationshipproof {
    pub target_agent: String,
    pub principal_id: String,
    pub kind: String,
    pub source_revision: String,
    pub verified_at: String,
    pub expires_at: String,
    pub execution_authority: String,
}

impl Operatorcorerequestv180adaptiverelationshipproof {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.target_agent.as_str(), "Odin" | "Heimdall" | "Huginn" | "Forseti" | "Var" | "Thor" | "Vidar" | "Saga" | "Bragi" | "Njord" | "Freyr" | "Loki" | "Mimir" | "Norns" | "Muninn") { return Err("invalid target_agent literal"); }
        if !matches!(self.kind.as_str(), "steward" | "collaborator") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv180semanticdocumentcontext {
    pub schema_version: String,
    pub source: String,
    pub principal_ref: String,
    pub conversation_ref: String,
    pub citations: Vec<String>,
    pub authorization_digest: String,
    pub receipt_digests: String,
    pub context_digest: String,
    pub execution_authority: String,
}

impl Operatorcorerequestv180semanticdocumentcontext {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.source.as_str(), "channel_attachment" | "web_reference") { return Err("invalid source literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv180semanticturn {
    pub utterance: String,
    pub principal: Box<Operatorcorerequestv180semanticturnprincipal>,
    pub session_id: String,
    pub turn_id: String,
    pub turn_sequence: i64,
    pub locale: String,
    pub purpose: String,
    pub deadline_at: String,
    pub view_context_digest: String,
    pub bound_context: String,
    pub investigation_continuation: String,
    pub prior_turns: Vec<Operatorcorerequestv180semanticturnpriorturnsitem>,
    pub planning_profile: String,
    pub include_model_trace: String,
    pub cancelled: String,
    pub execution_authority: bool,
    pub target_agent: String,
    pub relationship_proof: String,
    pub relationship_unknown_reason: String,
    pub conversation_model_tier: String,
    pub document_context: String,
}

impl Operatorcorerequestv180semanticturn {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv180 {
    pub schema_version: String,
    pub request_id: String,
    pub correlation_id: String,
    pub idempotency_key: String,
    pub resource_ref: String,
    pub request_kind: String,
    pub requested_at: String,
    pub context_digest: String,
    pub semantic_turn: String,
}

impl Operatorcorerequestv180 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.8.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.request_kind.as_str(), "query" | "proposal" | "semantic_query") { return Err("invalid request_kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv190semanticturnprincipal {
    pub subject_id: String,
    pub principal_kind: String,
    pub roles: Vec<String>,
    pub groups: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv190semanticturnboundcontext {
    pub kind: String,
    pub incident_id: String,
    pub correlation_id: String,
    pub screen_id: String,
    pub resource_group_id: String,
    pub selection_token: String,
    pub resource_ids: String,
    pub principal_id: String,
    pub principal_scope_digest: String,
    pub ontology_release_digest: String,
    pub source_generation: String,
    pub selection_digest: String,
    pub complete: String,
}

impl Operatorcorerequestv190semanticturnboundcontext {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "incident" | "screen" | "resource_group") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv190semanticturninvestigationcontinuation {
    pub schema_version: String,
    pub source_session_id: String,
    pub source_turn_id: String,
    pub source_turn_sequence: i64,
    pub target_type: String,
    pub target_value: String,
    pub recovery_measure_concepts: Vec<String>,
    pub baseline_start: String,
    pub baseline_end: String,
    pub initial_observation_cutoff: String,
    pub ontology_release_digest: String,
    pub principal_manifest_digest: String,
    pub source_frame_digest: String,
    pub source_plan_digest: String,
    pub source_execution_receipt_digest: String,
    pub execution_authority: bool,
}

impl Operatorcorerequestv190semanticturninvestigationcontinuation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv190semanticturnpriorturnsitem {
    pub role: String,
    pub content: String,
}

impl Operatorcorerequestv190semanticturnpriorturnsitem {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.role.as_str(), "user" | "assistant") { return Err("invalid role literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv190adaptiverelationshipproof {
    pub target_agent: String,
    pub principal_id: String,
    pub kind: String,
    pub source_revision: String,
    pub verified_at: String,
    pub expires_at: String,
    pub execution_authority: String,
}

impl Operatorcorerequestv190adaptiverelationshipproof {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.target_agent.as_str(), "Odin" | "Heimdall" | "Huginn" | "Forseti" | "Var" | "Thor" | "Vidar" | "Saga" | "Bragi" | "Njord" | "Freyr" | "Loki" | "Mimir" | "Norns" | "Muninn") { return Err("invalid target_agent literal"); }
        if !matches!(self.kind.as_str(), "steward" | "collaborator") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv190semanticdocumentcontext {
    pub schema_version: String,
    pub source: String,
    pub principal_ref: String,
    pub conversation_ref: String,
    pub citations: Vec<String>,
    pub authorization_digest: String,
    pub receipt_digests: String,
    pub context_digest: String,
    pub execution_authority: String,
}

impl Operatorcorerequestv190semanticdocumentcontext {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.source.as_str(), "channel_attachment" | "web_reference") { return Err("invalid source literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv190semanticturn {
    pub utterance: String,
    pub principal: Box<Operatorcorerequestv190semanticturnprincipal>,
    pub session_id: String,
    pub turn_id: String,
    pub turn_sequence: i64,
    pub locale: String,
    pub purpose: String,
    pub deadline_at: String,
    pub view_context_digest: String,
    pub bound_context: String,
    pub investigation_continuation: String,
    pub prior_turns: Vec<Operatorcorerequestv190semanticturnpriorturnsitem>,
    pub planning_profile: String,
    pub include_model_trace: String,
    pub cancelled: String,
    pub execution_authority: bool,
    pub target_agent: String,
    pub relationship_proof: String,
    pub relationship_unknown_reason: String,
    pub conversation_model_tier: String,
    pub document_context: String,
    pub authentication_receipt_ref: String,
}

impl Operatorcorerequestv190semanticturn {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Operatorcorerequestv190 {
    pub schema_version: String,
    pub request_id: String,
    pub correlation_id: String,
    pub idempotency_key: String,
    pub resource_ref: String,
    pub request_kind: String,
    pub requested_at: String,
    pub context_digest: String,
    pub semantic_turn: String,
}

impl Operatorcorerequestv190 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.9.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.request_kind.as_str(), "query" | "proposal" | "semantic_query") { return Err("invalid request_kind literal"); }
        Ok(())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AlertNoiseCommandV0_0_0", "AlertNoiseCommandV1_0_0", "AlertNoiseReadinessV0_0_0", "AlertNoiseReadinessV1_0_0", "AlertNoiseResultV0_0_0", "AlertNoiseResultV1_1_0", "ChannelAttachmentAdmissionV0_0_0", "ChannelAttachmentAdmissionV1_0_0", "ChannelAttachmentReceiptV0_0_0", "ChannelAttachmentReceiptV1_0_0", "CoreOperatorProjectionV1_0_0", "CoreOperatorProjectionV1_1_0", "CoreOperatorProjectionV1_2_0", "CoreOperatorProjectionV1_3_0", "CoreOperatorProjectionV1_4_0", "CoreOperatorProjectionV1_6_0", "CoreOperatorProjectionV1_7_0", "CoreOperatorProjectionV1_8_0", "DocumentIngestionActivityV1_0_0", "DocumentIngestionActivityV1_1_0", "DocumentWorkerAuditV1_0_0", "DocumentWorkerIndexV1_0_0", "ExecutorCommandV1_0_0", "ExecutorReceiptV1_0_0", "ExecutorReceiptV1_1_0", "OperatorCoreRequestV1_0_0", "OperatorCoreRequestV1_1_0", "OperatorCoreRequestV1_10_0", "OperatorCoreRequestV1_2_0", "OperatorCoreRequestV1_3_0", "OperatorCoreRequestV1_4_0", "OperatorCoreRequestV1_5_0", "OperatorCoreRequestV1_6_0", "OperatorCoreRequestV1_7_0", "OperatorCoreRequestV1_8_0", "OperatorCoreRequestV1_9_0"];
