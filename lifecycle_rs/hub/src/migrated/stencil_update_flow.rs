use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct StencilInstallationState {
    pub installation_id: String,
    pub customer_principal: String,
    pub subscribed_channel: String,
    pub current_release_id: String,
    pub current_stencil_id: String,
    pub current_stencil_digest: String,
    pub current_schema_revision: i64,
    pub selected_stencil_id: String,
    pub configuration_stencil_id: Option<String>,
    pub configuration_revision_digest: String,
    pub runtime_bundle_stencil_id: Option<String>,
    pub runtime_bundle_workloads: Vec<String>,
    pub runtime_bundle_component_images: BTreeMap<String, String>,
    pub trial_anchor_created_at: String,
    pub runtime_entitlement_digest: String,
    pub installation_key_id: String,
    pub pvc_journal_sequence: i64,
    pub catalog_minimum_revision: i64,
    pub last_accepted_export_digest: Option<String>,
    pub last_applied_plan_digest: Option<String>,
    pub maintenance_window_open: bool,
    pub next_window_starts_at: String,
    pub check_interval_seconds: i64,
    pub jitter_seconds: i64,
    pub agent_active: bool,
    pub inputs_staged: bool,
    pub db_and_model_ready: bool,
    pub pinned_grant_id: String,
    pub pinned_grant_revision: i64,
    pub pinned_grant_scope_digest: String,
    #[allow(clippy::type_complexity)]
    pub last_agent_report: Option<BTreeMap<String, String>>,
    #[allow(clippy::type_complexity)]
    pub last_failure: Option<BTreeMap<String, String>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StencilUpdateReconciliationResult {
    pub installation_id: String,
    pub classification: String,
    pub executable_readiness: bool,
    pub plan_issued: bool,
    pub plan_type: Option<String>,
    pub plan_digest: Option<String>,
    pub applied_in_window: bool,
    pub current_release_id: String,
    pub current_stencil_id: String,
    pub proposed_release_id: Option<String>,
    pub proposed_stencil_id: Option<String>,
    pub blocker_code: Option<String>,
    pub blocker_detail: Option<String>,
    pub decision_owner: String,
    pub inter_party_handoff_count: i64,
    pub additional_customer_apply_clicks: i64,
    pub outside_window_mutations: i64,
    #[allow(clippy::type_complexity)]
    pub changed_features: BTreeMap<String, Vec<String>>,
    pub mirrored_digests: Vec<String>,
    pub updated_state: Box<StencilInstallationState>,
    pub readiness_view: BTreeMap<String, String>,
}

impl StencilUpdateReconciliationResult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.classification.as_str(), "verified-ready" | "scheduled-waiting-window" | "blocked-prerequisite" | "recovery-rolloff-required" | "grant-expired-or-revoked" | "agent-inactive" | "catalog-untrusted" | "up-to-date") { return Err("invalid classification literal"); }
        Ok(())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn extract_stencil_sets(mut release: Option<String>) -> (std::collections::BTreeSet<String>, std::collections::BTreeSet<String>, std::collections::BTreeSet<String>) {
    (std::collections::BTreeSet::new(), std::collections::BTreeSet::new(), std::collections::BTreeSet::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn compute_feature_diff(mut current_release: Option<String>, mut proposed_release: Option<String>) -> std::collections::BTreeMap<String, Vec<String>> {
    let Some(mut proposed_release) = proposed_release.clone() else { return std::collections::BTreeMap::from([(String::from("added_panels"), Vec::<String>::new()), (String::from("removed_panels"), Vec::<String>::new()), (String::from("added_workloads"), Vec::<String>::new()), (String::from("removed_workloads"), Vec::<String>::new()), (String::from("added_loops"), Vec::<String>::new()), (String::from("removed_loops"), Vec::<String>::new())]); };
    std::collections::BTreeMap::from([(String::from("added_panels"), Vec::new()), (String::from("removed_panels"), Vec::new()), (String::from("added_workloads"), Vec::new()), (String::from("removed_workloads"), Vec::new()), (String::from("added_loops"), Vec::new()), (String::from("removed_loops"), Vec::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::too_many_arguments)]
pub fn reconcile_stencil_update(mut state: StencilInstallationState, mut scoped_export_raw: Vec<u8>, mut export_signature: String, mut export_scope_signature: String, mut export_public_key: String, mut grant_envelope: std::collections::BTreeMap<String, String>, mut grant_issuer_public_keys: Vec<String>, mut mirror: String, mut expected_grant_scope_digest: Option<String>, mut now: Option<String>) -> Result<StencilUpdateReconciliationResult, &'static str> {
    let mut recovery_only: bool = false;
    let min_grant_rev: i64 = (1_i64).max(state.pinned_grant_revision);
    if (!(true)) || (((export_scope_signature.clone()).trim().to_string()).is_empty()) {
        return Ok(build_blocked_result(state.clone(), String::from("catalog-untrusted"), String::from("export_scope_signature_invalid"), String::from("Export scope binding signature is required."), String::from("customer-installation-admin"), None, None, None, Vec::new()));
    }
    let mode: String = if recovery_only { String::from("recovery") } else { String::from("active") };
    let mut parsed_releases: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    let current_rel: Option<String> = (parsed_releases.clone()).get((state.current_release_id.clone()).as_str()).cloned();
    let mut current_recalled: bool = false;
    if (recovery_only) && (!(current_recalled)) {
        return Ok(build_blocked_result(state.clone(), String::from("grant-expired-or-revoked"), String::from("grant_expired\" if not verified_grant.grant.revoked else \"grant_revoked"), String::from("Distribution grant is expired or revoked; routine upgrades are held while \" \"installed workload continues."), String::from("customer-installation-admin"), None, None, None, Vec::new()));
    }
    let target_stencil_id: String = if current_recalled { state.current_stencil_id.clone() } else { state.selected_stencil_id.clone() };
    let stencil_switching: bool = (target_stencil_id.clone()) != (state.current_stencil_id.clone());
    if stencil_switching {
        if (state.configuration_stencil_id.clone()) != Some(target_stencil_id.clone()) {
            return Ok(build_blocked_result(state.clone(), String::from("blocked-prerequisite"), String::from("stencil_transition_config_unreviewed"), String::from("Stencil switch requires a customer-reviewed configuration revision for the \" \"target Stencil."), String::from("customer-configuration-owner"), None, None, None, Vec::new()));
        }
        if (state.runtime_bundle_stencil_id.clone()) != Some(target_stencil_id.clone()) {
            return Ok(build_blocked_result(state.clone(), String::from("blocked-prerequisite"), String::from("stencil_transition_bundle_mismatch"), String::from("Stencil switch requires a RuntimeBundle bound to the target Stencil."), String::from("customer-installation-admin"), None, None, None, Vec::new()));
        }
    }
    let mut matching_candidates: Vec<(String, String)> = Vec::<(String, String)>::new();
    if (matching_candidates.clone()).is_empty() {
        if current_recalled {
            return Ok(build_blocked_result(state.clone(), String::from("recovery-rolloff-required"), String::from("no_safe_rolloff_candidate"), String::from("Current release is recalled and no non-recalled roll-off candidate is \" \"available."), String::from("vendor-release-operator"), None, None, None, Vec::new()));
        }
        return Ok(build_up_to_date_result(Default::default()));
    }
    let diff: std::collections::BTreeMap<String, Vec<String>> = compute_feature_diff(current_rel.clone(), None);
    if (!(state.inputs_staged)) || (!(state.db_and_model_ready)) {
        return Ok(build_blocked_result(state.clone(), String::from("blocked-prerequisite"), String::from("prerequisites_unprepared"), String::from("Catalog candidate is accepted, but staged inputs or DB/model prerequisites \" \"are not ready."), String::from("customer-lifecycle-operator"), None, Some(target_stencil_id.clone()), Some(diff.clone()), Vec::new()));
    }
    if !(state.agent_active) {
        return Ok(build_blocked_result(state.clone(), String::from("agent-inactive"), String::from("lifecycle_agent_inactive"), String::from("Catalog candidate is staged, but the cluster Lifecycle Agent is inactive; \" \"executable readiness is false."), String::from("customer-platform-operator"), None, Some(target_stencil_id.clone()), Some(diff.clone()), Vec::new()));
    }
    let plan_type: String = if current_recalled { String::from("recall-rolloff") } else { if stencil_switching { String::from("configuration-change") } else { String::from("upgrade") } };
    if (!(state.maintenance_window_open)) && (!(current_recalled)) {
        let mut view: std::collections::BTreeMap<String, String> = build_customer_stencil_readiness_view(Default::default(), String::from("scheduled-waiting-window"), true, None, Some(target_stencil_id.clone()), diff.clone(), None, None, String::from("automatic-maintenance-window"));
        return Ok(StencilUpdateReconciliationResult { installation_id: state.installation_id.clone(), classification: String::from("scheduled-waiting-window"), executable_readiness: true, plan_issued: true, plan_type: Some(plan_type.clone()), applied_in_window: false, current_release_id: state.current_release_id.clone(), current_stencil_id: state.current_stencil_id.clone(), proposed_stencil_id: Some(target_stencil_id.clone()), blocker_code: None, blocker_detail: None, decision_owner: String::from("automatic-maintenance-window"), inter_party_handoff_count: 0_i64, additional_customer_apply_clicks: 0_i64, outside_window_mutations: 0_i64, ..Default::default() });
    }
    let mut view: std::collections::BTreeMap<String, String> = build_customer_stencil_readiness_view(Default::default(), String::from("verified-ready"), true, None, None, diff.clone(), None, None, String::from("none-automatic"));
    Ok(StencilUpdateReconciliationResult { installation_id: state.installation_id.clone(), classification: String::from("verified-ready"), executable_readiness: true, plan_issued: true, plan_type: Some(plan_type.clone()), applied_in_window: true, blocker_code: None, blocker_detail: None, decision_owner: String::from("none-automatic"), inter_party_handoff_count: 0_i64, additional_customer_apply_clicks: 0_i64, outside_window_mutations: 0_i64, ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_up_to_date_result(mut state: StencilInstallationState) -> StencilUpdateReconciliationResult {
    let empty_diff: std::collections::BTreeMap<String, Vec<String>> = compute_feature_diff(None, None);
    let view: std::collections::BTreeMap<String, String> = build_customer_stencil_readiness_view(state.clone(), String::from("up-to-date"), (state.agent_active) && (state.inputs_staged), None, None, empty_diff.clone(), None, None, String::from("none-automatic"));
    StencilUpdateReconciliationResult { installation_id: state.installation_id.clone(), classification: String::from("up-to-date"), executable_readiness: (state.agent_active) && (state.inputs_staged), plan_issued: false, plan_type: None, plan_digest: None, applied_in_window: false, current_release_id: state.current_release_id.clone(), current_stencil_id: state.current_stencil_id.clone(), proposed_release_id: None, proposed_stencil_id: None, blocker_code: None, blocker_detail: None, decision_owner: String::from("none-automatic"), inter_party_handoff_count: 0_i64, additional_customer_apply_clicks: 0_i64, outside_window_mutations: 0_i64, updated_state: Box::new(state.clone()), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn build_blocked_result(mut state: StencilInstallationState, mut classification: String, mut blocker_code: String, mut blocker_detail: String, mut decision_owner: String, mut proposed_release_id: Option<String>, mut proposed_stencil_id: Option<String>, mut changed_features: Option<std::collections::BTreeMap<String, Vec<String>>>, mut mirrored_digests: Vec<String>) -> StencilUpdateReconciliationResult {
    let view: std::collections::BTreeMap<String, String> = build_customer_stencil_readiness_view(Default::default(), classification.clone(), false, proposed_release_id.clone(), proposed_stencil_id.clone(), std::collections::BTreeMap::new(), Some(blocker_code.clone()), Some(blocker_detail.clone()), decision_owner.clone());
    StencilUpdateReconciliationResult { installation_id: state.installation_id.clone(), classification: classification.clone(), executable_readiness: false, plan_issued: false, plan_type: None, plan_digest: None, applied_in_window: false, current_release_id: state.current_release_id.clone(), current_stencil_id: state.current_stencil_id.clone(), proposed_release_id: proposed_release_id.clone(), proposed_stencil_id: proposed_stencil_id.clone(), blocker_code: Some(blocker_code.clone()), blocker_detail: Some(blocker_detail.clone()), decision_owner: decision_owner.clone(), inter_party_handoff_count: 0_i64, additional_customer_apply_clicks: 0_i64, outside_window_mutations: 0_i64, mirrored_digests: mirrored_digests.clone(), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn build_customer_stencil_readiness_view(mut state: StencilInstallationState, mut classification: String, mut executable_readiness: bool, mut proposed_release_id: Option<String>, mut proposed_stencil_id: Option<String>, mut changed_features: std::collections::BTreeMap<String, Vec<String>>, mut blocker_code: Option<String>, mut blocker_detail: Option<String>, mut decision_owner: String) -> std::collections::BTreeMap<String, String> {
    if (classification.clone()) == (String::from("scheduled-waiting-window")) {
        let mut next_action: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("action_id"), String::from("wait-for-maintenance-window")), (String::from("label"), format!("Scheduled automatic update at {} (no click required)", state.next_window_starts_at.clone())), (String::from("label_ko"), String::new()), (String::from("decision_owner"), decision_owner.clone()), (String::from("requires_extra_apply_click"), String::new()), (String::from("requires_machine_value_transcription"), String::new())]);
    } else if matches!(classification.as_str(), "verified-ready" | "up-to-date") {
        let mut next_action: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("action_id"), String::from("no-action-required")), (String::from("label"), String::from("Installation is aligned with the entitled Stencil channel")), (String::from("label_ko"), String::from("설치 환경이 승인된 Stencil 채널과 최신 상태로 동기화되어 있습니다")), (String::from("decision_owner"), String::from("none-automatic")), (String::from("requires_extra_apply_click"), String::new()), (String::from("requires_machine_value_transcription"), String::new())]);
    } else {
        let mut next_action: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("action_id"), format!("resolve-{}", (blocker_code.clone()).unwrap_or_else(|| String::from("blocker")))), (String::from("label"), String::new()), (String::from("label_ko"), String::new()), (String::from("decision_owner"), decision_owner.clone()), (String::from("requires_extra_apply_click"), String::new()), (String::from("requires_machine_value_transcription"), String::new())]);
    }
    std::collections::BTreeMap::from([(String::from("installation_id"), state.installation_id.clone()), (String::from("current_stencil_id"), state.current_stencil_id.clone()), (String::from("current_version"), state.current_release_id.clone()), (String::from("proposed_stencil_id"), (proposed_stencil_id.clone()).unwrap_or_default()), (String::from("proposed_version"), (proposed_release_id.clone()).unwrap_or_default()), (String::from("changed_features"), String::new()), (String::from("classification"), classification.clone()), (String::from("executable_readiness"), String::new()), (String::from("catalog_accepted"), String::new()), (String::from("inputs_staged"), String::new()), (String::from("agent_active"), String::new()), (String::from("next_execution_window"), state.next_window_starts_at.clone()), (String::from("check_interval_seconds"), String::new()), (String::from("jitter_seconds"), String::new()), (String::from("last_agent_report"), String::new()), (String::from("primary_next_action"), String::new()), (String::from("preservation_guarantees"), String::new()), (String::from("recovery_context"), String::new())])
}

pub const PUBLIC_EXPORTS: &[&str] = &["ReadinessClassification", "StencilInstallationState", "StencilUpdateReconciliationResult", "build_customer_stencil_readiness_view", "reconcile_stencil_update"];
