use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct LlmBindings {
    pub embedding_model: String,
    pub cross_check_models: Vec<String>,
    pub critic_model: Option<String>,
    pub judge_model: Option<String>,
    pub debate_orchestrator: Option<String>,
    pub rca_reasoner: Option<String>,
    pub rubric_evaluator: Option<String>,
    pub t2_proposer: Option<String>,
    pub conversation_t2_synthesizer: Option<String>,
    pub conversation_metering: Option<String>,
    pub conversation_pricing: Option<String>,
    pub conversation_t2_model_key: String,
    pub conversation_semantic_judgment_factory: String,
    pub conversation_synthesis_verifier: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Container {
    pub config: String,
    pub schema_registry: String,
    pub contract_validator: String,
    pub event_validator: String,
    pub exemption_registry: String,
    pub feasibility_probes: Vec<String>,
    pub startup_probe_specs: Vec<String>,
    pub startup_probes: Vec<String>,
    pub ontology_object_types: Vec<String>,
    pub ontology_link_types: Vec<String>,
    pub ontology_function_types: Vec<String>,
    pub ontology_interface_types: Vec<String>,
    pub ontology_interface_implementations: Vec<String>,
    pub compiled_ontology_interfaces: Option<String>,
    pub workflows: Vec<String>,
    pub resolved_models: Option<String>,
    pub resolved_models_artifact_digest: Option<String>,
    pub held_model_capabilities: Vec<String>,
    #[allow(clippy::type_complexity)]
    pub llm_bindings: Option<Box<LlmBindings>>,
    pub metric_provider: String,
    pub live_blast_probe: Option<String>,
    pub log_query_provider: String,
    pub trace_query_provider: String,
    pub telemetry_evidence_provider: Option<String>,
    pub inventory: String,
    pub knowledge_source: String,
    pub change_feed: String,
    pub change_safety_detector: Option<String>,
    pub change_safety_evidence_provider: Option<String>,
    pub assurance_twin_query_compiler: Option<String>,
    pub assurance_twin_discovery_sink: Option<String>,
    pub assurance_twin_retained_evidence_source: Option<String>,
    pub operational_readiness_posture: Option<String>,
    pub operational_readiness_report_publisher: Option<String>,
    pub operational_readiness_remediation: Option<String>,
    pub architecture_review_evidence_provider: Option<String>,
    pub architecture_review_sources: Option<String>,
    pub decision_evidence_admission_provider: Option<String>,
    pub operational_evidence_requester: Option<String>,
    pub distiller: String,
    pub manual_source: String,
    pub manual_classifier: String,
    pub capability_runtime: String,
    pub context_selection_policy_authority: Option<String>,
    pub context_selection_shadow_runner: Option<String>,
    pub trajectory_dataset_store: Option<String>,
    pub trajectory_join_service: Option<String>,
    pub mscp_expected_effect_provider: Option<String>,
    pub mscp_effect_observer: Option<String>,
    pub execution_backend_coordinator: Option<String>,
    pub browser_evidence_capture_service: Option<String>,
    pub browser_evidence_console_tool: Option<String>,
    pub browser_evidence_workflow_dispatcher: Option<String>,
    pub operational_evidence_source: Option<String>,
    pub operational_evidence_principal_contexts: Option<String>,
    pub execution_authorization_evaluator: Option<String>,
    pub execution_access_grant_sink: Option<String>,
    pub execution_authorization_required: bool,
    pub current_reuse_verifier: Option<String>,
    pub governed_knowledge: Option<String>,
    pub governed_document_reader: Option<String>,
    pub incident_member_source: Option<String>,
    pub incident_rca_context_source: Option<String>,
    #[allow(clippy::type_complexity)]
    pub resource_dependency_graph: BTreeMap<String, Vec<String>>,
    pub temporal_causal_evidence_provider: Option<String>,
    pub temporal_causality_config: Option<String>,
    pub causal_hypothesis_projection: Option<String>,
    pub causal_intervention_receipt_verifier: Option<String>,
    pub causal_closure_observation_source: Option<String>,
    pub dynamic_simulation_request_provider: Option<String>,
    pub effect_model_reader: Option<String>,
    pub effect_model_causal_evidence_verifier: Option<String>,
    pub graph_dynamic_simulation_request_provider: Option<String>,
    pub graph_effect_model_reader: Option<String>,
    pub graph_effect_model_causal_evidence_verifier: Option<String>,
    pub reconciliation_artifact_resolver: Option<String>,
    pub reconciliation_observation_verifier: Option<String>,
    pub executed_action_reconciliation_artifact_source: String,
    pub executed_action_observation_source: Option<String>,
    pub executed_action_observation_collector: Option<String>,
    pub rubric_promotion_receipt_source: Option<String>,
    pub rubric_promotion_receipt_verifier: Option<String>,
    pub t2_deterministic_evidence_verifiers: Vec<String>,
    pub operational_promotion_receipt_verifier: Option<String>,
    pub persisted_promotion_authority_verifier: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct LlmBindingsUnavailableError {
    pub message: String,
}

impl LlmBindingsUnavailableError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for LlmBindingsUnavailableError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for LlmBindingsUnavailableError {}

impl LlmBindings {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn require_t2_proposer(&self) -> Result<String, &'static str> {
        if self.t2_proposer.is_none() {
            return Err("LlmBindings.t2_proposer is None T2 reasoning cannot start");
        }
        Ok((self.t2_proposer.clone()).unwrap_or_default())
    }
}

impl Container {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn require_llm_bindings(&self) -> Result<LlmBindings, &'static str> {
        if self.llm_bindings.is_none() {
            return Err("Container.llm_bindings is None. In llm.modeazure the  entry point MUST c");
        }
        Err("runtime_binding_required")
    }
}

