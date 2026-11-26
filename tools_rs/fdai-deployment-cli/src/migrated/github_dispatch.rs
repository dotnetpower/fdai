#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::too_many_arguments)]
pub fn dispatch_plan(mut repository: String, mut environment: String, mut commit_sha: String, mut target_binding: String, mut region: String, mut run_id: String, mut selection: String, mut attempt: i64, mut run: Option<String>) -> Result<String, &'static str> {
    if (environment.clone()) == (String::from("prod")) {
        return Err("fdaictl production deployment inputs are not implemented");
    }
    let _ = dispatch(repository.clone(), environment.clone(), commit_sha.clone(), String::new(), String::new(), false, None, None, false, selection.clone(), run.clone()).unwrap_or_else(|_| ());
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::too_many_arguments)]
pub fn dispatch_apply(mut repository: String, mut environment: String, mut commit_sha: String, mut target_binding: String, mut region: String, mut approval_quorum: i64, mut run_id: String, mut plan_id: String, mut plan_digest: String, mut plan_expires_at: String, mut resume_verification: bool, mut selection: String, mut attempt: i64, mut run: Option<String>) -> Result<String, &'static str> {
    if (environment.clone()) == (String::from("prod")) {
        return Err("fdaictl production deployment inputs are not implemented");
    }
    if (approval_quorum) < (1_i64) {
        return Err("approval_quorum MUST be positive");
    }
    let _ = dispatch(repository.clone(), environment.clone(), commit_sha.clone(), String::new(), String::new(), true, Some(plan_id.clone()), Some(plan_digest.clone()), resume_verification, selection.clone(), None).unwrap_or_else(|_| ());
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn dispatch(mut repository: String, mut environment: String, mut commit_sha: String, mut context_digest: String, mut request_id_value: String, mut apply: bool, mut plan_id: Option<String>, mut plan_digest: Option<String>, mut resume_verification: bool, mut selection: String, mut run: Option<String>) -> Result<(), &'static str> {
    let mut fields: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("environment"), environment.clone()), (String::from("apply"), ((apply).to_string()).to_lowercase()), (String::from("promote_runtime_image"), String::new()), (String::from("resume_verification"), ((resume_verification).to_string()).to_lowercase()), (String::from("request_id"), request_id_value.clone()), (String::from("context_digest"), context_digest.clone()), (String::from("commit_sha"), commit_sha.clone())]);
    if apply {
        if (plan_id.is_none()) || (plan_digest.is_none()) {
            return Err("exact apply requires plan id and digest");
        }
        fields.insert(String::from("plan_id"), (plan_id.clone()).unwrap_or_default());
        fields.insert(String::from("plan_digest"), (plan_digest.clone()).unwrap_or_default());
    }
    let mut workflow: String = String::from("deploy-dev.yml");
    let mut arguments: Vec<String> = vec![String::from("workflow"), String::from("run"), workflow.clone(), String::from("--repo"), repository.clone(), String::from("--ref"), String::from("main")];
    Ok(())
}

