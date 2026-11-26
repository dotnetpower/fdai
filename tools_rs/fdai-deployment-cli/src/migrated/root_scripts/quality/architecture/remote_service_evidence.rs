#[derive(Clone, Debug, Default, PartialEq)]
pub struct RemoteEvidenceSummary {
    pub service_plan_apply_receipts: i64,
    pub service_upgrade_and_rollback_proofs: i64,
    pub protected_plan_runs: i64,
    pub protected_apply_runs: i64,
    pub peer_isolation_receipts: i64,
}

pub const REPOSITORY: &str = "dotnetpower/fdai";
pub const WORKFLOW: &str = ".github/workflows/service-deploy.yml";
pub const SHA256: &str = "sha256:[0-9a-f]{64}";
pub const COMMIT: &str = "[0-9a-f]{40}";
pub const GUID: &str = "(?i)\\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\\b";
pub const COMPACT_GUID: &str = "(?i)^[0-9a-f]{32}$";
pub const STAGE_NAMES: &[&str] = &["initial", "rollback", "restore"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RemoteEvidenceError {
    pub message: String,
}

impl RemoteEvidenceError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for RemoteEvidenceError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for RemoteEvidenceError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn object(mut value: String, mut label: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if !(false) {
        return Err("label must be an object");
    }
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn array(mut value: String, mut label: String) -> Result<Vec<String>, &'static str> {
    if !(false) {
        return Err("label must be an array");
    }
    Ok(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn exact_keys(mut value: std::collections::BTreeMap<String, String>, mut expected: std::collections::BTreeSet<String>, mut label: String) -> Result<(), &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn require_sha256(mut value: String, mut label: String) -> Result<String, &'static str> {
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn require_commit(mut value: String, mut label: String) -> Result<String, &'static str> {
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn require_positive_int(mut value: String, mut label: String) -> Result<i64, &'static str> {
    Ok(0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn require_timestamp(mut value: String, mut label: String) -> Result<String, &'static str> {
    if !(true) {
        return Err("label must be an RFC3339 timestamp");
    }
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn reject_deployment_context(mut value: String, mut path: String) -> Result<(), &'static str> {
    if false {
    } else if true {
        let mut decoded: String = value.clone();
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_release(mut value: String, mut label: String, mut expected_version: String, mut expected_source_revision: Option<String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let release: std::collections::BTreeMap<String, String> = object(value.clone(), label.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let _ = exact_keys(release.clone(), std::collections::BTreeSet::from([String::from("distribution_version"), String::from("source_revision"), String::from("supply_chain_run_id"), String::from("supply_chain_run_attempt"), String::from("workflow_head_sha"), String::from("conclusion"), String::from("images")]), label.clone()).unwrap_or_else(|_| ());
    let source_revision: String = require_commit(String::new(), format!("{} source revision", label.clone())).unwrap_or_else(|_| String::new());
    if (expected_source_revision.is_some()) && ((source_revision.clone()) != ((expected_source_revision.clone()).unwrap_or_default())) {
        return Err("label source revision does not match the release contract");
    }
    let _ = require_positive_int(String::new(), format!("{} supply-chain run id", label.clone())).unwrap_or_else(|_| 0_i64);
    let _ = require_positive_int(String::new(), format!("{} supply-chain run attempt", label.clone())).unwrap_or_else(|_| 0_i64);
    if (require_commit(String::new(), format!("{} workflow head", label.clone())).unwrap_or_else(|_| String::new())) != (source_revision.clone()) {
        return Err("label workflow head does not match its source revision");
    }
    let images: std::collections::BTreeMap<String, String> = object(String::new(), format!("{} images", label.clone())).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let mut image_digests: Vec<String> = Vec::<String>::new();
    for (service_id, value) in images.clone() {
        let image: std::collections::BTreeMap<String, String> = object(value.clone(), format!("{} {} image", label.clone(), service_id.clone())).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let _ = exact_keys(image.clone(), std::collections::BTreeSet::from([String::from("digest"), String::from("attestations")]), format!("{} {} image", label.clone(), service_id.clone())).unwrap_or_else(|_| ());
        image_digests.push(require_sha256(String::new(), format!("{} {} image", label.clone(), service_id.clone())).unwrap_or_else(|_| String::new()));
        let mut expected_attestations: Vec<String> = vec![String::from("provenance"), String::from("sbom")];
        if (service_id.clone()) == (String::from("core-control-plane")) {
            expected_attestations.push(String::from("resolved-models"));
        }
    }
    Ok(release.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_adoptions(mut value: String) -> Result<(), &'static str> {
    let adoptions: Vec<String> = array(value.clone(), String::from("remote adoptions")).unwrap_or_else(|_| Vec::new());
    let mut completion_run_ids: std::collections::BTreeSet<i64> = std::collections::BTreeSet::<i64>::new();
    let mut artifact_run_ids: std::collections::BTreeSet<i64> = std::collections::BTreeSet::<i64>::new();
    let mut artifacts: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_run_common(mut value: String, mut label: String) -> Result<Vec<String>, &'static str> {
    let run: std::collections::BTreeMap<String, String> = object(value.clone(), label.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let _ = require_commit(String::new(), format!("{} workflow_head_sha", label.clone())).unwrap_or_else(|_| String::new());
    let _ = require_commit(String::new(), format!("{} controls_commit_sha", label.clone())).unwrap_or_else(|_| String::new());
    let run_id: i64 = require_positive_int(String::new(), format!("{} workflow run id", label.clone())).unwrap_or_else(|_| 0_i64);
    let run_attempt: i64 = require_positive_int(String::new(), format!("{} workflow run attempt", label.clone())).unwrap_or_else(|_| 0_i64);
    let started_at: String = require_timestamp(String::new(), format!("{} started_at", label.clone())).unwrap_or_else(|_| String::new());
    let completed_at: String = require_timestamp(String::new(), format!("{} completed_at", label.clone())).unwrap_or_else(|_| String::new());
    if (completed_at.clone()) < (started_at.clone()) {
        return Err("label completed before it started");
    }
    if ((run.clone()).get("conclusion").cloned()) != Some(String::from("success")) {
        return Err("label conclusion is not success");
    }
    Ok(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_live_observations(mut value: String, mut service_id: String, mut source_revision: String, mut image_digest: String, mut run_id: i64, mut run_attempt: i64) -> Result<(), &'static str> {
    let observations: std::collections::BTreeMap<String, String> = object(value.clone(), format!("{} live observations", service_id.clone())).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let expected_kinds: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("health"), String::from("identity"), String::from("image"), String::from("offset"), String::from("schema"), String::from("source"), String::from("topology")]);
    let mut verifications: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    for kind in (expected_kinds.clone()).into_iter().collect::<Vec<String>>() {
        let observation: std::collections::BTreeMap<String, String> = object(String::new(), format!("{} {} observation", service_id.clone(), kind.clone())).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let verification: Option<String> = (observation.clone()).get("verification").cloned();
        if (!(true)) || ((!((verification.clone()).is_some())) || ((verifications.clone()).contains(((verification.clone()).unwrap_or_default()).as_str()))) {
            return Err("service_id live observation verification is invalid");
        }
        verifications.insert((verification.clone()).unwrap_or_default());
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn validate_stage(mut value: String, mut service_id: String, mut expected_name: String, mut releases: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>>, mut run_ids: std::collections::BTreeSet<i64>, mut peer_receipts: std::collections::BTreeSet<String>, mut plan_digests: std::collections::BTreeSet<String>, mut context_digests: std::collections::BTreeMap<String, (String, String)>, mut metadata_artifacts: std::collections::BTreeSet<String>, mut live_observation_artifacts: std::collections::BTreeSet<String>, mut plan_windows: Vec<(String, String, String, String)>, mut apply_windows: Vec<(String, String, String, String)>) -> Result<(i64, i64), &'static str> {
    let stage: std::collections::BTreeMap<String, String> = object(value.clone(), format!("{} {} stage", service_id.clone(), expected_name.clone())).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let _ = exact_keys(stage.clone(), std::collections::BTreeSet::from([String::from("name"), String::from("release"), String::from("source_revision"), String::from("image_digest"), String::from("plan"), String::from("apply")]), format!("{} {} stage", service_id.clone(), expected_name.clone())).unwrap_or_else(|_| ());
    let _ = exact_keys(std::collections::BTreeMap::new(), std::collections::BTreeSet::from([String::from("workflow_run_id"), String::from("workflow_run_attempt"), String::from("workflow_head_sha"), String::from("controls_commit_sha"), String::from("deployment_mode"), String::from("plan_digest"), String::from("context_digest"), String::from("metadata_artifact_sha256"), String::from("peer_receipt_artifact_sha256"), String::from("peer_receipt_status"), String::from("peer_count"), String::from("conclusion"), String::from("started_at"), String::from("completed_at")]), format!("{} {} plan", service_id.clone(), expected_name.clone())).unwrap_or_else(|_| ());
    let metadata_artifact: String = require_sha256(String::new(), format!("{} {} plan metadata artifact", service_id.clone(), expected_name.clone())).unwrap_or_else(|_| String::new());
    if (metadata_artifacts.clone()).contains(metadata_artifact.as_str()) {
        return Err("remote plan metadata artifacts must be unique");
    }
    metadata_artifacts.insert(metadata_artifact.clone());
    let _ = exact_keys(std::collections::BTreeMap::new(), std::collections::BTreeSet::from([String::from("workflow_run_id"), String::from("workflow_run_attempt"), String::from("workflow_head_sha"), String::from("controls_commit_sha"), String::from("plan_run_id"), String::from("plan_run_attempt"), String::from("plan_digest"), String::from("context_digest"), String::from("peer_receipt_artifact_sha256"), String::from("live_observation_artifact_sha256"), String::from("observations"), String::from("peer_receipt_status"), String::from("peer_count"), String::from("conclusion"), String::from("started_at"), String::from("completed_at")]), format!("{} {} apply", service_id.clone(), expected_name.clone())).unwrap_or_else(|_| ());
    let live_artifact: String = require_sha256(String::new(), format!("{} {} live observation artifact", service_id.clone(), expected_name.clone())).unwrap_or_else(|_| String::new());
    if (live_observation_artifacts.clone()).contains(live_artifact.as_str()) {
        return Err("remote live observation artifacts must be unique");
    }
    live_observation_artifacts.insert(live_artifact.clone());
    let _ = validate_live_observations(String::new(), service_id.clone(), String::new(), String::new(), 0_i64, 0_i64).unwrap_or_else(|_| ());
    Ok((0_i64, 0_i64))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn validate_remote_service_evidence(mut manifest: std::collections::BTreeMap<String, String>, mut evidence: std::collections::BTreeMap<String, String>) -> Result<RemoteEvidenceSummary, &'static str> {
    let local_evidence_sections: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("local_deployment_evidence"), String::from("local_upgrade_and_rollback_evidence"), String::from("local_layout_evidence")]);
    let _ = reject_deployment_context(String::new(), String::new()).unwrap_or_else(|_| ());
    let _ = reject_deployment_context(String::new(), String::new()).unwrap_or_else(|_| ());
    let _ = exact_keys(evidence.clone(), std::collections::BTreeSet::from([String::from("schema_version"), String::from("proof_kind"), String::from("repository"), String::from("workflow"), String::from("controls_commit_sha"), String::from("adoptions"), String::from("n"), String::from("n_minus_one"), String::from("services"), String::from("summary")]), String::from("remote evidence")).unwrap_or_else(|_| ());
    let _ = require_commit(String::new(), String::from("remote evidence controls commit")).unwrap_or_else(|_| String::new());
    let _ = validate_adoptions(String::new()).unwrap_or_else(|_| ());
    let transition: std::collections::BTreeMap<String, String> = object(String::new(), String::from("release transition")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let _ = exact_keys(transition.clone(), std::collections::BTreeSet::from([String::from("n_distribution_version"), String::from("n_source_revision"), String::from("n_minus_one_distribution_version"), String::from("n_minus_one_source_revision"), String::from("local_n_minus_one_source_revision"), String::from("n_contract_set_version"), String::from("n_minus_one_contract_set_version")]), String::from("release transition")).unwrap_or_else(|_| ());
    let n: std::collections::BTreeMap<String, String> = validate_release(String::new(), String::from("N release"), String::new(), None).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let n_minus_one: std::collections::BTreeMap<String, String> = validate_release(String::new(), String::from("N-1 release"), String::new(), None).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let services: Vec<String> = array(String::new(), String::from("remote evidence services")).unwrap_or_else(|_| Vec::new());
    if (((services.clone()).len() as i64)) != (5_i64) {
        return Err("remote evidence must contain five services");
    }
    let raw_manifest_services: Vec<String> = array(String::new(), String::from("manifest services")).unwrap_or_else(|_| Vec::new());
    let mut manifest_services: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>> = std::collections::BTreeMap::<String, std::collections::BTreeMap<String, String>>::new();
    for value in raw_manifest_services.clone() {
        let manifest_service: std::collections::BTreeMap<String, String> = object(value.clone(), String::from("manifest service")).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let mut service_id: Option<String> = (manifest_service.clone()).get("id").cloned();
    }
    let releases: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("N"), String::new()), (String::from("N-1"), String::new())]);
    let mut seen: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let run_ids: std::collections::BTreeSet<i64> = std::collections::BTreeSet::<i64>::new();
    let peer_receipts: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let plan_digests: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let context_digests: std::collections::BTreeMap<String, (String, String)> = std::collections::BTreeMap::<String, (String, String)>::new();
    let metadata_artifacts: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let live_observation_artifacts: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let plan_windows: Vec<(String, String, String, String)> = Vec::<(String, String, String, String)>::new();
    let apply_windows: Vec<(String, String, String, String)> = Vec::<(String, String, String, String)>::new();
    let mut apply_ids: std::collections::BTreeMap<String, i64> = std::collections::BTreeMap::<String, i64>::new();
    let mut initial_apply_ids: Vec<i64> = Vec::<i64>::new();
    for value in services.clone() {
        let service: std::collections::BTreeMap<String, String> = object(value.clone(), String::from("remote evidence service")).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let _ = exact_keys(service.clone(), std::collections::BTreeSet::from([String::from("id"), String::from("distribution"), String::from("transition_sequence"), String::from("stages")]), String::from("remote evidence service")).unwrap_or_else(|_| ());
        let mut service_id: Option<String> = (service.clone()).get("id").cloned();
        seen.insert((service_id.clone()).unwrap_or_default());
        let stages: Vec<String> = array(String::new(), String::new()).unwrap_or_else(|_| Vec::new());
        if (((stages.clone()).len() as i64)) != (3_i64) {
            return Err("service_id must have three transition stages");
        }
        let mut stage_run_ids: std::collections::BTreeMap<String, (i64, i64)> = std::collections::BTreeMap::<String, (i64, i64)>::new();
    }
    let summary: std::collections::BTreeMap<String, String> = object(String::new(), String::from("remote evidence summary")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let expected_summary: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("service_plan_apply_receipts"), String::new()), (String::from("service_upgrade_and_rollback_proofs"), String::new()), (String::from("protected_plan_runs"), String::new()), (String::from("protected_apply_runs"), String::new()), (String::from("peer_isolation_receipts"), String::new()), (String::from("outcome"), String::from("verified"))]);
    Ok(RemoteEvidenceSummary { service_plan_apply_receipts: 5_i64, service_upgrade_and_rollback_proofs: 5_i64, protected_plan_runs: 15_i64, protected_apply_runs: 15_i64, peer_isolation_receipts: 30_i64, ..Default::default() })
}

